import json
import logging
import os

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Payment
from orders.models import Invoice
from store.models import Product


logger = logging.getLogger(__name__)


def send_invoice_email(payment, invoice):
    order = payment.order
    if not order.user.email:
        return False

    items = ''.join(
        f'<tr><td>{item.product.name}</td><td>{item.quantity}</td><td>RWF {item.price:,.0f}</td><td>RWF {item.total:,.0f}</td></tr>'
        for item in order.items.select_related('product').all()
    )
    subject = f'AERIAL ELECTRONICS Invoice {invoice.number}'
    text = (
        f'Payment confirmed. Invoice {invoice.number}.\n'
        f'Order: #{order.id}\n'
        f'Total paid: RWF {order.total:,.0f}\n'
        f'Payment: {payment.provider}\n'
        f'Reference: {payment.reference}\n'
        'Your invoice is available in your AERIAL ELECTRONICS account.'
    )
    html = f'''<div style="font-family:Arial,sans-serif;max-width:760px;margin:auto">
        <h1 style="color:#0d6efd">AERIAL ELECTRONICS</h1>
        <h2>Invoice {invoice.number}</h2>
        <p><strong>Order:</strong> #{order.id}<br><strong>Customer:</strong> {order.user.get_full_name() or order.user.username}<br><strong>Email:</strong> {order.user.email}</p>
        <p>Payment confirmed by {payment.provider}.<br><strong>Payment reference:</strong> {payment.reference}</p>
        <table border="1" cellpadding="8" cellspacing="0" width="100%" style="border-collapse:collapse">
          <thead><tr><th align="left">Item</th><th>Quantity</th><th>Unit price</th><th>Total</th></tr></thead>
          <tbody>{items}</tbody>
        </table>
        <h3 style="text-align:right">Total paid: RWF {order.total:,.0f}</h3>
        <p>View or print this invoice from My Account.</p>
    </div>'''
    try:
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [order.user.email])
        message.attach_alternative(html, 'text/html')
        message.attach(f'{invoice.number}.html', html, 'text/html')
        sent = message.send(fail_silently=False)
        if sent:
            logger.info('Invoice %s emailed to %s', invoice.number, order.user.email)
        return bool(sent)
    except Exception as exc:
        logger.exception('Could not email invoice %s to %s: %s', invoice.number, order.user.email, exc)
        return False


def mark_payment_paid(payment):
    became_paid = payment.status != 'paid'
    payment.status = 'paid'
    payment.save(update_fields=['status'])
    payment.order.payment_status = 'paid'
    if payment.order.status != 'cancelled':
        payment.order.status = 'confirmed'
    payment.order.save(update_fields=['payment_status', 'status'])
    invoice, created = Invoice.objects.get_or_create(order=payment.order, defaults={'number': f'INV-{payment.order.id:06d}'})
    if became_paid or created:
        send_invoice_email(payment, invoice)
    return invoice


def release_reserved_stock(order):
    """Return cart-reserved stock after failed payment or cancellation."""
    with transaction.atomic():
        order = order.__class__.objects.select_for_update().get(id=order.id)
        if order.stock_released:
            return
        for item in order.items.select_related('product').all():
            product = Product.objects.select_for_update().get(id=item.product_id)
            product.stock += item.quantity
            product.save(update_fields=['stock'])
        order.stock_released = True
        order.save(update_fields=['stock_released'])


@csrf_exempt
@require_POST
def mtn_callback(request):
    secret = os.getenv('MTN_CALLBACK_SECRET', '')
    supplied = request.headers.get('X-MTN-Callback-Secret', '')
    if not secret or supplied != secret:
        return HttpResponseForbidden('Invalid callback secret')
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    reference = payload.get('reference') or payload.get('externalId')
    provider_status = str(payload.get('status', '')).upper()
    payment = Payment.objects.select_related('order').filter(reference=reference).first()
    if not payment:
        return JsonResponse({'error': 'Payment reference not found'}, status=404)
    if provider_status in {'SUCCESSFUL', 'PAID', 'SUCCESS'}:
        invoice = mark_payment_paid(payment)
        return JsonResponse({'received': True, 'status': 'paid', 'invoice': invoice.number})
    if provider_status in {'FAILED', 'REJECTED', 'CANCELLED'}:
        previously_failed = payment.status == 'failed'
        payment.status = 'failed'
        payment.save(update_fields=['status'])
        payment.order.payment_status = 'failed'
        payment.order.save(update_fields=['payment_status'])
        if not previously_failed:
            release_reserved_stock(payment.order)
    return JsonResponse({'received': True, 'status': payment.status})


@staff_member_required
@require_POST
def confirm_payment(request, order_id):
    payment = get_object_or_404(Payment, order_id=order_id)
    invoice = mark_payment_paid(payment)
    return JsonResponse({'status': 'paid', 'invoice': invoice.number})
