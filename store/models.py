from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, RegexValidator
from decimal import Decimal

class User(AbstractUser):
    ROLE_CHOICES = (
        ('Admin', 'Admin'),
        ('Manager', 'Manager'),
        ('Cashier', 'Cashier'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Cashier')

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True, null=True)

    def __str__(self):
        return self.name

# Data rules from Task 7 (Data Dictionary), owner: Systems Analysis & Requirements Lead
barcode_validator = RegexValidator(
    regex=r'^\d{13}$',
    message='Barcode must be exactly 13 digits (EAN-13).',
)


class Product(models.Model):
    barcode = models.CharField(max_length=13, unique=True, validators=[barcode_validator])
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.RESTRICT)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('5.00'), validators=[MinValueValidator(Decimal('0.00'))])
    expiry_date = models.DateField()

    def save(self, *args, **kwargs):
        # Governance rule (Task 7): a Product that breaks a data rule is never saved,
        # no matter where it comes from (admin form, POS, script).
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.barcode})'

class StockReceipt(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.RESTRICT)
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(User, on_delete=models.RESTRICT)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

class StockReceiptItem(models.Model):
    stock_receipt = models.ForeignKey(StockReceipt, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    expiry_date = models.DateField(null=True, blank=True)  # expiry of the delivered batch

class Sale(models.Model):
    PAYMENT_CHOICES = (
        ('Cash', 'Cash'),
        ('Kaspi_QR', 'Kaspi QR'),
        ('Card', 'Card'),
    )
    cashier = models.ForeignKey(User, on_delete=models.RESTRICT)
    created_at = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='Cash')

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
