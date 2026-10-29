import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = [pytest.mark.django_db, pytest.mark.protected_pages]
SIGN_IN = 'Strong-pass-1296'
INVESTMENTS = '/api/v1/accounting/investments/'
MPESA = '/api/v1/mpesa/dashboard/'


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


def set_pin(client, pin, page='', password=SIGN_IN):
    return client.post('/api/v1/auth/lock-pin/', {'password': password, 'pin': pin, 'page': page}, format='json')


def unlock(client, page, **body):
    return client.post('/api/v1/auth/protected/unlock/', {'page': page, **body}, format='json')


def test_private_pages_open_with_the_lock_pin_but_the_dashboard_needs_none(owner):
    client = signed_in(owner)
    assert client.get('/api/v1/inventory/dashboard/').status_code == 200
    for path in [INVESTMENTS, MPESA, '/api/v1/mpesa/transactions/']:
        response = client.get(path)
        assert response.status_code == 403 and response.json()['code'] == 'protected_locked'
    # The dashboard nudges stay open: they name what is due, never an amount.
    assert client.get(INVESTMENTS + 'reminder/').status_code == 200
    assert client.get('/api/v1/mpesa/commission/due/').json().keys() == {'due_label'}

    assert unlock(client, 'mpesa', pin='4826').json()['code'] == 'pin_unset'
    assert set_pin(client, '4826', password='wrong').status_code == 400
    assert set_pin(client, '1111').status_code == 400 and set_pin(client, '1234').status_code == 400
    assert set_pin(client, '48a6').status_code == 400
    pin = set_pin(client, '4826').json()['pin']
    assert pin['set'] is True and pin['length'] == 4
    # One PIN shared by every private page opens them together.
    response = unlock(client, 'mpesa', pin='4826')
    assert response.status_code == 200
    assert {key: page['unlocked'] for key, page in response.json()['protected']['pages'].items()} == {'mpesa': True, 'investments': True}
    assert client.get(INVESTMENTS).status_code == 200 and client.get(MPESA).status_code == 200


def test_a_page_with_its_own_pin_opens_alone(owner):
    client = signed_in(owner)
    assert set_pin(client, '5739', page='investments').json()['code'] == 'pin_unset'
    set_pin(client, '4826')
    pages = set_pin(client, '5739', page='investments').json()['pages']
    assert pages['investments'] == {'label': 'Investments', 'own_pin': True, 'length': 4}
    assert unlock(client, 'investments', pin='4826').status_code == 400  # the lock PIN no longer opens it
    assert unlock(client, 'mpesa', pin='4826').status_code == 200
    assert client.get(MPESA).status_code == 200 and client.get(INVESTMENTS).status_code == 403
    assert unlock(client, 'investments', pin='5739').status_code == 200
    assert client.get(INVESTMENTS).status_code == 200
    # Back to sharing the lock PIN.
    client.post('/api/v1/auth/protected/lock/')
    assert client.delete('/api/v1/auth/lock-pin/', {'password': SIGN_IN, 'page': 'investments'}, format='json').json()['pages']['investments']['own_pin'] is False
    assert unlock(client, 'investments', pin='4826').status_code == 200


def test_another_device_locking_now_and_a_locked_workspace_close_them(owner):
    first = signed_in(owner)
    set_pin(first, '4826')
    unlock(first, 'mpesa', pin='4826')
    second = signed_in(owner)
    assert second.get(INVESTMENTS).status_code == 403
    assert unlock(second, 'investments', pin='4826').status_code == 200
    second.post('/api/v1/auth/protected/lock/')
    assert second.get(INVESTMENTS).status_code == 403 and second.get(MPESA).status_code == 403
    assert first.get(MPESA).status_code == 200
    first.post('/api/v1/auth/lock/')
    response = first.post('/api/v1/auth/unlock/', {'pin': '4826'}, format='json')
    assert response.status_code == 200
    first.credentials(HTTP_AUTHORIZATION='Bearer ' + response.json()['access_token'])
    assert first.get(MPESA).status_code == 403


def test_five_wrong_pins_need_the_sign_in_password(owner):
    client = signed_in(owner)
    set_pin(client, '4826')
    for left in [4, 3, 2, 1]:
        assert unlock(client, 'mpesa', pin='0000').json()['detail'] == f'Wrong PIN. {left} {"try" if left == 1 else "tries"} left.'
    assert unlock(client, 'mpesa', pin='0000').json()['protected']['needs_password'] is True
    assert unlock(client, 'mpesa', pin='4826').json()['code'] == 'password_required'
    assert unlock(client, 'mpesa', password='wrong').status_code == 400
    assert unlock(client, 'mpesa', password=SIGN_IN).status_code == 429  # a wrong password waits a minute
    from apps.accounts.models import DeviceSession
    DeviceSession.objects.update(protected_blocked_until=None)
    response = unlock(client, 'mpesa', password=SIGN_IN)
    assert response.status_code == 200 and response.json()['protected']['needs_password'] is False
    assert client.get(INVESTMENTS).status_code == 200
