"""Qoyma ERP — automated verification tests.

Part 1 (V-01..V-05): data quality rules from Task 7 (Data Dictionary + Governance).
Part 2 (AC-01..AC-03): acceptance criteria for the main process (POS checkout).

Run:  python manage.py test store -v 2
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Product, Sale, SaleItem, User


def make_product(**overrides):
    data = {
        'barcode': '4870000000011',
        'name': 'Milk 2.5% 1L',
        'category': Category.objects.get_or_create(name='Dairy')[0],
        'sale_price': Decimal('550.00'),
        'quantity': Decimal('20.00'),
        'expiry_date': timezone.localdate() + timedelta(days=10),
    }
    data.update(overrides)
    return Product.objects.create(**data)


class DataQualityRulesTest(TestCase):
    """Task 7 rules: system must refuse to save bad Product data."""

    def test_v01_valid_product_is_saved(self):
        make_product()
        self.assertEqual(Product.objects.count(), 1)

    def test_v02_empty_quantity_is_rejected(self):
        # Task 7, Record 1: Milk with missing quantity (Completeness error)
        with self.assertRaises(ValidationError):
            make_product(quantity=None)
        self.assertEqual(Product.objects.count(), 0)

    def test_v03_negative_price_is_rejected(self):
        # Task 7, Record 2: Bread with price -190.00 (Validity error)
        with self.assertRaises(ValidationError):
            make_product(sale_price=Decimal('-190.00'))
        self.assertEqual(Product.objects.count(), 0)

    def test_v04_duplicate_barcode_is_rejected(self):
        # Task 7, Records 3-4: two Kefir rows with the same barcode (Uniqueness error)
        make_product(barcode='4870000000028', name='Kefir 1L - A')
        with self.assertRaises(ValidationError):
            make_product(barcode='4870000000028', name='Kefir 1L - B')
        self.assertEqual(Product.objects.count(), 1)

    def test_v05_negative_stock_and_bad_barcode_are_rejected(self):
        # Task 7, Record 5: quantity -5.00; plus barcode that is not 13 digits
        with self.assertRaises(ValidationError):
            make_product(quantity=Decimal('-5.00'))
        with self.assertRaises(ValidationError):
            make_product(barcode='12345')
        self.assertEqual(Product.objects.count(), 0)


class CheckoutAcceptanceTest(TestCase):
    """Acceptance criteria for the main user process: cashier sells products."""

    def setUp(self):
        self.cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        self.manager = User.objects.create_user('manager', password='pass12345', role='Manager')
        self.milk = make_product(barcode='4870000000011', name='Milk', quantity=Decimal('20.00'))
        self.bread = make_product(barcode='4870000000035', name='Bread',
                                  sale_price=Decimal('190.00'), quantity=Decimal('3.00'))

    def checkout(self, items, payment='Cash'):
        return self.client.post(
            reverse('pos_checkout'),
            data=json.dumps({'items': items, 'payment_method': payment}),
            content_type='application/json',
        )

    def test_ac01_sale_deducts_stock_and_saves_price(self):
        """AC-01: After a sale, stock decreases by the sold quantity and the sale is saved."""
        self.client.force_login(self.cashier)
        res = self.checkout([{'barcode': '4870000000011', 'qty': 2}], payment='Kaspi_QR')

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['total'], '1100.00')
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.quantity, Decimal('18.00'))
        sale = Sale.objects.get()
        self.assertEqual(sale.cashier, self.cashier)
        self.assertEqual(sale.payment_method, 'Kaspi_QR')
        self.assertEqual(SaleItem.objects.get().unit_price, Decimal('550.00'))

    def test_ac02_cannot_sell_more_than_stock_and_nothing_is_saved(self):
        """AC-02: Selling more than in stock is refused; the whole sale is rolled back."""
        self.client.force_login(self.cashier)
        res = self.checkout([
            {'barcode': '4870000000011', 'qty': 2},   # OK item
            {'barcode': '4870000000035', 'qty': 5},   # only 3 in stock
        ])

        self.assertEqual(res.status_code, 400)
        self.assertIn('Insufficient stock', res.json()['error'])
        self.milk.refresh_from_db()
        self.bread.refresh_from_db()
        self.assertEqual(self.milk.quantity, Decimal('20.00'))  # milk NOT deducted
        self.assertEqual(self.bread.quantity, Decimal('3.00'))
        self.assertEqual(Sale.objects.count(), 0)               # no half-saved sale

    def test_ac03_cashier_cannot_open_manager_dashboard(self):
        """AC-03: Cashier gets 403 on alerts; Manager sees low-stock alert for Bread."""
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('dashboard_alerts')).status_code, 403)

        self.client.force_login(self.manager)
        res = self.client.get(reverse('dashboard_alerts'))
        self.assertEqual(res.status_code, 200)
        low = [p['name'] for p in res.json()['low_stock_alerts']]
        self.assertIn('Bread', low)

    def test_ac04_not_logged_in_user_is_redirected_to_login(self):
        """Extra: anonymous user cannot sell; redirected to login page."""
        res = self.checkout([{'barcode': '4870000000011', 'qty': 1}])
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res['Location'])
        self.assertEqual(Sale.objects.count(), 0)
