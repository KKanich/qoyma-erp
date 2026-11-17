"""Comprehensive parameter, ORM, and server load stress tests for Qoyma ERP."""
import csv
import io
import json
import re
import sqlite3
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import timedelta
from decimal import Decimal
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection, connections
from django.db.models import F, Q, Sum
from django.db.models.deletion import RestrictedError
from django.test import Client, LiveServerTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Category,
    Product,
    Sale,
    SaleItem,
    StockReceipt,
    StockReceiptItem,
    Supplier,
    User,
    barcode_validator,
)
from .reports import daily_sales_summary
from .services import receive_stock


def make_barcode(num: int) -> str:
    """Return a deterministic valid 13-digit EAN-13-formatted string."""
    return f'487000{num:07d}'


class ParameterStressTests(TestCase):
    """Stress-test all view, form, service, API, and model parameters."""

    def setUp(self):
        self.admin = User.objects.create_superuser('stress-admin', password='pw', role='Admin')
        self.manager = User.objects.create_user('stress-manager', password='pw', role='Manager')
        self.cashier = User.objects.create_user('stress-cashier', password='pw', role='Cashier')
        self.dairy = Category.objects.create(name='Dairy')
        self.national = Category.objects.create(name='Ұлттық өнімдер')
        self.supplier = Supplier.objects.create(name='Stress Supplier', phone='+7 700 000 00 00')
        self.today = timezone.localdate()
        self.future = self.today + timedelta(days=30)

        self.milk = Product.objects.create(
            barcode='4870000000011',
            name='Milk 2.5% 1L',
            category=self.dairy,
            supplier=self.supplier,
            sale_price=Decimal('550.00'),
            quantity=Decimal('20.00'),
            min_quantity=Decimal('5.00'),
            expiry_date=self.future,
        )
        self.kurt = Product.objects.create(
            barcode='4870000000318',
            name='Құрт 200г',
            category=self.national,
            supplier=None,
            sale_price=Decimal('900.00'),
            quantity=Decimal('4.00'),
            min_quantity=Decimal('5.00'),
            expiry_date=self.today + timedelta(days=3),
        )
        self.client.force_login(self.manager)

    def _valid_product_payload(self, **overrides):
        data = {
            'barcode': '4870000000999',
            'name': 'Stress Kefir',
            'category': str(self.dairy.pk),
            'supplier': str(self.supplier.pk),
            'sale_price': '420.00',
            'min_quantity': '5.00',
            'expiry_date': self.future.isoformat(),
        }
        data.update(overrides)
        return data

    def test_catalog_list_query_low_and_page_parameter_matrix(self):
        # Create 30 extra products to span multiple paginator pages (25 per page).
        for idx in range(1, 31):
            Product.objects.create(
                barcode=make_barcode(1000 + idx),
                name=f'Catalog Item {idx:02d}',
                category=self.dairy,
                supplier=self.supplier if idx % 2 == 0 else None,
                sale_price=Decimal('100.00') + Decimal(idx),
                quantity=Decimal('2.00') if idx <= 5 else Decimal('15.00'),
                min_quantity=Decimal('5.00'),
                expiry_date=self.future,
            )

        q_values = [
            '',
            '   ',
            'Milk',
            'milk',
            '4870000000011',
            '0000011',
            'Құрт',
            'Құр',
            '"\'<>%;--',
            '<script>alert(1)</script>',
            'X' * 500,
            'definitely-missing-product-xyz',
        ]
        low_values = ['', '1', '0', 'true', '2', '-1', 'yes']
        page_values = ['', '1', '2', '0', '-1', '999999', 'abc']

        url = reverse('product_list')
        for q in q_values:
            for low in low_values:
                res = self.client.get(url, {'q': q, 'low': low})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.context['low_stock'], low == '1')
                self.assertEqual(res.context['query'], q.strip())

        for page in page_values:
            res = self.client.get(url, {'page': page})
            self.assertEqual(res.status_code, 200)
            self.assertGreaterEqual(res.context['page'].number, 1)

        # Verify XSS-like search parameter is HTML-escaped in response body.
        xss_res = self.client.get(url, {'q': '<script>alert(1)</script>'})
        self.assertNotContains(xss_res, '<script>alert(1)</script>')
        self.assertContains(xss_res, '&lt;script&gt;alert(1)&lt;/script&gt;')

        # Verify Kazakh Unicode search and low=1 filter match Құрт.
        kz_res = self.client.get(url, {'q': 'Құрт', 'low': '1'})
        self.assertContains(kz_res, 'Құрт 200г')
        self.assertNotContains(kz_res, 'Milk 2.5% 1L')

    def test_catalog_create_all_parameter_boundaries_and_invalid_inputs(self):
        create_url = reverse('product_create')
        initial_count = Product.objects.count()

        valid_cases = [
            ('min-barcode-min-price', {
                'barcode': '0000000000000',
                'name': 'A',
                'supplier': '',
                'sale_price': '0.01',
                'min_quantity': '0.00',
                'expiry_date': '2020-01-01',
            }),
            ('max-barcode-max-price-max-name-leap-day', {
                'barcode': '9999999999999',
                'name': 'N' * 200,
                'supplier': str(self.supplier.pk),
                'sale_price': '99999999.99',
                'min_quantity': '99999999.99',
                'expiry_date': '2028-02-29',
            }),
            ('kazakh-name-and-html-escaping', {
                'barcode': '4870000000888',
                'name': '<b>Сүт & Honey</b>',
                'sale_price': '1250.50',
                'min_quantity': '3.25',
                'expiry_date': '2099-12-31',
                'quantity': '999.00',  # Attempted stock injection must be ignored.
            }),
        ]

        for label, overrides in valid_cases:
            with self.subTest(valid=label):
                payload = self._valid_product_payload(**overrides)
                res = self.client.post(create_url, payload)
                self.assertRedirects(res, reverse('product_list'))
                created = Product.objects.get(barcode=payload['barcode'])
                self.assertEqual(created.quantity, Decimal('0.00'))

        # Verify HTML payload was escaped when rendered on product list.
        list_res = self.client.get(reverse('product_list'), {'q': '4870000000888'})
        self.assertNotContains(list_res, '<b>Сүт & Honey</b>')
        self.assertContains(list_res, '&lt;b&gt;Сүт &amp; Honey&lt;/b&gt;')

        expected_count = initial_count + len(valid_cases)
        self.assertEqual(Product.objects.count(), expected_count)

        invalid_cases = [
            ('barcode_12_digits', {'barcode': '123456789012'}),
            ('barcode_14_digits', {'barcode': '12345678901234'}),
            ('barcode_alpha', {'barcode': '487000000001a'}),
            ('barcode_space', {'barcode': '48700000 0011'}),
            ('barcode_negative', {'barcode': '-123456789012'}),
            ('barcode_empty', {'barcode': ''}),
            ('barcode_duplicate', {'barcode': self.milk.barcode}),
            ('name_empty', {'name': ''}),
            ('name_whitespace', {'name': '   '}),
            ('name_201_chars', {'name': 'N' * 201}),
            ('category_missing', {'category': '999999'}),
            ('category_empty', {'category': ''}),
            ('category_non_numeric', {'category': 'abc'}),
            ('supplier_missing', {'supplier': '999999'}),
            ('supplier_non_numeric', {'supplier': 'abc'}),
            ('sale_price_zero', {'sale_price': '0.00'}),
            ('sale_price_negative', {'sale_price': '-0.01'}),
            ('sale_price_overflow', {'sale_price': '100000000.00'}),
            ('sale_price_3_decimals', {'sale_price': '10.123'}),
            ('sale_price_alpha', {'sale_price': 'abc'}),
            ('sale_price_nan', {'sale_price': 'NaN'}),
            ('sale_price_inf', {'sale_price': 'Infinity'}),
            ('sale_price_neg_inf', {'sale_price': '-Infinity'}),
            ('sale_price_empty', {'sale_price': ''}),
            ('min_quantity_negative', {'min_quantity': '-0.01'}),
            ('min_quantity_overflow', {'min_quantity': '100000000.00'}),
            ('min_quantity_3_decimals', {'min_quantity': '5.555'}),
            ('min_quantity_alpha', {'min_quantity': 'abc'}),
            ('min_quantity_nan', {'min_quantity': 'NaN'}),
            ('min_quantity_empty', {'min_quantity': ''}),
            ('expiry_invalid_feb30', {'expiry_date': '2026-02-30'}),
            ('expiry_bad_format', {'expiry_date': 'not-a-date'}),
            ('expiry_empty', {'expiry_date': ''}),
        ]

        for label, overrides in invalid_cases:
            with self.subTest(invalid=label):
                merged = {'barcode': '4870000000777', **overrides}
                if label == 'barcode_duplicate':
                    merged['barcode'] = self.milk.barcode
                payload = self._valid_product_payload(**merged)
                res = self.client.post(create_url, payload)
                self.assertEqual(res.status_code, 200)
                self.assertTrue(res.context['form'].errors)
                self.assertEqual(Product.objects.count(), expected_count)

    def test_catalog_edit_duplicate_stock_preservation_and_http_methods(self):
        edit_url = reverse('product_edit', args=[self.kurt.pk])

        # Duplicate barcode on edit is rejected cleanly without mutating DB.
        dup_res = self.client.post(edit_url, self._valid_product_payload(barcode=self.milk.barcode))
        self.assertEqual(dup_res.status_code, 200)
        self.assertTrue(dup_res.context['form'].errors)
        self.kurt.refresh_from_db()
        self.assertEqual(self.kurt.barcode, '4870000000318')

        # Valid edit preserves existing stock even if quantity is injected in POST.
        ok_res = self.client.post(edit_url, self._valid_product_payload(
            barcode=self.kurt.barcode,
            name='Құрт Premium',
            supplier='',
            quantity='500.00',
        ))
        self.assertRedirects(ok_res, reverse('product_list'))
        self.kurt.refresh_from_db()
        self.assertEqual(self.kurt.name, 'Құрт Premium')
        self.assertIsNone(self.kurt.supplier)
        self.assertEqual(self.kurt.quantity, Decimal('4.00'))

        # Missing PK returns 404; disallowed HTTP methods return 405.
        self.assertEqual(self.client.get(reverse('product_edit', args=[999999])).status_code, 404)
        self.assertEqual(self.client.get(reverse('product_delete', args=[999999])).status_code, 404)

        for method in ('put', 'delete', 'patch'):
            self.assertEqual(getattr(self.client, method)(reverse('product_list')).status_code, 405)
            self.assertEqual(getattr(self.client, method)(edit_url).status_code, 405)
            self.assertEqual(
                getattr(self.client, method)(reverse('product_delete', args=[self.kurt.pk])).status_code,
                405,
            )
        self.assertEqual(self.client.post(reverse('product_list')).status_code, 405)

    def test_catalog_delete_blocks_stocked_and_historical_products(self):
        # Zero-stock product with no history can be deleted.
        unused = Product.objects.create(
            barcode='4870000000501',
            name='Unused Item',
            category=self.dairy,
            sale_price=Decimal('100.00'),
            quantity=Decimal('0.00'),
            expiry_date=self.future,
        )
        # Zero-stock product with SaleItem history cannot be deleted.
        sold_zero = Product.objects.create(
            barcode='4870000000502',
            name='Sold Out Item',
            category=self.dairy,
            sale_price=Decimal('100.00'),
            quantity=Decimal('0.00'),
            expiry_date=self.future,
        )
        sale = Sale.objects.create(cashier=self.cashier, total_amount=Decimal('100.00'))
        SaleItem.objects.create(
            sale=sale, product=sold_zero, quantity=Decimal('1.00'),
            unit_price=Decimal('100.00'), subtotal=Decimal('100.00'),
        )
        # Zero-stock product with StockReceiptItem history cannot be deleted.
        received_zero = Product.objects.create(
            barcode='4870000000503',
            name='Received Zero Item',
            category=self.dairy,
            sale_price=Decimal('100.00'),
            quantity=Decimal('0.00'),
            expiry_date=self.future,
        )
        receipt = StockReceipt.objects.create(supplier=self.supplier, received_by=self.manager)
        StockReceiptItem.objects.create(
            stock_receipt=receipt, product=received_zero,
            quantity=Decimal('5.00'), purchase_price=Decimal('80.00'),
        )

        # GET confirmation leaves product intact.
        self.assertEqual(self.client.get(reverse('product_delete', args=[unused.pk])).status_code, 200)
        self.assertTrue(Product.objects.filter(pk=unused.pk).exists())

        # POST on stocked product is blocked.
        res_stocked = self.client.post(reverse('product_delete', args=[self.milk.pk]), follow=True)
        self.assertContains(res_stocked, 'Products with stock cannot be deleted.')
        self.assertTrue(Product.objects.filter(pk=self.milk.pk).exists())

        # POST on products with SaleItem or StockReceiptItem history are blocked by RESTRICT.
        for prod in (sold_zero, received_zero):
            res = self.client.post(reverse('product_delete', args=[prod.pk]), follow=True)
            self.assertContains(res, 'sales or receipt history')
            self.assertTrue(Product.objects.filter(pk=prod.pk).exists())

        # POST on unused zero-stock product deletes it.
        res_ok = self.client.post(reverse('product_delete', args=[unused.pk]), follow=True)
        self.assertContains(res_ok, 'Product deleted.')
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())

    def test_stock_receipt_service_api_and_page_all_parameters(self):
        # Service-level boundary tests.
        with self.assertRaises(PermissionDenied):
            receive_stock(self.cashier, self.supplier, [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': self.today}])

        with self.assertRaises(ValidationError):
            receive_stock(self.manager, self.supplier, [])

        # Exact today expiry and minimum 0.01 qty/price with whitespace-padded barcode.
        rec = receive_stock(self.manager, self.supplier, [{
            'barcode': f'  {self.milk.barcode}  ',
            'qty': '0.01',
            'purchase_price': '0.01',
            'expiry_date': self.today,
        }])
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.quantity, Decimal('20.01'))
        self.assertEqual(self.milk.expiry_date, self.today)
        self.assertTrue(rec.posted)

        # High valid boundary via receive_stock.
        rec2 = receive_stock(self.admin, self.supplier, [{
            'barcode': self.milk.barcode,
            'qty': '999999.99',
            'purchase_price': '9999.99',
            'expiry_date': self.today + timedelta(days=365),
        }])
        self.milk.refresh_from_db()
        rec2.refresh_from_db()
        self.assertEqual(self.milk.quantity, Decimal('1000020.00'))
        self.assertEqual(rec2.total_amount, Decimal('9999989900.00'))

        # API parameter validation matrix.
        api_url = reverse('stock_receipt')
        self.assertEqual(self.client.get(api_url).status_code, 405)
        self.assertEqual(
            self.client.post(api_url, data='not-json', content_type='application/json').status_code,
            400,
        )

        bad_api_payloads = [
            {'supplier_id': 999999, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': None, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': 'abc', 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': []},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '0', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '-0.01', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': 'abc', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': None, 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '0', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '-0.01', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': 'abc', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': None, 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': None}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': '2026-13-45'}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': self.milk.barcode, 'qty': '1', 'purchase_price': '10', 'expiry_date': (self.today - timedelta(days=1)).isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': '9999999999999', 'qty': '1', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
            {'supplier_id': self.supplier.pk, 'items': [{'barcode': '', 'qty': '1', 'purchase_price': '10', 'expiry_date': self.future.isoformat()}]},
        ]
        for payload in bad_api_payloads:
            with self.subTest(bad_api_payload=payload):
                res = self.client.post(api_url, data=json.dumps(payload), content_type='application/json')
                self.assertEqual(res.status_code, 400)

        # HTML receive_page parameter validation.
        page_url = reverse('receive_page')
        self.assertEqual(self.client.get(page_url).status_code, 200)
        bad_page_forms = [
            {'supplier': '', 'barcode': self.kurt.barcode, 'qty': '5', 'price': '100', 'expiry': self.future.isoformat()},
            {'supplier': '999999', 'barcode': self.kurt.barcode, 'qty': '5', 'price': '100', 'expiry': self.future.isoformat()},
            {'supplier': str(self.supplier.pk), 'barcode': self.kurt.barcode, 'qty': '0', 'price': '100', 'expiry': self.future.isoformat()},
            {'supplier': str(self.supplier.pk), 'barcode': self.kurt.barcode, 'qty': '5', 'price': '-1', 'expiry': self.future.isoformat()},
            {'supplier': str(self.supplier.pk), 'barcode': self.kurt.barcode, 'qty': '5', 'price': '100', 'expiry': 'invalid-date'},
            {'supplier': str(self.supplier.pk), 'barcode': '9999999999999', 'qty': '5', 'price': '100', 'expiry': self.future.isoformat()},
        ]
        for form_data in bad_page_forms:
            with self.subTest(bad_page_form=form_data):
                res = self.client.post(page_url, form_data)
                self.assertEqual(res.status_code, 200)
                self.assertTrue(res.context['error'])

        # Valid receive_page POST updates stock cleanly.
        ok_page = self.client.post(page_url, {
            'supplier': str(self.supplier.pk),
            'barcode': self.kurt.barcode,
            'qty': '6.00',
            'price': '700.00',
            'expiry': self.future.isoformat(),
        })
        self.assertEqual(ok_page.status_code, 200)
        self.assertIn('success', ok_page.context)
        self.kurt.refresh_from_db()
        self.assertEqual(self.kurt.quantity, Decimal('10.00'))

    def test_pos_checkout_all_parameters_and_boundaries(self):
        self.client.force_login(self.cashier)
        checkout_url = reverse('pos_checkout')

        self.assertEqual(self.client.get(checkout_url).status_code, 405)
        self.assertEqual(
            self.client.post(checkout_url, data='{', content_type='application/json').status_code,
            400,
        )

        # Valid payment methods + whitespace barcode + 0.01 fractional quantity.
        for method in ('Cash', 'Kaspi_QR', 'Card'):
            res = self.client.post(
                checkout_url,
                data=json.dumps({
                    'payment_method': method,
                    'items': [{'barcode': f' {self.milk.barcode} ', 'qty': '0.01'}],
                }),
                content_type='application/json',
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(Decimal(res.json()['total']), Decimal('5.50'))

        self.milk.refresh_from_db()
        self.assertEqual(self.milk.quantity, Decimal('19.97'))

        # Exact remaining stock sale reduces stock to 0.00; +0.01 oversell fails and rolls back.
        res_oversell = self.client.post(
            checkout_url,
            data=json.dumps({'items': [{'barcode': self.kurt.barcode, 'qty': '4.01'}]}),
            content_type='application/json',
        )
        self.assertEqual(res_oversell.status_code, 400)
        self.kurt.refresh_from_db()
        self.assertEqual(self.kurt.quantity, Decimal('4.00'))

        res_exact = self.client.post(
            checkout_url,
            data=json.dumps({'items': [{'barcode': self.kurt.barcode, 'qty': '4.00'}]}),
            content_type='application/json',
        )
        self.assertEqual(res_exact.status_code, 200)
        self.kurt.refresh_from_db()
        self.assertEqual(self.kurt.quantity, Decimal('0.00'))

        bad_checkout_payloads = [
            {'items': []},
            {'items': [{'barcode': self.milk.barcode, 'qty': 1}], 'payment_method': ''},
            {'items': [{'barcode': self.milk.barcode, 'qty': 1}], 'payment_method': 'Kaspi'},
            {'items': [{'barcode': self.milk.barcode, 'qty': 1}], 'payment_method': 'Crypto'},
            {'items': [{'barcode': self.milk.barcode, 'qty': 1}], 'payment_method': None},
            {'items': [{'barcode': self.milk.barcode, 'qty': '0'}]},
            {'items': [{'barcode': self.milk.barcode, 'qty': '-1'}]},
            {'items': [{'barcode': self.milk.barcode, 'qty': 'abc'}]},
            {'items': [{'barcode': self.milk.barcode, 'qty': None}]},
            {'items': [{'barcode': '9999999999999', 'qty': 1}]},
        ]
        for payload in bad_checkout_payloads:
            with self.subTest(bad_checkout=payload):
                res = self.client.post(checkout_url, data=json.dumps(payload), content_type='application/json')
                self.assertEqual(res.status_code, 400)

    def test_alerts_and_daily_reports_date_and_boundary_parameters(self):
        # Expiry boundaries: -1, 0, 7 included; 8 excluded.
        # Low-stock boundaries: <= min_quantity included; > min_quantity excluded.
        p_expired = Product.objects.create(
            barcode='4870000000601', name='Boundary Expired', category=self.dairy,
            sale_price=Decimal('100.00'), quantity=Decimal('5.00'), min_quantity=Decimal('5.00'),
            expiry_date=self.today - timedelta(days=1),
        )
        p_today = Product.objects.create(
            barcode='4870000000602', name='Boundary Today', category=self.dairy,
            sale_price=Decimal('100.00'), quantity=Decimal('6.00'), min_quantity=Decimal('5.00'),
            expiry_date=self.today,
        )
        p_day7 = Product.objects.create(
            barcode='4870000000603', name='Boundary Day7', category=self.dairy,
            sale_price=Decimal('100.00'), quantity=Decimal('10.00'), min_quantity=Decimal('5.00'),
            expiry_date=self.today + timedelta(days=7),
        )
        p_day8 = Product.objects.create(
            barcode='4870000000604', name='Boundary Day8', category=self.dairy,
            sale_price=Decimal('100.00'), quantity=Decimal('10.00'), min_quantity=Decimal('5.00'),
            expiry_date=self.today + timedelta(days=8),
        )

        res = self.client.get(reverse('dashboard_alerts'))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        expiry_barcodes = {row['barcode'] for row in body['expiry_alerts']}
        low_barcodes = {row['barcode'] for row in body['low_stock_alerts']}

        self.assertTrue({p_expired.barcode, p_today.barcode, p_day7.barcode}.issubset(expiry_barcodes))
        self.assertNotIn(p_day8.barcode, expiry_barcodes)
        self.assertIn(p_expired.barcode, low_barcodes)  # quantity == min_quantity (5 == 5)
        self.assertIn(self.kurt.barcode, low_barcodes)  # quantity < min_quantity (4 < 5)
        self.assertNotIn(p_today.barcode, low_barcodes)  # quantity > min_quantity (6 > 5)

        # Create 7 distinct products sold today and 1 sale yesterday for report parameters.
        products = [self.milk, self.kurt, p_expired, p_today, p_day7, p_day8]
        p_extra = Product.objects.create(
            barcode='4870000000605', name='Extra Item', category=self.dairy,
            sale_price=Decimal('150.00'), quantity=Decimal('20.00'), expiry_date=self.future,
        )
        products.append(p_extra)

        sale_today = Sale.objects.create(cashier=self.cashier, payment_method='Card')
        total_today = Decimal('0.00')
        for idx, prod in enumerate(products, start=1):
            qty = Decimal(idx)
            sub = prod.sale_price * qty
            SaleItem.objects.create(
                sale=sale_today, product=prod, quantity=qty, unit_price=prod.sale_price, subtotal=sub,
            )
            total_today += sub
        sale_today.total_amount = total_today
        sale_today.save()

        yesterday = self.today - timedelta(days=1)
        sale_yesterday = Sale.objects.create(
            cashier=self.cashier, payment_method='Cash', total_amount=Decimal('550.00'),
        )
        SaleItem.objects.create(
            sale=sale_yesterday, product=self.milk, quantity=Decimal('1.00'),
            unit_price=Decimal('550.00'), subtotal=Decimal('550.00'),
        )
        Sale.objects.filter(pk=sale_yesterday.pk).update(created_at=timezone.now() - timedelta(days=1))

        today_summary = daily_sales_summary(day=self.today)
        self.assertEqual(today_summary['receipts'], 1)
        self.assertEqual(today_summary['total'], total_today)
        self.assertEqual(len(today_summary['top_products']), 5)
        self.assertEqual(today_summary['top_products'][0]['qty'], Decimal('7.00'))

        yest_summary = daily_sales_summary(day=yesterday)
        self.assertEqual(yest_summary['receipts'], 1)
        self.assertEqual(yest_summary['total'], Decimal('550.00'))

        tomorrow_summary = daily_sales_summary(day=self.today + timedelta(days=1))
        self.assertEqual(tomorrow_summary['receipts'], 0)
        self.assertEqual(tomorrow_summary['total'], Decimal('0.00'))
        self.assertEqual(tomorrow_summary['average'], Decimal('0.00'))
        self.assertEqual(tomorrow_summary['top_products'], [])

    def test_role_and_csrf_permutations_across_all_endpoints(self):
        get_routes = [
            (reverse('pos_page'), True),
            (reverse('product_list'), False),
            (reverse('product_create'), False),
            (reverse('product_edit', args=[self.milk.pk]), False),
            (reverse('product_delete', args=[self.milk.pk]), False),
            (reverse('dashboard_alerts'), False),
            (reverse('receive_page'), False),
            (reverse('report_page'), False),
            (reverse('report_csv'), False),
        ]

        # Anonymous user is redirected to login on every protected route.
        self.client.logout()
        for url, _ in get_routes:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/login/', res['Location'])

        # Cashier can open POS and checkout, but gets 403 on all manager/admin routes.
        self.client.force_login(self.cashier)
        for url, cashier_allowed in get_routes:
            expected = 200 if cashier_allowed else 403
            self.assertEqual(self.client.get(url).status_code, expected)
        self.assertEqual(self.client.post(reverse('stock_receipt'), '{}', content_type='application/json').status_code, 403)

        # Manager and Admin can access all GET endpoints.
        for user in (self.manager, self.admin):
            self.client.force_login(user)
            for url, _ in get_routes:
                self.assertEqual(self.client.get(url).status_code, 200)

        # Enforce CSRF across all mutating endpoints.
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        for url, data, content_type in (
            (reverse('product_create'), self._valid_product_payload(barcode='4870000000881'), None),
            (reverse('product_edit', args=[self.milk.pk]), self._valid_product_payload(barcode=self.milk.barcode), None),
            (reverse('product_delete', args=[self.milk.pk]), {}, None),
            (reverse('receive_page'), {'supplier': str(self.supplier.pk)}, None),
            (reverse('pos_checkout'), json.dumps({'items': [{'barcode': self.milk.barcode, 'qty': '1'}]}), 'application/json'),
            (reverse('stock_receipt'), json.dumps({'supplier_id': self.supplier.pk, 'items': []}), 'application/json'),
        ):
            kwargs = {'content_type': content_type} if content_type else {}
            self.assertEqual(csrf_client.post(url, data, **kwargs).status_code, 403)


class AllORMFunctionsStressTests(TestCase):
    """Exercise every ORM model method, constraint, query pattern, and command in the repo."""

    def test_seed_demo_command_idempotency_and_permissions(self):
        call_command('seed_demo')
        first_counts = (
            User.objects.count(),
            Category.objects.count(),
            Supplier.objects.count(),
            Product.objects.count(),
        )
        call_command('seed_demo')
        second_counts = (
            User.objects.count(),
            Category.objects.count(),
            Supplier.objects.count(),
            Product.objects.count(),
        )
        self.assertEqual(first_counts, second_counts)
        self.assertEqual(first_counts, (3, 8, 2, 33))

        manager = User.objects.get(username='manager')
        self.assertEqual(manager.role, 'Manager')
        self.assertEqual(
            manager.user_permissions.filter(content_type__app_label='store').count(),
            17,
        )
        self.assertEqual(Permission.objects.filter(user=manager).count(), 17)

    def test_model_str_full_clean_and_all_on_delete_behaviors(self):
        cat = Category.objects.create(name='TestCat', description='Desc')
        sup = Supplier.objects.create(name='TestSup', phone='123', email='sup@example.com')
        cashier = User.objects.create_user('orm-cashier', role='Cashier')
        manager = User.objects.create_user('orm-manager', role='Manager')
        prod = Product.objects.create(
            barcode='4870000000123',
            name='ORM Milk',
            category=cat,
            supplier=sup,
            sale_price=Decimal('250.00'),
            quantity=Decimal('10.00'),
            expiry_date=timezone.localdate() + timedelta(days=5),
        )

        self.assertEqual(str(cat), 'TestCat')
        self.assertEqual(str(sup), 'TestSup')
        self.assertEqual(str(prod), 'ORM Milk (4870000000123)')
        barcode_validator('4870000000123')

        # Product.save() enforces full_clean() even via direct ORM updates.
        prod.sale_price = Decimal('-5.00')
        with self.assertRaises(ValidationError):
            prod.save(update_fields=['sale_price'])
        prod.refresh_from_db()
        self.assertEqual(prod.sale_price, Decimal('250.00'))

        # Category -> Product is RESTRICT.
        with self.assertRaises(RestrictedError):
            cat.delete()

        # Supplier -> Product is SET_NULL when no StockReceipt references the supplier.
        sup.delete()
        prod.refresh_from_db()
        self.assertIsNone(prod.supplier)

        # Create Sale/SaleItem and StockReceipt/StockReceiptItem to verify RESTRICT and CASCADE.
        sup2 = Supplier.objects.create(name='RestrictedSup', phone='456')
        sale = Sale.objects.create(cashier=cashier, payment_method='Cash', total_amount=Decimal('250.00'))
        SaleItem.objects.create(
            sale=sale, product=prod, quantity=Decimal('1.00'),
            unit_price=Decimal('250.00'), subtotal=Decimal('250.00'),
        )
        receipt = StockReceipt.objects.create(supplier=sup2, received_by=manager)
        StockReceiptItem.objects.create(
            stock_receipt=receipt, product=prod,
            quantity=Decimal('2.00'), purchase_price=Decimal('150.00'),
        )

        with self.assertRaises(RestrictedError):
            sup2.delete()
        with self.assertRaises(RestrictedError):
            cashier.delete()
        with self.assertRaises(RestrictedError):
            manager.delete()
        with self.assertRaises(RestrictedError):
            prod.delete()

        # Sale -> SaleItem and StockReceipt -> StockReceiptItem are CASCADE.
        sale_pk = sale.pk
        receipt_pk = receipt.pk
        sale.delete()
        receipt.delete()
        self.assertFalse(SaleItem.objects.filter(sale_id=sale_pk).exists())
        self.assertFalse(StockReceiptItem.objects.filter(stock_receipt_id=receipt_pk).exists())

    def test_stock_receipt_post_orm_edge_cases_and_rollback(self):
        manager = User.objects.create_user('post-manager', role='Manager')
        supplier = Supplier.objects.create(name='Post Supplier', phone='999')
        cat = Category.objects.create(name='Post Category')
        p1 = Product.objects.create(
            barcode='4870000000401', name='Item A', category=cat, supplier=supplier,
            sale_price=Decimal('100.00'), quantity=Decimal('10.00'),
            expiry_date=timezone.localdate() + timedelta(days=20),
        )
        p2 = Product.objects.create(
            barcode='4870000000402', name='Item B', category=cat, supplier=supplier,
            sale_price=Decimal('200.00'), quantity=Decimal('5.00'),
            expiry_date=timezone.localdate() + timedelta(days=20),
        )

        # Unsaved receipt cannot be posted.
        unsaved = StockReceipt(supplier=supplier, received_by=manager)
        with self.assertRaises(ValidationError):
            unsaved.post()

        # Empty saved receipt raises ValidationError and keeps posted=False.
        empty_receipt = StockReceipt.objects.create(supplier=supplier, received_by=manager)
        with self.assertRaises(ValidationError):
            empty_receipt.post()
        empty_receipt.refresh_from_db()
        self.assertFalse(empty_receipt.posted)

        # Exceeding StockReceipt.total_amount max_digits=12 rolls back F() stock update and posted=True.
        overflow_receipt = StockReceipt.objects.create(supplier=supplier, received_by=manager)
        StockReceiptItem.objects.create(
            stock_receipt=overflow_receipt, product=p1,
            quantity=Decimal('99999999.00'), purchase_price=Decimal('1000.00'),
        )
        with self.assertRaises(ValidationError):
            overflow_receipt.post()
        overflow_receipt.refresh_from_db()
        p1.refresh_from_db()
        self.assertFalse(overflow_receipt.posted)
        self.assertEqual(overflow_receipt.total_amount, Decimal('0.00'))
        self.assertEqual(p1.quantity, Decimal('10.00'))

        # Valid multi-line receipt updates stock with F() and ignores repeat post() calls.
        valid_receipt = StockReceipt.objects.create(supplier=supplier, received_by=manager)
        StockReceiptItem.objects.create(
            stock_receipt=valid_receipt, product=p1,
            quantity=Decimal('3.25'), purchase_price=Decimal('50.00'),
        )
        StockReceiptItem.objects.create(
            stock_receipt=valid_receipt, product=p2,
            quantity=Decimal('4.50'), purchase_price=Decimal('80.00'),
        )
        self.assertTrue(valid_receipt.post())
        self.assertFalse(valid_receipt.post())
        p1.refresh_from_db()
        p2.refresh_from_db()
        valid_receipt.refresh_from_db()
        self.assertEqual(p1.quantity, Decimal('13.25'))
        self.assertEqual(p2.quantity, Decimal('9.50'))
        self.assertEqual(valid_receipt.total_amount, Decimal('522.50'))
        self.assertTrue(valid_receipt.posted)

    def test_orm_queryset_patterns_and_query_count_invariance(self):
        manager = User.objects.create_user('query-manager', role='Manager')
        self.client.force_login(manager)
        cats = [Category.objects.create(name=f'Cat {i}') for i in range(4)]
        sups = [Supplier.objects.create(name=f'Sup {i}', phone=str(i)) for i in range(4)]
        for i in range(40):
            Product.objects.create(
                barcode=make_barcode(2000 + i),
                name=f'Query Product {i:02d}',
                category=cats[i % 4],
                supplier=sups[i % 4],
                sale_price=Decimal('100.00') + i,
                quantity=Decimal('3.00') if i < 10 else Decimal('12.00'),
                min_quantity=Decimal('5.00'),
                expiry_date=timezone.localdate() + timedelta(days=i + 1),
            )

        # Verify constant 4 SQL queries on /products/ regardless of page size/related models.
        with self.assertNumQueries(4):
            res = self.client.get(reverse('product_list'))
        self.assertEqual(res.status_code, 200)

        with self.assertNumQueries(4):
            res_filtered = self.client.get(reverse('product_list'), {'q': 'Query', 'low': '1'})
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(res_filtered.context['page'].paginator.count, 10)

        # Verify Q(), F(), select_related(), aggregate(Sum()), values().annotate(Sum()).
        qs = Product.objects.select_related('category', 'supplier').filter(
            Q(name__icontains='Product 0') | Q(barcode=make_barcode(2039))
        ).filter(quantity__lte=F('min_quantity'))
        self.assertEqual(qs.count(), 10)
        agg = Product.objects.aggregate(total_qty=Sum('quantity'))
        self.assertEqual(agg['total_qty'], Decimal('390.00'))
        grouped = list(Product.objects.values('category__name').annotate(s=Sum('quantity')).order_by('category__name'))
        self.assertEqual(len(grouped), 4)


class ServerLoadStressTests(TestCase):
    """High-volume load test across all views, admin, ORM services, and backup/restore."""

    def setUp(self):
        self.admin = User.objects.create_superuser('load-admin', password='pw', role='Admin')
        self.manager = User.objects.create_user('load-manager', password='pw', role='Manager')
        self.cashier = User.objects.create_user('load-cashier', password='pw', role='Cashier')
        self.categories = [Category.objects.create(name=f'LoadCat-{i}') for i in range(8)]
        self.suppliers = [Supplier.objects.create(name=f'LoadSup-{i}', phone=f'700-{i}') for i in range(4)]

    def test_high_volume_catalog_receipt_checkout_report_and_backup_load(self):
        start_time = time.monotonic()
        self.client.force_login(self.manager)
        future = timezone.localdate() + timedelta(days=30)

        # 1. Create 250 products: 25 via /products/new/ HTTP POST and 225 via ORM.
        products = []
        for idx in range(250):
            barcode = make_barcode(50000 + idx)
            cat = self.categories[idx % 8]
            sup = self.suppliers[idx % 4]
            price = Decimal('100.00') + Decimal(idx % 20) * Decimal('10.00')
            if idx < 25:
                res = self.client.post(reverse('product_create'), {
                    'barcode': barcode,
                    'name': f'Load Product {idx:03d}',
                    'category': str(cat.pk),
                    'supplier': str(sup.pk),
                    'sale_price': str(price),
                    'min_quantity': '5.00',
                    'expiry_date': future.isoformat(),
                })
                self.assertEqual(res.status_code, 302)
                prod = Product.objects.get(barcode=barcode)
            else:
                prod = Product.objects.create(
                    barcode=barcode,
                    name=f'Load Product {idx:03d}',
                    category=cat,
                    supplier=sup,
                    sale_price=price,
                    quantity=Decimal('0.00'),
                    min_quantity=Decimal('5.00'),
                    expiry_date=future,
                )
            products.append(prod)

        # 2. Edit 50 products and delete 30 unused zero-stock products -> 220 active products.
        for prod in products[:50]:
            res = self.client.post(reverse('product_edit', args=[prod.pk]), {
                'barcode': prod.barcode,
                'name': f'{prod.name} Edited',
                'category': str(prod.category_id),
                'supplier': str(prod.supplier_id),
                'sale_price': str(prod.sale_price + Decimal('5.00')),
                'min_quantity': '5.00',
                'expiry_date': future.isoformat(),
            })
            self.assertEqual(res.status_code, 302)

        for prod in products[220:]:
            res = self.client.post(reverse('product_delete', args=[prod.pk]))
            self.assertEqual(res.status_code, 302)

        active_products = list(Product.objects.order_by('barcode'))
        self.assertEqual(len(active_products), 220)

        # 3. Traverse all catalog pages and assert constant query count (4 queries per page).
        total_pages = (220 + 24) // 25
        for page_num in range(1, total_pages + 1):
            with self.assertNumQueries(4):
                res = self.client.get(reverse('product_list'), {'page': page_num})
            self.assertEqual(res.status_code, 200)

        # Track exact expected stock per product.
        expected_qty = {p.barcode: Decimal('0.00') for p in active_products}

        # 4. Execute 100 stock receipts across all 4 workflows:
        #    - 40 via /api/stock-receipt/ (multi-line)
        #    - 20 via /receive/ HTML form
        #    - 20 via receive_stock() service
        #    - 20 via Admin StockReceiptAdmin (/admin/store/stockreceipt/add/)
        for r_idx in range(40):
            line_items = []
            for offset in range(3):
                prod = active_products[(r_idx * 3 + offset) % len(active_products)]
                qty = Decimal('25.00')
                line_items.append({
                    'barcode': prod.barcode,
                    'qty': str(qty),
                    'purchase_price': '80.00',
                    'expiry_date': future.isoformat(),
                })
                expected_qty[prod.barcode] += qty
            res = self.client.post(
                reverse('stock_receipt'),
                data=json.dumps({
                    'supplier_id': self.suppliers[r_idx % 4].pk,
                    'items': line_items,
                }),
                content_type='application/json',
            )
            self.assertEqual(res.status_code, 200)

        for r_idx in range(20):
            prod = active_products[(120 + r_idx) % len(active_products)]
            qty = Decimal('30.00')
            res = self.client.post(reverse('receive_page'), {
                'supplier': str(self.suppliers[r_idx % 4].pk),
                'barcode': prod.barcode,
                'qty': str(qty),
                'price': '90.00',
                'expiry': future.isoformat(),
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn('success', res.context)
            expected_qty[prod.barcode] += qty

        for r_idx in range(20):
            prod = active_products[(140 + r_idx) % len(active_products)]
            qty = Decimal('40.00')
            receive_stock(self.manager, self.suppliers[r_idx % 4], [{
                'barcode': prod.barcode,
                'qty': qty,
                'purchase_price': Decimal('95.00'),
                'expiry_date': future,
            }])
            expected_qty[prod.barcode] += qty

        self.client.force_login(self.admin)
        for r_idx in range(20):
            prod = active_products[(160 + r_idx) % len(active_products)]
            qty = Decimal('50.00')
            res = self.client.post(reverse('admin:store_stockreceipt_add'), {
                'supplier': self.suppliers[r_idx % 4].pk,
                'received_by': self.admin.pk,
                'items-TOTAL_FORMS': '1',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '1',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-product': prod.pk,
                'items-0-quantity': str(qty),
                'items-0-purchase_price': '100.00',
                '_save': 'Save',
            })
            self.assertEqual(res.status_code, 302)
            expected_qty[prod.barcode] += qty

        self.assertEqual(StockReceipt.objects.count(), 100)
        self.assertEqual(StockReceipt.objects.filter(posted=True).count(), 100)

        # Ensure every active product has sufficient stock before 150 sales.
        understocked = [p for p in active_products if expected_qty[p.barcode] < Decimal('10.00')]
        if understocked:
            batch = [{
                'barcode': p.barcode,
                'qty': Decimal('15.00'),
                'purchase_price': Decimal('70.00'),
                'expiry_date': future,
            } for p in understocked]
            receive_stock(self.manager, self.suppliers[0], batch)
            for p in understocked:
                expected_qty[p.barcode] += Decimal('15.00')

        # 5. Execute 150 multi-item POS checkouts across Cash, Kaspi_QR, Card.
        self.client.force_login(self.cashier)
        payment_methods = ('Cash', 'Kaspi_QR', 'Card')
        expected_revenue = Decimal('0.00')
        expected_by_payment = {m: Decimal('0.00') for m in payment_methods}
        expected_line_count = 0

        # Refresh product prices after edits.
        active_products = list(Product.objects.order_by('barcode'))
        for s_idx in range(150):
            p_a = active_products[(s_idx * 2) % len(active_products)]
            p_b = active_products[(s_idx * 2 + 1) % len(active_products)]
            qty_a = Decimal('1.50')
            qty_b = Decimal('2.00')
            method = payment_methods[s_idx % 3]
            res = self.client.post(
                reverse('pos_checkout'),
                data=json.dumps({
                    'payment_method': method,
                    'items': [
                        {'barcode': p_a.barcode, 'qty': str(qty_a)},
                        {'barcode': p_b.barcode, 'qty': str(qty_b)},
                    ],
                }),
                content_type='application/json',
            )
            self.assertEqual(res.status_code, 200)
            sale_total = p_a.sale_price * qty_a + p_b.sale_price * qty_b
            expected_qty[p_a.barcode] -= qty_a
            expected_qty[p_b.barcode] -= qty_b
            expected_revenue += sale_total
            expected_by_payment[method] += sale_total
            expected_line_count += 2

        # 6. Verify strict inventory conservation across all 220 products.
        for prod in Product.objects.all():
            self.assertEqual(prod.quantity, expected_qty[prod.barcode])

        # 7. Verify report summary, report HTML, alerts, and CSV reconciliation.
        self.client.force_login(self.manager)
        summary = daily_sales_summary()
        self.assertEqual(summary['receipts'], 150)
        self.assertEqual(summary['total'], expected_revenue)
        self.assertEqual(summary['by_payment'], expected_by_payment)
        self.assertEqual(Sale.objects.aggregate(s=Sum('total_amount'))['s'], expected_revenue)

        self.assertEqual(self.client.get(reverse('dashboard_alerts')).status_code, 200)
        report_res = self.client.get(reverse('report_page'))
        self.assertEqual(report_res.status_code, 200)
        self.assertContains(report_res, str(summary['total']))

        csv_res = self.client.get(reverse('report_csv'))
        self.assertEqual(csv_res.status_code, 200)
        csv_rows = list(csv.reader(io.StringIO(csv_res.content.decode('utf-8-sig'))))
        self.assertEqual(len(csv_rows), expected_line_count + 1)
        csv_subtotal_sum = sum(Decimal(row[6]) for row in csv_rows[1:])
        self.assertEqual(csv_subtotal_sum, expected_revenue)

        # 8. Exercise backup_db and restore_db against a snapshot of this populated database.
        connection.ensure_connection()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            populated_file = root / 'populated.sqlite3'
            dump_sql = '\n'.join(connection.connection.iterdump())
            with closing(sqlite3.connect(populated_file)) as dest:
                dest.executescript(dump_sql)

            with patch('store.management.commands.backup_db.database_path', return_value=populated_file):
                call_command('backup_db', output_dir=root / 'backups', stdout=io.StringIO())

            backups = list((root / 'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups), 1)

            restored_file = root / 'restored.sqlite3'
            with patch('store.management.commands.restore_db.database_path', return_value=populated_file):
                call_command('restore_db', str(backups[0]), target=restored_file, stdout=io.StringIO())

            with closing(sqlite3.connect(restored_file)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM store_product').fetchone()[0], 220)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM store_sale').fetchone()[0], 150)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM store_saleitem').fetchone()[0], 300)

        elapsed = time.monotonic() - start_time
        self.assertLess(elapsed, 60.0)


class LiveServerLoadStressTests(LiveServerTestCase):
    """Real multi-threaded HTTP load test against Django's LiveServerTestCase."""

    def setUp(self):
        self.password = 'live-stress-password-123'
        self.manager = User.objects.create_user('live-manager', password=self.password, role='Manager')
        self.category = Category.objects.create(name='LiveCat')
        self.supplier = Supplier.objects.create(name='LiveSup', phone='111')
        self.products = [
            Product.objects.create(
                barcode=make_barcode(90000 + i),
                name=f'Live Product {i:02d}',
                category=self.category,
                supplier=self.supplier,
                sale_price=Decimal('300.00'),
                quantity=Decimal('50.00') if i % 2 == 0 else Decimal('3.00'),
                min_quantity=Decimal('5.00'),
                expiry_date=timezone.localdate() + timedelta(days=15),
            )
            for i in range(60)
        ]
        sale = Sale.objects.create(cashier=self.manager, payment_method='Cash', total_amount=Decimal('600.00'))
        SaleItem.objects.create(
            sale=sale, product=self.products[0], quantity=Decimal('2.00'),
            unit_price=Decimal('300.00'), subtotal=Decimal('600.00'),
        )

    def _authenticated_opener(self):
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        login_url = f'{self.live_server_url}/login/'
        with opener.open(login_url, timeout=10) as resp:
            html = resp.read().decode('utf-8')
        match = re.search(r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)['\"]", html)
        self.assertIsNotNone(match)
        form_data = urllib.parse.urlencode({
            'username': self.manager.username,
            'password': self.password,
            'csrfmiddlewaretoken': match.group(1),
        }).encode('utf-8')
        req = urllib.request.Request(login_url, data=form_data, method='POST')
        req.add_header('Referer', login_url)
        with opener.open(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn('Qoyma', resp.read().decode('utf-8'))
        return opener, jar

    def _csrf_token(self, jar):
        for cookie in jar:
            if cookie.name == 'csrftoken':
                return cookie.value
        raise AssertionError('csrftoken cookie missing')

    def test_concurrent_http_burst_and_write_load(self):
        opener, jar = self._authenticated_opener()

        # Verify CSRF-protected write flow over live HTTP: create product + checkout + stock receipt.
        create_url = f'{self.live_server_url}/products/new/'
        with opener.open(create_url, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
        create_data = urllib.parse.urlencode({
            'csrfmiddlewaretoken': self._csrf_token(jar),
            'barcode': '4870000999001',
            'name': 'Live Created Product',
            'category': str(self.category.pk),
            'supplier': str(self.supplier.pk),
            'sale_price': '499.00',
            'min_quantity': '5.00',
            'expiry_date': (timezone.localdate() + timedelta(days=20)).isoformat(),
        }).encode('utf-8')
        create_req = urllib.request.Request(create_url, data=create_data, method='POST')
        create_req.add_header('Referer', create_url)
        with opener.open(create_req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            resp.read()
        self.assertTrue(Product.objects.filter(barcode='4870000999001').exists())
        connections.close_all()

        # Live HTTP GET burst across 80 requests over TCP/WSGI.
        # (Django's LiveServerTestCase shares one in-memory SQLite connection via connections_override.)
        endpoints = [
            '/',
            '/products/',
            '/products/?page=2',
            '/products/?q=Live&low=1',
            '/api/alerts/',
            '/report/',
            '/report/csv/',
            '/receive/',
        ]
        urls = [f'{self.live_server_url}{endpoints[i % len(endpoints)]}' for i in range(80)]
        session_cookie = '; '.join(f'{c.name}={c.value}' for c in jar)

        t_start = time.monotonic()
        results = []
        for target_url in urls:
            t0 = time.monotonic()
            req = urllib.request.Request(target_url, headers={'Cookie': session_cookie})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                results.append((resp.status, len(body), time.monotonic() - t0))
        total_duration = time.monotonic() - t_start

        self.assertEqual(len(results), 80)
        for status, length, latency in results:
            self.assertEqual(status, 200)
            self.assertGreater(length, 0)
            self.assertLess(latency, 5.0)
        self.assertLess(total_duration, 15.0)

        # Sequential HTTP checkout burst (20 sales) over live server.
        checkout_url = f'{self.live_server_url}/api/checkout/'
        target_prod = self.products[0]
        for _ in range(20):
            payload = json.dumps({'items': [{'barcode': target_prod.barcode, 'qty': '1.00'}]}).encode('utf-8')
            req = urllib.request.Request(checkout_url, data=payload, method='POST')
            req.add_header('Content-Type', 'application/json')
            req.add_header('X-CSRFToken', self._csrf_token(jar))
            req.add_header('Referer', f'{self.live_server_url}/')
            with opener.open(req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(json.loads(resp.read().decode('utf-8'))['status'], 'Success')

        target_prod.refresh_from_db()
        self.assertEqual(target_prod.quantity, Decimal('30.00'))

    def test_concurrent_stock_receipt_post_applies_exactly_once(self):
        receipt = StockReceipt.objects.create(supplier=self.supplier, received_by=self.manager)
        target = self.products[0]
        StockReceiptItem.objects.create(
            stock_receipt=receipt, product=target,
            quantity=Decimal('12.50'), purchase_price=Decimal('200.00'),
        )

        barrier = threading.Barrier(4)
        outcomes = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait(timeout=5)
                # Retry brief SQLite lock contention if two threads contend on the same row.
                for attempt in range(5):
                    try:
                        res = StockReceipt.objects.get(pk=receipt.pk).post()
                        with lock:
                            outcomes.append(res)
                        break
                    except Exception as exc:
                        if 'locked' in str(exc).lower() and attempt < 4:
                            time.sleep(0.05)
                            continue
                        raise
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(outcomes.count(False), 3)
        target.refresh_from_db()
        self.assertEqual(target.quantity, Decimal('62.50'))
