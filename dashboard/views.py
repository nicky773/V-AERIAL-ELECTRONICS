from django.contrib import messages as django_messages
from django.contrib.admin.views.decorators import staff_member_required
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from store.models import Category, Product, Promotion, SiteSettings
from orders.models import Order
from messaging.models import CustomerMessage
from orders.views import generate_invoice_qr

logger = logging.getLogger(__name__)


@staff_member_required
def dashboard(request):
    return render(request, 'dashboard/dashboard.html', {
        'revenue': Order.objects.filter(payment_status='paid').aggregate(total=Sum('total'))['total'] or 0,
        'orders_count': Order.objects.count(),
        'customers_count': User.objects.filter(is_staff=False).count(),
        'low_stock': Product.objects.filter(stock__lte=5).order_by('stock')[:10],
        'orders': Order.objects.select_related('user').order_by('-created_at')[:8],
        'messages': CustomerMessage.objects.filter(replied=False).count(),
    })


@staff_member_required
def categories(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            category = get_object_or_404(Category, id=request.POST.get('category_id'))
            if not category.products.exists():
                category.delete()
        elif action == 'edit':
            category = get_object_or_404(Category, id=request.POST.get('category_id'))
            name = request.POST.get('name', '').strip()
            if name:
                category.name = name
                category.icon = request.POST.get('icon', '')
                category.image_url = request.POST.get('image_url', '')
                category.slug = slugify(name)
                category.save()
        else:
            name = request.POST.get('name', '').strip()
            if name:
                base_slug = slugify(name)
                slug = base_slug
                suffix = 1
                while Category.objects.filter(slug=slug).exists():
                    slug = f'{base_slug}-{suffix}'
                    suffix += 1
                Category.objects.create(name=name, slug=slug, icon=request.POST.get('icon', 'cpu'), image_url=request.POST.get('image_url', ''))
        return redirect('admin_categories')
    return render(request, 'dashboard/categories.html', {'categories': Category.objects.all().order_by('name')})


@staff_member_required
def inventory(request):
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            product = get_object_or_404(Product, id=request.POST.get('product_id'))
            product.delete()
            return redirect('admin_inventory')

        product_id = request.POST.get('product_id')
        if product_id:
            product = get_object_or_404(Product, id=product_id)
            product.name = request.POST.get('name', product.name)
            product.description = request.POST.get('description', product.description)
            product.category_id = request.POST.get('category', product.category_id)
            product.price = request.POST.get('price', product.price)
            product.stock = request.POST.get('stock', product.stock)
            product.image_url = request.POST.get('image_url', product.image_url)
            product.featured = request.POST.get('featured') == 'on'
            if 'image' in request.FILES:
                product.image = request.FILES['image']
            product.save()
        else:
            name = request.POST['name']
            base_slug = slugify(name)
            slug = base_slug
            suffix = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{suffix}'
                suffix += 1
            Product.objects.create(category_id=request.POST['category'], name=name, slug=slug, description=request.POST['description'], price=request.POST['price'], stock=request.POST['stock'], image_url=request.POST.get('image_url', ''), featured=request.POST.get('featured') == 'on', **({'image': request.FILES['image']} if 'image' in request.FILES else {}))
        return redirect('admin_inventory')
    return render(request, 'dashboard/inventory.html', {'products': Product.objects.select_related('category').all(), 'categories': Category.objects.all()})


@staff_member_required
def orders(request):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=request.POST['order_id'])
        previous_status = order.status

        if request.POST.get('action') == 'confirm_payment':
            if hasattr(order, 'payment'):
                from payments.views import mark_payment_paid
                mark_payment_paid(order.payment)
                django_messages.success(request, f'Payment confirmed for order #{order.id}. Invoice emailed to the customer.')
            else:
                django_messages.error(request, f'Order #{order.id} has no payment record.')
            return redirect('admin_orders')

        if request.POST.get('action') == 'confirm_order':
            order.status = 'confirmed'
            order.save(update_fields=['status'])
            if order.payment_status == 'paid' and hasattr(order, 'payment'):
                from payments.views import mark_payment_paid
                mark_payment_paid(order.payment)
                django_messages.success(request, f'Order #{order.id} confirmed and invoice issued.')
            else:
                django_messages.success(request, f'Order #{order.id} confirmed. Invoice will be issued after payment confirmation.')
            return redirect('admin_orders')

        if request.POST.get('action') == 'resend_invoice':
            if hasattr(order, 'invoice') and hasattr(order, 'payment'):
                from payments.views import send_invoice_email
                sent = send_invoice_email(order.payment, order.invoice)
                if sent:
                    django_messages.success(request, f'Invoice {order.invoice.number} sent to {order.user.email}.')
                else:
                    django_messages.error(request, f'Could not email invoice {order.invoice.number}. Check the SMTP settings.')
            else:
                django_messages.warning(request, f'Order #{order.id} does not have an issued invoice.')
            return redirect('admin_orders')

        order.status = request.POST['status']
        order.payment_status = request.POST['payment_status']
        order.save()
        if order.status == 'cancelled' and previous_status != 'cancelled':
            from payments.views import release_reserved_stock
            release_reserved_stock(order)
        if order.payment_status == 'paid' and hasattr(order, 'payment'):
            from payments.views import mark_payment_paid
            mark_payment_paid(order.payment)
        return redirect('admin_orders')
    return render(request, 'dashboard/orders.html', {'orders': Order.objects.select_related('user').prefetch_related('items__product').order_by('-created_at')})


@staff_member_required
def customers(request):
    query = request.GET.get('q', '').strip()
    customers = User.objects.filter(is_staff=False).order_by('-date_joined')
    if query:
        from django.db.models import Q
        customers = customers.filter(
            Q(first_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(phone_credential__phone__icontains=query)
        ).distinct()
    return render(request, 'dashboard/customers.html', {
        'customers': customers,
        'query': query,
    })


@staff_member_required
def messages(request):
    if request.method == 'POST':
        message = get_object_or_404(CustomerMessage, id=request.POST.get('message_id'))
        reply = request.POST.get('reply', '').strip()
        if not reply:
            django_messages.error(request, 'Write a reply before sending.')
            return redirect('admin_messages')

        message.reply = reply
        try:
            send_mail(
                f'Re: {message.subject}',
                f'Hello {message.name},\n\n{reply}\n\nAERIAL ELECTRONICS\nUnder the Makuza Building, KN 74 St, Kigali, Rwanda',
                settings.DEFAULT_FROM_EMAIL,
                [message.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception('Could not email a reply to a customer message.')
            message.replied = False
            message.save(update_fields=['reply', 'replied'])
            django_messages.error(request, f'The reply was saved, but the email to {message.email} could not be sent. Try again.')
            return redirect('admin_messages')

        message.replied = True
        message.save(update_fields=['reply', 'replied'])
        django_messages.success(request, f'Reply sent to {message.email}.')
        return redirect('admin_messages')
    return render(request, 'dashboard/messages.html', {'messages': CustomerMessage.objects.order_by('-created_at')})


@staff_member_required
def promotions(request):
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'delete':
            get_object_or_404(Promotion, id=request.POST.get('promotion_id')).delete()
        elif action == 'edit':
            promotion = get_object_or_404(Promotion, id=request.POST.get('promotion_id'))
            promotion.title = request.POST['title']
            promotion.description = request.POST['description']
            promotion.discount_percent = request.POST['discount_percent']
            promotion.starts_at = request.POST['starts_at']
            promotion.ends_at = request.POST['ends_at']
            promotion.active = request.POST.get('active') == 'on'
            promotion.save()
        else:
            Promotion.objects.create(title=request.POST['title'], description=request.POST['description'], discount_percent=request.POST['discount_percent'], starts_at=request.POST['starts_at'], ends_at=request.POST['ends_at'], active=request.POST.get('active') == 'on')
        return redirect('admin_promotions')
    return render(request, 'dashboard/promotions.html', {'promotions': Promotion.objects.all().order_by('-starts_at')})


@staff_member_required
def invoices(request):
    return render(request, 'dashboard/invoices.html', {'orders': Order.objects.filter(invoice__isnull=False).select_related('invoice', 'user')})


@staff_member_required
def invoice_detail(request, order_id):
    order = get_object_or_404(Order.objects.select_related('user', 'payment', 'invoice').prefetch_related('items__product'), id=order_id, invoice__isnull=False)
    return render(request, 'store/invoice.html', {
        'order': order,
        'invoice_available': order.payment_status == 'paid',
        'admin_view': True,
        'invoice_qr': generate_invoice_qr(request, order),
    })


@staff_member_required
def website(request):
    settings = SiteSettings.get_settings()
    if request.method == 'POST':
        for field in (
            'business_name', 'brand_slogan', 'logo_url', 'footer_text',
            'hero_badge', 'hero_title', 'hero_highlight', 'hero_description',
            'hero_image_url', 'hero_caption', 'about_title', 'about_text',
            'phone', 'email', 'address', 'building', 'ceo_name', 'map_query',
            'facebook_url', 'instagram_url', 'whatsapp_url',
        ):
            setattr(settings, field, request.POST.get(field, getattr(settings, field, '')))
        if 'hero_image' in request.FILES:
            settings.hero_image = request.FILES['hero_image']
        settings.save()
        django_messages.success(request, 'Website settings saved successfully.')
        return redirect('admin_website')
    return render(request, 'dashboard/website.html', {'site': settings})
