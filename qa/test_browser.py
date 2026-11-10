"""Real Chromium journeys against Django's isolated live test server."""
from datetime import timedelta
from decimal import Decimal
import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from store.models import Sale, SaleItem, StockReceipt, Supplier, User
from store.tests import make_product


class BrowserJourneys(StaticLiveServerTestCase):
    def setUp(self):
        self.password = 'qa-only-local-fixture-password'
        User.objects.create_user('browser-manager', password=self.password, role='Manager')
        User.objects.create_user('browser-cashier', password=self.password, role='Cashier')
        self.supplier = Supplier.objects.create(name='Browser supplier')
        self.product = make_product()
        # Fixtures are created before starting Playwright's sync event loop.
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(
            headless=os.environ.get('QA_HEADED') != '1',
            channel=os.environ.get('QA_BROWSER_CHANNEL') or None,
        )
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)

    def login(self, username):
        self.page.goto(self.live_server_url + '/login/')
        self.page.get_by_label('Username').fill(username)
        self.page.get_by_label('Password').fill(self.password)
        self.page.get_by_role('button', name='Log in', exact=True).click()
        expect(self.page).to_have_title('Qoyma — POS')

    def add_item(self, quantity):
        self.page.locator('#barcode').fill(self.product.barcode)
        self.page.locator('#qty').fill(str(quantity))
        self.page.get_by_role('button', name='Add', exact=True).click()

    def stop_browser_for_db_assertions(self):
        # Django forbids sync ORM calls inside Playwright's running event loop.
        # Run and consume the registered cleanups before inspecting persisted data.
        self.doCleanups()

    def test_e01_manager_receives_then_cashier_sells_and_logs_out(self):
        self.login('browser-manager')
        self.page.get_by_role('link', name='Receive stock', exact=True).click()
        self.page.get_by_label('Supplier', exact=True).select_option(str(self.supplier.pk))
        self.page.get_by_label('Product barcode (13 digits)').fill(self.product.barcode)
        self.page.get_by_label('Quantity received').fill('5')
        self.page.get_by_label('Purchase price per unit (₸)').fill('400')
        self.page.get_by_label('Expiry date of this batch').fill((timezone.localdate() + timedelta(days=10)).isoformat())
        self.page.get_by_role('button', name='Receive goods').click()
        expect(self.page.locator('.notice.ok')).to_contain_text('25.00')
        self.page.get_by_role('button', name='Log out', exact=True).click()
        self.login('browser-cashier')
        self.add_item(2)
        expect(self.page.locator('#total')).to_have_text('1100.00')
        self.page.locator('#payment').select_option('Card')
        self.page.get_by_role('button', name='Complete sale').click()
        expect(self.page.locator('#msg')).to_contain_text('completed')
        # Reload proves persisted stock is rendered, rather than only a JS message.
        self.page.reload()
        stock_row = self.page.locator('tr').filter(has_text=self.product.barcode)
        expect(stock_row).to_contain_text('23.00')
        self.page.get_by_role('button', name='Log out', exact=True).click()
        self.page.goto(self.live_server_url + '/')
        expect(self.page).to_have_title('Qoyma — Login')
        self.stop_browser_for_db_assertions()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('23'))
        self.assertEqual(StockReceipt.objects.get().total_amount, Decimal('2000'))
        self.assertEqual(Sale.objects.get().payment_method, 'Card')
        self.assertEqual(SaleItem.objects.get().subtotal, Decimal('1100'))

    def test_e02_overselling_shows_error_and_preserves_stock(self):
        self.login('browser-cashier')
        self.add_item(21)
        self.page.get_by_role('button', name='Complete sale').click()
        expect(self.page.locator('#msg')).to_contain_text('Insufficient stock')
        expect(self.page.locator('#cart')).to_contain_text('Milk')
        self.stop_browser_for_db_assertions()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))
        self.assertEqual(Sale.objects.count(), 0)

    def test_e03_wrong_password_and_cashier_receipt_access_denied(self):
        self.page.goto(self.live_server_url + '/login/')
        self.page.get_by_label('Username').fill('browser-cashier')
        self.page.get_by_label('Password').fill('wrong-password')
        self.page.get_by_role('button', name='Log in', exact=True).click()
        expect(self.page.locator('.err')).to_have_text('Wrong username or password.')
        self.login('browser-cashier')
        expect(self.page.get_by_role('link', name='Receive stock', exact=True)).to_have_count(0)
        response = self.page.goto(self.live_server_url + '/receive/')
        self.assertEqual(response.status, 403)
