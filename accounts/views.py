import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.db.models import Q
from fido2.cbor import decode as cbor_decode
from fido2.cbor import encode as cbor_encode
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (
    AttestedCredentialData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
)

from django.contrib.admin.views.decorators import staff_member_required

from .forms import ProfileForm
from .models import PasskeyCredential, PhoneCredential, UserProfile
from orders.models import EmailOTP, Order
from .otp import OTPRateLimitError, issue_email_otp, mask_email, verify_email_otp

logger = logging.getLogger(__name__)

REMEMBER_ME_SECONDS = 60 * 60 * 24 * 14


def passkey_challenge(value):
    if isinstance(value, str):
        return value
    return websafe_encode(value)


def get_passkey_server(request):
    host = request.get_host().split(':')[0]
    # WebAuthn passkeys use the effective hostname as RP ID.
    # On local development, always use localhost; 127.0.0.1 is an IP
    # and can trigger "invalid domain" or origin/RP-ID mismatches.
    rp_id = 'localhost' if host in {'localhost', '127.0.0.1'} else host
    rp = PublicKeyCredentialRpEntity(name='AERIAL ELECTRONICS', id=rp_id)
    allowed_origins = {
        f'{request.scheme}://{request.get_host()}',
        'http://localhost:8000',
    }
    return Fido2Server(rp, verify_origin=lambda origin: origin in allowed_origins)


def _set_otp_session(request, user, purpose, email=None):
    request.session['otp_user_id'] = user.pk if user else None
    request.session['otp_purpose'] = purpose
    request.session['otp_email'] = email or (user.email if user else '')
    request.session['otp_last_sent'] = timezone.now().timestamp()


def _clear_otp_session(request):
    for key in ('otp_user_id', 'otp_purpose', 'otp_email', 'otp_last_sent', 'otp_next', 'otp_remember', 'password_reset_user_id', 'password_reset_verified', 'password_reset_verified_at'):
        request.session.pop(key, None)


def _safe_next(request, value):
    """Only allow same-site redirect targets, so ?next= cannot send users to another website."""
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return ''


def _otp_page_context(request, user):
    purpose = request.session.get('otp_purpose', '')
    email = user.email if user else request.session.get('otp_email', '')
    last_sent = float(request.session.get('otp_last_sent', timezone.now().timestamp()))
    if user:
        latest_otp = EmailOTP.objects.filter(user=user, purpose=purpose, used=False).order_by('-created_at').first()
        if latest_otp:
            last_sent = latest_otp.created_at.timestamp()
    resend_wait = max(0, settings.OTP_RESEND_INTERVAL_SECONDS - int(timezone.now().timestamp() - last_sent))
    lifetime = settings.OTP_EXPIRY_MINUTES * 60
    return {
        'otp_purpose': purpose,
        'masked_email': mask_email(email),
        'otp_seconds_left': max(0, lifetime - int(timezone.now().timestamp() - last_sent)),
        'resend_seconds_left': resend_wait,
        'is_password_reset': purpose == 'password-reset',
    }


def _pending_registration_user(user, password):
    """Return an unverified self-registered account whose password matches, so it can get a fresh code.

    Accounts that have signed in before, or that were never created through registration,
    are excluded so a deactivated account cannot be reactivated through the sign-up flow.
    """
    if user is None or user.is_active or user.last_login is not None:
        return None
    if not EmailOTP.objects.filter(user=user, purpose='registration').exists():
        return None
    return user if user.check_password(password) else None


def _send_registration_code(request, user):
    """Send a new registration code and open the verification page. Returns None if sending failed."""
    try:
        issue_email_otp(user, 'registration', 'Your Account Verification Code', 'Thank you for registering on AERIAL ELECTRONICS.')
    except OTPRateLimitError:
        _set_otp_session(request, user, 'registration')
        messages.warning(request, 'A verification code was sent recently. Check your inbox, or wait before requesting another.')
        return redirect('verify_otp')
    except Exception:
        logger.exception('Could not send a registration verification email.')
        messages.error(request, 'We could not send the verification email. Check your email settings and try again.')
        return None
    _set_otp_session(request, user, 'registration')
    messages.success(request, f'We sent a verification code to {mask_email(user.email)}.')
    return redirect('verify_otp')


def register(request):
    if request.method == 'POST':
        full_name = ' '.join(request.POST.get('name', '').split())
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        raw_phone = request.POST.get('phone', '').strip()
        phone = normalize_phone(raw_phone) if raw_phone else ''

        if not full_name or len(full_name) > 150:
            messages.error(request, 'Enter your full name (up to 150 characters).')
        else:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Enter a valid email address.')
            else:
                existing_user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()
                pending_user = _pending_registration_user(existing_user, password) if existing_user else None
                if pending_user:
                    # Same unverified account, correct password: send a fresh code instead of blocking the user.
                    resumed = _send_registration_code(request, pending_user)
                    if resumed:
                        return resumed
                elif existing_user:
                    messages.error(request, 'An account with this email already exists. If you have not verified it yet, sign in with your password to receive a new code.')
                elif raw_phone and len(phone) < 12:
                    messages.error(request, 'Enter a valid Rwanda phone number or leave it blank.')
                elif phone and PhoneCredential.objects.filter(phone=phone).exists():
                    messages.error(request, 'An account already uses this phone number.')
                elif password != password_confirm:
                    messages.error(request, 'The passwords do not match.')
                else:
                    try:
                        validate_password(password)
                    except ValidationError as exc:
                        for error in exc.messages:
                            messages.error(request, error)
                    else:
                        try:
                            with transaction.atomic():
                                user = User.objects.create_user(
                                    username=email,
                                    email=email,
                                    password=password,
                                    first_name=full_name,
                                    is_active=False,
                                )
                                if phone:
                                    PhoneCredential.objects.create(user=user, phone=phone)
                                issue_email_otp(
                                    user,
                                    'registration',
                                    'Your Account Verification Code',
                                    'Thank you for registering on AERIAL ELECTRONICS.',
                                )
                        except IntegrityError:
                            messages.error(request, 'An account with this email or phone already exists.')
                        except OTPRateLimitError:
                            messages.warning(request, 'Please wait before requesting another verification code.')
                        except Exception:
                            logger.exception('Could not send the registration verification email.')
                            messages.error(request, 'We could not send the verification email. Check your email settings and try again.')
                        else:
                            _set_otp_session(request, user, 'registration')
                            messages.success(request, f'We sent a verification code to {user.email}.')
                            return redirect('verify_otp')
    return render(request, 'accounts/register.html')


def login_view(request):
    if request.method == 'POST':
        identifier = (request.POST.get('identifier', '') or request.POST.get('email', '')).strip().lower()
        password = request.POST.get('password', '')
        phone = normalize_phone(identifier) if '@' not in identifier else ''
        credential = PhoneCredential.objects.select_related('user').filter(phone=phone).first() if phone else None
        username = credential.user.username if credential else identifier
        user = authenticate(request, username=username, password=password)

        next_url = _safe_next(request, request.GET.get('next') or request.POST.get('next'))
        remember = bool(request.POST.get('remember'))
        if user and user.is_active and user.is_staff:
            # Administrators must use the separate admin sign-in page; never send them a customer code.
            messages.error(request, 'Administrator accounts sign in on the Admin sign-in page.')
        elif user and user.is_active:
            try:
                issue_email_otp(user, 'login', 'Your Sign-In Verification Code', 'Use this code to finish signing in.')
            except OTPRateLimitError:
                _set_otp_session(request, user, 'login')
                request.session['otp_next'] = next_url
                request.session['otp_remember'] = remember
                messages.info(request, 'A recent sign-in code may still be valid. Check your inbox before requesting another.')
                return redirect('verify_otp')
            except Exception:
                logger.exception('Could not send the sign-in verification email.')
                messages.error(request, 'We could not send the verification email. Check your email settings and try again.')
            else:
                _set_otp_session(request, user, 'login')
                request.session['otp_next'] = next_url
                request.session['otp_remember'] = remember
                messages.success(request, f'We sent a verification code to {mask_email(user.email)}.')
                return redirect('verify_otp')
        else:
            pending_user = _pending_registration_user(User.objects.filter(username__iexact=username).first(), password)
            if pending_user:
                # Unverified sign-up with the correct password: resend the registration code.
                resumed = _send_registration_code(request, pending_user)
                if resumed:
                    return resumed
            else:
                messages.error(request, 'Invalid email, phone number, or password.')
    return render(request, 'accounts/login.html')


def staff_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        user = authenticate(request, username=email, password=password)
        if user and user.is_staff:
            try:
                issue_email_otp(user, 'admin-login', 'Administrator Sign-In Code', 'Use this code to finish signing in to the administration area.')
            except OTPRateLimitError:
                _set_otp_session(request, user, 'admin-login')
                messages.info(request, 'A recent sign-in code may still be valid. Check your inbox before requesting another.')
                return redirect('verify_otp')
            except Exception:
                logger.exception('Could not send the administrator verification email.')
                messages.error(request, 'We could not send the administrator verification email. Check email settings.')
            else:
                _set_otp_session(request, user, 'admin-login')
                messages.success(request, f'We sent a verification code to {mask_email(user.email)}.')
                return redirect('verify_otp')
        else:
            messages.error(request, 'Invalid administrator credentials.')
    return render(request, 'accounts/staff_login.html')


def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Enter a valid email address.')
            return render(request, 'accounts/forgot_password.html')

        _clear_otp_session(request)
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        request.session['password_reset_user_id'] = user.pk if user else None
        _set_otp_session(request, user, 'password-reset', email=email)
        if user:
            try:
                issue_email_otp(user, 'password-reset', 'Your Password Reset Code', 'Use this code to reset your AERIAL ELECTRONICS password.')
                request.session['otp_last_sent'] = timezone.now().timestamp()
            except OTPRateLimitError:
                pass
            except Exception:
                logger.exception('Could not send the password reset email.')
        messages.success(request, 'If an active account uses that email, a reset code is on its way. Check your inbox and Spam folder.')
        return redirect('verify_otp')
    return render(request, 'accounts/forgot_password.html')


def reset_password(request):
    verified_at = float(request.session.get('password_reset_verified_at', 0))
    if not request.session.get('password_reset_verified') or timezone.now().timestamp() - verified_at > settings.OTP_EXPIRY_MINUTES * 60:
        _clear_otp_session(request)
        messages.error(request, 'Verify your password reset code first.')
        return redirect('forgot_password')
    user = User.objects.filter(pk=request.session.get('password_reset_user_id'), is_active=True).first()
    if not user:
        _clear_otp_session(request)
        return redirect('forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        if password != password_confirm:
            messages.error(request, 'The passwords do not match.')
        else:
            try:
                validate_password(password, user)
            except ValidationError as exc:
                for error in exc.messages:
                    messages.error(request, error)
            else:
                user.set_password(password)
                user.save(update_fields=['password'])
                _clear_otp_session(request)
                messages.success(request, 'Your password has been reset. Sign in with your new password.')
                return redirect('login')
    return render(request, 'accounts/reset_password.html')


def resend_otp(request):
    if request.method != 'POST' or 'otp_purpose' not in request.session:
        messages.error(request, 'Start the verification process again.')
        return redirect('login')

    purpose = request.session.get('otp_purpose')
    user = User.objects.filter(pk=request.session.get('otp_user_id')).first()
    last_sent = float(request.session.get('otp_last_sent', 0))
    elapsed = timezone.now().timestamp() - last_sent
    if elapsed < settings.OTP_RESEND_INTERVAL_SECONDS:
        messages.warning(request, f'Please wait {int(settings.OTP_RESEND_INTERVAL_SECONDS - elapsed)} seconds before requesting another code.')
        return redirect('verify_otp')

    request.session['otp_last_sent'] = timezone.now().timestamp()
    if purpose == 'password-reset' and not user:
        messages.success(request, 'If an active account uses that email, a new password reset code is on its way.')
        return redirect('verify_otp')
    if not user:
        _clear_otp_session(request)
        messages.error(request, 'Start the verification process again.')
        return redirect('login')

    subject_and_intro = {
        'registration': ('Your Account Verification Code', 'Use this code to verify your AERIAL ELECTRONICS account.'),
        'login': ('Your Sign-In Verification Code', 'Use this code to finish signing in.'),
        'admin-login': ('Administrator Sign-In Code', 'Use this code to finish signing in to the administration area.'),
        'password-reset': ('Your Password Reset Code', 'Use this code to reset your AERIAL ELECTRONICS password.'),
    }
    subject, intro = subject_and_intro.get(purpose, subject_and_intro['login'])
    if purpose == 'password-reset':
        try:
            issue_email_otp(user, purpose, subject, intro)
        except OTPRateLimitError:
            pass  # Same generic message either way; no account details are revealed.
        except Exception:
            logger.exception('Could not resend the password reset email.')
        messages.success(request, 'If an active account uses that email, a new password reset code is on its way.')
        return redirect('verify_otp')

    try:
        issue_email_otp(user, purpose, subject, intro)
    except OTPRateLimitError:
        messages.warning(request, 'Please wait before requesting another verification code.')
    except Exception:
        logger.exception('Could not resend an authentication email.')
        messages.error(request, 'We could not send the email. Check the email settings and try again.')
    else:
        messages.success(request, f'We sent a new code to {mask_email(user.email)}.')
    return redirect('verify_otp')


def verify_otp(request):
    purpose = request.session.get('otp_purpose')
    if not purpose:
        return redirect('login')
    user = User.objects.filter(pk=request.session.get('otp_user_id')).first()
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not user or not verify_email_otp(user, purpose, code):
            messages.error(request, 'That code is invalid, expired, or has reached its attempt limit. Request a new code and try again.')
        elif purpose == 'password-reset':
            request.session['password_reset_verified'] = True
            request.session['password_reset_user_id'] = user.pk
            request.session['password_reset_verified_at'] = timezone.now().timestamp()
            request.session.pop('otp_user_id', None)
            request.session.pop('otp_purpose', None)
            request.session.pop('otp_email', None)
            request.session.pop('otp_last_sent', None)
            return redirect('reset_password')
        else:
            if purpose == 'registration':
                user.is_active = True
                user.save(update_fields=['is_active'])
                phone_credential = PhoneCredential.objects.filter(user=user).first()
                if phone_credential:
                    phone_credential.verified = True
                    phone_credential.save(update_fields=['verified'])
            # Only a customer sign-in carries a return address; other purposes never use it.
            next_url = _safe_next(request, request.session.get('otp_next', '')) if purpose == 'login' else ''
            remember = purpose == 'login' and bool(request.session.get('otp_remember'))
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            _clear_otp_session(request)
            # Remember me keeps the sign-in for two weeks; otherwise it ends when the browser closes.
            request.session.set_expiry(REMEMBER_ME_SECONDS if remember else 0)
            if next_url:
                return redirect(next_url)
            if user.is_staff:
                return redirect('admin_dashboard')
            return redirect('account')

    return render(request, 'accounts/verify_otp.html', _otp_page_context(request, user))


@login_required
def account(request):
    return render(request, 'accounts/account.html', {'orders': Order.objects.filter(user=request.user).order_by('-created_at')})


def _handle_profile(request, base_template, redirect_name):
    """Show and save the profile: display name and optional photo, for customers and administrators alike."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        if request.POST.get('action') == 'remove_photo':
            if profile.photo:
                profile.photo.delete(save=False)
                profile.photo = ''
                profile.save(update_fields=['photo', 'updated_at'])
            messages.success(request, 'Your profile photo was removed.')
            return redirect(redirect_name)

        form = ProfileForm(request.POST, request.FILES)
        if form.is_valid():
            request.user.first_name = form.cleaned_data['full_name']
            request.user.save(update_fields=['first_name'])
            photo = form.cleaned_data.get('photo')
            if photo:
                if profile.photo:
                    profile.photo.delete(save=False)
                profile.photo = photo
                profile.save()
            messages.success(request, 'Your profile was saved.')
            return redirect(redirect_name)
    else:
        form = ProfileForm(initial={'full_name': request.user.get_full_name()})
    return render(request, 'accounts/profile.html', {
        'form': form,
        'profile': profile,
        'base_template': base_template,
    })


@login_required
def profile(request):
    return _handle_profile(request, 'base.html', 'profile')


@staff_member_required
def admin_profile(request):
    return _handle_profile(request, 'dashboard/base.html', 'admin_profile')


def logout_view(request):
    logout(request)
    return redirect('home')


def passkey_options(request):
    if not request.user.is_staff:
        return redirect('account')
    host = request.get_host().split(':')[0]
    if host == '127.0.0.1':
        return redirect('http://localhost:8000' + request.get_full_path())
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            if not request.user.check_password(current_password):
                messages.error(request, 'The current administrator password is incorrect.')
            elif len(new_password) < 12:
                messages.error(request, 'The new password must contain at least 12 characters.')
            elif new_password != confirm_password:
                messages.error(request, 'The new password and confirmation do not match.')
            else:
                request.user.set_password(new_password)
                request.user.save(update_fields=['password'])
                login(request, request.user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Administrator password changed successfully.')
        elif action == 'delete_passkey':
            credential = PasskeyCredential.objects.filter(user=request.user, id=request.POST.get('credential_id')).first()
            if credential:
                credential.delete()
                request.session.pop('passkey_verified', None)
                messages.success(request, 'The passkey was removed.')
        elif action == 'rename_passkey':
            credential = PasskeyCredential.objects.filter(user=request.user, id=request.POST.get('credential_id')).first()
            name = request.POST.get('name', '').strip()
            if credential and name:
                credential.name = name
                credential.save(update_fields=['name'])
                messages.success(request, 'Passkey name updated.')
        return redirect('passkey_register')

    return render(request, 'accounts/passkey.html', {
        'passkeys': PasskeyCredential.objects.filter(user=request.user).order_by('-created_at')
    })


@login_required
@require_POST
def passkey_register_begin(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Administrator access required.'}, status=403)
    server = get_passkey_server(request)
    user = PublicKeyCredentialUserEntity(
        name=request.user.email or request.user.username,
        id=str(request.user.id).encode('utf-8'),
        display_name=request.user.get_full_name() or request.user.username,
    )
    credentials = [
        AttestedCredentialData.create(b'\0' * 16, bytes(item.credential_id), CoseKey.parse(cbor_decode(bytes(item.public_key))))
        for item in PasskeyCredential.objects.filter(user=request.user)
    ]
    options, state = server.register_begin(
        user,
        credentials=credentials,
        user_verification='required',
        resident_key_requirement='required',
    )
    request.session['passkey_register_state'] = {
        'challenge': passkey_challenge(state['challenge']),
        'user_verification': 'required',
    }
    public_key = options.public_key
    return JsonResponse({
        'publicKey': {
            'rp': {'name': public_key.rp.name, 'id': public_key.rp.id},
            'user': {
                'id': websafe_encode(public_key.user.id),
                'name': public_key.user.name,
                'displayName': public_key.user.display_name or public_key.user.name,
            },
            'challenge': passkey_challenge(public_key.challenge),
            'pubKeyCredParams': [{'type': p.type.value, 'alg': p.alg} for p in public_key.pub_key_cred_params],
            'timeout': 60000,
            'excludeCredentials': [],
            'authenticatorSelection': {
                'authenticatorAttachment': 'platform',
                'residentKey': 'required',
                'requireResidentKey': True,
                'userVerification': 'required',
            },
            'attestation': 'none',
        }
    })


@login_required
@require_POST
def passkey_register_complete(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Administrator access required.'}, status=403)
    try:
        response_data = __import__('json').loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'Invalid passkey response.'}, status=400)
    state_session = request.session.get('passkey_register_state')
    if not state_session:
        return JsonResponse({'error': 'Passkey registration session expired.'}, status=400)
    server = get_passkey_server(request)
    state = {'challenge': websafe_decode(state_session['challenge']), 'user_verification': state_session['user_verification']}
    try:
        auth_data = server.register_complete(state, response_data)
        credential = auth_data.credential_data
        PasskeyCredential.objects.update_or_create(
            credential_id=credential.credential_id,
            defaults={
                'user': request.user,
                'public_key': cbor_encode(credential.public_key),
                'sign_count': auth_data.sign_count,
                'name': 'Windows Hello / Passkey',
            },
        )
        request.session.pop('passkey_register_state', None)
        request.session.pop('require_passkey_registration', None)
        request.session['passkey_verified'] = True
        return JsonResponse({'status': 'registered'})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@login_required
@require_POST
def passkey_verify_begin(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Administrator access required.'}, status=403)
    items = PasskeyCredential.objects.filter(user=request.user)
    if not items.exists():
        return JsonResponse({'error': 'Register a passkey first.', 'register': True}, status=400)
    credentials = [
        AttestedCredentialData.create(b'\0' * 16, bytes(item.credential_id), CoseKey.parse(cbor_decode(bytes(item.public_key))))
        for item in items
    ]
    server = get_passkey_server(request)
    options, state = server.authenticate_begin(
        credentials=credentials,
        user_verification='required',
    )
    request.session['passkey_auth_state'] = {
        'challenge': passkey_challenge(state['challenge']),
        'user_verification': 'required',
    }
    public_key = options.public_key
    return JsonResponse({
        'publicKey': {
            'challenge': passkey_challenge(public_key.challenge),
            'rpId': public_key.rp_id,
            'timeout': 60000,
            'allowCredentials': [
                {'type': 'public-key', 'id': websafe_encode(bytes(item.credential_id))}
                for item in items
            ],
            'userVerification': 'required',
        }
    })


@login_required
@require_POST
def passkey_verify_complete(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Administrator access required.'}, status=403)
    try:
        response_data = __import__('json').loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'Invalid passkey response.'}, status=400)
    state_session = request.session.get('passkey_auth_state')
    if not state_session:
        return JsonResponse({'error': 'Passkey verification session expired.'}, status=400)
    items = list(PasskeyCredential.objects.filter(user=request.user))
    credentials = [
        AttestedCredentialData.create(b'\0' * 16, bytes(item.credential_id), CoseKey.parse(cbor_decode(bytes(item.public_key))))
        for item in items
    ]
    state = {'challenge': websafe_decode(state_session['challenge']), 'user_verification': state_session['user_verification']}
    server = get_passkey_server(request)
    try:
        verified = server.authenticate_complete(state, credentials, response_data)
        credential_id = verified.credential_id
        matched = next(item for item in items if bytes(item.credential_id) == credential_id)
        try:
            from fido2.webauthn import AuthenticationResponse
            sign_count = AuthenticationResponse.from_dict(response_data).response.authenticator_data.sign_count
            matched.sign_count = sign_count
        except Exception:
            pass
        matched.save(update_fields=['sign_count'])
        request.session.pop('passkey_auth_state', None)
        request.session['passkey_verified'] = True
        return JsonResponse({'status': 'verified'})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@require_POST
def passkey_login_begin(request):
    items = list(PasskeyCredential.objects.filter(user__is_staff=True).select_related('user'))
    if not items:
        return JsonResponse({'error': 'No administrator face or fingerprint passkey has been registered.'}, status=400)

    credentials = [
        AttestedCredentialData.create(b'\0' * 16, bytes(item.credential_id), CoseKey.parse(cbor_decode(bytes(item.public_key))))
        for item in items
    ]
    server = get_passkey_server(request)
    options, state = server.authenticate_begin(credentials=credentials, user_verification='required')
    request.session['passkey_login_state'] = {
        'challenge': passkey_challenge(state['challenge']),
        'user_verification': 'required',
    }
    public_key = options.public_key
    return JsonResponse({'publicKey': {
        'challenge': passkey_challenge(public_key.challenge),
        'rpId': public_key.rp_id,
        'timeout': 60000,
        'allowCredentials': [],
        'userVerification': 'required',
    }})


@require_POST
def passkey_login_complete(request):
    try:
        import json
        response_data = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'Invalid passkey response.'}, status=400)

    state_session = request.session.get('passkey_login_state')
    if not state_session:
        return JsonResponse({'error': 'Face or fingerprint sign-in session expired.'}, status=400)

    items = list(PasskeyCredential.objects.filter(user__is_staff=True).select_related('user'))
    try:
        response_id = websafe_decode(response_data['rawId'])
    except Exception:
        return JsonResponse({'error': 'Invalid passkey credential.'}, status=400)

    matched = next((item for item in items if bytes(item.credential_id) == response_id), None)
    if not matched:
        return JsonResponse({'error': 'This face or fingerprint passkey is not registered to an administrator.'}, status=400)

    user = matched.user
    credentials = [
        AttestedCredentialData.create(b'\0' * 16, bytes(item.credential_id), CoseKey.parse(cbor_decode(bytes(item.public_key))))
        for item in items
    ]
    state = {
        'challenge': websafe_decode(state_session['challenge']),
        'user_verification': state_session['user_verification'],
    }
    server = get_passkey_server(request)
    try:
        verified = server.authenticate_complete(state, credentials, response_data)
        if bytes(matched.credential_id) != verified.credential_id:
            raise ValueError('Credential mismatch.')
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop('passkey_login_state', None)
        request.session['passkey_verified'] = True
        return JsonResponse({'status': 'logged_in', 'redirect': reverse('admin_dashboard')})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


def normalize_phone(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits.startswith('250'):
        return '+' + digits
    if digits.startswith('0'):
        digits = '250' + digits[1:]
    return '+' + digits if digits else ''


def send_sms_otp(phone, code, purpose='phone-login'):
    message = f'Your AERIAL ELECTRONICS {purpose.replace("-", " ")} verification code is {code}. It expires in 10 minutes.'
    sms_backend = getattr(settings, 'SMS_BACKEND', 'django.core.mail.backends.console.EmailBackend')

    if sms_backend.endswith('console.EmailBackend'):
        print(f'AERIAL ELECTRONICS SMS OTP for {phone}: {code}')
        return code

    api_url = getattr(settings, 'MTN_SMS_API_URL', '')
    if not api_url:
        raise ValueError('MTN_SMS_API_URL is not configured.')

    import json
    from urllib.request import Request, urlopen

    headers = {'Content-Type': 'application/json'}
    auth_token = getattr(settings, 'MTN_SMS_AUTH_TOKEN', '')
    api_key = getattr(settings, 'MTN_SMS_API_KEY', '')
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'
    elif api_key:
        headers['Authorization'] = f'Basic {api_key}'
        headers['Ocp-Apim-Subscription-Key'] = api_key

    payload = json.dumps({
        'sender': getattr(settings, 'MTN_SMS_SENDER_ID', 'AERIAL'),
        'to': [phone],
        'message': message,
    }).encode('utf-8')
    request = Request(api_url, data=payload, headers=headers, method='POST')
    with urlopen(request, timeout=20) as response:
        if response.status < 200 or response.status >= 300:
            raise ValueError('SMS provider rejected the request.')
    return code
