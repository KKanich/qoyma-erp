from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from .models import StockMovement, StockReceipt, StockReceiptItem, Supplier, User
from .services import receive_stock
from .tests import make_product


class InventoryAuditTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user('operator', role='Manager')
        self.cashier = User.objects.create_user('cashier', role='Cashier')
        self.client.force_login(self.manager)
        self.product = make_product(barcode='0123456789012')
        self.url = reverse('adjust_stock', args=[self.product.pk])
        self.data = dict(expected='20', last_movement=0, counted='18.25', reason='Shelf count')

    def test_count_export_and_history_preserve_snapshots(self):
        self.assertRedirects(self.client.post(self.url, {**self.data, 'reason': '=Shelf count'}),
                             reverse('inventory_audit'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('18.25'))
        self.product.name = 'Renamed'
        self.product.save()
        movement = StockMovement.objects.get()
        self.assertEqual(movement.change, Decimal('-1.75'))
        self.assertEqual(movement.actor, self.manager)
        self.assertContains(self.client.get(reverse('inventory_audit')), 'Milk 2.5% 1L')
        response = self.client.get(reverse('inventory_xlsx'))
        ws = load_workbook(BytesIO(response.content)).active
        self.assertEqual([c.value for c in ws[5]][2:],
                         ['Milk 2.5% 1L', '0123456789012', 'Adjustment', 20, -1.75, 18.25,
                          'operator', '=Shelf count'])
        self.assertEqual(ws['J5'].data_type, 's')

    def test_replayed_form_rejected_even_after_stock_returns_to_previous_balance(self):
        self.client.post(self.url, self.data)
        first = StockMovement.objects.get()
        self.client.post(self.url, {**self.data, 'expected': '18.25', 'counted': '20',
                                    'last_movement': first.pk})
        self.assertContains(self.client.post(self.url, self.data), 'Reload the page')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 20)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_validation_access_and_write_failure_preserve_stock(self):
        for invalid in [{'reason': '  '}, {'counted': '-1'}, {'counted': '20'}, {'counted': '0.001'}]:
            self.assertTrue(self.client.post(self.url, {**self.data, **invalid}).context['form'].errors)
        with patch.object(StockMovement, 'record', side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, self.data)
        self.client.force_login(self.cashier)
        for url in [self.url, reverse('inventory_audit'), reverse('inventory_xlsx')]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 20)
        self.assertFalse(StockMovement.objects.exists())

    def test_receipts_checkout_and_failed_cart(self):
        supplier = Supplier.objects.create(name='Dairy supplier')
        receipt = receive_stock(self.manager, supplier, [{
            'barcode': self.product.barcode, 'qty': '2.50', 'purchase_price': '1',
            'expiry_date': self.product.expiry_date,
        }])
        self.assertFalse(receipt.post())
        draft = StockReceipt.objects.create(received_by=self.manager, supplier=supplier)
        StockReceiptItem.objects.create(stock_receipt=draft, product=self.product,
                                        quantity='1.50', purchase_price=1)
        self.assertTrue(draft.post())
        self.assertFalse(draft.post())
        self.client.force_login(self.cashier)
        line = {'barcode': self.product.barcode, 'qty': '3.25'}
        for lines, status in [([line, {**line, 'qty': '1000'}], 400), ([line], 200)]:
            response = self.client.post(reverse('pos_checkout'), {'items': lines},
                                        content_type='application/json')
            self.assertEqual(response.status_code, status)
        movements = list(StockMovement.objects.order_by('pk'))
        self.assertEqual([m.kind for m in movements], ['Receipt', 'Receipt', 'Sale'])
        self.assertEqual([m.change for m in movements],
                         [Decimal('2.50'), Decimal('1.50'), Decimal('-3.25')])
        self.assertEqual(movements[-1].username, self.cashier.username)
        self.product.refresh_from_db()
        self.assertEqual(movements[-1].after, self.product.quantity)
