from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order
from payments.models import Payment
from payments.views import mark_payment_paid


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='no-reply@aerialelectronics.rw',
)
class AdminPaymentInvoiceTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='customer', email='customer@example.com', password='test-pass')
        self.staff = User.objects.create_user(username='staff', password='test-pass', is_staff=True)
        self.order = Order.objects.create(
            user=self.customer,
            phone='+250788000000',
            address='Kigali',
            total=25000,
        )
        self.payment = Payment.objects.create(
            order=self.order,
            provider='MTN Mobile Money',
            phone='+250788000000',
            reference='AER-TEST-001',
            amount=25000,
        )

    def test_confirming_payment_creates_invoice_and_confirms_order(self):
        invoice = mark_payment_paid(self.payment)

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'paid')
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(self.order.status, 'confirmed')
        self.assertEqual(invoice.number, f'INV-{self.order.id:06d}')

    def test_admin_orders_and_invoices_pages_are_available(self):
        mark_payment_paid(self.payment)
        self.client.force_login(self.staff)

        orders_response = self.client.get(reverse('admin_orders'))
        invoices_response = self.client.get(reverse('admin_invoices'))
        invoice_response = self.client.get(reverse('admin_invoice_detail', args=[self.order.id]))

        self.assertEqual(orders_response.status_code, 200)
        self.assertContains(orders_response, 'Invoice ready')
        self.assertEqual(invoices_response.status_code, 200)
        self.assertContains(invoices_response, f'INV-{self.order.id:06d}')
        self.assertEqual(invoice_response.status_code, 200)

    def test_admin_confirm_action_makes_invoice_available_to_customer(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('admin_orders'), {
            'action': 'confirm_payment',
            'order_id': self.order.id,
        })

        self.assertRedirects(response, reverse('admin_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertTrue(hasattr(self.order, 'invoice'))

        self.client.force_login(self.customer)
        invoice_response = self.client.get(reverse('customer_invoice', args=[self.order.id]))
        self.assertEqual(invoice_response.status_code, 200)
        self.assertContains(invoice_response, f'INV-{self.order.id:06d}')

    def test_confirm_payment_emails_invoice_attachment_to_customer(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('admin_orders'), {
            'action': 'confirm_payment',
            'order_id': self.order.id,
        })

        self.assertRedirects(response, reverse('admin_orders'))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.customer.email])
        self.assertIn('Invoice INV-', email.subject)
        self.assertEqual(len(email.attachments), 1)
        self.assertTrue(email.attachments[0][0].endswith('.html'))

    def test_customer_can_download_confirmed_invoice(self):
        mark_payment_paid(self.payment)
        self.order.customer_name = 'Test Customer'
        self.order.payer_name = 'Payment Account Holder'
        self.order.save(update_fields=['customer_name', 'payer_name'])
        self.client.force_login(self.customer)

        response = self.client.get(reverse('customer_invoice_download', args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertContains(response, 'Test Customer')
        self.assertContains(response, 'Payment Account Holder')
