"""Tests for the daily sales report page /report/ (AC-D1 on the page, AC-D11)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Product, Sale, SaleItem, User


class ReportPageTest(TestCase):

    def setUp(self):
        self.manager = User.objects.create_user('manager', password='pass12345', role='Manager')
        self.cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        milk = Product.objects.create(
            barcode='4870000000011', name='Milk', category=Category.objects.create(name='Dairy'),
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'),
            expiry_date=timezone.localdate() + timedelta(days=10))
        sale = Sale.objects.create(cashier=self.cashier, payment_method='Cash',
                                   total_amount=Decimal('1100.00'))
        SaleItem.objects.create(sale=sale, product=milk, quantity=Decimal('2'),
                                unit_price=Decimal('550.00'), subtotal=Decimal('1100.00'))

    def test_manager_sees_report_with_total(self):
        """Manager opens /report/ and sees today's total and top product."""
        self.client.force_login(self.manager)
        res = self.client.get(reverse('report_page'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '1100.00')
        self.assertContains(res, 'Milk')

    def test_acd11_cashier_cannot_open_report(self):
        """AC-D11: cashier gets 403 on /report/."""
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('report_page')).status_code, 403)

    def test_not_logged_in_is_redirected(self):
        """Anonymous user is sent to the login page."""
        res = self.client.get(reverse('report_page'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res['Location'])