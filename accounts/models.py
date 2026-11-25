import uuid

from django.contrib.auth.models import User
from django.db import models


def avatar_upload_to(instance, filename):
    """Store each photo under the user's folder with a random name, so filenames cannot collide or be guessed."""
    extension = filename.rsplit('.', 1)[-1].lower()
    return f'avatars/{instance.user_id}/{uuid.uuid4().hex}.{extension}'


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    photo = models.ImageField(upload_to=avatar_upload_to, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Profile of {self.user.username}'


class PasskeyCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='passkeys')
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=100, default='Windows Hello')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} - {self.name}'


class PhoneCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='phone_credential')
    phone = models.CharField(max_length=20, unique=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} - {self.phone}'
