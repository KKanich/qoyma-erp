"""Regression tests for November 18, 2026 commits (Excel report, report UI, POS header date)."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.chart import BarChart

from .excel_export import build_sales_workbook
from .models import Category, Product, Sale, SaleItem, User
from .reports import daily_sales_summary, sales_rows
from .tests import make_product


class ReportExcelRegressionTests(TestCase):
    """Covers /report/xlsx/, sales_rows(), and build_sales_workbook() edge cases."""

    def setUp(self):
        self.admin = User.objects.create_user('report-admin', password='pass12345', role='Admin')
        self.manager = User.objects.create_user('report-manager', password='pass12345', role='Manager')
        self.cashier = User.objects.create_user('report-cashier', password='pass12345', role='Cashier')
        self.category = Category.objects.create(name='Dairy')
        self.future = timezone.localdate() + timedelta(days=10)
        self.milk = make_product(
            barcode='4870000000011', name='Milk 2.5% 1L', category=self.category,
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'),
            min_quantity=Decimal('5.00'), expiry_date=self.future,
        )
        self.bread = make_product(
            barcode='4870000000035', name='Rye Bread', category=self.category,
            sale_price=Decimal('200.00'), quantity=Decimal('3.00'),
            min_quantity=Decimal('5.00'), expiry_date=self.future,
        )

    def _create_sale(self, items, payment='Cash', days_ago=0):
        sale = Sale.objects.create(cashier=self.cashier, payment_method=payment)
        total = Decimal('0.00')
        for product, qty in items:
            qty_dec = Decimal(str(qty))
            subtotal = (product.sale_price * qty_dec).quantize(Decimal('0.01'))
            SaleItem.objects.create(
                sale=sale, product=product, quantity=qty_dec,
                unit_price=product.sale_price, subtotal=subtotal,
            )
            total += subtotal
        sale.total_amount = total
        sale.save()
        if days_ago:
            Sale.objects.filter(pk=sale.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago),
            )
            sale.refresh_from_db()
        return sale

    def test_report_xlsx_anonymous_redirects_and_admin_allowed(self):
        anon_res = self.client.get(reverse('report_xlsx'))
        self.assertEqual(anon_res.status_code, 302)
        self.assertIn('/login/', anon_res['Location'])

        self.client.force_login(self.admin)
        admin_res = self.client.get(reverse('report_xlsx'))
        self.assertEqual(admin_res.status_code, 200)
        self.assertIn('spreadsheetml', admin_res['Content-Type'])
        self.assertIn(f'sales_{timezone.localdate()}.xlsx', admin_res['Content-Disposition'])

    def test_report_xlsx_empty_day_structure_and_no_charts(self):
        # Yesterday's sale must not leak into today's Excel export.
        self._create_sale([(self.milk, 3)], payment='Cash', days_ago=1)
        Product.objects.filter(pk=self.bread.pk).update(quantity=Decimal('10.00'))

        self.client.force_login(self.manager)
        res = self.client.get(reverse('report_xlsx'))
        self.assertEqual(res.status_code, 200)

        wb = load_workbook(BytesIO(res.content))
        summary_ws = wb['Summary']
        sales_ws = wb['Sales']
        top_ws = wb['Top products']

        self.assertEqual(summary_ws['A5'].value, 0.0)
        self.assertEqual(summary_ws['C5'].value, 0)
        self.assertEqual(summary_ws['E5'].value, 0.0)
        self.assertEqual([summary_ws[f'C{r}'].value for r in (9, 10, 11)], [0, 0, 0])
        self.assertEqual(len(summary_ws._charts), 0)
        self.assertEqual(summary_ws['A15'].value, 'All products are above minimum')

        self.assertEqual(sales_ws['A2'].value, 'No sales today')
        self.assertIsNone(sales_ws.auto_filter.ref)
        self.assertEqual(sales_ws.freeze_panes, 'A2')

        self.assertEqual(top_ws['A2'].value, 'No sales today')
        self.assertEqual(len(top_ws._charts), 0)

    def test_sales_workbook_payment_bar_chart_general_qty_and_formulas(self):
        self._create_sale([(self.milk, '2.00')], payment='Cash')
        self._create_sale([(self.bread, '1.50')], payment='Kaspi_QR')
        self._create_sale([(self.bread, '2.50')], payment='Card')

        summary = daily_sales_summary()
        items = sales_rows()
        wb_in_memory = build_sales_workbook(summary, items, dict(Sale.PAYMENT_CHOICES))

        # Commit ddda735 replaced the payment PieChart with a column BarChart.
        self.assertEqual(len(wb_in_memory['Summary']._charts), 1)
        pay_chart = wb_in_memory['Summary']._charts[0]
        self.assertIsInstance(pay_chart, BarChart)
        self.assertEqual(pay_chart.type, 'col')
        self.assertEqual(pay_chart.title.tx.rich.p[0].r[0].t, 'Sales by payment method, ₸')
        self.assertIsNone(pay_chart.legend)
        self.assertEqual(pay_chart.y_axis.numFmt.formatCode, '#,##0')
        self.assertEqual(pay_chart.series[0].graphicalProperties.solidFill.srgbClr, '1F3B57')

        self.client.force_login(self.manager)
        res = self.client.get(reverse('report_xlsx'))
        wb = load_workbook(BytesIO(res.content))

        summary_ws = wb['Summary']
        self.assertEqual(summary_ws['A1'].value, 'Daily sales report — Bereke Grocery Store')
        self.assertEqual(summary_ws['A2'].value, f'Date: {summary["day"]:%d.%m.%Y}')
        self.assertEqual(summary_ws['A5'].value, 1900.0)
        self.assertEqual(summary_ws['C5'].value, 3)
        self.assertEqual(summary_ws['E5'].value, 633.33)
        self.assertEqual(summary_ws['B12'].value, '=SUM(B9:B11)')
        self.assertEqual(summary_ws['C9'].number_format, '0%')
        self.assertAlmostEqual(
            sum(summary_ws[f'C{r}'].value for r in (9, 10, 11)), 1.0, places=6,
        )
        # Low-stock table lists only Rye Bread (3.00 <= 5.00), using General qty format.
        self.assertEqual(summary_ws['A16'].value, 'Rye Bread')
        self.assertEqual(summary_ws['B16'].value, 3.0)
        self.assertEqual(summary_ws['B16'].number_format, 'General')
        self.assertEqual(summary_ws['C16'].number_format, 'General')
        self.assertIsNone(summary_ws['A17'].value)

        sales_ws = wb['Sales']
        self.assertEqual(sales_ws['E2'].number_format, 'General')
        self.assertEqual(sales_ws['F2'].number_format, '#,##0.00 "₸"')
        self.assertEqual(sales_ws['G2'].number_format, '#,##0.00 "₸"')
        self.assertEqual(sales_ws['D5'].value, 'Total')
        self.assertEqual(sales_ws['E5'].value, '=SUM(E2:E4)')
        self.assertEqual(sales_ws['G5'].value, '=SUM(G2:G4)')
        self.assertEqual(sales_ws.auto_filter.ref, 'A1:H4')
        self.assertEqual(sales_ws.freeze_panes, 'A2')

        top_ws = wb['Top products']
        self.assertEqual(top_ws['A2'].value, 'Rye Bread')
        self.assertEqual(top_ws['B2'].value, 4.0)
        self.assertEqual(top_ws['B2'].number_format, 'General')
        self.assertEqual(top_ws['C2'].number_format, '#,##0.00 "₸"')

    def test_sales_workbook_top_products_capped_at_five_and_ordered(self):
        # 6 products sold today + 1 yesterday's sale to verify filtering & top-5 cap.
        products = [self.milk, self.bread]
        for idx in range(4):
            products.append(make_product(
                barcode=f'487000000010{idx}', name=f'Extra Item {idx}',
                category=self.category, sale_price=Decimal('100.00'),
                quantity=Decimal('50.00'), expiry_date=self.future,
            ))

        self._create_sale([(self.milk, 10)], days_ago=1)  # excluded from today
        today_sale = self._create_sale([
            (products[0], 1),
            (products[1], 6),
            (products[2], 4),
            (products[3], 4),  # tie with Extra Item 0 -> alphabetical order
            (products[4], 3),
            (products[5], 2),
        ])

        rows = sales_rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual([r['sale_id'] for r in rows], [today_sale.id] * 6)
        self.assertEqual(rows[0]['time'], timezone.localtime(today_sale.created_at).strftime('%H:%M'))

        wb = build_sales_workbook(daily_sales_summary(), rows, dict(Sale.PAYMENT_CHOICES))
        top_ws = wb['Top products']
        self.assertEqual(top_ws.max_row, 6)  # header + 5 products
        self.assertEqual(
            [top_ws[f'A{r}'].value for r in range(2, 7)],
            ['Rye Bread', 'Extra Item 0', 'Extra Item 1', 'Extra Item 2', 'Extra Item 3'],
        )
        top_chart = top_ws._charts[0]
        self.assertIsInstance(top_chart, BarChart)
        self.assertEqual(top_chart.type, 'bar')
        self.assertEqual(top_chart.x_axis.scaling.orientation, 'maxMin')


class ReportAndPosTemplateNov18Tests(TestCase):
    """Covers Nov 18 template updates: report.html formatting/CSS and pos.html date header."""

    def setUp(self):
        self.manager = User.objects.create_user('ui-manager', password='pass12345', role='Manager')
        self.cashier = User.objects.create_user('ui-cashier', password='pass12345', role='Cashier')
        dairy = Category.objects.create(name='Dairy')
        future = timezone.localdate() + timedelta(days=10)
        self.milk = make_product(
            barcode='4870000000011', name='Milk 2.5%', category=dairy,
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'), expiry_date=future,
        )
        self.cheese = make_product(
            barcode='4870000000097', name='Cheese 200g', category=dairy,
            sale_price=Decimal('400.00'), quantity=Decimal('20.00'), expiry_date=future,
        )

    def test_report_page_excel_link_header_styles_and_unified_formatting(self):
        sale = Sale.objects.create(
            cashier=self.cashier, payment_method='Cash', total_amount=Decimal('1600.00'),
        )
        SaleItem.objects.create(
            sale=sale, product=self.milk, quantity=Decimal('2.00'),
            unit_price=Decimal('550.00'), subtotal=Decimal('1100.00'),
        )
        SaleItem.objects.create(
            sale=sale, product=self.cheese, quantity=Decimal('1.25'),
            unit_price=Decimal('400.00'), subtotal=Decimal('500.00'),
        )

        self.client.force_login(self.manager)
        res = self.client.get(reverse('report_page'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'href="/report/xlsx/"')
        self.assertContains(res, 'Download Excel')
        self.assertContains(res, 'href="/report/csv/"')
        self.assertContains(res, 'header > div { white-space: nowrap; }')
        self.assertContains(res, '1600.00 ₸')
        # Unified table cell formatting: integer qty renders as "2", decimal as "1.25".
        self.assertContains(
            res, '<tr><td>Milk 2.5%</td><td>2</td><td>1100.00</td></tr>', html=True,
        )
        self.assertContains(
            res, '<tr><td>Cheese 200g</td><td>1.25</td><td>500.00</td></tr>', html=True,
        )

    def test_pos_header_shows_weekday_and_date_and_role_links(self):
        expected_date = timezone.localtime(timezone.now()).strftime('%A, %d.%m.%Y')

        self.client.force_login(self.cashier)
        cashier_res = self.client.get(reverse('pos_page'))
        self.assertEqual(cashier_res.status_code, 200)
        self.assertContains(cashier_res, expected_date)
        self.assertNotContains(cashier_res, 'href="/products/"')
        self.assertNotContains(cashier_res, 'href="/receive/"')

        self.client.force_login(self.manager)
        manager_res = self.client.get(reverse('pos_page'))
        self.assertEqual(manager_res.status_code, 200)
        self.assertContains(manager_res, expected_date)
        self.assertContains(manager_res, 'href="/products/"')
        self.assertContains(manager_res, 'href="/report/"')
