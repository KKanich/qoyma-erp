from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand
from django.utils import timezone

from store.models import Category, Product, Supplier, User

DEMO_USERS = [
    # username, password, role, is_staff, is_superuser
    ('admin', 'QoymaAdmin2026', 'Admin', True, True),
    ('manager', 'QoymaManager2026', 'Manager', True, False),
    ('cashier', 'QoymaCashier2026', 'Cashier', False, False),
]

MANAGER_PERMS = [
    'add_product', 'change_product', 'view_product',
    'add_category', 'change_category', 'view_category',
    'add_supplier', 'change_supplier', 'view_supplier',
    'add_stockreceipt', 'change_stockreceipt', 'view_stockreceipt',
    'add_stockreceiptitem', 'change_stockreceiptitem', 'view_stockreceiptitem',
    'view_sale', 'view_saleitem',
]


class Command(BaseCommand):
    help = 'Create demo users, categories, a supplier and products for Bereke store.'

    def handle(self, *args, **options):
        today = timezone.localdate()

        for username, password, role, is_staff, is_superuser in DEMO_USERS:
            user, _ = User.objects.get_or_create(username=username)
            user.role = role
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            if role == 'Manager':
                user.user_permissions.set(Permission.objects.filter(
                    content_type__app_label='store', codename__in=MANAGER_PERMS))

        dairy, _ = Category.objects.get_or_create(name='Dairy')
        bakery, _ = Category.objects.get_or_create(name='Bakery')
        meat, _ = Category.objects.get_or_create(name='Meat')
        drinks, _ = Category.objects.get_or_create(name='Drinks')

        supplier, _ = Supplier.objects.get_or_create(
            name='Almaty Food Distribution', defaults={'phone': '+7 727 000 00 00'})

        products = [
            # barcode, name, category, price, qty, min_qty, days_to_expiry
            ('4870000000011', 'Milk 2.5% 1L', dairy, '550.00', '20.00', '5.00', 5),
            ('4870000000028', 'Kefir 1L', dairy, '450.00', '4.00', '5.00', 12),
            ('4870000000035', 'Rye Bread', bakery, '190.00', '30.00', '10.00', 2),
            ('4870000000042', 'Fresh Beef 1kg', meat, '3900.00', '8.00', '3.00', 4),
            ('4870000000059', 'Water 1.5L', drinks, '220.00', '60.00', '12.00', 300),
            ('4870000000066', 'Apple Juice 1L', drinks, '690.00', '15.00', '5.00', 90),
        ]
        for barcode, name, cat, price, qty, min_qty, days in products:
            Product.objects.update_or_create(
                barcode=barcode,
                defaults={
                    'name': name,
                    'category': cat,
                    'supplier': supplier,
                    'sale_price': Decimal(price),
                    'quantity': Decimal(qty),
                    'min_quantity': Decimal(min_qty),
                    'expiry_date': today + timedelta(days=days),
                },
            )

        self.stdout.write(self.style.SUCCESS('Demo data created.'))
        for username, password, role, *_ in DEMO_USERS:
            self.stdout.write(f'  {role:<8} login: {username:<8} password: {password}')
