from django import forms
from django.core.exceptions import ValidationError

MAX_PHOTO_BYTES = 2 * 1024 * 1024
ALLOWED_PHOTO_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp')
ALLOWED_PHOTO_FORMATS = {'JPEG', 'PNG', 'WEBP'}


class ProfileForm(forms.Form):
    full_name = forms.CharField(max_length=150, label='Full name')
    photo = forms.ImageField(required=False, label='Profile photo')

    def clean_full_name(self):
        return ' '.join(self.cleaned_data['full_name'].split())

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if not photo:
            return photo
        extension = photo.name.rsplit('.', 1)[-1].lower() if '.' in photo.name else ''
        if extension not in ALLOWED_PHOTO_EXTENSIONS:
            raise ValidationError('Upload a JPG, PNG or WebP image.')
        if photo.size > MAX_PHOTO_BYTES:
            raise ValidationError('The photo must be 2 MB or smaller.')
        # forms.ImageField has already opened the file with Pillow; confirm the real format too.
        if getattr(photo, 'image', None) is not None and photo.image.format not in ALLOWED_PHOTO_FORMATS:
            raise ValidationError('Upload a JPG, PNG or WebP image.')
        return photo
