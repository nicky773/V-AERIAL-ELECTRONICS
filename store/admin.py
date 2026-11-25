from django.contrib import admin
from .models import Category, Product, Promotion, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Identity', {'fields': ('business_name', 'brand_slogan', 'logo_url', 'footer_text')}),
        ('Hero', {'fields': ('hero_badge', 'hero_title', 'hero_highlight', 'hero_description', 'hero_image_url', 'hero_image', 'hero_caption')}),
        ('About and contact', {'fields': ('about_title', 'about_text', 'phone', 'email', 'address', 'building', 'ceo_name', 'map_query')}),
        ('Social links', {'fields': ('facebook_url', 'instagram_url', 'whatsapp_url')}),
    )


admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Promotion)
