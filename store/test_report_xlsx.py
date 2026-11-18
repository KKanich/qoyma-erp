
"""Tests for the Excel export of the daily sales report (fixes UAT defect D-01)."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .excel_export import build_sales_workbook
from .models import Category, Product, Sale, SaleItem, User
from .reports import daily_sales_summary, sales_rows


class ReportExcelTest(TestCase):

    def setUp(self):
        self.manager = User.objects.create_user('manager', password='pass12345', role='Manager')
        self.cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        dairy = Category.objects.create(name='Dairy')
        future = timezone.localdate() + timedelta(days=10)
        milk = Product.objects.create(
            barcode='4870000000011', name='Milk', category=dairy,
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'), expiry_date=future)
        bread = Product.objects.create(
            barcode='4870000000035', name='Bread', category=dairy,
            sale_price=Decimal('190.00'), quantity=Decimal('30.00'), expiry_date=future)
        sale = Sale.objects.create(cashier=self.cashier, payment_method='Kaspi_QR',
                                   total_amount=Decimal('1290.00'))
        SaleItem.objects.create(sale=sale, product=milk, quantity=Decimal('2'),
                                unit_price=Decimal('550.00'), subtotal=Decimal('1100.00'))
        SaleItem.objects.create(sale=sale, product=bread, quantity=Decimal('1'),
                                unit_price=Decimal('190.00'), subtotal=Decimal('190.00'))

    def download(self):
        self.client.force_login(self.manager)
        return self.client.get(reverse('report_xlsx'))

    def test_excel_is_downloaded_as_file(self):
        """Manager downloads sales_YYYY-MM-DD.xlsx."""
        res = self.download()
        self.assertEqual(res.status_code, 200)
        self.assertIn('spreadsheetml', res['Content-Type'])
        self.assertIn(f'sales_{timezone.localdate()}.xlsx', res['Content-Disposition'])

    def test_excel_has_three_sheets_with_correct_data(self):
        """Each value is in its own column (UAT defect D-01 fixed)."""
        wb = load_workbook(BytesIO(self.download().content))
        self.assertEqual(wb.sheetnames, ['Summary', 'Sales', 'Top products'])
        sales = wb['Sales']
        self.assertEqual(sales['D1'].value, 'Product')
        self.assertEqual(sales['D2'].value, 'Milk')
        self.assertEqual(sales['G2'].value, 1100.0)
        self.assertEqual(sales['H2'].value, 'Kaspi QR')
        self.assertEqual(sales['D3'].value, 'Bread')
        self.assertEqual(wb['Summary']['A5'].value, 1290.0)
        self.assertEqual(wb['Top products']['A2'].value, 'Milk')

    def test_excel_has_charts(self):
        """Summary has a payment-method chart, Top products has a bar chart."""
        summary = daily_sales_summary()
        wb = build_sales_workbook(summary, sales_rows(), dict(Sale.PAYMENT_CHOICES))
        self.assertEqual(len(wb['Summary']._charts), 1)
        self.assertEqual(len(wb['Top products']._charts), 1)

    def test_cashier_cannot_download_excel(self):
        """Cashier gets 403 on /report/xlsx/."""
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('report_xlsx')).status_code, 403)
