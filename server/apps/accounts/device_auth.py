"""API-only JWT authentication; Django admin sessions remain independent."""
import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4
import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.authentication import BaseAuthentication
from .models import DeviceSession, RefreshCredential, SessionAudit

COOKIE = 'lintech_refresh'
COOKIE_PATH = '/api/v1/auth/'
COOKIE_ENDPOINTS = {'me', 'session', 'refresh', 'unlock', 'lock', 'logout'}
PUBLIC_ENDPOINTS = {'csrf', 'login', 'password/reset', 'password/reset/confirm'}


def token_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def state(device):
    now = timezone.now()
    deadline = device.last_user_activity_at + timedelta(seconds=settings.DEVICE_IDLE_SECONDS)
    return {'id':str(device.pk), 'expires_at':deadline.timestamp(), 'server_time':now.timestamp(),
        'absolute_expires_at':device.expires_at.timestamp(), 'idle_timeout':settings.DEVICE_IDLE_SECONDS,
        'warning_seconds':0, 'locked':bool(device.locked_at or now >= deadline)}


def valid(device):
    return (device and device.user.is_active and not device.revoked_at and device.expires_at > timezone.now()
        and constant_time_compare(device.password_fingerprint, device.user.get_session_auth_hash()))


def access_token(device):
    now = timezone.now()
    return jwt.encode({'sub':str(device.user_id), 'sid':str(device.pk), 'ver':device.version,
        'jti':str(uuid4()), 'iss':settings.JWT_ISSUER, 'aud':settings.JWT_AUDIENCE,
        'iat':now, 'nbf':now, 'exp':min(now+timedelta(seconds=settings.JWT_ACCESS_SECONDS),device.expires_at)},
        settings.JWT_SIGNING_KEY, algorithm='HS256', headers={'kid':settings.JWT_KEY_ID})


def issue_credential(device):
    raw = secrets.token_urlsafe(48)
    RefreshCredential.objects.create(session=device, token_hash=token_hash(raw))
    return raw


def set_cookie(response, raw, device):
    response.set_cookie(COOKIE, raw, max_age=max(0,int((device.expires_at-timezone.now()).total_seconds())),
        httponly=True, secure=settings.COOKIE_SECURE, samesite='Strict', path=COOKIE_PATH)
    return response


@transaction.atomic
def create_device(user):
    now = timezone.now()
    device = DeviceSession.objects.create(user=user, password_fingerprint=user.get_session_auth_hash(),
        last_user_activity_at=now, expires_at=now+timedelta(seconds=settings.DEVICE_ABSOLUTE_SECONDS))
    raw = issue_credential(device)
    SessionAudit.objects.create(session=device,event='LOGIN')
    return device, raw


def cookie_credential(request):
    raw = request.COOKIES.get(COOKIE, '')
    if not raw or len(raw) > 200:
        return None
    return RefreshCredential.objects.select_related('session__user').filter(token_hash=token_hash(raw)).first()


class DeviceJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        device = getattr(request._request, 'device_session', None)
        if device and valid(device):
            return device.user, device
        return None
    def authenticate_header(self, request):
        return 'Bearer'


class DeviceAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response=get_response
    def __call__(self, request):
        if not request.path.startswith(('/api/v1/', '/media/')):
            return self.get_response(request)
        request.user=AnonymousUser()
        request.device_session=None
        endpoint=request.path.removeprefix('/api/v1/auth/').strip('/') if request.path.startswith('/api/v1/auth/') else None
        error=None
        if endpoint in COOKIE_ENDPOINTS:
            credential=cookie_credential(request)
            if credential and valid(credential.session):
                # Refresh handles consumed credentials itself to audit reuse.
                if not credential.consumed_at or endpoint == 'refresh':
                    request.device_session=credential.session
                    request.user=credential.session.user
        elif endpoint not in PUBLIC_ENDPOINTS:
            header=request.headers.get('Authorization','')
            if header.startswith('Bearer '):
                try:
                    token=header[7:]
                    if len(token)>4096 or jwt.get_unverified_header(token).get('kid') != settings.JWT_KEY_ID:
                        raise ValueError
                    claims=jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=['HS256'], issuer=settings.JWT_ISSUER,
                        audience=settings.JWT_AUDIENCE, options={'require':['sub','sid','ver','jti','exp','iat','nbf','iss','aud']})
                    device=DeviceSession.objects.select_related('user').filter(pk=claims['sid'],user_id=claims['sub'],version=claims['ver']).first()
                    if not valid(device):
                        raise ValueError
                    request.device_session=device; request.user=device.user
                    if state(device)['locked']:
                        DeviceSession.objects.filter(pk=device.pk,locked_at=None).update(locked_at=timezone.now())
                        error=JsonResponse({'detail':'Your workspace is locked. Enter your password.', 'code':'session_locked','session':state(device)},status=423)
                except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
                    error=JsonResponse({'detail':'Sign in again or refresh your session.','code':'token_expired'},status=401)
        if endpoint in COOKIE_ENDPOINTS and endpoint not in {'session','me','unlock','lock','logout','refresh'}:
            error=JsonResponse({'detail':'Authentication required.'},status=401)
        response=error or self.get_response(request)
        response['Cache-Control']='private, no-store'
        return response
