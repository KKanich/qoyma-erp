import json
from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone

from .decorators import role_required
from .models import Product, Sale, SaleItem


class CheckoutError(Exception):
    """A business-rule problem in the cart. The whole sale is rolled back."""


@ensure_csrf_cookie
@role_required('Cashier', 'Manager', 'Admin')
def pos_page(request):
    """Simple POS screen: scan barcode, add quantity, checkout."""
    products = Product.objects.select_related('category').order_by('name')
    products_json = {p.barcode: {'name': p.name, 'price': str(p.sale_price)} for p in products}
    return render(request, 'store/pos.html', {'products': products, 'products_json': products_json})


@role_required('Cashier', 'Manager', 'Admin')
def pos_checkout(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    items_data = data.get('items', [])
    payment_method = data.get('payment_method', 'Cash')

    if not items_data:
        return JsonResponse({'error': 'Cart is empty'}, status=400)
    if payment_method not in dict(Sale.PAYMENT_CHOICES):
        return JsonResponse({'error': f'Unknown payment method: {payment_method}'}, status=400)

    try:
        # Atomic: either the sale AND all stock deductions are saved, or nothing is.
        with transaction.atomic():
            sale = Sale.objects.create(
                cashier=request.user,
                payment_method=payment_method,
                total_amount=Decimal('0.00'),
            )
            running_total = Decimal('0.00')

            for item in items_data:
                barcode = str(item.get('barcode', '')).strip()
                try:
                    sale_qty = Decimal(str(item.get('qty')))
                except (InvalidOperation, TypeError):
                    raise CheckoutError(f'Invalid quantity for barcode {barcode}')
                if sale_qty <= 0:
                    raise CheckoutError(f'Quantity must be greater than 0 (barcode {barcode})')

                try:
                    product = Product.objects.select_for_update().get(barcode=barcode)
                except Product.DoesNotExist:
                    raise CheckoutError(f'Product with barcode {barcode} not found')

                if product.quantity < sale_qty:
                    raise CheckoutError(
                        f'Insufficient stock for {product.name}. Available: {product.quantity}'
                    )

                product.quantity -= sale_qty
                product.save()

                subtotal = product.sale_price * sale_qty
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    quantity=sale_qty,
                    unit_price=product.sale_price,  # price snapshot (3NF / history)
                    subtotal=subtotal,
                )
                running_total += subtotal

            sale.total_amount = running_total
            sale.save()
    except CheckoutError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'status': 'Success', 'sale_id': sale.id, 'total': str(running_total)})


@role_required('Manager', 'Admin')
def dashboard_alerts(request):
    today = timezone.localdate()
    seven_days_later = today + timedelta(days=7)

    expiry_alerts = Product.objects.filter(expiry_date__lte=seven_days_later).order_by('expiry_date')
    low_stock_alerts = Product.objects.filter(quantity__lte=F('min_quantity')).order_by('quantity')

    return JsonResponse({
        'expiry_alerts': [
            {'barcode': p.barcode, 'name': p.name, 'expiry': str(p.expiry_date)}
            for p in expiry_alerts
        ],
        'low_stock_alerts': [
            {'barcode': p.barcode, 'name': p.name, 'qty': str(p.quantity), 'min_qty': str(p.min_quantity)}
            for p in low_stock_alerts
        ],
    })
