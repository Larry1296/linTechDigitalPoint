"""A second password for the protected pages: the M-Pesa agency and the investments.

Signing in opens the dashboard; these pages also ask for this password, which is each person's own, different
from their sign-in password. It lasts seven days, then a new one is set, and no password is ever used twice.
Once entered, the pages stay open on that device until the workspace locks or the person signs out.
"""
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import DeviceSession, ProtectedPagesPassword, SessionAudit

LIFETIME = timedelta(days=7)
SHORTEST = 6
TRIES = 5
BLOCK = timedelta(minutes=5)
PREFIXES = ('/api/v1/mpesa/', '/api/v1/accounting/investments/')
# Dashboard nudges say only that something is due, never an amount, so they work without the password.
OPEN_PATHS = {'/api/v1/accounting/investments/reminder/', '/api/v1/mpesa/commission/due/'}


def is_protected(path):
    return path.startswith(PREFIXES) and path not in OPEN_PATHS


def digest(password, salt):
    # Fixed iterations, so a digest made years ago still matches the same password today.
    iterations = getattr(settings, 'PROTECTED_PASSWORD_ITERATIONS', 600_000)
    return PBKDF2PasswordHasher().encode(password, salt, iterations)


def current(user):
    return ProtectedPagesPassword.objects.filter(user=user).first()


def is_open(device):
    return device.protected_version is not None and device.protected_version == device.version


def status(device):
    latest = current(device.user)
    now = timezone.now()
    expires = latest.created_at + LIFETIME if latest else None
    blocked = device.protected_blocked_until if device.protected_blocked_until and device.protected_blocked_until > now else None
    return {'has_password': bool(latest), 'set_at': latest.created_at if latest else None, 'expires_at': expires,
            'expired': bool(latest and now >= expires), 'unlocked': bool(latest and now < expires and is_open(device)),
            'blocked_until': blocked, 'lifetime_days': LIFETIME.days, 'shortest': SHORTEST}


def guard(request):
    """The refusal for a protected request on a device that has not entered the password, else None."""
    device = request.device_session
    if not is_protected(request.path) or (is_open(device) and not status(device)['expired']):
        return None
    return JsonResponse({'detail': 'This page is protected. Enter the protected pages password to open it.',
                         'code': 'protected_locked', 'protected': status(device)}, status=403, json_dumps_params={'default': str})


def locked_device(request):
    return DeviceSession.objects.select_for_update().select_related('user').get(pk=request.auth.pk)


def failed(device, message):
    device.protected_failures += 1
    if device.protected_failures >= TRIES:
        device.protected_blocked_until = timezone.now() + BLOCK
        device.protected_failures = 0
    device.save(update_fields=['protected_failures', 'protected_blocked_until'])
    SessionAudit.objects.create(session=device, event='PROTECTED_FAILED')
    return Response({'detail': message, 'protected': status(device)}, status=400)


def blocked(device):
    if device.protected_blocked_until and device.protected_blocked_until > timezone.now():
        return Response({'detail': 'Too many wrong passwords. Wait five minutes and try again.', 'protected': status(device)}, status=429)
    return None


def opened(device, event):
    device.protected_version = device.version
    device.protected_failures = 0
    device.protected_blocked_until = None
    device.save(update_fields=['protected_version', 'protected_failures', 'protected_blocked_until'])
    SessionAudit.objects.create(session=device, event=event)
    return Response({'protected': status(device)})


def confirm(request, password):
    """The person's protected pages password typed again before something that cannot be undone, such as deleting a
    whole business. None when it is right; else the refusal. Wrong tries count towards the same five-minute block."""
    device = locked_device(request) if isinstance(request.auth, DeviceSession) else None
    refusal = blocked(device) if device else None
    if refusal:
        return refusal
    latest = current(request.user)
    if not latest:
        return Response({'detail': 'Set your protected pages password first, then try again.', 'code': 'protected_unset'}, status=400)
    if not isinstance(password, str) or not constant_time_compare(digest(password, latest.salt), latest.digest):
        if device:
            return failed(device, 'Incorrect protected pages password.')
        return Response({'detail': 'Incorrect protected pages password.'}, status=400)
    if timezone.now() >= latest.created_at + LIFETIME:
        return Response({'detail': 'Your protected pages password is a week old. Set a new one, then try again.', 'code': 'protected_expired'}, status=400)
    return None


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def protected_status(request):
    return Response({'protected': status(request.auth)})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def protected_unlock(request):
    device = locked_device(request)
    refusal = blocked(device)
    if refusal:
        return refusal
    latest = current(device.user)
    if not latest:
        return Response({'detail': 'Set a protected pages password first.', 'code': 'protected_unset', 'protected': status(device)}, status=400)
    password = request.data.get('password', '')
    if not isinstance(password, str) or not constant_time_compare(digest(password, latest.salt), latest.digest):
        return failed(device, 'Incorrect protected pages password.')
    if status(device)['expired']:
        return Response({'detail': 'This password is a week old. Set a new one to continue.', 'code': 'protected_expired',
                         'protected': status(device)}, status=400)
    return opened(device, 'PROTECTED_UNLOCK')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def protected_set(request):
    """Set a new password. Proved with the one in use (even if it is a week old), or with the sign-in password
    when there is none yet or it is forgotten."""
    device = locked_device(request)
    refusal = blocked(device)
    if refusal:
        return refusal
    user = device.user
    latest = current(user)
    proof, new = request.data.get('proof', ''), request.data.get('new_password', '')
    if not isinstance(proof, str) or not isinstance(new, str):
        return Response({'detail': 'Enter the passwords as text.'}, status=400)
    proved = (latest and constant_time_compare(digest(proof, latest.salt), latest.digest)) or user.check_password(proof)
    if not proved:
        return failed(device, 'That is neither your protected pages password nor your sign-in password.')
    if len(new) < SHORTEST:
        return Response({'detail': f'Use at least {SHORTEST} characters.'}, status=400)
    if user.check_password(new):
        return Response({'detail': 'Use a password different from your sign-in password.'}, status=400)
    salt = latest.salt if latest else secrets.token_hex(16)
    new_digest = digest(new, salt)
    if ProtectedPagesPassword.objects.filter(user=user, digest=new_digest).exists():
        return Response({'detail': 'You have used this password before. Choose one you have never used.'}, status=400)
    try:
        with transaction.atomic():
            ProtectedPagesPassword.objects.create(user=user, salt=salt, digest=new_digest)
    except IntegrityError:
        return Response({'detail': 'You have used this password before. Choose one you have never used.'}, status=400)
    return opened(device, 'PROTECTED_SET')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def protected_lock(request):
    device = locked_device(request)
    device.protected_version = None
    device.save(update_fields=['protected_version'])
    SessionAudit.objects.create(session=device, event='PROTECTED_LOCK')
    return Response({'protected': status(device)})
