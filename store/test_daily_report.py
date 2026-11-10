"""Tests for the daily sales report calculations (AC-D1..AC-D8)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from .models import Category, Product, Sale, SaleItem, User
from .reports import daily_sales_summary


class DailySalesSummaryTest(TestCase):

    def setUp(self):
        self.cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        dairy = Category.objects.create(name='Dairy')
        future = timezone.localdate() + timedelta(days=10)
        self.milk = Product.objects.create(
            barcode='4870000000011', name='Milk', category=dairy,
            sale_price=Decimal('550.00'), quantity=Decimal('20.00'), expiry_date=future)
        self.bread = Product.objects.create(
            barcode='4870000000035', name='Bread', category=dairy,
            sale_price=Decimal('190.00'), quantity=Decimal('30.00'), expiry_date=future)
        self.kefir = Product.objects.create(
            barcode='4870000000028', name='Kefir', category=dairy,
            sale_price=Decimal('450.00'), quantity=Decimal('4.00'),
            min_quantity=Decimal('5.00'), expiry_date=future)

    def sell(self, items, payment='Cash'):
        """Create one sale. items = [(product, qty), ...]"""
        sale = Sale.objects.create(cashier=self.cashier, payment_method=payment)
        total = Decimal('0.00')
        for product, qty in items:
            qty = Decimal(qty)
            subtotal = product.sale_price * qty
            SaleItem.objects.create(sale=sale, product=product, quantity=qty,
                                    unit_price=product.sale_price, subtotal=subtotal)
            total += subtotal
        sale.total_amount = total
        sale.save()
        return sale

    def test_acd1_total_amount_today(self):
        """AC-D1: 2 Milk (1 100) + 1 Bread (190) = 1 290."""
        self.sell([(self.milk, 2), (self.bread, 1)])
        self.assertEqual(daily_sales_summary()['total'], Decimal('1290.00'))

    def test_acd2_number_of_receipts(self):
        """AC-D2: 3 sales -> 3 receipts."""
        for _ in range(3):
            self.sell([(self.bread, 1)])
        self.assertEqual(daily_sales_summary()['receipts'], 3)

    def test_acd3_average_receipt(self):
        """AC-D3: 1 100 and 2 200 -> average 1 650."""
        self.sell([(self.milk, 2)])
        self.sell([(self.milk, 4)])
        self.assertEqual(daily_sales_summary()['average'], Decimal('1650.00'))

    def test_acd4_split_by_payment_method(self):
        """AC-D4: Cash and Kaspi QR shown separately, Card = 0."""
        self.sell([(self.milk, 1)], payment='Cash')
        self.sell([(self.bread, 1)], payment='Kaspi_QR')
        by_payment = daily_sales_summary()['by_payment']
        self.assertEqual(by_payment['Cash'], Decimal('550.00'))
        self.assertEqual(by_payment['Kaspi_QR'], Decimal('190.00'))
        self.assertEqual(by_payment['Card'], Decimal('0.00'))

    def test_acd5_top_products(self):
        """AC-D5: Milk sold 5, Bread sold 2 -> Milk is first."""
        self.sell([(self.milk, 5), (self.bread, 2)])
        top = daily_sales_summary()['top_products']
        self.assertEqual(top[0]['product__name'], 'Milk')
        self.assertEqual(top[0]['qty'], Decimal('5.00'))

    def test_acd6_low_stock_list(self):
        """AC-D6: Kefir 4 <= minimum 5 -> in low-stock list; Milk is not."""
        names = [p['name'] for p in daily_sales_summary()['low_stock']]
        self.assertIn('Kefir', names)
        self.assertNotIn('Milk', names)

    def test_acd7_only_today_is_counted(self):
        """AC-D7: a sale from yesterday is not in today's total."""
        old = self.sell([(self.milk, 10)])
        Sale.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.sell([(self.bread, 1)])
        summary = daily_sales_summary()
        self.assertEqual(summary['total'], Decimal('190.00'))
        self.assertEqual(summary['receipts'], 1)

    def test_acd8_no_sales_no_error(self):
        """AC-D8: no sales today -> zeros, no error."""
        summary = daily_sales_summary()
        self.assertEqual(summary['total'], Decimal('0.00'))
        self.assertEqual(summary['receipts'], 0)
        self.assertEqual(summary['average'], Decimal('0.00'))
        self.assertEqual(summary['top_products'], [])