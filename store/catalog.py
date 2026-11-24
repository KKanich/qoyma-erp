"""Manager-facing ORM CRUD views for the product catalog."""
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.deletion import RestrictedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .decorators import role_required
from .forms import ProductForm
from .models import Product


@role_required('Manager', 'Admin')
@require_http_methods(['GET'])
def product_list(request):
    products = Product.objects.select_related('category', 'supplier').order_by('name', 'pk')
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
    low_stock = request.GET.get('low') == '1'
    if low_stock:
        products = products.filter(quantity__lte=F('min_quantity'))
    return render(request, 'store/products.html', {
        'page': Paginator(products, 25).get_page(request.GET.get('page')),
        'query': query, 'low_stock': low_stock,
    })


@role_required('Manager', 'Admin')
@require_http_methods(['GET', 'POST'])
def product_edit(request, pk=None):
    # A new product starts at zero; edits never write a stale stock quantity.
    with transaction.atomic():
        product = (get_object_or_404(Product.objects.select_for_update(), pk=pk)
                   if pk is not None else Product(quantity=Decimal('0.00')))
        form = ProductForm(request.POST if request.method == 'POST' else None, instance=product)
        if request.method == 'POST' and form.is_valid():
            try:
                with transaction.atomic():
                    product = form.save(commit=False)
                    product.save(update_fields=form.Meta.fields if pk is not None else None)
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
            except IntegrityError:
                form.add_error(None, 'The product conflicts with another saved record. Please retry.')
            else:
                messages.success(request, f'Product {product.name} saved.')
                return redirect('product_list')
    return render(request, 'store/product_form.html', {'form': form, 'product': product})


@role_required('Manager', 'Admin')
@require_http_methods(['GET', 'POST'])
def product_delete(request, pk):
    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), pk=pk)
        if request.method == 'POST':
            if product.quantity != 0:
                messages.error(request, 'Products with stock cannot be deleted.')
            else:
                try:
                    with transaction.atomic():
                        product.delete()
                except (RestrictedError, IntegrityError):
                    messages.error(request, 'This product has sales or receipt history, or a recorded stock adjustment, and cannot be deleted.')
                else:
                    messages.success(request, 'Product deleted.')
            return redirect('product_list')
    return render(request, 'store/product_delete.html', {'product': product})
