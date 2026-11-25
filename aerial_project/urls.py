"""
URL configuration for aerial_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from store import views as store
from accounts import views as accounts
from orders import views as orders
from dashboard import views as dashboard
from payments import views as payments

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', store.home, name='home'),
    path('products/', store.product_list, name='products'),
    path('products/<slug:slug>/', store.product_detail, name='product_detail'),
    path('cart/', store.cart, name='cart'),
    path('cart/add/<int:product_id>/', store.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:item_id>/', store.update_cart, name='update_cart'),
    path('cart/remove/<int:item_id>/', store.remove_from_cart, name='remove_from_cart'),
    path('checkout/', store.checkout, name='checkout'),
    path('promotions/', store.promotions, name='promotions'),
    path('contact/', store.contact, name='contact'),
    path('ai-assistant/', store.ai_assistant, name='ai_assistant'),
    path('register/', accounts.register, name='register'),
    path('login/', accounts.login_view, name='login'),
    path('staff-login/', accounts.staff_login, name='staff_login'),
    path('verify-otp/', accounts.verify_otp, name='verify_otp'),
    path('resend-otp/', accounts.resend_otp, name='resend_otp'),
    path('forgot-password/', accounts.forgot_password, name='forgot_password'),
    path('reset-password/', accounts.reset_password, name='reset_password'),
    path('admin/passkey/register/', accounts.passkey_options, name='passkey_register'),
    path('admin/passkey/register/begin/', accounts.passkey_register_begin, name='passkey_register_begin'),
    path('admin/passkey/register/complete/', accounts.passkey_register_complete, name='passkey_register_complete'),
    path('admin/passkey/verify/', accounts.passkey_options, name='passkey_verify'),
    path('admin/passkey/verify/begin/', accounts.passkey_verify_begin, name='passkey_verify_begin'),
    path('admin/passkey/verify/complete/', accounts.passkey_verify_complete, name='passkey_verify_complete'),
    path('logout/', accounts.logout_view, name='logout'),
    path('account/', accounts.account, name='account'),
    path('order/<int:order_id>/', orders.order_detail, name='order_detail'),
    path('order/<int:order_id>/invoice/', orders.customer_invoice, name='customer_invoice'),
    path('order/<int:order_id>/invoice/download/', orders.customer_invoice_download, name='customer_invoice_download'),
    path('payments/mtn/callback/', payments.mtn_callback, name='mtn_callback'),
    path('payments/confirm/<int:order_id>/', payments.confirm_payment, name='confirm_payment'),
    path('admin-panel/', dashboard.dashboard, name='admin_dashboard'),
    path('admin-panel/categories/', dashboard.categories, name='admin_categories'),
    path('admin-panel/inventory/', dashboard.inventory, name='admin_inventory'),
    path('admin-panel/orders/', dashboard.orders, name='admin_orders'),
    path('admin-panel/customers/', dashboard.customers, name='admin_customers'),
    path('admin-panel/messages/', dashboard.messages, name='admin_messages'),
    path('admin-panel/promotions/', dashboard.promotions, name='admin_promotions'),
    path('admin-panel/invoices/', dashboard.invoices, name='admin_invoices'),
    path('admin-panel/invoices/<int:order_id>/', dashboard.invoice_detail, name='admin_invoice_detail'),
    path('admin-panel/website/', dashboard.website, name='admin_website'),
    path('staff/passkey/login/begin/', accounts.passkey_login_begin, name='passkey_login_begin'),
    path('staff/passkey/login/complete/', accounts.passkey_login_complete, name='passkey_login_complete'),
    path('invoice/verify/<str:invoice_number>/', orders.verify_invoice, name='verify_invoice'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
