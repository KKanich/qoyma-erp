from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import Product, StockMovement, Supplier, User
from .services import receive_stock
from .tests import make_product


class ReceiptWorkflowIntegrationTests(TestCase):
    def test_service_receipt_cannot_be_posted_twice(self):
        manager = User.objects.create_user('receipt-manager', role='Manager')
        supplier = Supplier.objects.create(name='Receipt supplier')
        product = make_product()
        receipt = receive_stock(manager, supplier, [{
            'barcode': product.barcode, 'qty': '5', 'purchase_price': '100',
            'expiry_date': timezone.localdate() + timedelta(days=10),
        }])
        receipt.refresh_from_db()
        self.assertTrue(receipt.posted)
        self.assertFalse(receipt.post())
        product.refresh_from_db()
        self.assertEqual(product.quantity, Decimal('25'))
        self.assertEqual(receipt.total_amount, Decimal('500'))


class ReceiptMigrationIntegrationTests(TransactionTestCase):
    def test_scanner_upgrade_preserves_stock_history_and_existing_barcodes(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('store', '0005_merge_20261124_1857')])
            milk = make_product(barcode='4870000000011', name='Milk 2.5% 1L', quantity=18)
            actor = User.objects.create(username='counter')
            movement = StockMovement.record(milk, 20, actor, reason='Shelf count')
            # Both codes already exist for kefir. The migration must preserve
            # the two rows and their respective quantities for reconciliation.
            legacy = make_product(barcode='4870000000028', name='Kefir 1L', quantity=3)
            current = make_product(barcode='4870000000029', name='Kefir 1L', quantity=4)
            custom = make_product(barcode='4870000000035', name='Custom item')
            MigrationExecutor(connection).migrate(latest)
            milk.refresh_from_db()
            movement.refresh_from_db()
            self.assertEqual((milk.barcode, milk.quantity), ('4870000000012', 18))
            self.assertEqual((movement.product_id, movement.barcode), (milk.pk, '4870000000011'))
            for product in (legacy, current, custom):
                saved = Product.objects.get(pk=product.pk)
                self.assertEqual((saved.barcode, saved.quantity), (product.barcode, product.quantity))
        finally:
            MigrationExecutor(connection).migrate(latest)

    def test_legacy_receipts_preserve_stock_and_cannot_be_reposted(self):
        previous = [('store', '0002_stockreceiptitem_expiry_date')]
        latest = [('store', '0003_merge_receipt_workflows')]
        executor = MigrationExecutor(connection)
        try:
            # A target on one sibling branch does not unapply the other sibling.
            # Rewind to their common ancestor before recreating the old schema.
            executor.migrate([('store', '0001_initial')])
            executor = MigrationExecutor(connection)
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            user = apps.get_model('store', 'User').objects.create(username='legacy-receiver')
            supplier = apps.get_model('store', 'Supplier').objects.create(name='Legacy supplier')
            category = apps.get_model('store', 'Category').objects.create(name='Legacy category')
            product = apps.get_model('store', 'Product').objects.create(
                barcode='4870000000011', name='Legacy milk', category=category,
                sale_price='100', quantity='25', expiry_date=timezone.localdate(),
            )
            receipt = apps.get_model('store', 'StockReceipt').objects.create(
                supplier=supplier, received_by=user, total_amount='500',
            )
            apps.get_model('store', 'StockReceiptItem').objects.create(
                stock_receipt=receipt, product=product, quantity='5', purchase_price='100',
            )
            MigrationExecutor(connection).migrate(latest)
            from .models import StockReceipt
            migrated = StockReceipt.objects.get(pk=receipt.pk)
            self.assertTrue(migrated.posted)
            self.assertFalse(migrated.post())
            self.assertEqual(Product.objects.get(pk=product.pk).quantity, Decimal('25'))
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
