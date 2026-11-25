import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from orders.models import EmailOTP


class OTPRateLimitError(Exception):
    pass


def is_otp_locked(user, purpose):
    """Stop guessing across re-issued codes: too many failures in the last hour lock verification."""
    window_start = timezone.now() - timedelta(hours=1)
    failures = EmailOTP.objects.filter(
        user=user, purpose=purpose, created_at__gte=window_start,
    ).aggregate(total=Sum('attempts'))['total'] or 0
    return failures >= settings.OTP_MAX_ATTEMPTS * 3


def generate_otp():
    return f'{secrets.randbelow(1_000_000):06d}'


def issue_email_otp(user, purpose, subject, greeting=''):
    """Email a fresh code, then persist only its password hash."""
    latest = EmailOTP.objects.filter(user=user, purpose=purpose).order_by('-created_at').first()
    cooldown = timedelta(seconds=settings.OTP_RESEND_INTERVAL_SECONDS)
    if latest and timezone.now() - latest.created_at < cooldown:
        raise OTPRateLimitError

    recipient = (user.email or '').strip()
    if not recipient:
        raise ValueError('This account does not have an email address.')

    code = generate_otp()
    intro = greeting or 'Use this code to continue.'
    expiry = settings.OTP_EXPIRY_MINUTES
    text = (
        f'Hello {user.get_full_name() or ""},\n\n{intro}\n\n'
        f'Your six-digit verification code is: {code}\n\n'
        f'This code expires in {expiry} minutes. Do not share it with anyone.'
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#172033">'
        '<h2>AERIAL ELECTRONICS</h2>'
        f'<p>{intro}</p><p>Your six-digit verification code is:</p>'
        f'<p style="font-size:32px;font-weight:bold;letter-spacing:8px">{code}</p>'
        f'<p>This code expires in {expiry} minutes. Do not share it with anyone.</p></div>'
    )
    sent = send_mail(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=False,
        html_message=html,
    )
    if sent != 1:
        raise RuntimeError('The email service did not accept the message.')

    EmailOTP.objects.filter(user=user, purpose=purpose, used=False).update(used=True)
    EmailOTP.objects.create(user=user, purpose=purpose, code=make_password(code))
    return code


def verify_email_otp(user, purpose, submitted_code):
    if is_otp_locked(user, purpose):
        return False

    otp = EmailOTP.objects.filter(user=user, purpose=purpose, used=False).order_by('-created_at').first()
    if not otp:
        return False

    lifetime = timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
    if timezone.now() - otp.created_at >= lifetime:
        otp.used = True
        otp.save(update_fields=['used'])
        return False

    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        otp.used = True
        otp.save(update_fields=['used'])
        return False

    if len(submitted_code) == 6 and submitted_code.isascii() and submitted_code.isdigit() and check_password(submitted_code, otp.code):
        otp.used = True
        otp.save(update_fields=['used'])
        return True

    otp.attempts += 1
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        otp.used = True
    otp.save(update_fields=['attempts', 'used'])
    return False


def mask_email(email):
    if not email or '@' not in email:
        return ''
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        visible = local[:1]
    else:
        visible = local[:2]
    return f'{visible}{"*" * max(3, min(8, len(local) - len(visible)))}@{domain}'
