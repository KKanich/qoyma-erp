# -*- coding: utf-8 -*-
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

        cats = {}
        for cat_name in ['Dairy', 'Bakery', 'Meat', 'Drinks', 'Grocery', 'Sweets', 'Fruits & Vegetables', 'Ұлттық өнімдер']:
            cats[cat_name], _ = Category.objects.get_or_create(name=cat_name)

        supplier, _ = Supplier.objects.get_or_create(
            name='Almaty Food Distribution', defaults={'phone': '+7 727 000 00 00'})
        supplier2, _ = Supplier.objects.get_or_create(
            name='Алатау Сүт ЖШС', defaults={'phone': '+7 727 111 22 33'})

        products = [
            # barcode, name, category, price, qty, min_qty, days_to_expiry
            ('4870000000011', 'Milk 2.5% 1L', 'Dairy', '550.00', '20.00', '5.00', 5),
            ('4870000000028', 'Kefir 1L', 'Dairy', '450.00', '4.00', '5.00', 12),
            ('4870000000035', 'Rye Bread', 'Bakery', '190.00', '30.00', '10.00', 2),
            ('4870000000042', 'Fresh Beef 1kg', 'Meat', '3900.00', '8.00', '3.00', 4),
            ('4870000000059', 'Water 1.5L', 'Drinks', '220.00', '60.00', '12.00', 300),
            ('4870000000066', 'Apple Juice 1L', 'Drinks', '690.00', '15.00', '5.00', 90),
            ('4870000000073', 'Ayran 0.5L', 'Dairy', '320.00', '25.00', '6.00', 9),
            ('4870000000080', 'Sour Cream 20% 400g', 'Dairy', '780.00', '12.00', '4.00', 14),
            ('4870000000097', 'Cottage Cheese 5% 200g', 'Dairy', '640.00', '3.00', '4.00', 6),
            ('4870000000103', 'Butter 72.5% 180g', 'Dairy', '1150.00', '18.00', '5.00', 45),
            ('4870000000110', 'White Bread Baton', 'Bakery', '160.00', '40.00', '10.00', 3),
            ('4870000000127', 'Lepyoshka', 'Bakery', '150.00', '22.00', '8.00', 2),
            ('4870000000134', 'Croissant', 'Bakery', '350.00', '10.00', '4.00', 4),
            ('4870000000141', 'Chicken Fillet 1kg', 'Meat', '2400.00', '10.00', '3.00', 5),
            ('4870000000158', 'Minced Beef 500g', 'Meat', '2100.00', '2.00', '3.00', 3),
            ('4870000000165', 'Horse Meat Kazy 500g', 'Meat', '4800.00', '6.00', '2.00', 30),
            ('4870000000172', 'Coca-Cola 1L', 'Drinks', '550.00', '48.00', '12.00', 240),
            ('4870000000189', 'Black Tea 100 bags', 'Drinks', '1350.00', '20.00', '5.00', 540),
            ('4870000000196', 'Mineral Water Sary-Agash 1L', 'Drinks', '280.00', '36.00', '10.00', 360),
            ('4870000000202', 'Rice 1kg', 'Grocery', '690.00', '30.00', '8.00', 365),
            ('4870000000219', 'Buckwheat 900g', 'Grocery', '620.00', '25.00', '8.00', 365),
            ('4870000000226', 'Pasta Spaghetti 400g', 'Grocery', '380.00', '35.00', '8.00', 400),
            ('4870000000233', 'Sunflower Oil 1L', 'Grocery', '890.00', '20.00', '6.00', 300),
            ('4870000000240', 'Sugar 1kg', 'Grocery', '520.00', '28.00', '8.00', 700),
            ('4870000000257', 'Flour 2kg', 'Grocery', '760.00', '15.00', '5.00', 300),
            ('4870000000264', 'Chocolate Kazakhstan 100g', 'Sweets', '650.00', '30.00', '8.00', 250),
            ('4870000000271', 'Rakhat Candies 250g', 'Sweets', '990.00', '14.00', '5.00', 180),
            ('4870000000288', 'Apples Aport 1kg', 'Fruits & Vegetables', '850.00', '25.00', '8.00', 14),
            ('4870000000295', 'Potatoes 1kg', 'Fruits & Vegetables', '250.00', '50.00', '15.00', 30),
            ('4870000000301', 'Tomatoes 1kg', 'Fruits & Vegetables', '1200.00', '9.00', '5.00', 6),
            ('4870000000318', 'Құрт 200г', 'Ұлттық өнімдер', '900.00', '16.00', '5.00', 120),
            ('4870000000325', 'Қымыз 1л', 'Ұлттық өнімдер', '1500.00', '8.00', '4.00', 5),
            ('4870000000332', 'Шұбат 1л', 'Ұлттық өнімдер', '1700.00', '6.00', '4.00', 6),
        ]
        for barcode, name, cat, price, qty, min_qty, days in products:
            Product.objects.update_or_create(
                barcode=barcode,
                defaults={
                    'name': name,
                    'category': cats[cat],
                    'supplier': supplier2 if cat == 'Dairy' else supplier,
                    'sale_price': Decimal(price),
                    'quantity': Decimal(qty),
                    'min_quantity': Decimal(min_qty),
                    'expiry_date': today + timedelta(days=days),
                },
            )

        self.stdout.write(self.style.SUCCESS(f'Demo data created: {Product.objects.count()} products, {Category.objects.count()} categories.'))
        for username, password, role, *_ in DEMO_USERS:
            self.stdout.write(f'  {role:<8} login: {username:<8} password: {password}')
