from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

import base64
import io

import qrcode

from .models import Invoice, Order


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'store/order_detail.html', {'order': order})


@login_required
def customer_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    invoice_available = order.payment_status == 'paid' and hasattr(order, 'invoice')
    context = {
        'order': order,
        'invoice_available': invoice_available,
    }
    if invoice_available:
        context['invoice_qr'] = generate_invoice_qr(request, order)
    return render(request, 'store/invoice.html', context)


@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.payment_status != 'paid' or not hasattr(order, 'invoice'):
        return HttpResponse("Invoice not available.", status=404)

    # Assuming the invoice is a PDF file stored in the invoice field of the order
    response = HttpResponse(order.invoice, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{order_id}.pdf"'
    return response


@login_required
def customer_invoice_download(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('user', 'payment', 'invoice').prefetch_related('items__product'),
        id=order_id,
        user=request.user,
    )
    if order.payment_status != 'paid' or not hasattr(order, 'invoice'):
        return HttpResponse('Invoice not available until payment is confirmed.', status=403)

    response = render(request, 'store/invoice.html', {
        'order': order,
        'invoice_available': True,
        'download_view': True,
        'invoice_qr': generate_invoice_qr(request, order),
    })
    response['Content-Disposition'] = f'attachment; filename="{order.invoice.number}.html"'
    return response


def invoice_qr_payload(request, order):
    return request.build_absolute_uri(f'/invoice/verify/{order.invoice.number}/')


def generate_invoice_qr(request, order):
    qr = qrcode.QRCode(version=4, box_size=8, border=2)
    qr.add_data(invoice_qr_payload(request, order))
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def verify_invoice(request, invoice_number):
    invoice = get_object_or_404(Invoice.objects.select_related('order__user', 'order__payment').prefetch_related('order__items__product'), number=invoice_number)
    order = invoice.order
    if order.payment_status != 'paid':
        return render(request, 'store/invoice_verification.html', {'verified': False, 'invoice': invoice})
    return render(request, 'store/invoice_verification.html', {
        'verified': True,
        'invoice': invoice,
        'order': order,
    })
