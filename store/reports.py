"""Daily sales report — calculations (AC-D1..AC-D8).

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)
"""
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

from .models import Product, Sale, SaleItem


def daily_sales_summary(day=None):
    """Return the numbers the manager sees on the daily sales report."""
    day = day or timezone.localdate()

    # AC-D7: only sales made on this day are counted
    sales = Sale.objects.filter(created_at__date=day)

    # AC-D1: total amount; AC-D8: 0 when there are no sales
    total = sales.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')

    # AC-D2: number of receipts
    receipts = sales.count()

    # AC-D3: average receipt
    average = (total / receipts).quantize(Decimal('0.01')) if receipts else Decimal('0.00')

    # AC-D4: total split by payment method (every method is shown, even if 0)
    by_payment = {code: Decimal('0.00') for code, _ in Sale.PAYMENT_CHOICES}
    for row in sales.values('payment_method').annotate(s=Sum('total_amount')):
        by_payment[row['payment_method']] = row['s']

    # AC-D5: top 5 products by quantity sold today
    top_products = list(
        SaleItem.objects.filter(sale__in=sales)
        .values('product__name')
        .annotate(qty=Sum('quantity'), amount=Sum('subtotal'))
        .order_by('-qty', 'product__name')[:5]
    )

    # AC-D6: products at or below their minimum stock level
    low_stock = list(
        Product.objects.filter(quantity__lte=F('min_quantity'))
        .order_by('quantity')
        .values('name', 'quantity', 'min_quantity')
    )

    return {
        'day': day,
        'total': total,
        'receipts': receipts,
        'average': average,
        'by_payment': by_payment,
        'top_products': top_products,
        'low_stock': low_stock,
    }



def sales_rows(day=None):
    """Every item sold on this day, ready for CSV / Excel export."""
    day = day or timezone.localdate()
    items = (SaleItem.objects.filter(sale__created_at__date=day)
             .select_related('sale', 'sale__cashier', 'product')
             .order_by('sale__created_at', 'id'))
    return [{
        'sale_id': item.sale.id,
        'time': timezone.localtime(item.sale.created_at).strftime('%H:%M'),
        'cashier': item.sale.cashier.username,
        'product': item.product.name,
        'qty': item.quantity,
        'unit_price': item.unit_price,
        'subtotal': item.subtotal,
        'payment': item.sale.payment_method,
    } for item in items]