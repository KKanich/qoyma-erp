"""Join the independent scanner and stock ledger migrations."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0004_receiptscansession_receiptscanevent'),
        ('store', '0004_stock_movement'),
    ]

    operations = [
    ]
