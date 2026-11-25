import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aerial_project.settings')
import django
django.setup()

from store.models import Category, Product

category_images = {
    'laptops-computers': 'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=85',
    'smartphones': 'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=900&q=85',
    'printers': 'https://images.unsplash.com/photo-1612815154858-60aa4c59eaa6?auto=format&fit=crop&w=900&q=85',
    'accessories': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=900&q=85',
}

product_images = {
    'dell-latitude-5420': category_images['laptops-computers'],
    'samsung-galaxy-a55': category_images['smartphones'],
    'hp-laserjet-pro': category_images['printers'],
    'wireless-headphones': category_images['accessories'],
}

for slug, url in category_images.items():
    Category.objects.filter(slug=slug).update(image_url=url)

for slug, url in product_images.items():
    Product.objects.filter(slug=slug).update(image_url=url)

print('Catalog imagery updated')
