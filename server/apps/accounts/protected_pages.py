"""PINs, and the private pages they open: the M-Pesa agency and the investments.

Each person has a lock PIN (4 to 6 digits). It opens the workspace after they lock it, and every private page that
has no PIN of its own; a private page can instead have its own PIN. Signing in opens the dashboard, never a private
page: once its PIN is entered a page stays open on that device until it is left untouched for a while (the browser
locks it), the person locks it, the workspace locks or they sign out. After five wrong PINs only the sign-in password
opens the private pages again on that device.
"""
import re
from datetime import timedelta
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import DeviceSession, LockPin, SessionAudit

# Each private page: its name, and the addresses of its records.
PAGES = {
    'mpesa': ('M-Pesa', ('/api/v1/mpesa/',)),
    'investments': ('Investments', ('/api/v1/accounting/investments/',)),
}
TRIES = 5
BLOCK = timedelta(minutes=1)
# Dashboard nudges say only that something is due, never an amount, so they work without the PIN.
OPEN_PATHS = {'/api/v1/accounting/investments/reminder/', '/api/v1/mpesa/commission/due/'}


def page_of(path):
    if path in OPEN_PATHS:
        return None
    return next((key for key, (_, prefixes) in PAGES.items() if path.startswith(prefixes)), None)


def is_protected(path):
    return page_of(path) is not None


def pins(user):
    """The person's PINs by page ('' is the lock PIN)."""
    return {pin.page: pin for pin in LockPin.objects.filter(user=user)}


def pin_for(user, page, known=None):
    """The PIN that opens ``page`` ('' for the workspace): the page's own, else the lock PIN; None when neither is set."""
    known = pins(user) if known is None else known
    return known.get(page) or known.get('')


def sharing(page, known):
    """The pages one PIN opens together: a page with its own PIN opens alone; the rest share the lock PIN."""
    if page in known:
        return [page]
    return [key for key in PAGES if key not in known]


def is_open(device, page=None):
    if device.protected_version is None or device.protected_version != device.version:
        return False
    return page is None or page in (device.protected_open or [])


def status(device):
    known = pins(device.user)
    now = timezone.now()
    blocked = device.protected_blocked_until if device.protected_blocked_until and device.protected_blocked_until > now else None
    pages = {}
    for key, (label, _) in PAGES.items():
        pin = pin_for(device.user, key, known)
        pages[key] = {'label': label, 'own_pin': key in known, 'pin_length': pin.length if pin else None,
                      'unlocked': bool(pin and is_open(device, key))}
    return {'has_pin': '' in known, 'pages': pages, 'needs_password': device.protected_failures >= TRIES,
            'blocked_until': blocked, 'tries_left': max(0, TRIES - device.protected_failures)}


def guard(request):
    """The refusal for a private page's records on a device where that page is not open, else None."""
    device = request.device_session
    page = page_of(request.path)
    if not page or (is_open(device, page) and pin_for(device.user, page)):
        return None
    return JsonResponse({'detail': f'{PAGES[page][0]} is a private page. Enter its PIN to open it.',
                         'code': 'protected_locked', 'page': page, 'protected': status(device)},
                        status=403, json_dumps_params={'default': str})


def locked_device(request):
    return DeviceSession.objects.select_for_update().select_related('user').get(pk=request.auth.pk)


def blocked(device):
    if device.protected_blocked_until and device.protected_blocked_until > timezone.now():
        return Response({'detail': 'Too many wrong tries. Wait a minute and try again.', 'protected': status(device)}, status=429)
    return None


def failed(device, wrong_pin):
    device.protected_failures += 1
    if not wrong_pin:
        device.protected_blocked_until = timezone.now() + BLOCK
    device.save(update_fields=['protected_failures', 'protected_blocked_until'])
    SessionAudit.objects.create(session=device, event='PROTECTED_FAILED')
    left = max(0, TRIES - device.protected_failures)
    if not wrong_pin:
        detail = 'Incorrect password. Wait a minute and try again.'
    elif left:
        detail = f'Wrong PIN. {left} {"try" if left == 1 else "tries"} left.'
    else:
        detail = 'Wrong PIN too many times. Enter your sign-in password to open the private pages.'
    return Response({'detail': detail, 'code': 'wrong_pin' if wrong_pin else 'wrong_password', 'protected': status(device)}, status=400)


def open_pages(device, pages, event):
    current = device.protected_open if is_open(device) else []
    device.protected_open = sorted(set(current) | set(pages))
    device.protected_version = device.version
    device.protected_failures = 0
    device.protected_blocked_until = None
    device.save(update_fields=['protected_open', 'protected_version', 'protected_failures', 'protected_blocked_until'])
    SessionAudit.objects.create(session=device, event=event)
    return Response({'protected': status(device)})


def confirm(request, password):
    """The sign-in password typed again before something that cannot be undone, such as deleting a whole business.
    None when it is right; else the refusal."""
    if isinstance(password, str) and request.user.check_password(password):
        return None
    return Response({'detail': 'Incorrect password.', 'code': 'wrong_password'}, status=400)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def protected_status(request):
    return Response({'protected': status(request.auth)})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def protected_unlock(request):
    """Open a private page with its PIN (which opens the pages sharing it too), or every private page with the
    sign-in password, which is also the way back after too many wrong PINs."""
    device = locked_device(request)
    refusal = blocked(device)
    if refusal:
        return refusal
    page, pin, password = request.data.get('page'), request.data.get('pin'), request.data.get('password')
    if page not in PAGES:
        return Response({'detail': 'Choose a private page to open.'}, status=400)
    known = pins(device.user)
    if password is not None:
        if not isinstance(password, str) or not device.user.check_password(password):
            return failed(device, wrong_pin=False)
        return open_pages(device, list(PAGES), 'PROTECTED_UNLOCK_PASSWORD')
    expected = pin_for(device.user, page, known)
    if not expected:
        return Response({'detail': 'Set your lock PIN first.', 'code': 'pin_unset', 'protected': status(device)}, status=400)
    if device.protected_failures >= TRIES:
        return Response({'detail': 'Enter your sign-in password to open the private pages.', 'code': 'password_required',
                         'protected': status(device)}, status=400)
    if not isinstance(pin, str) or not check_password(pin, expected.digest):
        return failed(device, wrong_pin=True)
    return open_pages(device, sharing(page, known), 'PROTECTED_UNLOCK')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def protected_lock(request):
    """Lock the private pages on this device: all of them, as one PIN may open several."""
    device = locked_device(request)
    device.protected_version = None
    device.protected_open = []
    device.save(update_fields=['protected_version', 'protected_open'])
    SessionAudit.objects.create(session=device, event='PROTECTED_LOCK')
    return Response({'protected': status(device)})


def pin_settings(user):
    known = pins(user)
    lock = known.get('')
    return {'pin': {'set': bool(lock), 'length': lock.length if lock else None, 'updated_at': lock.updated_at if lock else None},
            'pages': {key: {'label': label, 'own_pin': key in known, 'length': known[key].length if key in known else None}
                      for key, (label, _) in PAGES.items()}}


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def lock_pin(request):
    """The person's PINs. POST sets the lock PIN, or with ``page`` that private page's own PIN; DELETE with ``page``
    makes the page use the lock PIN again. Changes need the sign-in password."""
    if request.method == 'GET':
        return Response(pin_settings(request.user))
    page = request.data.get('page') or ''
    if page and page not in PAGES:
        return Response({'detail': 'There is no such private page.'}, status=400)
    if not request.user.check_password(request.data.get('password') or ''):
        return Response({'detail': 'Your sign-in password is incorrect.', 'code': 'wrong_password'}, status=400)
    if request.method == 'DELETE':
        if not page:
            return Response({'detail': 'Your lock PIN can be changed, not removed.'}, status=400)
        LockPin.objects.filter(user=request.user, page=page).delete()
        return Response(pin_settings(request.user))
    pin = request.data.get('pin')
    if not isinstance(pin, str) or not re.fullmatch(r'\d{4,6}', pin):
        return Response({'detail': 'A PIN is 4 to 6 digits.'}, status=400)
    if len(set(pin)) == 1 or pin in '0123456789' or pin in '9876543210':
        return Response({'detail': 'Choose a PIN harder to guess than repeated or running digits.'}, status=400)
    if page and not LockPin.objects.filter(user=request.user, page='').exists():
        return Response({'detail': 'Set your lock PIN first.', 'code': 'pin_unset'}, status=400)
    LockPin.objects.update_or_create(user=request.user, page=page, defaults={'digest': make_password(pin), 'length': len(pin)})
    return Response(pin_settings(request.user))
