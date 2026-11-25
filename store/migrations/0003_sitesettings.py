from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0002_category_image_url_product_image_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('business_name', models.CharField(default='AERIAL ELECTRONICS', max_length=200)),
                ('brand_slogan', models.CharField(default='YOUR DESTINATION FOR RELIABLE ELECTRONIC DEVICES', max_length=300)),
                ('logo_url', models.URLField(blank=True)),
                ('footer_text', models.CharField(default='Technology for a smarter world.', max_length=300)),
                ('hero_badge', models.CharField(default='Technology for a smarter world', max_length=200)),
                ('hero_title', models.CharField(default='YOUR DESTINATION FOR RELIABLE', max_length=200)),
                ('hero_highlight', models.CharField(default='ELECTRONIC DEVICES', max_length=200)),
                ('hero_description', models.TextField(default='Discover computers, smartphones, printers, accessories and more.')),
                ('hero_image_url', models.URLField(default='https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=85')),
                ('hero_image', models.ImageField(blank=True, null=True, upload_to='site/')),
                ('hero_caption', models.CharField(default='Smart devices. Better living.', max_length=200)),
                ('about_title', models.CharField(default='Technology for a smarter world', max_length=200)),
                ('about_text', models.TextField(default='AERIAL ELECTRONICS is a Kigali-based technology retailer serving homes and businesses with computers, smartphones, printers, accessories and electronics.')),
                ('phone', models.CharField(default='+250 788 945 021', max_length=50)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('address', models.CharField(default='KN 74 St, Kigali, Rwanda', max_length=200)),
                ('building', models.CharField(default='Under the Makuza Building', max_length=200)),
                ('ceo_name', models.CharField(default='Joseph Byiringiro', max_length=100)),
                ('map_query', models.CharField(default='Makuza Peace Plaza, KN 74 St, Kigali, Rwanda', max_length=300)),
                ('facebook_url', models.URLField(blank=True)),
                ('instagram_url', models.URLField(blank=True)),
                ('whatsapp_url', models.URLField(blank=True)),
            ],
            options={'verbose_name': 'Website settings', 'verbose_name_plural': 'Website settings'},
        ),
    ]
