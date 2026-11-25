from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_customer_name_order_payer_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emailotp',
            name='code',
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name='emailotp',
            name='purpose',
            field=models.CharField(default='login', max_length=32),
        ),
        migrations.AddField(
            model_name='emailotp',
            name='attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
