from django.db import migrations


def invalidate_legacy_plaintext_codes(apps, schema_editor):
    EmailOTP = apps.get_model('orders', 'EmailOTP')
    EmailOTP.objects.all().update(used=True, code='')


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_emailotp_secure_codes'),
    ]

    operations = [
        migrations.RunPython(invalidate_legacy_plaintext_codes, migrations.RunPython.noop),
    ]
