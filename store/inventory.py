"""Physical stock counts and the inventory audit trail."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Round
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .decorators import role_required
from .excel_export import build_inventory_workbook
from .forms import StockCountForm
from .models import Product, StockMovement


@role_required('Manager', 'Admin')
@require_http_methods(['GET', 'POST'])
def adjust_stock(request, pk):
    product = get_object_or_404(Product.objects.annotate(last_move=Max('stockmovement__id')), pk=pk)
    form = StockCountForm(request.POST if request.method == 'POST' else None, initial={
        'expected': product.quantity, 'last_movement': product.last_move or 0,
    })
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        if data['counted'] == data['expected']:
            form.add_error('counted', 'The count matches the recorded balance.')
        else:
            with transaction.atomic():
                # The first statement takes the SQLite write lock. Verify both the
                # balance and the ledger version, even if stock returned to its old value.
                current = Product.objects.alias(balance=Round('quantity', 2)).filter(
                    pk=pk, balance=data['expected'],
                ).exclude(stockmovement__pk__gt=data['last_movement'])
                if current.update(quantity=data['counted']):
                    product.refresh_from_db()
                    movement = StockMovement.record(product, data['expected'], request.user,
                                                    reason=data['reason'])
                    messages.success(request, f'Adjustment #{movement.pk} saved for {product.name}.')
                    return redirect('inventory_audit')
            form.add_error(None, 'Stock changed since this count was opened. Reload the page and recount.')
    return render(request, 'store/adjust_stock.html', {'product': product, 'form': form})


def movement_rows():
    return StockMovement.objects.select_related('sale_item', 'receipt_item')


@role_required('Manager', 'Admin')
@require_GET
def inventory_audit(request):
    page = Paginator(movement_rows().order_by('-pk'), 50).get_page(request.GET.get('page'))
    return render(request, 'store/inventory_audit.html', {'page': page})


@role_required('Manager', 'Admin')
@require_GET
def inventory_xlsx(request):
    workbook = build_inventory_workbook(movement_rows().order_by('pk').iterator())
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="inventory_audit_{timezone.localdate()}.xlsx"'
    workbook.save(response)
    return response
