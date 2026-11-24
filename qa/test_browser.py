"""Real Chromium journeys against Django's isolated live test server."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright

from store.models import Sale, SaleItem, StockMovement, StockReceipt, Supplier, User
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

    def test_manager_posts_a_physical_count_and_downloads_ledger(self):
        self.login('browser-manager')
        self.page.get_by_role('link', name='Products', exact=True).click()
        self.page.get_by_role('link', name='Adjust stock').click()
        self.page.get_by_label('Counted stock').fill('19')
        self.page.get_by_label('Reason for the difference').fill('One damaged carton removed')
        self.page.get_by_role('button', name='Post adjustment').click()
        row = self.page.get_by_role('row').filter(has_text='One damaged carton removed')
        expect(row).to_contain_text('browser-manager')
        expect(row.get_by_role('cell').nth(4)).to_have_text('20.00')
        expect(row.get_by_role('cell').nth(6)).to_have_text('19.00')
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='Download Excel').click()
        self.assertTrue(download.value.suggested_filename.endswith('.xlsx'))

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

    def test_nov18_pos_date_and_report_excel_download(self):
        self.login('browser-manager')
        expected_date = timezone.localtime(timezone.now()).strftime('%A, %d.%m.%Y')
        expect(self.page.locator('header')).to_contain_text(expected_date)
        self.add_item(2)
        self.page.get_by_role('button', name='Complete sale').click()
        expect(self.page.locator('#msg')).to_contain_text('completed')
        stock_row = self.page.locator('tr').filter(has_text=self.product.barcode)
        expect(stock_row).to_contain_text('18.00')
        self.page.get_by_role('link', name='Daily report', exact=True).click()
        expect(self.page).to_have_title('Qoyma — Daily sales report')
        expect(self.page.locator('.cards')).to_contain_text('1100.00 ₸')
        top_row = self.page.get_by_role('row').filter(has_text='Milk 2.5% 1L')
        expect(top_row.get_by_role('cell').nth(1)).to_have_text('2')
        expect(top_row.get_by_role('cell').nth(2)).to_have_text('1100.00')
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='Download Excel', exact=True).click()
        self.assertTrue(download.value.suggested_filename.startswith('sales_'))
        self.assertTrue(download.value.suggested_filename.endswith('.xlsx'))
        wb = load_workbook(BytesIO(Path(download.value.path()).read_bytes()))
        self.assertEqual(wb.sheetnames, ['Summary', 'Sales', 'Top products'])
        self.assertEqual(wb['Summary']['A5'].value, 1100.0)
        self.assertEqual(wb['Sales']['D2'].value, 'Milk 2.5% 1L')
        self.assertEqual(wb['Sales']['E2'].value, 2)
        self.assertEqual(wb['Sales']['G2'].value, 1100.0)

    def test_nov24_stale_adjustment_blocked_after_cashier_sale_and_audit_trail(self):
        self.login('browser-manager')
        self.page.get_by_role('link', name='Products', exact=True).click()
        self.page.get_by_role('link', name='Adjust stock').click()
        expect(self.page).to_have_title('Qoyma — Adjust stock')
        expect(self.page.locator('main')).to_contain_text('20.00')

        cashier_context = self.browser.new_context()
        self.addCleanup(cashier_context.close)
        cashier_page = cashier_context.new_page()
        cashier_page.set_default_timeout(10000)
        cashier_page.goto(self.live_server_url + '/login/')
        cashier_page.get_by_label('Username').fill('browser-cashier')
        cashier_page.get_by_label('Password').fill(self.password)
        cashier_page.get_by_role('button', name='Log in', exact=True).click()
        expect(cashier_page).to_have_title('Qoyma — POS')
        cashier_page.locator('#barcode').fill(self.product.barcode)
        cashier_page.locator('#qty').fill('2')
        cashier_page.get_by_role('button', name='Add', exact=True).click()
        cashier_page.get_by_role('button', name='Complete sale').click()
        expect(cashier_page.locator('#msg')).to_contain_text('completed')
        cashier_context.close()

        self.page.get_by_label('Counted stock').fill('19')
        self.page.get_by_label('Reason for the difference').fill('Stale count attempt')
        self.page.get_by_role('button', name='Post adjustment').click()
        expect(self.page.locator('main')).to_contain_text('Stock changed since this count was opened.')
        self.page.get_by_role('link', name='Open a fresh count').click()
        expect(self.page.locator('main')).to_contain_text('18.00')

        self.page.get_by_label('Counted stock').fill('17')
        self.page.get_by_label('Reason for the difference').fill('Damaged carton written off')
        self.page.get_by_role('button', name='Post adjustment').click()
        expect(self.page).to_have_title('Qoyma — Inventory audit')

        adj_row = self.page.get_by_role('row').filter(has_text='Damaged carton written off')
        expect(adj_row).to_contain_text('browser-manager')
        expect(adj_row.get_by_role('cell').nth(4)).to_have_text('18.00')
        expect(adj_row.get_by_role('cell').nth(6)).to_have_text('17.00')

        sale_row = self.page.get_by_role('row').filter(has_text='Sale #')
        expect(sale_row).to_contain_text('browser-cashier')
        expect(sale_row.get_by_role('cell').nth(4)).to_have_text('20.00')
        expect(sale_row.get_by_role('cell').nth(6)).to_have_text('18.00')

        self.stop_browser_for_db_assertions()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('17.00'))
        self.assertEqual(StockMovement.objects.count(), 2)
