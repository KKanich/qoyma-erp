from datetime import date

from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Product, Sale, SaleItem, Supplier, User


class CatalogTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user('catalog-manager', role='Manager')
        self.client.force_login(self.manager)
        self.category = Category.objects.create(name='Dairy')
        self.supplier = Supplier.objects.create(name='Local supplier', phone='123')
        self.data = dict(barcode='0123456789012', name='Demo milk', category=self.category.pk,
                         supplier=self.supplier.pk, sale_price='450.00', min_quantity='5.00',
                         expiry_date='2030-01-01')
        self.product = Product.objects.create(**{**self.data, 'category': self.category,
                                                'supplier': self.supplier, 'quantity': 0,
                                                'expiry_date': date(2030, 1, 1)})

    def test_create_edit_and_preserve_stock(self):
        data = {**self.data, 'barcode': '0123456789013', 'quantity': '999'}
        self.assertRedirects(self.client.post(reverse('product_create'), data), reverse('product_list'))
        product = Product.objects.get(barcode=data['barcode'])
        self.assertEqual(product.quantity, 0)
        Product.objects.filter(pk=product.pk).update(quantity=7)
        self.client.post(reverse('product_edit', args=[product.pk]), {**data, 'name': 'Updated'})
        product.refresh_from_db()
        self.assertEqual(product.name, 'Updated')
        self.assertEqual(product.quantity, 7)

    def test_invalid_data_is_not_saved(self):
        for changes in ({'barcode': 'bad'}, {'sale_price': '-1'}, {'category': '99999'},
                        {'min_quantity': '-1'}, {'expiry_date': 'invalid'}, {}):
            with self.subTest(changes=changes):
                response = self.client.post(reverse('product_create'), {**self.data, **changes})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertEqual(Product.objects.count(), 1)

    def test_search_and_low_stock(self):
        response = self.client.get(reverse('product_list'), {'q': 'Demo', 'low': '1'})
        self.assertContains(response, 'Demo milk')
        self.assertContains(response, 'Local supplier')
        self.assertNotContains(self.client.get(reverse('product_list'), {'q': 'missing'}), 'Demo milk')
        Product.objects.filter(pk=self.product.pk).update(quantity=10)
        self.assertNotContains(self.client.get(reverse('product_list'), {'low': '1'}), 'Demo milk')

    def test_delete_requires_post_and_zero_stock(self):
        url = reverse('product_delete', args=[self.product.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        Product.objects.filter(pk=self.product.pk).update(quantity=1)
        self.assertContains(self.client.post(url, follow=True), 'Products with stock cannot be deleted.')
        Product.objects.filter(pk=self.product.pk).update(quantity=0)
        self.client.post(url)
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())

    def test_historical_product_cannot_be_deleted(self):
        sale = Sale.objects.create(cashier=self.manager)
        SaleItem.objects.create(sale=sale, product=self.product, quantity=1, unit_price=450, subtotal=450)
        response = self.client.post(reverse('product_delete', args=[self.product.pk]), follow=True)
        self.assertContains(response, 'has sales or receipt history')
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_roles_and_anonymous_access(self):
        urls = [reverse('product_list'), reverse('product_create'),
                reverse('product_edit', args=[self.product.pk]),
                reverse('product_delete', args=[self.product.pk])]
        cashier = User.objects.create_user('catalog-cashier', role='Cashier')
        self.client.force_login(cashier)
        for url in urls:
            for method in ('get', 'post'):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        admin = User.objects.create_user('catalog-admin', role='Admin')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(urls[0]).status_code, 200)

    def test_csrf_and_missing_product(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        self.assertEqual(client.post(reverse('product_create'), self.data).status_code, 403)
        self.assertEqual(self.client.get(reverse('product_edit', args=[99999])).status_code, 404)

    def test_related_rows_do_not_add_queries(self):
        for i in range(5):
            Product.objects.create(barcode=f'{i+10:013}', name=f'Product {i}', category=self.category,
                                   supplier=self.supplier, sale_price=1, quantity=0, expiry_date=date(2030, 1, 1))
        # Session, user, count and the joined product query; no per-row lookups.
        with self.assertNumQueries(4):
            self.client.get(reverse('product_list'))
