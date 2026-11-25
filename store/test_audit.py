"""Automated tests (inventory adjustments, StockMovement ledger, admin/catalog/seed updates)."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
import sqlite3
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .models import (Category, Product, Sale, SaleItem, StockMovement,
                     StockReceipt, StockReceiptItem, Supplier, User)
from .services import receive_stock
from .tests import make_product


class StockMovementModelAndSchemaTests(TestCase):
    """Verifies StockMovement DB constraints, PROTECT rules, snapshots, and schema.sql."""

    def setUp(self):
        self.manager = User.objects.create_user('ledger-manager', role='Manager')
        self.supplier = Supplier.objects.create(name='Ledger supplier', phone='123')
        self.product = make_product(barcode='0123456789012', name='Original Milk')

    def test_stock_movement_check_constraint_rejects_invalid_rows(self):
        sale = Sale.objects.create(cashier=self.manager, total_amount=Decimal('550.00'))
        sale_item = SaleItem.objects.create(
            sale=sale, product=self.product, quantity=Decimal('1.00'),
            unit_price=Decimal('550.00'), subtotal=Decimal('550.00'),
        )
        receipt = StockReceipt.objects.create(supplier=self.supplier, received_by=self.manager)
        receipt_item = StockReceiptItem.objects.create(
            stock_receipt=receipt, product=self.product,
            quantity=Decimal('2.00'), purchase_price=Decimal('400.00'),
        )

        invalid_cases = [
            ('negative_before', dict(before=Decimal('-1.00'), after=Decimal('5.00'), reason='Bad')),
            ('negative_after', dict(before=Decimal('5.00'), after=Decimal('-1.00'), reason='Bad')),
            ('adjustment_empty_reason', dict(before=Decimal('5.00'), after=Decimal('4.00'), reason='')),
            ('adjustment_zero_delta', dict(before=Decimal('5.00'), after=Decimal('5.00'), reason='No change')),
            ('sale_increases_stock', dict(sale_item=sale_item, before=Decimal('5.00'), after=Decimal('6.00'), reason='')),
            ('sale_equal_stock', dict(sale_item=sale_item, before=Decimal('5.00'), after=Decimal('5.00'), reason='')),
            ('sale_with_reason', dict(sale_item=sale_item, before=Decimal('5.00'), after=Decimal('4.00'), reason='Extra')),
            ('receipt_decreases_stock', dict(receipt_item=receipt_item, before=Decimal('5.00'), after=Decimal('4.00'), reason='')),
            ('receipt_with_reason', dict(receipt_item=receipt_item, before=Decimal('5.00'), after=Decimal('7.00'), reason='Extra')),
            ('both_source_items', dict(sale_item=sale_item, receipt_item=receipt_item, before=Decimal('5.00'), after=Decimal('4.00'), reason='')),
        ]
        for label, fields in invalid_cases:
            with self.subTest(case=label):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        StockMovement.objects.create(
                            product=self.product, actor=self.manager,
                            username=self.manager.username, product_name=self.product.name,
                            barcode=self.product.barcode, **fields,
                        )

    def test_stock_movement_protects_related_records_and_snapshots_immutable(self):
        receipt = receive_stock(self.manager, self.supplier, [{
            'barcode': self.product.barcode, 'qty': '5.00', 'purchase_price': '400.00',
            'expiry_date': self.product.expiry_date,
        }])
        receipt_item = receipt.items.get()
        self.client.force_login(self.manager)
        self.client.post(
            reverse('pos_checkout'),
            {'items': [{'barcode': self.product.barcode, 'qty': '2.00'}]},
            content_type='application/json',
        )
        sale_item = SaleItem.objects.get()
        adj = StockMovement.objects.create(
            product=self.product, actor=self.manager, username=self.manager.username,
            product_name=self.product.name, barcode=self.product.barcode,
            before=Decimal('23.00'), after=Decimal('21.00'), reason='Damaged',
        )

        self.product.name = 'Renamed Milk'
        self.product.barcode = '9999999999999'
        self.product.save()
        self.manager.username = 'renamed-manager'
        self.manager.save()

        adj.refresh_from_db()
        self.assertEqual(adj.product_name, 'Original Milk')
        self.assertEqual(adj.barcode, '0123456789012')
        self.assertEqual(adj.username, 'ledger-manager')

        for obj in (self.product, self.manager, sale_item, receipt_item):
            with self.subTest(protected=type(obj).__name__):
                with self.assertRaises(ProtectedError):
                    obj.delete()

    def test_schema_sql_initializes_clean_sqlite_with_stockmovement_constraint(self):
        sql = (Path(settings.BASE_DIR) / 'schema.sql').read_text(encoding='utf-8')
        conn = sqlite3.connect(':memory:')
        try:
            conn.execute('PRAGMA foreign_keys = ON;')
            conn.executescript(sql)
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list('store_stockmovement')").fetchall()
            }
            self.assertIn('stockmovement_product', indexes)
            self.assertIn('stockmovement_actor', indexes)

            conn.execute("INSERT INTO store_user (id, username, password, role) VALUES (1, 'mgr', 'pw', 'Manager')")
            conn.execute("INSERT INTO store_category (id, name) VALUES (1, 'Dairy')")
            conn.execute(
                "INSERT INTO store_product (id, barcode, name, category_id, sale_price, quantity, min_quantity, expiry_date) "
                "VALUES (1, '4870000000011', 'Milk', 1, 550.00, 20.00, 5.00, '2030-01-01')"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO store_stockmovement (actor_id, product_id, username, barcode, product_name, before, after, reason) "
                    "VALUES (1, 1, 'mgr', '4870000000011', 'Milk', 20.00, 19.00, '')"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO store_stockmovement (actor_id, product_id, username, barcode, product_name, before, after, reason) "
                    "VALUES (1, 1, 'mgr', '4870000000011', 'Milk', 20.00, 20.00, 'No difference')"
                )
        finally:
            conn.close()


class StockAdjustmentViewTests(TestCase):
    """Covers upward/zero adjustments, Admin role, concurrent movement detection, and HTTP guards."""

    def setUp(self):
        self.admin = User.objects.create_user('adj-admin', role='Admin')
        self.manager = User.objects.create_user('adj-manager', role='Manager')
        self.cashier = User.objects.create_user('adj-cashier', role='Cashier')
        self.supplier = Supplier.objects.create(name='Adj supplier', phone='123')
        self.product = make_product(barcode='4870000000011', quantity=Decimal('20.00'))
        self.url = reverse('adjust_stock', args=[self.product.pk])

    def test_upward_and_zero_adjustments_and_admin_access(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(reverse('inventory_audit')).status_code, 200)
        self.assertEqual(self.client.get(reverse('inventory_xlsx')).status_code, 200)

        # Upward adjustment: 20.00 -> 25.50
        res_up = self.client.post(self.url, {
            'expected': '20.00', 'last_movement': '0',
            'counted': '25.50', 'reason': 'Found extra crate',
        }, follow=True)
        self.assertEqual(res_up.status_code, 200)
        self.assertContains(res_up, 'Adjustment #1 saved for Milk 2.5% 1L.')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('25.50'))
        up_move = StockMovement.objects.get()
        self.assertEqual(up_move.change, Decimal('5.50'))
        self.assertEqual(up_move.kind, 'Adjustment')
        self.assertEqual(up_move.reference, 'Found extra crate')

        # Adjust down to zero: 25.50 -> 0.00
        res_zero = self.client.post(self.url, {
            'expected': '25.50', 'last_movement': str(up_move.pk),
            'counted': '0.00', 'reason': 'Full batch spoiled',
        })
        self.assertRedirects(res_zero, reverse('inventory_audit'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('0.00'))
        zero_move = StockMovement.objects.order_by('pk').last()
        self.assertEqual(zero_move.change, Decimal('-25.50'))

    def test_concurrent_sale_or_receipt_between_get_and_post_blocks_stale_adjustment(self):
        self.client.force_login(self.manager)
        page = self.client.get(self.url)
        self.assertEqual(page.context['form'].initial['expected'], Decimal('20.00'))
        self.assertEqual(page.context['form'].initial['last_movement'], 0)

        # Cashier sells 2 units before the manager submits the open count form.
        cashier_client = Client()
        cashier_client.force_login(self.cashier)
        checkout_res = cashier_client.post(
            reverse('pos_checkout'),
            {'items': [{'barcode': self.product.barcode, 'qty': '2.00'}]},
            content_type='application/json',
        )
        self.assertEqual(checkout_res.status_code, 200)

        stale_after_sale = self.client.post(self.url, {
            'expected': '20.00', 'last_movement': '0',
            'counted': '19.00', 'reason': 'Stale count after sale',
        })
        self.assertEqual(stale_after_sale.status_code, 200)
        self.assertContains(stale_after_sale, 'Stock changed since this count was opened.')
        self.assertContains(stale_after_sale, 'Open a fresh count')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('18.00'))
        self.assertEqual(StockMovement.objects.count(), 1)

        # Reload fresh count, then receive stock before posting: still rejected.
        sale_move = StockMovement.objects.get()
        receive_stock(self.manager, self.supplier, [{
            'barcode': self.product.barcode, 'qty': '4.00', 'purchase_price': '400.00',
            'expiry_date': self.product.expiry_date,
        }])
        stale_after_receipt = self.client.post(self.url, {
            'expected': '18.00', 'last_movement': str(sale_move.pk),
            'counted': '17.00', 'reason': 'Stale count after receipt',
        })
        self.assertContains(stale_after_receipt, 'Stock changed since this count was opened.')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('22.00'))
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_adjust_stock_validation_boundaries_and_http_guards(self):
        # Anonymous redirects to login on all three inventory routes.
        for route in (self.url, reverse('inventory_audit'), reverse('inventory_xlsx')):
            res = self.client.get(route)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/login/', res['Location'])

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('adjust_stock', args=[99999])).status_code, 404)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse('inventory_audit')).status_code, 405)
        self.assertEqual(self.client.post(reverse('inventory_xlsx')).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)
        self.assertEqual(csrf_client.post(self.url, {
            'expected': '20.00', 'last_movement': '0',
            'counted': '19.00', 'reason': 'Missing CSRF',
        }).status_code, 403)

        # 201-char reason and negative last_movement are rejected; 200-char reason succeeds.
        too_long = self.client.post(self.url, {
            'expected': '20.00', 'last_movement': '0',
            'counted': '19.00', 'reason': 'x' * 201,
        })
        self.assertTrue(too_long.context['form'].errors)
        bad_seq = self.client.post(self.url, {
            'expected': '20.00', 'last_movement': '-1',
            'counted': '19.00', 'reason': 'Negative seq',
        })
        self.assertTrue(bad_seq.context['form'].errors)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20.00'))
        self.assertFalse(StockMovement.objects.exists())

        max_reason = self.client.post(self.url, {
            'expected': '20.00', 'last_movement': '0',
            'counted': '19.00', 'reason': 'r' * 200,
        })
        self.assertRedirects(max_reason, reverse('inventory_audit'))
        self.assertEqual(StockMovement.objects.get().reason, 'r' * 200)


class InventoryAuditAndExcelTests(TestCase):
    """Covers /inventory/audit/ pagination, ordering, XSS escaping, and /inventory/audit/xlsx/."""

    def setUp(self):
        self.manager = User.objects.create_user('audit-manager', role='Manager')
        self.cashier = User.objects.create_user('audit-cashier', role='Cashier')
        self.supplier = Supplier.objects.create(name='Audit supplier', phone='123')
        self.product = make_product(barcode='0012345678901', name='Leading Zero Milk', quantity=Decimal('20.00'))
        self.client.force_login(self.manager)

    def test_audit_page_empty_order_pagination_and_escaping(self):
        empty_res = self.client.get(reverse('inventory_audit'))
        self.assertEqual(empty_res.status_code, 200)
        self.assertContains(empty_res, 'No inventory movements recorded yet.')

        # Create 55 movements (alternating 20 -> 21 -> 20) to trigger 50-row pagination.
        for i in range(55):
            after = Decimal('21.00') if i % 2 == 0 else Decimal('20.00')
            before = Decimal('20.00') if i % 2 == 0 else Decimal('21.00')
            reason = '<script>alert(1)</script>' if i == 54 else f'Count #{i + 1}'
            StockMovement.objects.create(
                product=self.product, actor=self.manager, username=self.manager.username,
                product_name=self.product.name, barcode=self.product.barcode,
                before=before, after=after, reason=reason,
            )

        page1 = self.client.get(reverse('inventory_audit'))
        self.assertEqual(page1.status_code, 200)
        self.assertContains(page1, 'Page 1 of 2')
        self.assertContains(page1, '?page=2')
        self.assertEqual(len(page1.context['page']), 50)
        # Newest-first (-pk): XSS reason from entry #55 is on page 1 and escaped.
        self.assertNotContains(page1, '<script>alert(1)</script>')
        self.assertContains(page1, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page1, 'Count #1</td>')

        page2 = self.client.get(reverse('inventory_audit'), {'page': 2})
        self.assertEqual(page2.status_code, 200)
        self.assertContains(page2, 'Page 2 of 2')
        self.assertContains(page2, '?page=1')
        self.assertEqual(len(page2.context['page']), 5)
        self.assertContains(page2, 'Count #1')

    def test_audit_excel_empty_and_all_movement_types_in_ascending_order(self):
        empty_res = self.client.get(reverse('inventory_xlsx'))
        self.assertEqual(empty_res.status_code, 200)
        self.assertIn('spreadsheetml', empty_res['Content-Type'])
        self.assertIn(f'inventory_audit_{timezone.localdate()}.xlsx', empty_res['Content-Disposition'])
        empty_ws = load_workbook(BytesIO(empty_res.content)).active
        self.assertEqual(empty_ws.title, 'Inventory audit')
        self.assertEqual(empty_ws.max_row, 4)
        self.assertEqual(empty_ws.freeze_panes, 'C5')
        self.assertEqual(empty_ws.auto_filter.ref, 'A4:J4')

        # 1. Receipt via receive_stock
        receipt = receive_stock(self.manager, self.supplier, [{
            'barcode': self.product.barcode, 'qty': '5.00', 'purchase_price': '300.00',
            'expiry_date': self.product.expiry_date,
        }])
        # 2. Sale via pos_checkout
        cashier_client = Client()
        cashier_client.force_login(self.cashier)
        sale_res = cashier_client.post(
            reverse('pos_checkout'),
            {'items': [{'barcode': self.product.barcode, 'qty': '3.00'}]},
            content_type='application/json',
        )
        sale_id = sale_res.json()['sale_id']
        # 3. Adjustment via adjust_stock with formula prefix
        last_pk = StockMovement.objects.order_by('pk').last().pk
        self.client.post(reverse('adjust_stock', args=[self.product.pk]), {
            'expected': '22.00', 'last_movement': str(last_pk),
            'counted': '21.00', 'reason': '=1+1 damaged',
        })

        res = self.client.get(reverse('inventory_xlsx'))
        ws = load_workbook(BytesIO(res.content)).active
        self.assertEqual(ws.max_row, 7)
        self.assertEqual(ws.auto_filter.ref, 'A4:J7')
        self.assertEqual(ws['A4'].value, 'Entry')
        self.assertEqual(ws['J4'].value, 'Source or reason')

        # Ascending posting order: Receipt -> Sale -> Adjustment
        self.assertEqual([c.value for c in ws[5]][2:], [
            'Leading Zero Milk', '0012345678901', 'Receipt', 20.0, 5.0, 25.0,
            'audit-manager', f'Receipt #{receipt.pk}',
        ])
        self.assertEqual([c.value for c in ws[6]][2:], [
            'Leading Zero Milk', '0012345678901', 'Sale', 25.0, -3.0, 22.0,
            'audit-cashier', f'Sale #{sale_id}',
        ])
        self.assertEqual([c.value for c in ws[7]][2:], [
            'Leading Zero Milk', '0012345678901', 'Adjustment', 22.0, -1.0, 21.0,
            'audit-manager', '=1+1 damaged',
        ])
        for row in (5, 6, 7):
            self.assertEqual(ws.cell(row, 2).number_format, 'yyyy-mm-dd hh:mm:ss')
            for col in (3, 4, 5, 9, 10):
                self.assertEqual(ws.cell(row, col).data_type, 's')
            for col in (6, 7, 8):
                self.assertEqual(ws.cell(row, col).number_format, '#,##0.00')
        # Even row (row 6) gets zebra fill; odd rows do not.
        self.assertEqual(ws.cell(6, 1).fill.fill_type, 'solid')
        self.assertEqual(ws.cell(6, 1).fill.fgColor.rgb, '00EAF1F8')
        self.assertIsNone(ws.cell(5, 1).fill.fill_type)


class LedgerIntegrationWithCheckoutReceiptsAdminCatalogSeedTests(TestCase):
    """Covers Nov 24 ledger integration in checkout, admin, catalog deletion, and seed_demo."""

    def setUp(self):
        self.superuser = User.objects.create_superuser('super-admin', password='pw', role='Admin')
        self.manager = User.objects.create_user('flow-manager', password='pw', role='Manager')
        self.cashier = User.objects.create_user('flow-cashier', password='pw', role='Cashier')
        self.supplier = Supplier.objects.create(name='Flow supplier', phone='123')
        self.product = make_product(barcode='4870000000012', quantity=Decimal('20.00'))

    def test_multiline_checkout_and_failed_receipt_ledger_atomicity(self):
        self.client.force_login(self.cashier)
        # Same product on two cart lines must create chained before/after movements.
        res = self.client.post(
            reverse('pos_checkout'),
            {'items': [
                {'barcode': self.product.barcode, 'qty': '2.00'},
                {'barcode': self.product.barcode, 'qty': '3.00'},
            ]},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)
        moves = list(StockMovement.objects.order_by('pk'))
        self.assertEqual([(m.before, m.after) for m in moves], [
            (Decimal('20.00'), Decimal('18.00')),
            (Decimal('18.00'), Decimal('15.00')),
        ])

        # Failed multi-item receive_stock rolls back the first item's StockMovement too.
        yesterday = timezone.localdate() - timedelta(days=1)
        with self.assertRaises(ValidationError):
            receive_stock(self.manager, self.supplier, [
                {'barcode': self.product.barcode, 'qty': '5.00', 'purchase_price': '100',
                 'expiry_date': self.product.expiry_date},
                {'barcode': self.product.barcode, 'qty': '5.00', 'purchase_price': '100',
                 'expiry_date': yesterday},
            ])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('15.00'))
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_admin_receipt_records_posting_actor_and_rolls_back_on_error(self):
        self.client.force_login(self.superuser)
        payload = {
            'supplier': self.supplier.pk,
            'received_by': self.manager.pk,  # different from posting request.user (superuser)
            'items-TOTAL_FORMS': '2', 'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '1', 'items-MAX_NUM_FORMS': '1000',
            'items-0-product': self.product.pk, 'items-0-quantity': '2.00',
            'items-0-purchase_price': '100.00',
            'items-1-product': self.product.pk, 'items-1-quantity': '3.00',
            'items-1-purchase_price': '100.00',
            '_save': 'Save',
        }
        res = self.client.post(reverse('admin:store_stockreceipt_add'), payload)
        self.assertEqual(res.status_code, 302)
        moves = list(StockMovement.objects.order_by('pk'))
        self.assertEqual(len(moves), 2)
        self.assertEqual([(m.before, m.after) for m in moves], [
            (Decimal('20.00'), Decimal('22.00')),
            (Decimal('22.00'), Decimal('25.00')),
        ])
        # StockReceiptAdmin passes actor=request.user (superuser), not received_by (manager).
        self.assertEqual([m.actor for m in moves], [self.superuser, self.superuser])
        self.assertEqual([m.username for m in moves], ['super-admin', 'super-admin'])

        # Simulated failure inside StockReceipt.post() rolls back StockMovement rows as well.
        with patch.object(StockReceipt._meta.get_field('total_amount'), 'clean',
                          side_effect=ValidationError('boom')):
            with self.assertRaises(ValidationError):
                self.client.post(reverse('admin:store_stockreceipt_add'), payload)
        self.assertEqual(StockMovement.objects.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('25.00'))

    def test_product_admin_quantity_readonly_and_preserves_concurrent_stock_on_edit(self):
        self.client.force_login(self.superuser)
        add_res = self.client.get(reverse('admin:store_product_add'))
        self.assertContains(add_res, 'name="quantity"')

        change_url = reverse('admin:store_product_change', args=[self.product.pk])
        change_res = self.client.get(change_url)
        self.assertEqual(change_res.status_code, 200)
        # On edit, quantity is readonly in ProductAdmin so no editable input is rendered.
        self.assertNotContains(change_res, 'name="quantity"')

        # Simulate concurrent stock update in DB before submitting a catalog name edit.
        Product.objects.filter(pk=self.product.pk).update(quantity=Decimal('13.50'))
        post_data = {
            'barcode': self.product.barcode,
            'name': 'Admin Edited Milk',
            'category': self.product.category_id,
            'supplier': '',
            'sale_price': '590.00',
            'min_quantity': '5.00',
            'expiry_date': self.product.expiry_date.isoformat(),
            'quantity': '999.00',  # ignored because quantity is readonly & update_fields used
            '_save': 'Save',
        }
        self.assertEqual(self.client.post(change_url, post_data).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Admin Edited Milk')
        self.assertEqual(self.product.sale_price, Decimal('590.00'))
        self.assertEqual(self.product.quantity, Decimal('13.50'))

        # No-op save (changed_data == []) succeeds cleanly too.
        self.assertEqual(self.client.post(change_url, post_data).status_code, 302)

    def test_product_delete_blocked_when_product_has_adjustment_even_at_zero_stock(self):
        self.client.force_login(self.manager)
        self.client.post(reverse('adjust_stock', args=[self.product.pk]), {
            'expected': '20.00', 'last_movement': '0',
            'counted': '0.00', 'reason': 'Clear shelf',
        })
        delete_url = reverse('product_delete', args=[self.product.pk])
        self.assertContains(self.client.get(delete_url), 'adjustment history')
        res = self.client.post(delete_url, follow=True)
        self.assertContains(
            res,
            'This product has sales or receipt history, or a recorded stock adjustment, and cannot be deleted.',
        )
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_seed_demo_preserves_existing_product_quantity_and_movements(self):
        out = StringIO()
        call_command('seed_demo', stdout=out)
        milk = Product.objects.get(pk=self.product.pk)
        self.assertEqual(milk.quantity, Decimal('20.00'))

        # Adjust Milk from 20 -> 15 and mutate sale_price; delete another demo product.
        self.client.force_login(self.manager)
        self.client.post(reverse('adjust_stock', args=[milk.pk]), {
            'expected': '20.00', 'last_movement': '0',
            'counted': '15.00', 'reason': 'Demo count before re-seed',
        })
        Product.objects.filter(pk=milk.pk).update(sale_price=Decimal('999.00'))
        Product.objects.get(barcode='4870000000333').delete()

        # Re-running seed_demo updates catalog details & recreates missing items,
        # while preserving Milk's adjusted stock quantity and StockMovement history.
        call_command('seed_demo', stdout=out)
        milk.refresh_from_db()
        self.assertEqual(milk.sale_price, Decimal('550.00'))
        self.assertEqual(milk.quantity, Decimal('15.00'))
        self.assertEqual(StockMovement.objects.filter(product=milk).count(), 1)
        recreated = Product.objects.get(barcode='4870000000333')
        self.assertEqual(recreated.quantity, Decimal('6.00'))
