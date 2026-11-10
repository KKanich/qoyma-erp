from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import Supplier, User
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
            from .models import Product, StockReceipt
            migrated = StockReceipt.objects.get(pk=receipt.pk)
            self.assertTrue(migrated.posted)
            self.assertFalse(migrated.post())
            self.assertEqual(Product.objects.get(pk=product.pk).quantity, Decimal('25'))
        finally:
            MigrationExecutor(connection).migrate(latest)
