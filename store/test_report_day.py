"""Tests for choosing the report day (?day=YYYY-MM-DD)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Product, Sale, SaleItem, User


class ReportDayTest(TestCase):

    def setUp(self):
        self.manager = User.objects.create_user('manager', password='pass12345', role='Manager')
        cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        milk = Product.objects.create(
            barcode='4870000000011', name='Milk', category=Category.objects.create(name='Dairy'),
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'),
            expiry_date=timezone.localdate() + timedelta(days=10))
        sale = Sale.objects.create(cashier=cashier, payment_method='Cash',
                                   total_amount=Decimal('1100.00'))
        SaleItem.objects.create(sale=sale, product=milk, quantity=Decimal('2'),
                                unit_price=Decimal('550.00'), subtotal=Decimal('1100.00'))
        # move this sale to yesterday
        Sale.objects.filter(pk=sale.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)
        self.client.force_login(self.manager)

    def test_yesterday_report_shows_yesterday_sales(self):
        """?day=yesterday shows yesterday's sale (1100.00)."""
        res = self.client.get(reverse('report_page'), {'day': self.yesterday.isoformat()})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '1100.00')
        self.assertContains(res, self.yesterday.strftime('%d.%m.%Y'))

    def test_today_report_does_not_show_yesterday_sales(self):
        """Without ?day the report is for today: yesterday's sale is not counted."""
        res = self.client.get(reverse('report_page'))
        self.assertContains(res, 'No sales on this day')
        self.assertNotContains(res, '1100.00')

    def test_wrong_or_future_day_falls_back_to_today(self):
        """?day=abc or a future date shows today's report, no error."""
        for value in ('abc', (self.today + timedelta(days=5)).isoformat()):
            res = self.client.get(reverse('report_page'), {'day': value})
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, self.today.strftime('%d.%m.%Y'))

    def test_excel_and_csv_use_chosen_day(self):
        """Downloads for ?day=yesterday are named with yesterday's date."""
        params = {'day': self.yesterday.isoformat()}
        xlsx = self.client.get(reverse('report_xlsx'), params)
        csv_res = self.client.get(reverse('report_csv'), params)
        self.assertIn(f'sales_{self.yesterday}.xlsx', xlsx['Content-Disposition'])
        self.assertIn(f'sales_{self.yesterday}.csv', csv_res['Content-Disposition'])
        self.assertIn('Milk', csv_res.content.decode('utf-8-sig'))
