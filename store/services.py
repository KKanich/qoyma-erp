"""Business logic for receiving goods from a supplier (stock receipt).

Acceptance criteria (Requirements, Aizada):
  AC-R1  Received quantity is added to the product stock.
  AC-R2  Quantity must be greater than 0 (no negative or zero).
  AC-R3  Only Manager or Admin may register a stock receipt (cashier -> 403).
  AC-R4  Goods whose expiry date has already passed cannot be received.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Product, StockReceipt, StockReceiptItem

ALLOWED_ROLES = ('Manager', 'Admin')


def receive_stock(user, supplier, items):
    """Register one delivery. Either everything is saved or nothing (atomic).

    items: list of dicts {barcode, qty, purchase_price, expiry_date (date)}
    """
    if user.role not in ALLOWED_ROLES:                                   # AC-R3
        raise PermissionDenied(f"Role '{user.role}' cannot receive stock.")
    if not items:
        raise ValidationError('Delivery has no items.')

    today = timezone.localdate()

    with transaction.atomic():
        receipt = StockReceipt.objects.create(supplier=supplier, received_by=user)
        total = Decimal('0.00')

        for item in items:
            barcode = str(item.get('barcode', '')).strip()
            try:
                qty = Decimal(str(item.get('qty')))
                price = Decimal(str(item.get('purchase_price')))
            except (InvalidOperation, TypeError):
                raise ValidationError(f'Invalid number for barcode {barcode}.')

            if qty <= 0:                                                 # AC-R2
                raise ValidationError(f'Quantity must be greater than 0 (barcode {barcode}).')
            if price <= 0:
                raise ValidationError(f'Purchase price must be greater than 0 (barcode {barcode}).')

            expiry = item.get('expiry_date')
            if expiry is None:
                raise ValidationError(f'Expiry date is required (barcode {barcode}).')
            if expiry < today:                                           # AC-R4
                raise ValidationError(f'Product {barcode} is already expired ({expiry}).')

            try:
                product = Product.objects.select_for_update().get(barcode=barcode)
            except Product.DoesNotExist:
                raise ValidationError(f'Product with barcode {barcode} not found.')

            StockReceiptItem.objects.create(
                stock_receipt=receipt, product=product,
                quantity=qty, purchase_price=price, expiry_date=expiry,
            )
            product.quantity += qty                                      # AC-R1
            product.expiry_date = expiry
            product.save()
            total += qty * price

        receipt.total_amount = total
        # This workflow has already applied every line inside the transaction.
        # Protect it from being applied again by the admin/script post() method.
        receipt.posted = True
        receipt.save()

    return receipt
