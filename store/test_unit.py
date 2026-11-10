"""Isolated validation and authorization tests: no database access allowed."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from .decorators import role_required
from .models import Product, barcode_validator
from .services import receive_stock


class ProductValidationUnitTests(SimpleTestCase):
    def test_u01_barcode_length_and_characters(self):
        barcode_validator('4870000000011')
        for value in ('123', '48700000000111', '48700000000AB', ''):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                barcode_validator(value)

    def test_u02_price_boundary(self):
        field = Product._meta.get_field('sale_price')
        self.assertEqual(field.clean('0.01', None), Decimal('0.01'))
        for value in ('0', '-0.01', 'abc', 'NaN', 'Infinity', '1.001'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.clean(value, None)

    def test_u03_stock_boundary(self):
        field = Product._meta.get_field('quantity')
        self.assertEqual(field.clean('0', None), Decimal('0'))
        for value in ('-0.01', None, 'NaN'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.clean(value, None)


class AuthorizationUnitTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/receive/?source=qa')
        self.view = Mock(return_value=HttpResponse('allowed'))
        self.protected = role_required('Manager', 'Admin')(self.view)

    def test_u04_anonymous_redirect_does_not_call_view(self):
        self.request.user = SimpleNamespace(is_authenticated=False)
        response = self.protected(self.request)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/?next=', response.url)
        self.view.assert_not_called()

    def test_u05_wrong_role_does_not_call_view(self):
        self.request.user = SimpleNamespace(is_authenticated=True, role='Cashier')
        with self.assertRaises(PermissionDenied):
            self.protected(self.request)
        self.view.assert_not_called()

    def test_u06_manager_and_admin_are_allowed(self):
        for role in ('Manager', 'Admin'):
            with self.subTest(role=role):
                self.request.user = SimpleNamespace(is_authenticated=True, role=role)
                self.assertEqual(self.protected(self.request).status_code, 200)
        self.assertEqual(self.view.call_count, 2)

    def test_u07_receipt_rejects_cashier_before_database_work(self):
        with self.assertRaises(PermissionDenied):
            receive_stock(SimpleNamespace(role='Cashier'), None, [])

    def test_u08_receipt_rejects_empty_delivery_before_database_work(self):
        with self.assertRaisesMessage(ValidationError, 'Delivery has no items'):
            receive_stock(SimpleNamespace(role='Manager'), None, [])
