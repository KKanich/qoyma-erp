from django.db import migrations


# Frozen from the two versions of seed_demo. Match the original demo identity
# before changing the barcode. Stock and historical barcode snapshots stay intact.
DEMO_BARCODES = (
    ('4870000000011', '4870000000012', 'Milk 2.5% 1L'),
    ('4870000000028', '4870000000029', 'Kefir 1L'),
    ('4870000000035', '4870000000036', 'Rye Bread'),
    ('4870000000042', '4870000000043', 'Fresh Beef 1kg'),
    ('4870000000059', '4870000000050', 'Water 1.5L'),
    ('4870000000066', '4870000000067', 'Apple Juice 1L'),
    ('4870000000073', '4870000000074', 'Ayran 0.5L'),
    ('4870000000080', '4870000000081', 'Sour Cream 20% 400g'),
    ('4870000000097', '4870000000098', 'Cottage Cheese 5% 200g'),
    ('4870000000103', '4870000000104', 'Butter 72.5% 180g'),
    ('4870000000110', '4870000000111', 'White Bread Baton'),
    ('4870000000127', '4870000000128', 'Lepyoshka'),
    ('4870000000134', '4870000000135', 'Croissant'),
    ('4870000000141', '4870000000142', 'Chicken Fillet 1kg'),
    ('4870000000158', '4870000000159', 'Minced Beef 500g'),
    ('4870000000165', '4870000000166', 'Horse Meat Kazy 500g'),
    ('4870000000172', '4870000000173', 'Coca-Cola 1L'),
    ('4870000000189', '4870000000180', 'Black Tea 100 bags'),
    ('4870000000196', '4870000000197', 'Mineral Water Sary-Agash 1L'),
    ('4870000000202', '4870000000203', 'Rice 1kg'),
    ('4870000000219', '4870000000210', 'Buckwheat 900g'),
    ('4870000000226', '4870000000227', 'Pasta Spaghetti 400g'),
    ('4870000000233', '4870000000234', 'Sunflower Oil 1L'),
    ('4870000000240', '4870000000241', 'Sugar 1kg'),
    ('4870000000257', '4870000000258', 'Flour 2kg'),
    ('4870000000264', '4870000000265', 'Chocolate Kazakhstan 100g'),
    ('4870000000271', '4870000000272', 'Rakhat Candies 250g'),
    ('4870000000288', '4870000000289', 'Apples Aport 1kg'),
    ('4870000000295', '4870000000296', 'Potatoes 1kg'),
    ('4870000000301', '4870000000302', 'Tomatoes 1kg'),
    ('4870000000318', '4870000000319', 'Құрт 200г'),
    ('4870000000325', '4870000000326', 'Қымыз 1л'),
    ('4870000000332', '4870000000333', 'Шұбат 1л'),
)


def correct_demo_barcodes(apps, schema_editor):
    products = apps.get_model('store', 'Product').objects.using(schema_editor.connection.alias)
    for old, new, name in DEMO_BARCODES:
        # Both codes may already have stock and history of their own.
        if not products.filter(barcode=new).exists():
            products.filter(barcode=old, name=name).update(barcode=new)


class Migration(migrations.Migration):
    dependencies = [('store', '0005_merge_20261124_1857')]
    operations = [migrations.RunPython(correct_demo_barcodes, migrations.RunPython.noop)]
