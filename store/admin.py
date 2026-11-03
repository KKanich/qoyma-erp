from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (Category, Product, Sale, SaleItem, StockReceipt,
                     StockReceiptItem, Supplier, User)


@admin.register(User)
class QoymaUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Qoyma role', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Qoyma role', {'fields': ('role',)}),
    )
    list_display = ('username', 'role', 'is_staff')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'barcode', 'category', 'sale_price', 'quantity',
        'min_quantity', 'expiry_date',
    )
    search_fields = ('name', 'barcode')
    list_filter = ('category',)


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'unit_price', 'subtotal')


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'cashier', 'created_at', 'payment_method', 'total_amount',
    )
    inlines = [SaleItemInline]


class StockReceiptItemInline(admin.TabularInline):
    model = StockReceiptItem
    extra = 1


@admin.register(StockReceipt)
class StockReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'supplier', 'received_by', 'received_at', 'total_amount',
    )
    inlines = [StockReceiptItemInline]


admin.site.register(Category)
admin.site.register(Supplier)
admin.site.site_header = 'Qoyma ERP — Bereke Grocery Store'
