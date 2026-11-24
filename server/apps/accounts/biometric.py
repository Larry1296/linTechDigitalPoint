"""Unlocking the workspace with a fingerprint, face or eye.

A person turns it on for one phone or computer in Settings, with their sign-in password. The device makes a WebAuthn
key that it opens only after its own fingerprint, face or eye check (whichever it has), and the server keeps only the
public half (BiometricKey). On the lock screen the device signs a fresh request from the server with that key.

On the lock screen, like the lock PIN, it opens only a lock the person made, while the session's 12 hours last and
before too many wrong tries; it never lengthens that session. On the sign-in page (and on a lock screen it cannot open)
it signs in as the password does, starting a fresh 12-hour session. It never opens a private page (those need their own
PIN). Anyone whose fingerprint or face the device itself accepts can use it, so it belongs on a device only its owner opens.
"""
import ipaddress
import json
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement)

from .models import BiometricKey, DeviceSession, SessionAudit

CHALLENGE_SECONDS = 300
KEYS_PER_PERSON = 10


class BiometricThrottle(UserRateThrottle):
    rate = '10/minute'
    scope = 'biometric'


def origin_of(request):
    """The page's origin and the WebAuthn site name (its host), when the page is one of ours; else (None, None).
    Browsers refuse an IP address as the site name, so those pages cannot use a fingerprint or face."""
    origin = request.headers.get('Origin') or ''
    if origin not in {*settings.CSRF_TRUSTED_ORIGINS, settings.FRONTEND_URL}:
        return None, None
    host = urlparse(origin).hostname or ''
    try:
        ipaddress.ip_address(host)
        return None, None
    except ValueError:
        return (origin, host) if host else (None, None)


def keys_of(user, rp_id=None):
    keys = BiometricKey.objects.filter(user=user)
    return keys.filter(rp_id=rp_id) if rp_id else keys


def has_keys(user):
    return BiometricKey.objects.filter(user=user).exists()


def _give_challenge(device, challenge):
    DeviceSession.objects.filter(pk=device.pk).update(biometric_challenge=bytes_to_base64url(challenge),
                                                      biometric_challenge_at=timezone.now())


def _take_challenge(device):
    """The challenge last given to this device, used up: each one answers a single try."""
    device = DeviceSession.objects.select_for_update().get(pk=device.pk)
    raw, at = device.biometric_challenge, device.biometric_challenge_at
    DeviceSession.objects.filter(pk=device.pk).update(biometric_challenge='', biometric_challenge_at=None)
    if not raw or not at or timezone.now() - at > timedelta(seconds=CHALLENGE_SECONDS):
        return None
    return base64url_to_bytes(raw)


def key_data(key):
    return {'id': key.pk, 'credential_id': key.credential_id, 'label': key.label,
            'created_at': key.created_at, 'last_used_at': key.last_used_at}


def _no_site():
    return Response({'detail': 'Fingerprint and face unlock work only on the LinTech web address, not this one.',
                     'code': 'biometric_unavailable'}, status=400)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def biometric_keys(request):
    return Response({'keys': [key_data(key) for key in keys_of(request.user)]})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([BiometricThrottle])
def biometric_start(request):
    """Turning on fingerprint or face unlock for this device, step one: the sign-in password, then the request the
    device answers by making its key."""
    if not request.user.check_password(request.data.get('password') or ''):
        return Response({'detail': 'Your sign-in password is incorrect.', 'code': 'wrong_password'}, status=400)
    _origin, rp_id = origin_of(request)
    if not rp_id:
        return _no_site()
    keys = keys_of(request.user, rp_id)
    if keys.count() >= KEYS_PER_PERSON:
        return Response({'detail': f'You have {KEYS_PER_PERSON} devices with fingerprint or face unlock. Remove one first.'}, status=400)
    user = request.user
    options = generate_registration_options(
        rp_id=rp_id, rp_name='LinTech', user_id=str(user.pk).encode(), user_name=user.username,
        user_display_name=user.get_full_name() or user.username, timeout=CHALLENGE_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id)) for key in keys])
    _give_challenge(request.auth, options.challenge)
    return Response({'options': json.loads(options_to_json(options))})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([BiometricThrottle])
@transaction.atomic
def biometric_finish(request):
    """Step two: the key the device made, checked against the request it answered, kept for this person."""
    origin, rp_id = origin_of(request)
    if not rp_id:
        return _no_site()
    challenge = _take_challenge(request.auth)
    if not challenge:
        return Response({'detail': 'That took too long. Try again.', 'code': 'biometric_expired'}, status=400)
    try:
        verified = verify_registration_response(credential=request.data.get('credential'), expected_challenge=challenge,
                                                expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
    except (WebAuthnException, ValueError, TypeError, KeyError):
        return Response({'detail': 'This device could not turn on fingerprint or face unlock. Try again.'}, status=400)
    credential_id = bytes_to_base64url(verified.credential_id)
    if BiometricKey.objects.filter(credential_id=credential_id).exists():
        return Response({'detail': 'Fingerprint or face unlock is already on for this device.'}, status=400)
    label = str(request.data.get('label') or 'This device').strip()[:80] or 'This device'
    key = BiometricKey.objects.create(user=request.user, credential_id=credential_id, public_key=verified.credential_public_key,
                                      sign_count=verified.sign_count, rp_id=rp_id, label=label)
    SessionAudit.objects.create(session=request.auth, event='BIOMETRIC_ADDED')
    return Response(key_data(key), status=201)


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def biometric_remove(request, pk):
    deleted, _ = keys_of(request.user).filter(pk=pk).delete()
    if not deleted:
        return Response({'detail': 'That device is not on your list.'}, status=404)
    SessionAudit.objects.create(session=request.auth, event='BIOMETRIC_REMOVED')
    return Response(status=204)


def unlock_options(request, device):
    """The request the lock screen's device signs, or None when no key of this person's works on this page."""
    _origin, rp_id = origin_of(request)
    keys = list(keys_of(device.user, rp_id)) if rp_id else []
    if not keys:
        return None
    options = generate_authentication_options(
        rp_id=rp_id, timeout=CHALLENGE_SECONDS * 1000, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id)) for key in keys])
    _give_challenge(device, options.challenge)
    return json.loads(options_to_json(options))


def check_unlock(request, device, credential):
    """Whether ``credential`` is this person's device's fresh answer, checked by the device's fingerprint, face or eye."""
    origin, rp_id = origin_of(request)
    challenge = _take_challenge(device)
    if not (rp_id and challenge and isinstance(credential, dict)):
        return False
    key = keys_of(device.user, rp_id).filter(credential_id=str(credential.get('id') or '')).first()
    return bool(key) and _verified(key, credential, challenge, origin, rp_id)


def _verified(key, credential, challenge, origin, rp_id):
    try:
        verified = verify_authentication_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
                                                  expected_origin=origin, credential_public_key=bytes(key.public_key),
                                                  credential_current_sign_count=key.sign_count, require_user_verification=True)
    except (WebAuthnException, ValueError, TypeError, KeyError):
        return False
    key.sign_count = verified.new_sign_count
    key.last_used_at = timezone.now()
    key.save(update_fields=['sign_count', 'last_used_at'])
    return True


class SignInThrottle(AnonRateThrottle):
    rate = '20/minute'
    scope = 'biometric_sign_in'


def _signing_key(request, credential_id):
    _origin, rp_id = origin_of(request)
    if not (rp_id and isinstance(credential_id, str) and credential_id):
        return None
    return BiometricKey.objects.select_related('user').filter(credential_id=credential_id, rp_id=rp_id, user__is_active=True).first()


def _forgotten():
    return Response({'detail': 'Fingerprint or face sign-in is no longer on for this device. Sign in with your password.',
                     'code': 'biometric_unknown'}, status=400)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([SignInThrottle])
@csrf_protect
def biometric_sign_in_start(request):
    """Signing in with a fingerprint or face, step one: the request the device signs with the key it made here."""
    key = _signing_key(request, request.data.get('credential_id'))
    if not key:
        return _forgotten()
    options = generate_authentication_options(
        rp_id=key.rp_id, timeout=CHALLENGE_SECONDS * 1000, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id))])
    BiometricKey.objects.filter(pk=key.pk).update(sign_in_challenge=bytes_to_base64url(options.challenge), sign_in_challenge_at=timezone.now())
    return Response({'options': json.loads(options_to_json(options))})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([SignInThrottle])
@csrf_protect
@transaction.atomic
def biometric_sign_in(request):
    """Step two: the signed request. Checked, it signs in as the password does: a new device session of 12 hours."""
    credential = request.data.get('credential')
    found = _signing_key(request, credential.get('id') if isinstance(credential, dict) else None)
    if not found:
        return _forgotten()
    key = BiometricKey.objects.select_for_update().select_related('user').get(pk=found.pk)
    raw, at = key.sign_in_challenge, key.sign_in_challenge_at
    BiometricKey.objects.filter(pk=key.pk).update(sign_in_challenge='', sign_in_challenge_at=None)
    origin, rp_id = origin_of(request)
    if not raw or not at or timezone.now() - at > timedelta(seconds=CHALLENGE_SECONDS) \
            or not _verified(key, credential, base64url_to_bytes(raw), origin, rp_id):
        return Response({'detail': 'Fingerprint or face not accepted. Try again or sign in with your password.',
                         'code': 'wrong_biometric'}, status=400)
    from .device_api import payload
    from .device_auth import create_device, set_cookie
    device, cookie = create_device(key.user)
    SessionAudit.objects.create(session=device, event='LOGIN_BIOMETRIC')
    request.session.pop('organization_id', None)
    request.session.pop('branch_id', None)
    return set_cookie(Response(payload(request, device, True)), cookie, device)
