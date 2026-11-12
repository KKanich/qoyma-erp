"""Tests for CSV export of the daily sales report (AC-D9, AC-D10, AC-D11)."""
import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Product, Sale, SaleItem, User


class ReportCsvTest(TestCase):

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
        return self.client.get(reverse('report_csv'))

    def rows(self, response):
        text = response.content.decode('utf-8-sig')
        return list(csv.reader(io.StringIO(text)))

    def test_acd9_csv_is_downloaded_as_file(self):
        """AC-D9: manager downloads sales_YYYY-MM-DD.csv."""
        res = self.download()
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res['Content-Type'])
        self.assertIn(f'sales_{timezone.localdate()}.csv', res['Content-Disposition'])

    def test_acd10_one_row_per_item_with_correct_columns(self):
        """AC-D10: header + 1 row per sold item (Milk, Bread)."""
        rows = self.rows(self.download())
        self.assertEqual(rows[0], ['sale_id', 'time', 'cashier', 'product', 'qty',
                                   'unit_price', 'subtotal', 'payment'])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][3], 'Milk')
        self.assertEqual(rows[1][6], '1100.00')
        self.assertEqual(rows[2][3], 'Bread')
        self.assertEqual(rows[2][7], 'Kaspi_QR')

    def test_acd11_cashier_cannot_download_csv(self):
        """AC-D11: cashier gets 403 on /report/csv/."""
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('report_csv')).status_code, 403)