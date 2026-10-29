import time

import pytest
from django.contrib.auth.models import User
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.device_auth import COOKIE, token_hash
from apps.accounts.models import DeviceSession, RefreshCredential
from django.utils import timezone
from datetime import timedelta
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def locked_client(settings):
    settings.DEVICE_IDLE_SECONDS = 900  # an idle lock is off by default; a deployment may still turn it on
    cache.clear()
    user = User.objects.create_user('lock-owner', password='Strong-pass-1296')
    org = Organization.objects.create(name='Locked business', slug='locked-business', owner=user)
    Membership.objects.create(user=user, organization=org, role='OWNER')
    OrganizationSubscription.objects.create(organization=org, status='ACTIVE')
    client = APIClient()
    response = client.post('/api/v1/auth/login/', {'credential': user.username, 'password': 'Strong-pass-1296'}, format='json')
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'])
    return client, user, org


def device(client):
    return RefreshCredential.objects.select_related('session').get(token_hash=token_hash(client.cookies[COOKIE].value)).session


def expire(client):
    DeviceSession.objects.filter(pk=device(client).pk).update(last_user_activity_at=timezone.now()-timedelta(seconds=settings.DEVICE_IDLE_SECONDS + 1))


def test_polling_does_not_extend_access_but_explicit_activity_does(locked_client):
    client, user, org = locked_client
    original = device(client).last_user_activity_at
    for path in ['/api/v1/auth/me/', '/api/v1/auth/session/', '/api/v1/inventory/dashboard/']:
        assert client.get(path).status_code == 200
        assert device(client).last_user_activity_at == original
    DeviceSession.objects.filter(pk=device(client).pk).update(last_user_activity_at=timezone.now()-timedelta(seconds=100))
    response = client.post('/api/v1/auth/refresh/', {}, format='json')
    assert response.status_code == 200
    assert response.data['session']['expires_at'] < time.time() + settings.DEVICE_IDLE_SECONDS + 5
    response = client.post('/api/v1/auth/activity/', {}, format='json')
    assert response.status_code == 200
    assert response.data['session']['expires_at'] > time.time() + settings.DEVICE_IDLE_SECONDS - 5


def test_expired_access_blocks_reads_writes_refresh_and_private_media(locked_client):
    client, user, org = locked_client
    expire(client)
    for method, path in [('get', 'inventory/dashboard/'), ('post', 'inventory/receive/'),
                         ('post', 'tenancy/select/'), ('post', 'auth/refresh/'), ('post', 'auth/password/change/')]:
        response = getattr(client, method)('/api/v1/' + path)
        assert response.status_code == 423, (path, response.content)
        assert response.json()['code'] == 'session_locked'
        assert response['Cache-Control'] == 'private, no-store'
    assert client.get('/media/private.jpg').status_code == 423
    identity = client.get('/api/v1/auth/me/').json()
    assert identity['session']['locked'] is True
    assert identity['username'] == user.username
    assert 'organization' not in identity and 'permissions' not in identity
    assert client.post('/api/v1/auth/logout/').status_code == 204
    assert client.get('/api/v1/auth/session/').json()['authenticated'] is False


def test_password_unlock_rotates_token_and_keeps_business_selection(locked_client):
    client, user, org = locked_client
    original_token = client.cookies[COOKIE].value
    expire(client)
    assert client.post('/api/v1/auth/unlock/', {'password': 'wrong'}, format='json').status_code == 400
    assert client.get('/api/v1/inventory/dashboard/').status_code == 423
    User.objects.create_user('other', password='Other-pass-1296')
    assert client.post('/api/v1/auth/unlock/', {'credential': 'other', 'password': 'Other-pass-1296'}, format='json').status_code == 400
    response = client.post('/api/v1/auth/unlock/', {'password': 'Strong-pass-1296'}, format='json')
    assert response.status_code == 200, response.content
    assert response.data['id'] == user.pk
    assert response.data['organization']['id'] == org.pk
    assert response.data['session']['locked'] is False
    assert client.cookies[COOKIE].value != original_token
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'])
    assert client.get('/api/v1/inventory/dashboard/').status_code == 200


def test_unlock_is_rate_limited_even_for_authenticated_locked_users(locked_client):
    client, user, org = locked_client
    expire(client)
    for _ in range(5):
        assert client.post('/api/v1/auth/unlock/', {'password': 'wrong'}, format='json').status_code == 400
    assert client.post('/api/v1/auth/unlock/', {'password': 'wrong'}, format='json').status_code == 429


def test_unlock_requires_csrf_and_never_restores_a_disabled_account(locked_client):
    client, user, org = locked_client
    expire(client)
    protected = APIClient(enforce_csrf_checks=True)
    protected.cookies = client.cookies
    assert protected.post('/api/v1/auth/unlock/', {'password': 'Strong-pass-1296'}, format='json').status_code == 403
    csrf = protected.get('/api/v1/auth/csrf/').json()['csrfToken']
    user.is_active = False
    user.save(update_fields=['is_active'])
    response = protected.post('/api/v1/auth/unlock/', {'credential': user.username, 'password': 'Strong-pass-1296'}, format='json', HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 401


def test_expired_cookie_requires_full_login(locked_client):
    client, user, org = locked_client
    client.cookies.clear()
    response = client.post('/api/v1/auth/unlock/', {'credential': user.username, 'password': 'Strong-pass-1296'}, format='json')
    assert response.status_code == 401
