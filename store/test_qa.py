"""Additional integration coverage and explicit regression cases for open defects."""
from datetime import timedelta
from decimal import Decimal
from unittest import expectedFailure

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Sale, SaleItem, StockReceipt, StockReceiptItem, Supplier, User
from .services import receive_stock
from .tests import make_product


class QAIntegrationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user('qa-manager', role='Manager')
        self.product = make_product()
        self.supplier = Supplier.objects.create(name='QA supplier')
        self.client.force_login(self.manager)

    def post_checkout(self, data, client=None):
        return (client or self.client).post(reverse('pos_checkout'), data, content_type='application/json')

    def test_i01_receipt_rolls_back_valid_first_item_when_second_fails(self):
        valid = {'barcode': self.product.barcode, 'qty': '5', 'purchase_price': '100',
                 'expiry_date': timezone.localdate() + timedelta(days=10)}
        with self.assertRaises(ValidationError):
            receive_stock(self.manager, self.supplier, [valid, {**valid, 'barcode': '9999999999999'}])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))
        self.assertEqual(StockReceipt.objects.count(), 0)
        self.assertEqual(StockReceiptItem.objects.count(), 0)

    def test_i02_checkout_invalid_inputs_leave_no_sale(self):
        for data in (
            {'items': []},
            {'items': [{'barcode': self.product.barcode, 'qty': 1}], 'payment_method': 'Bitcoin'},
            {'items': [{'barcode': self.product.barcode, 'qty': 0}]},
            {'items': [{'barcode': self.product.barcode, 'qty': 'abc'}]},
            {'items': [{'barcode': '9999999999999', 'qty': 1}]},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.post_checkout(data).status_code, 400)
                self.assertEqual(Sale.objects.count(), 0)
                self.assertEqual(SaleItem.objects.count(), 0)
                self.product.refresh_from_db()
                self.assertEqual(self.product.quantity, Decimal('20'))

    def test_i03_checkout_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        response = self.post_checkout({'items': [{'barcode': self.product.barcode, 'qty': 1}]}, client)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)

    def test_i04_sale_keeps_price_snapshot_after_catalog_change(self):
        self.assertEqual(self.post_checkout({'items': [{'barcode': self.product.barcode, 'qty': 2}]}).status_code, 200)
        self.product.sale_price = Decimal('999')
        self.product.save()
        self.assertEqual(SaleItem.objects.get().unit_price, Decimal('550'))
        self.assertEqual(Sale.objects.get().total_amount, Decimal('1100'))

    @expectedFailure
    def test_d01_json_array_should_return_400_not_500(self):
        # Open defect QA-01. Remove expectedFailure when the application fix lands.
        self.client.raise_request_exception = False
        self.assertEqual(self.post_checkout([{'barcode': self.product.barcode, 'qty': 1}]).status_code, 400)

    @expectedFailure
    def test_d02_nan_quantity_should_return_400_not_500(self):
        # Open defect QA-02. Decimal('NaN') currently bypasses parsing rejection.
        self.client.raise_request_exception = False
        self.assertEqual(self.post_checkout({'items': [{'barcode': self.product.barcode, 'qty': 'NaN'}]}).status_code, 400)
