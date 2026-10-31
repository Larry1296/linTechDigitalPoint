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


@pytest.fixture
def employee(owner):
    from apps.tenancy.models import Organization
    user = User.objects.create_user('vault-manager', password=SIGN_IN)
    Membership.objects.create(user=user, organization=Organization.objects.get(owner=owner), role='MANAGER')
    return user


def test_each_private_page_opens_only_with_its_own_pin_which_the_owner_sets(owner):
    client = signed_in(owner)
    assert client.get('/api/v1/inventory/dashboard/').status_code == 200
    for path in [INVESTMENTS, MPESA, '/api/v1/mpesa/transactions/']:
        response = client.get(path)
        assert response.status_code == 403 and response.json()['code'] == 'protected_locked'
    # The dashboard nudges stay open: they name what is due, never an amount.
    assert client.get(INVESTMENTS + 'reminder/').status_code == 200
    assert client.get('/api/v1/mpesa/commission/due/').json().keys() == {'due_label'}

    assert unlock(client, 'mpesa', pin='4826').json()['code'] == 'pin_unset'
    assert set_pin(client, '4826', page='mpesa', password='wrong').status_code == 400
    assert set_pin(client, '1111', page='mpesa').status_code == 400 and set_pin(client, '1234', page='mpesa').status_code == 400
    pages = set_pin(client, '4826', page='mpesa').json()['pages']
    assert pages['mpesa']['set'] is True and pages['mpesa']['length'] == 4 and pages['investments']['set'] is False
    # Each page has a different PIN.
    same = set_pin(client, '4826', page='investments')
    assert same.status_code == 400 and 'different from the M-Pesa PIN' in same.json()['detail']
    set_pin(client, '573910', page='investments')
    set_pin(client, '2468')  # the owner's own workspace lock PIN opens no private page
    assert unlock(client, 'investments', pin='2468').status_code == 400
    response = unlock(client, 'mpesa', pin='4826')
    assert response.status_code == 200
    assert {key: page['unlocked'] for key, page in response.json()['protected']['pages'].items()} == {'mpesa': True, 'investments': False}
    assert client.get(MPESA).status_code == 200 and client.get(INVESTMENTS).status_code == 403
    assert unlock(client, 'investments', pin='573910').status_code == 200 and client.get(INVESTMENTS).status_code == 200
    # The sign-in password never opens a private page.
    client.post('/api/v1/auth/protected/lock/')
    assert unlock(client, 'mpesa', password=SIGN_IN).json()['code'] == 'pin_only'


def test_investments_are_the_owners_alone_and_staff_open_m_pesa_with_the_pin_the_owner_gave(owner, employee):
    boss = signed_in(owner)
    set_pin(boss, '4826', page='mpesa')
    set_pin(boss, '573910', page='investments')
    staff = signed_in(employee)
    refused = staff.get(INVESTMENTS)
    assert refused.status_code == 403 and refused.json()['code'] in ('owner_only', 'protected_locked') or refused.status_code == 403
    assert unlock(staff, 'investments', pin='573910').json()['code'] == 'owner_only'  # not even with the PIN
    assert staff.get(INVESTMENTS).status_code == 403
    assert 'investments' not in staff.get('/api/v1/auth/lock-pin/').json()['pages']
    assert staff.get('/api/v1/auth/protected/').json()['protected']['pages']['investments']['allowed'] is False
    # Staff cannot set or reset a private page's PIN, nor use their password to get in.
    assert set_pin(staff, '9753', page='mpesa').status_code == 403
    assert unlock(staff, 'mpesa', password=SIGN_IN).json()['code'] == 'pin_only'
    assert unlock(staff, 'mpesa', pin='4826').status_code == 200 and staff.get(MPESA).status_code == 200
    # Their own lock PIN is still theirs to set.
    assert set_pin(staff, '9753').status_code == 200


def test_five_wrong_pins_wait_a_few_minutes_and_the_owner_resets_a_forgotten_pin(owner, employee):
    boss = signed_in(owner)
    set_pin(boss, '4826', page='mpesa')
    staff = signed_in(employee)
    for left in [4, 3, 2, 1]:
        assert unlock(staff, 'mpesa', pin='0000').json()['detail'] == f'Wrong PIN. {left} {"try" if left == 1 else "tries"} left.'
    last = unlock(staff, 'mpesa', pin='0000').json()
    assert 'ask the business owner to reset the M-Pesa PIN' in last['detail']
    assert unlock(staff, 'mpesa', pin='4826').status_code == 429  # waiting, even with the right PIN
    # The owner resets it with their own sign-in password; the old PIN no longer opens it.
    assert set_pin(boss, '8642', page='mpesa').status_code == 200
    from apps.accounts.models import DeviceSession
    DeviceSession.objects.update(protected_blocked_until=None)
    assert unlock(staff, 'mpesa', pin='4826').status_code == 400
    assert unlock(staff, 'mpesa', pin='8642').status_code == 200


def test_another_device_locking_now_and_a_locked_workspace_close_them(owner):
    first = signed_in(owner)
    set_pin(first, '2468')
    set_pin(first, '4826', page='mpesa')
    set_pin(first, '573910', page='investments')
    unlock(first, 'mpesa', pin='4826')
    second = signed_in(owner)
    assert second.get(INVESTMENTS).status_code == 403
    assert unlock(second, 'investments', pin='573910').status_code == 200
    second.post('/api/v1/auth/protected/lock/')
    assert second.get(INVESTMENTS).status_code == 403 and second.get(MPESA).status_code == 403
    assert first.get(MPESA).status_code == 200
    first.post('/api/v1/auth/lock/')
    response = first.post('/api/v1/auth/unlock/', {'pin': '2468'}, format='json')
    assert response.status_code == 200
    first.credentials(HTTP_AUTHORIZATION='Bearer ' + response.json()['access_token'])
    assert first.get(MPESA).status_code == 403


def test_the_owner_keeps_an_employee_out_of_the_pages_they_choose(owner, employee):
    from apps.tenancy.models import Membership
    boss = signed_in(owner)
    set_pin(boss, '4826', page='mpesa')
    staff_row = Membership.objects.get(user=employee, role='MANAGER')
    listed = boss.get('/api/v1/tenancy/staff/').json()
    assert {page['key'] for page in listed['pages']} >= {'loans', 'money', 'profit'}
    assert boss.patch(f'/api/v1/tenancy/staff/{staff_row.pk}/', {'hidden_pages': ['nowhere']}, format='json').status_code == 400
    changed = boss.patch(f'/api/v1/tenancy/staff/{staff_row.pk}/', {'hidden_pages': ['mpesa', 'loans']}, format='json')
    assert changed.status_code == 200 and changed.json()['hidden_pages'] == ['loans', 'mpesa']
    staff = signed_in(employee)
    permissions = set(staff.get('/api/v1/auth/me/').json()['permissions'])
    assert not any(p.startswith('mpesa.') for p in permissions) and 'accounting.view_loan' not in permissions
    assert staff.get('/api/v1/accounting/loans/').status_code == 403
    refused = unlock(staff, 'mpesa', pin='4826')
    assert refused.status_code == 403 and refused.json()['detail'] == 'The business owner has not given you M-Pesa.'
    assert staff.get(MPESA).status_code == 403
    # Only the owner chooses; giving the page back opens it again with its PIN.
    assert staff.patch(f'/api/v1/tenancy/staff/{staff_row.pk}/', {'hidden_pages': []}, format='json').status_code == 403
    boss.patch(f'/api/v1/tenancy/staff/{staff_row.pk}/', {'hidden_pages': []}, format='json')
    assert unlock(staff, 'mpesa', pin='4826').status_code == 200
