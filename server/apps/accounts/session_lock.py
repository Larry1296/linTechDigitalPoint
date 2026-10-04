"""Idle access expiry for the opaque HttpOnly session token.

The longer-lived session identifies the locked account; it does not grant
business access once the idle deadline has passed. Reads never renew access.
"""
import time
from django.conf import settings
from django.http import JsonResponse

DEADLINE_KEY = 'workspace_access_expires_at'
PUBLIC_PATHS = {
    '/api/v1/auth/csrf/', '/api/v1/auth/login/', '/api/v1/auth/logout/',
    '/api/v1/auth/me/', '/api/v1/auth/session/', '/api/v1/auth/unlock/',
    '/api/v1/auth/password/reset/', '/api/v1/auth/password/reset/confirm/',
    '/api/v1/tenancy/platform/',
}


def renew_access(request):
    request.session[DEADLINE_KEY] = time.time() + settings.SESSION_IDLE_TIMEOUT
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    return access_state(request)


def access_state(request):
    now = time.time()
    deadline = request.session.get(DEADLINE_KEY)
    # Existing authenticated sessions migrate once, without an interruption.
    if deadline is None:
        deadline = now + settings.SESSION_IDLE_TIMEOUT
        request.session[DEADLINE_KEY] = deadline
    return {'expires_at': deadline, 'server_time': now,
            'idle_timeout': settings.SESSION_IDLE_TIMEOUT,
            'warning_seconds': 60, 'locked': now >= deadline}


class IdleSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(('/api/v1/', '/media/', '/platform-admin/')) and request.user.is_authenticated:
            state = access_state(request)
            if state['locked'] and request.path not in PUBLIC_PATHS and not request.path.startswith('/api/v1/tenancy/public/'):
                response = JsonResponse({'detail': 'Your workspace is locked. Enter your password to unlock.',
                                         'code': 'session_locked', 'session': state}, status=423)
                response['Cache-Control'] = 'private, no-store'
                return response
        response = self.get_response(request)
        if request.path.startswith('/api/v1/auth/'):
            response['Cache-Control'] = 'private, no-store'
        return response
