from django.db import models
from django.contrib.auth.models import User


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=50, blank=True)
    image_url = models.URLField(blank=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    image_url = models.URLField(blank=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Promotion(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    discount_percent = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    starts_at = models.DateField()
    ends_at = models.DateField()

    def __str__(self):
        return self.title


class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def total(self):
        return self.product.price * self.quantity


class SiteSettings(models.Model):
    business_name = models.CharField(max_length=200, default='AERIAL ELECTRONICS')
    brand_slogan = models.CharField(max_length=300, default='YOUR DESTINATION FOR RELIABLE ELECTRONIC DEVICES')
    logo_url = models.URLField(blank=True)
    footer_text = models.CharField(max_length=300, default='Technology for a smarter world.')

    hero_badge = models.CharField(max_length=200, default='Technology for a smarter world')
    hero_title = models.CharField(max_length=200, default='YOUR DESTINATION FOR RELIABLE')
    hero_highlight = models.CharField(max_length=200, default='ELECTRONIC DEVICES')
    hero_description = models.TextField(default='Discover computers, smartphones, printers, accessories and more.')
    hero_image_url = models.URLField(default='https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=85')
    hero_image = models.ImageField(upload_to='site/', blank=True, null=True)
    hero_caption = models.CharField(max_length=200, default='Smart devices. Better living.')

    about_title = models.CharField(max_length=200, default='Technology for a smarter world')
    about_text = models.TextField(default='AERIAL ELECTRONICS is a Kigali-based technology retailer serving homes and businesses with computers, smartphones, printers, accessories and electronics.')

    phone = models.CharField(max_length=50, default='+250 788 945 021')
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, default='KN 74 St, Kigali, Rwanda')
    building = models.CharField(max_length=200, default='Under the Makuza Building')
    ceo_name = models.CharField(max_length=100, default='Joseph Byiringiro')
    map_query = models.CharField(max_length=300, default='Makuza Peace Plaza, KN 74 St, Kigali, Rwanda')

    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    whatsapp_url = models.URLField(blank=True)

    class Meta:
        verbose_name = 'Website settings'
        verbose_name_plural = 'Website settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        return cls.objects.first() or cls.objects.create(pk=1)

    def __str__(self):
        return self.business_name
