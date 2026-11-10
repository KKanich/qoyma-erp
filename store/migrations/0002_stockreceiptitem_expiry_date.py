from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockreceiptitem',
            name='expiry_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
