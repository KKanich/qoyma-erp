from django.db import models, router, transaction
from django.db.models import F
from django.core.exceptions import ValidationError
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

    posted = models.BooleanField(default=False, editable=False)

    def post(self):
        """Apply all receipt lines exactly once, together with the posting marker."""
        if self.pk is None:
            raise ValidationError('Save the receipt before posting it.')
        using = self._state.db or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            # A conditional write serializes competing attempts, including on SQLite.
            claimed = type(self).objects.using(using).filter(
                pk=self.pk, posted=False,
            ).update(posted=True)
            if not claimed:
                self.refresh_from_db(using=using)
                return False
            items = list(self.items.using(using).order_by('product_id', 'pk'))
            if not items:
                raise ValidationError('A receipt must contain at least one item.')
            total = Decimal('0.00')
            for item in items:
                item.full_clean()
                total += item.quantity * item.purchase_price
                Product.objects.using(using).filter(pk=item.product_id).update(
                    quantity=F('quantity') + item.quantity,
                )
            total = total.quantize(Decimal('0.01'))
            self._meta.get_field('total_amount').clean(total, self)
            type(self).objects.using(using).filter(pk=self.pk).update(total_amount=total)
        self.posted = True
        self.total_amount = total
        return True

class StockReceiptItem(models.Model):
    stock_receipt = models.ForeignKey(StockReceipt, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])

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
