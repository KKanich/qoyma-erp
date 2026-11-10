import json
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone

from .decorators import role_required
from .models import Product, Sale, SaleItem, Supplier
from .services import receive_stock


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


@role_required('Manager', 'Admin')
def stock_receipt_api(request):
    """Register goods arriving from a supplier. Manager/Admin only (cashier -> 403)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    try:
        data = json.loads(request.body)
        supplier = Supplier.objects.get(pk=data.get('supplier_id'))
        items = []
        for it in data.get('items', []):
            it = dict(it)
            it['expiry_date'] = date.fromisoformat(it['expiry_date']) if it.get('expiry_date') else None
            items.append(it)
    except (json.JSONDecodeError, Supplier.DoesNotExist, ValueError, KeyError) as e:
        return JsonResponse({'error': f'Invalid request: {e}'}, status=400)

    try:
        receipt = receive_stock(request.user, supplier, items)
    except ValidationError as e:
        return JsonResponse({'error': ' '.join(e.messages)}, status=400)

    return JsonResponse({'status': 'Success', 'receipt_id': receipt.id, 'total': str(receipt.total_amount)})


@role_required('Manager', 'Admin')
def receive_page(request):
    """Manager screen for receiving goods. Uses the same receive_stock() rules (AC-R1..AC-R4)."""
    ctx = {
        'suppliers': Supplier.objects.order_by('name'),
        'default_expiry': (timezone.localdate() + timedelta(days=10)).isoformat(),
        'form': {},
    }
    if request.method == 'POST':
        form = {k: request.POST.get(k, '').strip() for k in ('supplier', 'barcode', 'qty', 'price', 'expiry')}
        ctx['form'] = form
        try:
            supplier = Supplier.objects.get(pk=form['supplier'])
            expiry = date.fromisoformat(form['expiry']) if form['expiry'] else None
            product = Product.objects.filter(barcode=form['barcode']).first()
            before = product.quantity if product else None
            receive_stock(request.user, supplier, [{
                'barcode': form['barcode'], 'qty': form['qty'],
                'purchase_price': form['price'], 'expiry_date': expiry,
            }])
            product.refresh_from_db()
            ctx['success'] = (f'Received {form["qty"]} × {product.name}. '
                              f'Stock: {before} → {product.quantity}')
            ctx['changed'] = product.barcode
            ctx['form'] = {}
        except (Supplier.DoesNotExist, ValueError):
            ctx['error'] = 'Check the supplier and the date.'
        except ValidationError as e:
            ctx['error'] = ' '.join(e.messages)
    ctx['products'] = Product.objects.order_by('name')
    return render(request, 'store/receive.html', ctx)
