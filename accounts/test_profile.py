import io
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import UserProfile

PASSWORD = 'Strong-test-password-42!'


def png_bytes(size=(12, 12)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'red').save(buffer, 'PNG')
    return buffer.getvalue()


class ProfileTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_root = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls.media_root)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.customer = User.objects.create_user(username='cust@example.com', email='cust@example.com', password=PASSWORD, first_name='Amina')
        self.staff = User.objects.create_user(username='boss@example.com', email='boss@example.com', password=PASSWORD, is_staff=True)

    def upload(self, name='me.png', content=None, content_type='image/png'):
        return SimpleUploadedFile(name, content if content is not None else png_bytes(), content_type=content_type)

    def test_profile_pages_require_the_right_kind_of_account(self):
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('admin_profile')).status_code, 302)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('admin_profile')).status_code, 200)

    def test_customer_can_change_name_and_add_photo(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse('profile'), {'full_name': '  Amina   Uwase  ', 'photo': self.upload()})
        self.assertRedirects(response, reverse('profile'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, 'Amina Uwase')
        profile = UserProfile.objects.get(user=self.customer)
        self.assertTrue(profile.photo.name.startswith(f'avatars/{self.customer.pk}/'))
        self.assertTrue(profile.photo.name.endswith('.png'))

    def test_new_photo_replaces_the_old_file(self):
        self.client.force_login(self.customer)
        self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload('a.png')})
        first = UserProfile.objects.get(user=self.customer).photo.path
        self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload('b.png')})
        second = UserProfile.objects.get(user=self.customer).photo.path
        self.assertNotEqual(first, second)
        import os
        self.assertFalse(os.path.exists(first))
        self.assertTrue(os.path.exists(second))

    def test_remove_photo_deletes_the_file(self):
        self.client.force_login(self.customer)
        self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload()})
        path = UserProfile.objects.get(user=self.customer).photo.path
        self.client.post(reverse('profile'), {'action': 'remove_photo'})
        self.assertFalse(UserProfile.objects.get(user=self.customer).photo)
        import os
        self.assertFalse(os.path.exists(path))

    def test_text_file_renamed_as_image_is_rejected(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload('evil.png', b'not an image', 'image/png')})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserProfile.objects.get(user=self.customer).photo)

    def test_unsupported_extension_is_rejected(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload('x.gif', png_bytes(), 'image/gif')})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload a JPG, PNG or WebP image.')

    def test_photo_over_size_limit_is_rejected(self):
        self.client.force_login(self.customer)
        with patch('accounts.forms.MAX_PHOTO_BYTES', 10):
            response = self.client.post(reverse('profile'), {'full_name': 'Amina', 'photo': self.upload()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2 MB or smaller')

    def test_administrator_profile_saves_photo_on_admin_layout(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('admin_profile'), {'full_name': 'Joseph', 'photo': self.upload()})
        self.assertRedirects(response, reverse('admin_profile'))
        self.assertTrue(UserProfile.objects.get(user=self.staff).photo)
        page = self.client.get(reverse('admin_profile'))
        self.assertContains(page, 'AERIAL ADMIN')
