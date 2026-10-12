from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import ProtectedPagesPassword
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = [pytest.mark.django_db, pytest.mark.protected_pages]
SIGN_IN = 'Strong-pass-1296'
INVESTMENTS = '/api/v1/accounting/investments/'


@pytest.fixture
def owner():
    cache.clear()
    user = User.objects.create_user('vault-owner', password=SIGN_IN)
    org = Organization.objects.create(name='Vault business', slug='vault-business', owner=user)
    Membership.objects.create(user=user, organization=org, role='OWNER')
    OrganizationSubscription.objects.create(organization=org, status='ACTIVE')
    return user


def signed_in(user):
    client = APIClient()
    response = client.post('/api/v1/auth/login/', {'credential': user.username, 'password': SIGN_IN}, format='json')
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.json()['access_token'])
    return client


def set_password(client, proof, new):
    return client.post('/api/v1/auth/protected/password/', {'proof': proof, 'new_password': new}, format='json')


def test_protected_pages_need_their_own_password_but_the_dashboard_does_not(owner):
    client = signed_in(owner)
    assert client.get('/api/v1/inventory/dashboard/').status_code == 200
    for path in [INVESTMENTS, '/api/v1/mpesa/dashboard/', '/api/v1/mpesa/transactions/']:
        response = client.get(path)
        assert response.status_code == 403 and response.json()['code'] == 'protected_locked'
    # The dashboard nudges stay open: they name what is due, never an amount.
    assert client.get(INVESTMENTS + 'reminder/').status_code == 200
    assert client.get('/api/v1/mpesa/commission/due/').json().keys() == {'due_label'}

    assert client.get('/api/v1/auth/protected/').json()['protected']['has_password'] is False
    assert set_password(client, 'wrong-one', 'vault-2026').status_code == 400
    assert set_password(client, SIGN_IN, SIGN_IN).json()['detail'] == 'Use a password different from your sign-in password.'
    assert set_password(client, SIGN_IN, 'short').status_code == 400
    response = set_password(client, SIGN_IN, 'vault-2026')
    assert response.status_code == 200 and response.json()['protected']['unlocked'] is True
    assert client.get(INVESTMENTS).status_code == 200


def test_a_new_device_and_a_relocked_workspace_ask_again(owner):
    first = signed_in(owner)
    set_password(first, SIGN_IN, 'vault-2026')
    second = signed_in(owner)
    assert second.get(INVESTMENTS).status_code == 403
    assert second.post('/api/v1/auth/protected/unlock/', {'password': SIGN_IN}, format='json').status_code == 400
    assert second.post('/api/v1/auth/protected/unlock/', {'password': 'vault-2026'}, format='json').status_code == 200
    assert second.get(INVESTMENTS).status_code == 200
    second.post('/api/v1/auth/protected/lock/')
    assert second.get(INVESTMENTS).status_code == 403


def test_after_a_week_a_new_password_is_needed_and_none_can_repeat(owner):
    client = signed_in(owner)
    set_password(client, SIGN_IN, 'vault-one')
    ProtectedPagesPassword.objects.filter(user=owner).update(created_at=timezone.now() - timedelta(days=7, minutes=1))
    assert client.get(INVESTMENTS).status_code == 403
    response = client.post('/api/v1/auth/protected/unlock/', {'password': 'vault-one'}, format='json')
    assert response.status_code == 400 and response.json()['code'] == 'protected_expired'
    assert set_password(client, 'vault-one', 'vault-one').json()['detail'].startswith('You have used this password before')
    assert set_password(client, 'vault-one', 'vault-two').status_code == 200
    assert client.get(INVESTMENTS).status_code == 200
    # Forgotten: the sign-in password sets a new one, but still never an old one.
    assert set_password(client, SIGN_IN, 'vault-one').status_code == 400
    assert set_password(client, SIGN_IN, 'vault-three').status_code == 200
    assert ProtectedPagesPassword.objects.filter(user=owner).count() == 3


def test_five_wrong_passwords_wait_five_minutes(owner):
    client = signed_in(owner)
    set_password(client, SIGN_IN, 'vault-2026')
    client.post('/api/v1/auth/protected/lock/')
    for _ in range(5):
        assert client.post('/api/v1/auth/protected/unlock/', {'password': 'guess-123'}, format='json').status_code == 400
    assert client.post('/api/v1/auth/protected/unlock/', {'password': 'vault-2026'}, format='json').status_code == 429
