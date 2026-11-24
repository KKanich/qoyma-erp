from decimal import Decimal

from django import forms

from .models import Product


class ProductForm(forms.ModelForm):
    """Catalog fields only. Stock changes go through inventory workflows."""

    class Meta:
        model = Product
        fields = ['barcode', 'name', 'category', 'supplier', 'sale_price',
                  'min_quantity', 'expiry_date']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}


class StockCountForm(forms.Form):
    counted = forms.DecimalField(label='Counted stock', min_value=Decimal('0'),
                                 max_digits=10, decimal_places=2)
    reason = forms.CharField(max_length=200, label='Reason for the difference')
    expected = forms.DecimalField(widget=forms.HiddenInput, max_digits=10, decimal_places=2)
    last_movement = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
