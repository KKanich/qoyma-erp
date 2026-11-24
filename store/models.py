from django.db import models, router, transaction
from django.db.models import F
from django.db.models.functions import Round
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

    def post(self, *, actor=None):
        """Apply all receipt lines exactly once, together with the posting marker."""
        if self.pk is None:
            raise ValidationError('Save the receipt before posting it.')
        using = self._state.db or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
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
                product = Product.objects.using(using).select_for_update().get(pk=item.product_id)
                before = product.quantity
                product.quantity = Product._meta.get_field('quantity').clean(before + item.quantity, product)
                Product.objects.using(using).filter(pk=item.product_id).update(
                    quantity=Round(F('quantity') + item.quantity, 2),
                )
                StockMovement.record(product, before, actor or self.received_by, receipt_item=item)
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


class StockMovement(models.Model):
    """One committed stock change. Source lines identify sales and deliveries."""
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)
    product_name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=13)
    username = models.CharField(max_length=150)
    before = models.DecimalField(max_digits=10, decimal_places=2)
    after = models.DecimalField(max_digits=10, decimal_places=2)
    sale_item = models.OneToOneField(SaleItem, null=True, on_delete=models.PROTECT)
    receipt_item = models.OneToOneField(StockReceiptItem, null=True, on_delete=models.PROTECT)
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(name='stock_movement_valid', check=(
                models.Q(before__gte=0, after__gte=0) & (
                    models.Q(sale_item__isnull=False, receipt_item__isnull=True, after__lt=F('before'), reason='')
                    | models.Q(receipt_item__isnull=False, sale_item__isnull=True, after__gt=F('before'), reason='')
                    | (models.Q(sale_item__isnull=True, receipt_item__isnull=True)
                       & ~models.Q(reason='') & ~models.Q(after=F('before')))
                )
            )),
        ]

    @classmethod
    def record(cls, product, before, actor, **source):
        return cls.objects.using(product._state.db).create(
            product=product, actor=actor, username=actor.username,
            product_name=product.name, barcode=product.barcode,
            before=before, after=product.quantity, **source,
        )

    @property
    def change(self):
        return self.after - self.before

    @property
    def kind(self):
        if self.sale_item_id:
            return 'Sale'
        if self.receipt_item_id:
            return 'Receipt'
        return 'Adjustment'

    @property
    def reference(self):
        if self.sale_item_id:
            return f'Sale #{self.sale_item.sale_id}'
        if self.receipt_item_id:
            return f'Receipt #{self.receipt_item.stock_receipt_id}'
        return self.reason
