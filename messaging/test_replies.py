from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from messaging.models import CustomerMessage

PASSWORD = 'Strong-test-password-42!'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminReplyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='boss@example.com', email='boss@example.com', password=PASSWORD, is_staff=True)
        self.customer = User.objects.create_user(username='cust@example.com', email='cust@example.com', password=PASSWORD)
        self.message = CustomerMessage.objects.create(
            name='Amina', email='amina@example.com', subject='Delivery question', message='When will my order arrive?',
        )

    def test_reply_is_emailed_to_customer_and_marked_sent(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_messages'), {'message_id': self.message.id, 'reply': 'Tomorrow morning.'})
        self.assertRedirects(response, reverse('admin_messages'))
        self.message.refresh_from_db()
        self.assertTrue(self.message.replied)
        self.assertEqual(self.message.reply, 'Tomorrow morning.')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['amina@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'Re: Delivery question')
        self.assertIn('Tomorrow morning.', mail.outbox[0].body)

    def test_empty_reply_is_rejected_and_nothing_is_sent(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_messages'), {'message_id': self.message.id, 'reply': '   '})
        self.message.refresh_from_db()
        self.assertFalse(self.message.replied)
        self.assertEqual(self.message.reply, '')
        self.assertEqual(len(mail.outbox), 0)

    @patch('dashboard.views.send_mail', side_effect=OSError('smtp down'))
    def test_failed_email_keeps_reply_but_is_not_marked_sent(self, mocked_send):
        self.client.force_login(self.admin)
        with self.assertLogs('dashboard.views', level='ERROR'):
            response = self.client.post(reverse('admin_messages'), {'message_id': self.message.id, 'reply': 'Tomorrow.'})
        self.assertRedirects(response, reverse('admin_messages'))
        self.message.refresh_from_db()
        self.assertFalse(self.message.replied)
        self.assertEqual(self.message.reply, 'Tomorrow.')

    def test_customer_cannot_send_replies(self):
        self.client.force_login(self.customer)
        self.client.post(reverse('admin_messages'), {'message_id': self.message.id, 'reply': 'Hacked'})
        self.message.refresh_from_db()
        self.assertFalse(self.message.replied)
        self.assertEqual(self.message.reply, '')
        self.assertEqual(len(mail.outbox), 0)
