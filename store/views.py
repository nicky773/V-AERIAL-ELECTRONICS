from types import SimpleNamespace
import json
import os
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
import requests

from .models import Cart, Category, Product, Promotion
from messaging.models import CustomerMessage
from orders.models import Order, OrderItem
from payments.models import Payment


def home(request):
    return render(request, 'store/home.html', {
        'categories': Category.objects.all(),
        'products': Product.objects.filter(stock__gt=0).order_by('-featured', '-created_at')[:8],
        'promotions': Promotion.objects.filter(active=True),
    })


def product_list(request):
    products = Product.objects.filter(stock__gt=0)
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if category:
        products = products.filter(category__slug=category)
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    return render(request, 'store/products.html', {
        'products': products,
        'categories': Category.objects.all(),
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    related = Product.objects.filter(category=product.category).exclude(id=product.id)[:4]
    return render(request, 'store/product_detail.html', {'product': product, 'related': related})


def add_to_cart(request, product_id):
    with transaction.atomic():
        product = Product.objects.select_for_update().get(id=product_id)
        if product.stock < 1:
            messages.error(request, 'This product is out of stock.')
            return redirect('product_detail', slug=product.slug)

        if request.user.is_authenticated:
            item, created = Cart.objects.get_or_create(user=request.user, product=product)
            if not created:
                item.quantity += 1
                item.save(update_fields=['quantity'])
        else:
            cart = request.session.get('cart', {})
            key = str(product_id)
            cart[key] = int(cart.get(key, 0)) + 1
            request.session['cart'] = cart
            request.session.modified = True

        product.stock -= 1
        product.save(update_fields=['stock'])

    messages.success(request, f'{product.name} added to cart. {product.stock} left in stock.')
    return redirect('cart')


def cart(request):
    if request.user.is_authenticated:
        items = list(Cart.objects.filter(user=request.user).select_related('product'))
    else:
        items = []
        for product_id, quantity in request.session.get('cart', {}).items():
            product = Product.objects.filter(id=int(product_id)).first()
            if product:
                quantity = int(quantity)
                items.append(SimpleNamespace(id=int(product_id), product=product, quantity=quantity, total=product.price * quantity))
    total = sum(item.total for item in items)
    return render(request, 'store/cart.html', {'items': items, 'total': total})


def update_cart(request, item_id):
    action = request.GET.get('action')
    if request.user.is_authenticated:
        with transaction.atomic():
            item = Cart.objects.select_for_update().select_related('product').filter(id=item_id, user=request.user).first()
            if not item:
                return redirect('cart')

            if action == 'increase':
                product = Product.objects.select_for_update().get(id=item.product_id)
                if product.stock < 1:
                    messages.error(request, 'No more units are available.')
                    return redirect('cart')
                item.quantity += 1
                item.save(update_fields=['quantity'])
                product.stock -= 1
                product.save(update_fields=['stock'])

            if action == 'decrease':
                item.quantity -= 1
                if item.quantity < 1:
                    item.delete()
                else:
                    item.save(update_fields=['quantity'])
                product = Product.objects.select_for_update().get(id=item.product_id)
                product.stock += 1
                product.save(update_fields=['stock'])
    else:
        cart = request.session.get('cart', {})
        key = str(item_id)
        quantity = int(cart.get(key, 0))
        if quantity:
            with transaction.atomic():
                product = Product.objects.select_for_update().get(id=int(item_id))
                if action == 'increase':
                    if product.stock < 1:
                        messages.error(request, 'No more units are available.')
                        return redirect('cart')
                    quantity += 1
                    product.stock -= 1
                    product.save(update_fields=['stock'])
                elif action == 'decrease':
                    quantity -= 1
                    product.stock += 1
                    product.save(update_fields=['stock'])

        if quantity < 1:
            cart.pop(key, None)
        else:
            cart[key] = quantity
        request.session['cart'] = cart
        request.session.modified = True
    return redirect('cart')


def remove_from_cart(request, item_id):
    if request.user.is_authenticated:
        with transaction.atomic():
            item = Cart.objects.select_for_update().select_related('product').filter(id=item_id, user=request.user).first()
            if item:
                product = Product.objects.select_for_update().get(id=item.product_id)
                product.stock += item.quantity
                product.save(update_fields=['stock'])
                item.delete()
    else:
        cart = request.session.get('cart', {})
        key = str(item_id)
        quantity = int(cart.get(key, 0))
        if quantity:
            with transaction.atomic():
                product = Product.objects.select_for_update().get(id=int(item_id))
                product.stock += quantity
                product.save(update_fields=['stock'])
        cart.pop(key, None)
        request.session['cart'] = cart
        request.session.modified = True
    return redirect('cart')


@login_required
def checkout(request):
    session_cart = request.session.get('cart', {})
    for product_id, quantity in session_cart.items():
        product = Product.objects.filter(id=int(product_id), stock__gt=0).first()
        if product:
            item, created = Cart.objects.get_or_create(user=request.user, product=product)
            item.quantity = item.quantity + int(quantity) if not created else int(quantity)
            item.save()
    request.session['cart'] = {}

    items = Cart.objects.filter(user=request.user).select_related('product')
    if not items:
        return redirect('cart')
    total = sum(item.total for item in items)

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'mtn')
        phone = request.POST.get('phone', '').strip()
        bank_reference = request.POST.get('bank_reference', '').strip()
        customer_name = request.POST.get('customer_name', '').strip() or request.user.get_full_name() or request.user.username
        payer_name = request.POST.get('payer_name', '').strip()

        if payment_method == 'equity':
            provider = 'Equity Bank Transfer'
            phone = bank_reference
        elif payment_method == 'bk':
            provider = 'Bank of Kigali Transfer'
            phone = bank_reference
        else:
            provider = 'MTN Mobile Money'

        order = Order.objects.create(
            user=request.user,
            customer_name=customer_name,
            payer_name=payer_name,
            phone=phone,
            address=request.POST.get('address', ''),
            total=total,
        )
        for item in items:
            OrderItem.objects.create(order=order, product=item.product, quantity=item.quantity, price=item.product.price)
        reference = 'AER-' + uuid.uuid4().hex[:10].upper()
        Payment.objects.create(order=order, provider=provider, phone=phone, reference=reference, amount=total)
        items.delete()
        if payment_method in {'equity', 'bk'}:
            messages.success(request, 'Order placed. Complete the bank transfer and await administrator confirmation.')
        else:
            messages.success(request, 'Order placed. Complete the MTN Mobile Money payment prompt.')
        return redirect('order_detail', order_id=order.id)

    return render(request, 'store/checkout.html', {
        'items': items,
        'total': total,
        'equity_account': os.getenv('EQUITY_BANK_ACCOUNT', 'Configure Equity account in .env'),
        'bk_account': os.getenv('BK_ACCOUNT', 'Configure BK account in .env'),
    })


def promotions(request):
    return render(request, 'store/promotions.html', {'promotions': Promotion.objects.filter(active=True)})


def contact(request):
    if request.method == 'POST':
        CustomerMessage.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=request.POST.get('name', ''),
            email=request.POST.get('email', ''),
            subject=request.POST.get('subject', ''),
            message=request.POST.get('message', ''),
        )
        messages.success(request, 'Your message has been sent.')
        return redirect('contact')
    return render(request, 'store/contact.html')


def ai_assistant(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        data = request.POST

    message = str(data.get('message', '')).strip()
    language = str(data.get('language', 'auto')).strip().lower()
    if not message:
        return JsonResponse({'error': 'Please enter a question.'}, status=400)

    products = list(Product.objects.filter(stock__gt=0).select_related('category')[:30])
    catalog = '\n'.join(
        f"- {p.name} | {p.category.name} | RWF {p.price:,.0f} | {p.stock} in stock | {p.description}"
        for p in products
    )

    language_names = {
        'en': 'English', 'rw': 'Kinyarwanda', 'fr': 'French', 'sw': 'Kiswahili'
    }
    requested_language = language_names.get(language, 'the same language used in the customer question')

    api_key = os.getenv('AI_API_KEY', '')
    api_url = os.getenv('AI_API_URL', '')
    model = os.getenv('AI_MODEL', 'gpt-4o-mini')
    if api_key and api_url:
        try:
            response = requests.post(
                api_url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': model,
                    'messages': [
                        {
                            'role': 'system',
                            'content': (
                                'You are AERIAL ELECTRONICS AI assistant in Kigali, Rwanda. '
                                'Answer customer questions from the supplied stored product catalog, original '
                                'product names, descriptions, categories, prices, stock, and the product image '
                                'displayed on that product page. Do not answer from theme, layout, passkey, '
                                'administrator settings, or anything that is not in the supplied catalog. '
                                'For shopping help, explain browsing, searching, adding to cart, checkout, '
                                'MTN Mobile Money payment, order tracking, and invoices. '
                                f'Reply in {requested_language}. Keep answers brief and helpful.'
                            ),
                        },
                        {'role': 'user', 'content': f'Live catalog:\n{catalog}\n\nCustomer question:\n{message}'},
                    ],
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            answer = payload['choices'][0]['message']['content']
            return JsonResponse({'answer': answer, 'ai': True, 'language': language})
        except Exception:
            pass

    lower = message.lower()
    rw = language == 'rw' or any(word in lower for word in ('muraho', 'mwaramutse', 'gute', 'amakuru'))
    fr = language == 'fr' or any(word in lower for word in ('bonjour', 'comment', 'acheter', 'produit'))
    sw = language == 'sw' or any(word in lower for word in ('habari', 'jinsi', 'nunua', 'bidhaa'))

    stop_words = {'how', 'do', 'i', 'pay', 'the', 'can', 'you', 'help', 'show', 'me', 'a', 'is', 'for', 'with', 'to', 'and'}
    search_words = [word for word in lower.replace('?', '').replace(',', '').split() if word not in stop_words]
    matches = [p for p in products if lower in p.name.lower() or lower in p.category.name.lower() or any(word in p.name.lower() for word in search_words)]

    if 'payment' in lower or 'pay' in lower or 'mtn' in lower or 'ishyura' in lower or 'payer' in lower or 'lipa' in lower:
        if rw:
            answer = 'Wishyura ukoresha MTN Mobile Money. Iyo provider yemeye ubwishyu, inyemezabuguzi igaragara ku buryo bwawe.'
        elif fr:
            answer = 'Le paiement se fait uniquement avec MTN Mobile Money. La facture apparaît après confirmation du paiement.'
        elif sw:
            answer = 'Lipa kwa MTN Mobile Money pekee. Ankara inaonekana baada ya malipo kuthibitishwa.'
        else:
            answer = 'AERIAL ELECTRONICS accepts MTN Mobile Money only. Your invoice becomes available after provider-confirmed payment.'
    elif 'cart' in lower or 'cart' in lower or 'igikapu' in lower or 'panier' in lower:
        if rw:
            answer = 'Kugirango ukoreshe Cart: hitamo igicuruzwa, kanda Add to cart, omeza umubare cyangwa usibe, hanyuma kanda Checkout.'
        elif fr:
            answer = 'Pour utiliser le panier: ajoutez un produit, modifiez les quantités, puis cliquez sur Checkout.'
        elif sw:
            answer = 'Kutumia cart: ongeza bidhaa, badilisha idadi, kisha bonyeza Checkout.'
        else:
            answer = 'To use the cart: select a product, choose Add to cart, adjust quantities or remove items, then choose Checkout.'
    elif matches:
        product_lines = '\n'.join(f"• {p.name} — RWF {p.price:,.0f} ({p.stock} in stock)" for p in matches[:5])
        if rw:
            answer = 'Nabonye ibicuruzwa bikurikira:\n' + product_lines
        elif fr:
            answer = 'Voici les produits disponibles:\n' + product_lines
        elif sw:
            answer = 'Hizi ndizo bidhaa zinazopatikana:\n' + product_lines
        else:
            answer = 'I found these available products:\n' + product_lines
    else:
        if rw:
            answer = 'Murakaza neza. Nshobora kugufasha gushakisha ibicuruzwa, kugura, kwishyura na MTN Mobile Money, cyangwa kureba inyemezabuguzi.'
        elif fr:
            answer = 'Bienvenue. Je peux vous aider à rechercher des produits, utiliser le panier, payer avec MTN Mobile Money ou voir vos factures.'
        elif sw:
            answer = 'Karibu. Ninaweza kukusaidia kutafuta bidhaa, kutumia cart, kulipa kwa MTN Mobile Money, au kuona Ankara.'
        else:
            answer = 'Welcome. I can help you browse products, use the cart, pay with MTN Mobile Money, track orders, or print invoices.'

    picture_request = any(word in lower for word in ('picture', 'photo', 'image', 'ifoto', 'ishusho', 'photo', 'image'))
    if picture_request:
        picture_matches = [p for p in products if p.name.lower() in lower or p.category.name.lower() in lower]
        if picture_matches:
            p = picture_matches[0]
            if rw:
                answer = f"Ifoto y'igicuruzwa " + p.name + " igaragara ku rupapuro rw'igicuruzwa. " + p.description
            elif fr:
                answer = f"La photo de {p.name} apparaît sur la page du produit. " + p.description
            elif sw:
                answer = f"Picha ya {p.name} inaonyeshwa kwenye ukurasa wa bidhaa. " + p.description
            else:
                answer = f"The picture of {p.name} is shown on its product page. " + p.description
        else:
            if rw:
                answer = 'Nyamuneka andika izina ry’igicuruzwa cyangwa category ushaka kureba ifoto yacyo.'
            elif fr:
                answer = 'Veuillez saisir le nom du produit ou de la catégorie dont vous souhaitez voir la photo.'
            elif sw:
                answer = 'Tafadhali andika jina la bidhaa au kategori unayotaka kuona picha yake.'
            else:
                answer = 'Please tell me the product name or category whose picture you want to see.'
        return JsonResponse({'answer': answer, 'ai': False, 'language': language})

    return JsonResponse({'answer': answer, 'ai': False, 'language': language})
