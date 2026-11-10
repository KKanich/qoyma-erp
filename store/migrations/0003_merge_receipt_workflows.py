from django.db import migrations


def preserve_existing_inventory(apps, schema_editor):
    # Legacy receipts have no reliable marker identifying whether their stock
    # was already applied. Preserve current inventory and prevent automatic
    # re-posting; any historical discrepancies require manual reconciliation.
    receipt = apps.get_model('store', 'StockReceipt')
    receipt.objects.using(schema_editor.connection.alias).filter(posted=False).update(posted=True)


class Migration(migrations.Migration):
    dependencies = [
        ('store', '0002_stockreceipt_posted'),
        ('store', '0002_stockreceiptitem_expiry_date'),
    ]

    operations = [
        migrations.RunPython(preserve_existing_inventory, migrations.RunPython.noop),
    ]
