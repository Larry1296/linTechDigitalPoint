"""The private pages, the M-Pesa agency and the investments, and the PINs that open them.

Each private page opens only with a PIN (PagePin), and each person has their own: the owner sets theirs in Settings;
an employee the owner lets into a page sets their own the first time they open it. A person's pages have different
PINs. The sign-in password never opens a private page. Only the owner resets a PIN: their own with their sign-in
password, an employee's from Settings → Staff, after which the employee sets a new one. The investments are the
owner's, unless the owner gives them to an employee: nobody else can open them, with or without a PIN. After five wrong PINs a device waits a few minutes before trying again. Signing in opens the dashboard, never
a private page: once its PIN is entered a page stays open on that device until it is left untouched for a while (the
browser locks it), the person locks it, the workspace locks or they sign out.

Each person's own lock PIN (LockPin) opens the workspace after they lock it, and nothing else.
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
from apps.tenancy.permissions import is_business_owner
from .models import DeviceSession, LockPin, PagePin, SessionAudit

# Each private page: its name, and the addresses of its records.
PAGES = {
    'mpesa': ('M-Pesa', ('/api/v1/mpesa/',)),
    'investments': ('Investments', ('/api/v1/accounting/investments/',)),
}
# Nobody but the owner opens these, unless the owner gives them to an employee.
OWNER_ONLY = {'investments'}
TRIES = 5
BLOCK = timedelta(minutes=5)
# Dashboard nudges say only that something is due, never an amount, so they work without the PIN.
OPEN_PATHS = {'/api/v1/accounting/investments/reminder/', '/api/v1/mpesa/commission/due/'}


def page_of(path):
    if path in OPEN_PATHS:
        return None
    return next((key for key, (_, prefixes) in PAGES.items() if path.startswith(prefixes)), None)


def is_protected(path):
    return page_of(path) is not None


def page_pins(user):
    """``user``'s private page PINs by page: the owner's are the ones with no person on them."""
    owner = is_business_owner(user)
    return {pin.page: pin for pin in PagePin.objects.filter(user=None if owner else user)}


def lock_pin_of(user):
    """The person's own lock PIN, which opens the workspace after they lock it; None when not set."""
    return LockPin.objects.filter(user=user, page='').first()


def kept_out(user, page):
    """Why ``user`` cannot open ``page``: 'owner_only' (the investments), 'hidden' (the owner kept them out of it), or None."""
    from apps.tenancy.permissions import membership_for
    if is_business_owner(user):
        return None
    membership = membership_for(user)
    if membership and membership.role == 'EMPLOYEE':
        # An employee opens only the pages the owner ticked for them, investments included.
        return None if page in (membership.open_pages or []) else 'owner_only' if page in OWNER_ONLY else 'hidden'
    if page in OWNER_ONLY:
        return 'owner_only'
    return 'hidden' if membership and page in (membership.hidden_pages or []) else None


def allowed(user, page):
    return kept_out(user, page) is None


def refusal_text(user, page):
    reason = kept_out(user, page)
    if reason == 'owner_only':
        return f'{PAGES[page][0]} is for the business owner only.'
    return f'The business owner has not given you {PAGES[page][0]}.'


def is_open(device, page=None):
    if device.protected_version is None or device.protected_version != device.version:
        return False
    return page is None or page in (device.protected_open or [])


def status(device):
    known = page_pins(device.user)
    owner = is_business_owner(device.user)
    now = timezone.now()
    blocked = device.protected_blocked_until if device.protected_blocked_until and device.protected_blocked_until > now else None
    pages = {}
    for key, (label, _) in PAGES.items():
        pin = known.get(key)
        may = allowed(device.user, key)
        pages[key] = {'label': label, 'allowed': may, 'kept_out': kept_out(device.user, key), 'pin_set': bool(pin), 'pin_length': pin.length if pin and may else None,
                      'can_set': bool(may and (owner or not pin)), 'unlocked': bool(may and pin and is_open(device, key))}
    return {'is_owner': owner, 'pages': pages, 'blocked_until': blocked, 'tries_left': max(0, TRIES - device.protected_failures)}


# What opens before a new account's first set-up is done: signing in and out, the set-up itself, choosing a business.
SETUP_PATHS = ('/api/v1/auth/', '/api/v1/tenancy/organizations/', '/api/v1/tenancy/select/', '/api/v1/tenancy/platform/')


def setup_pending(user):
    from apps.tenancy.models import Membership
    return Membership.objects.filter(user=user, setup_pending=True).exists()


def guard(request):
    """The refusal for a private page's records on a device where that page is not open, else None. It runs before the
    business is chosen for the request, so it works the business out the same way. A new account opens nothing until
    its person has chosen their own password and lock PIN."""
    if not request.path.startswith(SETUP_PATHS) and setup_pending(request.device_session.user):
        return JsonResponse({'detail': 'Choose your own password and lock PIN first.', 'code': 'setup_required'}, status=403)
    page = page_of(request.path)
    if not page:
        return None
    from apps.tenancy.context import organization_context
    from apps.tenancy.middleware import resolve_membership
    membership = getattr(request, 'membership', None) or resolve_membership(request)
    with organization_context(membership.organization if membership else None):
        return _guard(request, page)


def _guard(request, page):
    device = request.device_session
    if not allowed(device.user, page):
        return JsonResponse({'detail': refusal_text(device.user, page), 'code': 'owner_only', 'page': page,
                             'protected': status(device)}, status=403, json_dumps_params={'default': str})
    if is_open(device, page) and page_pins(device.user).get(page):
        return None
    return JsonResponse({'detail': f'{PAGES[page][0]} is a private page. Enter its PIN to open it.',
                         'code': 'protected_locked', 'page': page, 'protected': status(device)},
                        status=403, json_dumps_params={'default': str})


def locked_device(request):
    return DeviceSession.objects.select_for_update().select_related('user').get(pk=request.auth.pk)


def blocked(device):
    if device.protected_blocked_until and device.protected_blocked_until > timezone.now():
        return Response({'detail': 'Too many wrong PINs. Wait a few minutes and try again.', 'code': 'blocked', 'protected': status(device)}, status=429)
    return None


def failed(device, page):
    device.protected_failures += 1
    left = max(0, TRIES - device.protected_failures)
    if not left:
        # A pause, never the password: the PIN stays the only way in. The owner can reset a forgotten one.
        device.protected_blocked_until = timezone.now() + BLOCK
        device.protected_failures = 0
    device.save(update_fields=['protected_failures', 'protected_blocked_until'])
    SessionAudit.objects.create(session=device, event='PROTECTED_FAILED')
    if left:
        detail = f'Wrong PIN. {left} {"try" if left == 1 else "tries"} left.'
    elif is_business_owner(device.user):
        detail = f'Wrong PIN {TRIES} times. Wait {BLOCK.seconds // 60} minutes, or reset the {PAGES[page][0]} PIN in Settings with your sign-in password.'
    else:
        detail = f'Wrong PIN {TRIES} times. Wait {BLOCK.seconds // 60} minutes, or ask the business owner to reset your {PAGES[page][0]} PIN.'
    return Response({'detail': detail, 'code': 'wrong_pin', 'protected': status(device)}, status=400)


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
    """Open a private page with its PIN, the only way in."""
    device = locked_device(request)
    refusal = blocked(device)
    if refusal:
        return refusal
    page, pin = request.data.get('page'), request.data.get('pin')
    if page not in PAGES:
        return Response({'detail': 'Choose a private page to open.'}, status=400)
    if not allowed(device.user, page):
        return Response({'detail': refusal_text(device.user, page), 'code': 'owner_only', 'protected': status(device)}, status=403)
    if request.data.get('password') is not None:
        return Response({'detail': f'{PAGES[page][0]} opens with its PIN only.', 'code': 'pin_only', 'protected': status(device)}, status=400)
    expected = page_pins(device.user).get(page)
    if not expected:
        detail = f'Set the {PAGES[page][0]} PIN first.' if is_business_owner(device.user) else f'Set your own {PAGES[page][0]} PIN first.'
        return Response({'detail': detail, 'code': 'pin_unset', 'protected': status(device)}, status=400)
    if not isinstance(pin, str) or not check_password(pin, expected.digest):
        return failed(device, page)
    return open_pages(device, [page], 'PROTECTED_UNLOCK')


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
    lock = lock_pin_of(user)
    known = page_pins(user)
    owner = is_business_owner(user)
    return {'pin': {'set': bool(lock), 'length': lock.length if lock else None, 'updated_at': lock.updated_at if lock else None},
            'is_owner': owner,
            'pages': {key: {'label': label, 'set': key in known, 'length': known[key].length if key in known else None,
                            'updated_at': known[key].updated_at if key in known else None, 'can_set': owner or key not in known}
                      for key, (label, _) in PAGES.items() if owner or allowed(user, key)}}


def _weak(pin):
    if not isinstance(pin, str) or not re.fullmatch(r'\d{4,6}', pin):
        return 'A PIN is 4 to 6 digits.'
    if len(set(pin)) == 1 or pin in '0123456789' or pin in '9876543210':
        return 'Choose a PIN harder to guess than repeated or running digits.'
    return None


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def lock_pin(request):
    """PINs. POST without ``page`` sets the person's own lock PIN; with ``page`` it sets the person's PIN for that private
    page: the owner sets or resets theirs, an employee sets theirs once (the owner resets it). Every change needs the
    sign-in password."""
    if request.method == 'GET':
        return Response(pin_settings(request.user))
    page = request.data.get('page') or ''
    if page and page not in PAGES:
        return Response({'detail': 'There is no such private page.'}, status=400)
    owner = is_business_owner(request.user)
    if page and not allowed(request.user, page):
        return Response({'detail': refusal_text(request.user, page), 'code': 'owner_only'}, status=403)
    if page and not owner and page in page_pins(request.user):
        return Response({'detail': f'Your {PAGES[page][0]} PIN is already set. Only the business owner can reset it: ask them, then set a new one.',
                         'code': 'owner_only'}, status=403)
    if not request.user.check_password(request.data.get('password') or ''):
        return Response({'detail': 'Your sign-in password is incorrect.', 'code': 'wrong_password'}, status=400)
    pin = request.data.get('pin')
    problem = _weak(pin)
    if problem:
        return Response({'detail': problem}, status=400)
    lock = lock_pin_of(request.user)
    if page:
        others = [other for key, other in page_pins(request.user).items() if key != page and check_password(pin, other.digest)]
        if others:
            return Response({'detail': f'Choose a PIN different from the {PAGES[others[0].page][0]} PIN: each private page has its own.'}, status=400)
        if lock and check_password(pin, lock.digest):
            return Response({'detail': 'Choose a PIN different from your lock PIN: a private page has its own.'}, status=400)
        PagePin.objects.update_or_create(page=page, user=None if owner else request.user,
                                         defaults={'digest': make_password(pin), 'length': len(pin), 'updated_by': request.user})
        # Devices already open on the page stay open until they lock; every new opening needs the new PIN.
    else:
        if any(check_password(pin, other.digest) for other in page_pins(request.user).values()):
            return Response({'detail': 'Choose a lock PIN different from your private pages\' PINs.'}, status=400)
        LockPin.objects.update_or_create(user=request.user, page='', defaults={'digest': make_password(pin), 'length': len(pin)})
    return Response(pin_settings(request.user))


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def first_setup(request):
    """A new (or reset) account's first sign-in: the person replaces the password the owner gave them with their own
    and chooses their lock PIN. This device stays signed in; any other is signed out."""
    from django.contrib.auth import password_validation
    from django.core.exceptions import ValidationError
    from apps.tenancy.models import Membership
    user = request.user
    if not setup_pending(user):
        return Response({'detail': 'Your account is already set up.'}, status=400)
    password, pin = request.data.get('new_password') or '', request.data.get('pin')
    if user.check_password(password):
        return Response({'detail': 'Choose a new password, not the one the business owner gave you.', 'field': 'new_password'}, status=400)
    try:
        password_validation.validate_password(password, user)
    except ValidationError as exc:
        return Response({'detail': ' '.join(exc.messages), 'field': 'new_password'}, status=400)
    problem = _weak(pin)
    if problem:
        return Response({'detail': problem, 'field': 'pin'}, status=400)
    user.set_password(password)
    user.save(update_fields=['password'])
    LockPin.objects.update_or_create(user=user, page='', defaults={'digest': make_password(pin), 'length': len(pin)})
    Membership.objects.filter(user=user, setup_pending=True).update(setup_pending=False)
    device = locked_device(request)
    device.password_fingerprint = user.get_session_auth_hash()
    device.save(update_fields=['password_fingerprint'])
    DeviceSession.objects.filter(user=user, revoked_at=None).exclude(pk=device.pk).update(revoked_at=timezone.now())
    SessionAudit.objects.create(session=device, event='FIRST_SETUP')
    from .device_api import payload
    return Response(payload(request, device))
