import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import PhoneCredential
from accounts.otp import generate_otp
from orders.models import EmailOTP


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationFlowTests(TestCase):
    def get_code(self, message=None):
        body = message or mail.outbox[-1].body
        match = re.search(r'Your six-digit verification code is: (\d{6})', body)
        self.assertIsNotNone(match, body)
        return match.group(1)

    def test_authentication_pages_render(self):
        for route in ('register', 'login', 'staff_login', 'forgot_password'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 200)

    def test_secure_otp_has_six_digits_and_preserves_leading_zeroes(self):
        with patch('accounts.otp.secrets.randbelow', return_value=7):
            self.assertEqual(generate_otp(), '000007')

    def test_registration_sends_otp_and_activates_account_only_after_verification(self):
        response = self.client.post(reverse('register'), {
            'name': 'Test Customer',
            'email': 'Customer@example.com',
            'phone': '0788000000',
            'password': 'Strong-test-password-42!',
            'password_confirm': 'Strong-test-password-42!',
        })
        self.assertRedirects(response, reverse('verify_otp'))
        user = User.objects.get(email='customer@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(user.first_name, 'Test Customer')
        self.assertEqual(mail.outbox[-1].to, ['customer@example.com'])
        self.assertTrue(check_password(self.get_code(), EmailOTP.objects.get(user=user).code))

        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('account'))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(PhoneCredential.objects.get(user=user).verified)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_registration_requires_password_confirmation_and_rejects_duplicate_email_case_insensitively(self):
        response = self.client.post(reverse('register'), {
            'name': 'Test Customer', 'email': 'customer@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'different-password',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='customer@example.com').exists())

        User.objects.create_user(username='customer@example.com', email='customer@example.com', password='Strong-test-password-42!')
        response = self.client.post(reverse('register'), {
            'name': 'Another Customer', 'email': 'CUSTOMER@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact='customer@example.com').count(), 1)

    def test_login_requires_email_otp_before_authenticating(self):
        user = User.objects.create_user(username='legacy@example.com', email='legacy@example.com', password='Strong-test-password-42!')
        response = self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('account'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_wrong_otp_is_counted_and_cannot_be_reused(self):
        user = User.objects.create_user(username='otp@example.com', email='otp@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        otp = EmailOTP.objects.get(user=user, purpose='login')
        response = self.client.post(reverse('verify_otp'), {'code': '123456'})
        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 1)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        otp.refresh_from_db()
        self.assertTrue(otp.used)
        self.client.logout()
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_five_wrong_codes_lock_the_otp(self):
        user = User.objects.create_user(username='locked@example.com', email='locked@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        otp = EmailOTP.objects.get(user=user, purpose='login')
        for _ in range(5):
            self.client.post(reverse('verify_otp'), {'code': '123456'})
        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 5)
        self.assertTrue(otp.used)
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_expired_otp_is_rejected(self):
        user = User.objects.create_user(username='expired@example.com', email='expired@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        otp = EmailOTP.objects.get(user=user, purpose='login')
        otp.created_at = timezone.now() - timedelta(minutes=6)
        otp.save(update_fields=['created_at'])
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        otp.refresh_from_db()
        self.assertTrue(otp.used)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_resend_is_throttled(self):
        user = User.objects.create_user(username='resend@example.com', email='resend@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        response = self.client.post(reverse('resend_otp'))
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_after_cooldown_replaces_the_previous_code(self):
        user = User.objects.create_user(username='resend@example.com', email='resend@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        old_otp = EmailOTP.objects.get(user=user, purpose='login')
        old_otp.created_at = timezone.now() - timedelta(seconds=61)
        old_otp.save(update_fields=['created_at'])
        session = self.client.session
        session['otp_last_sent'] = (timezone.now() - timedelta(seconds=61)).timestamp()
        session.save()

        self.client.post(reverse('resend_otp'))
        old_otp.refresh_from_db()
        self.assertTrue(old_otp.used)
        self.assertEqual(len(mail.outbox), 2)
        new_otp = EmailOTP.objects.filter(user=user, purpose='login', used=False).latest('created_at')
        self.assertTrue(check_password(self.get_code(mail.outbox[-1].body), new_otp.code))

    @patch('accounts.otp.send_mail', side_effect=OSError('mail unavailable'))
    def test_registration_rolls_back_if_email_cannot_be_sent(self, mocked_send_mail):
        with self.assertLogs('accounts.views', level='ERROR'):
            response = self.client.post(reverse('register'), {
                'name': 'Test Customer', 'email': 'offline@example.com',
                'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
            })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='offline@example.com').exists())
        self.assertContains(response, 'could not send the verification email')

    def test_forgot_password_is_generic_and_resets_password_after_otp(self):
        user = User.objects.create_user(username='reset@example.com', email='reset@example.com', password='Old-strong-password-42!')
        response = self.client.post(reverse('forgot_password'), {'email': user.email})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('If an active account uses that email', list(response.wsgi_request._messages)[0].message)

        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('reset_password'))
        response = self.client.post(reverse('reset_password'), {
            'password': 'New-strong-password-84!',
            'password_confirm': 'New-strong-password-84!',
        })
        self.assertRedirects(response, reverse('login'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('New-strong-password-84!'))
        self.assertFalse(user.check_password('Old-strong-password-42!'))

    def test_forgot_password_does_not_disclose_unknown_email(self):
        response = self.client.post(reverse('forgot_password'), {'email': 'unknown@example.com'})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(self.client.session.get('otp_user_id'))

    def test_staff_login_requires_otp(self):
        user = User.objects.create_user(username='admin@example.com', email='admin@example.com', password='Strong-test-password-42!', is_staff=True)
        response = self.client.post(reverse('staff_login'), {'email': user.email, 'password': 'Strong-test-password-42!'})
        self.assertRedirects(response, reverse('verify_otp'))
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def age_pending_codes(self):
        """Pretend the last code was sent over a minute ago so the resend cooldown has passed."""
        past = timezone.now() - timedelta(seconds=61)
        EmailOTP.objects.update(created_at=past)
        session = self.client.session
        session['otp_last_sent'] = past.timestamp()
        session.save()

    def test_unverified_registration_gets_a_new_code_when_registering_again(self):
        payload = {
            'name': 'Pending Customer', 'email': 'pending@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
        }
        self.client.post(reverse('register'), payload)
        self.age_pending_codes()

        response = self.client.post(reverse('register'), payload)
        self.assertRedirects(response, reverse('verify_otp'))
        user = User.objects.get(email='pending@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(EmailOTP.objects.filter(user=user, purpose='registration', used=False).count(), 1)

        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('account'))
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_unverified_registration_with_wrong_password_is_still_rejected(self):
        payload = {
            'name': 'Pending Customer', 'email': 'pending2@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
        }
        self.client.post(reverse('register'), payload)
        self.age_pending_codes()
        other = {**payload, 'password': 'Other-strong-password-99!', 'password_confirm': 'Other-strong-password-99!'}
        response = self.client.post(reverse('register'), other)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(len(mail.outbox), 1)

    def test_unverified_account_receives_new_code_when_signing_in(self):
        payload = {
            'name': 'Late Customer', 'email': 'late@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
        }
        self.client.post(reverse('register'), payload)
        self.age_pending_codes()
        response = self.client.post(reverse('login'), {'identifier': 'late@example.com', 'password': 'Strong-test-password-42!'})
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 2)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_deactivated_account_cannot_be_reactivated_through_registration(self):
        user = User.objects.create_user(username='banned@example.com', email='banned@example.com', password='Strong-test-password-42!', is_active=False)
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        EmailOTP.objects.create(user=user, purpose='registration', code=make_password('123456'))
        response = self.client.post(reverse('register'), {
            'name': 'Banned', 'email': 'banned@example.com',
            'password': 'Strong-test-password-42!', 'password_confirm': 'Strong-test-password-42!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(len(mail.outbox), 0)

    def test_failures_across_reissued_codes_lock_verification(self):
        user = User.objects.create_user(username='brute@example.com', email='brute@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login'), {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        for round_number in range(3):
            if round_number:
                self.age_pending_codes()
                self.client.post(reverse('resend_otp'))
            for _ in range(5):
                self.client.post(reverse('verify_otp'), {'code': '999999'})
        self.age_pending_codes()
        self.client.post(reverse('resend_otp'))
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_returns_customer_to_requested_page_after_code(self):
        user = User.objects.create_user(username='nextok@example.com', email='nextok@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login') + '?next=/cart/', {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, '/cart/')
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_external_next_address_is_ignored_after_code(self):
        user = User.objects.create_user(username='nextbad@example.com', email='nextbad@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('login') + '?next=https://evil.example.com/', {'identifier': user.email, 'password': 'Strong-test-password-42!'})
        response = self.client.post(reverse('verify_otp'), {'code': self.get_code()})
        self.assertRedirects(response, reverse('account'))

    def test_password_reset_resend_during_cooldown_does_not_send_mail(self):
        User.objects.create_user(username='cool@example.com', email='cool@example.com', password='Strong-test-password-42!')
        self.client.post(reverse('forgot_password'), {'email': 'cool@example.com'})
        response = self.client.post(reverse('resend_otp'))
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(len(mail.outbox), 1)
