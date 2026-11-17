from django import forms

from .models import Product


class ProductForm(forms.ModelForm):
    """Catalog fields only: inventory is changed by receipts and sales."""

    class Meta:
        model = Product
        fields = ['barcode', 'name', 'category', 'supplier', 'sale_price',
                  'min_quantity', 'expiry_date']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}
