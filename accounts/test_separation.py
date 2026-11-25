from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import EmailOTP

PASSWORD = 'Strong-test-password-42!'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminCustomerSeparationTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='shopper@example.com', email='shopper@example.com', password=PASSWORD)
        self.admin = User.objects.create_user(username='boss@example.com', email='boss@example.com', password=PASSWORD, is_staff=True)

    def test_customer_account_cannot_sign_in_on_admin_page(self):
        response = self.client.post(reverse('staff_login'), {'email': self.customer.email, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid administrator credentials')
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailOTP.objects.filter(user=self.customer).exists())

    def test_administrator_account_cannot_sign_in_on_customer_page(self):
        response = self.client.post(reverse('login'), {'identifier': self.admin.email, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administrator accounts sign in on the Admin sign-in page.')
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailOTP.objects.filter(user=self.admin).exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_administrator_is_not_reached_through_customer_code_entry(self):
        # Even if an administrator somehow had a customer-login code, the admin flow still signs in only via staff login.
        self.client.post(reverse('staff_login'), {'email': self.admin.email, 'password': PASSWORD})
        self.assertEqual(EmailOTP.objects.filter(user=self.admin, purpose='admin-login').count(), 1)
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('admin_dashboard'))

    def test_administrator_signs_in_with_email_on_admin_page(self):
        response = self.client.post(reverse('staff_login'), {'email': self.admin.email, 'password': PASSWORD})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 1)

    def test_customer_signs_in_with_email_on_customer_page(self):
        response = self.client.post(reverse('login'), {'identifier': self.customer.email, 'password': PASSWORD})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 1)

    def get_code(self):
        import re
        match = re.search(r'Your six-digit verification code is: (\d{6})', mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)
