import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = [pytest.mark.django_db, pytest.mark.protected_pages]
OWNER_PASSWORD = 'Strong-pass-1296'
GIVEN = 'Given-by-boss-77'
OWN = 'Chosen-by-me-4821'


def signed_in(username, password):
    client = APIClient()
    response = client.post('/api/v1/auth/login/', {'credential': username, 'password': password}, format='json')
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.json()['access_token'])
    return client


@pytest.fixture
def boss():
    cache.clear()
    user = User.objects.create_user('shop-owner', password=OWNER_PASSWORD)
    org = Organization.objects.create(name='Corner shop', slug='corner-shop', owner=user,
                                      enabled_modules=['pos', 'inventory', 'mpesa', 'investments', 'expenses'])
    Membership.objects.create(user=user, organization=org, role='OWNER')
    OrganizationSubscription.objects.create(organization=org, status='ACTIVE')
    from apps.core.models import Store
    from apps.tenancy.context import organization_context
    with organization_context(org):
        Store.objects.create(name='Corner shop')
    return signed_in('shop-owner', OWNER_PASSWORD)


def add_employee(boss, pages):
    return boss.post('/api/v1/tenancy/staff/', {'username': 'jane', 'first_name': 'Jane', 'password': GIVEN, 'open_pages': pages}, format='json')


def set_up(client):
    return client.post('/api/v1/auth/setup/', {'new_password': OWN, 'pin': '4826'}, format='json')


def test_the_owner_adds_an_employee_who_chooses_their_own_password_and_pin_before_anything_opens(boss):
    refused = add_employee(boss, ['sales', 'loans'])
    assert refused.status_code == 400 and "the owner's" in str(refused.json())
    added = add_employee(boss, ['sales', 'mpesa'])
    assert added.status_code == 201
    member = added.json()
    assert member['role'] == 'EMPLOYEE' and member['open_pages'] == ['mpesa', 'sales'] and member['setup_pending'] is True

    jane = signed_in('jane', GIVEN)
    me = jane.get('/api/v1/auth/me/').json()
    assert me['setup_required'] is True and me['is_owner'] is False and me['open_pages'] == ['mpesa', 'sales']
    blocked = jane.get('/api/v1/inventory/dashboard/work/')
    assert blocked.status_code == 403 and blocked.json()['code'] == 'setup_required'
    same = jane.post('/api/v1/auth/setup/', {'new_password': GIVEN, 'pin': '4826'}, format='json')
    assert same.status_code == 400 and same.json()['field'] == 'new_password'
    assert jane.post('/api/v1/auth/setup/', {'new_password': OWN, 'pin': '1111'}, format='json').json()['field'] == 'pin'
    done = set_up(jane)
    assert done.status_code == 200 and done.json()['setup_required'] is False
    # This device stays signed in; the given password no longer works.
    assert jane.get('/api/v1/inventory/dashboard/work/').status_code == 200
    assert APIClient().post('/api/v1/auth/login/', {'credential': 'jane', 'password': GIVEN}, format='json').status_code == 400
    signed_in('jane', OWN)


def test_an_employee_gets_only_the_work_pages_they_were_given_never_the_owners_side(boss):
    add_employee(boss, ['sales', 'mpesa'])
    jane = signed_in('jane', GIVEN)
    set_up(jane)
    granted = set(jane.get('/api/v1/auth/me/').json()['permissions'])
    assert {'commerce.add_sale', 'catalog.view_product', 'accounts.add_customerprofile', 'mpesa.add_mpesatransaction', 'mpesa.add_mpesareconciliation'} <= granted
    assert not any(key.startswith(('accounting.', 'chama.')) for key in granted)
    assert not any('commission' in key or key.split('.')[1].startswith('delete_') for key in granted)
    assert 'mpesa.view_mpesareconciliation' not in granted and 'catalog.add_product' not in granted
    # The business's dashboard, money, profit and the owner's pages are refused; their own dashboard opens.
    assert jane.get('/api/v1/inventory/dashboard/').json()['code'] == 'owner_only'
    for path in ['/api/v1/accounting/loans/', '/api/v1/accounting/expenses/', '/api/v1/tenancy/billing/', '/api/v1/tenancy/staff/']:
        assert jane.get(path).status_code == 403, path
    work = jane.get('/api/v1/inventory/dashboard/work/').json()
    assert [page['key'] for page in work['pages']] == ['sales', 'mpesa'] and work['sales'] == {'mine_today': 0}
    assert work['mpesa'] == {'shift_open': False, 'transactions': 0} and 'revenue' not in str(work)


def test_on_the_agent_desk_an_employee_records_and_counts_blind_without_seeing_money_or_commission(boss):
    from apps.mpesa.models import MpesaReconciliation
    boss.post('/api/v1/auth/lock-pin/', {'password': OWNER_PASSWORD, 'pin': '573910', 'page': 'mpesa'}, format='json')
    boss.post('/api/v1/auth/protected/unlock/', {'page': 'mpesa', 'pin': '573910'}, format='json')
    outlet = boss.post('/api/v1/mpesa/outlets/', {'display_name': 'Main line', 'agent_reference': '123456'}, format='json')
    assert outlet.status_code == 201, outlet.content
    add_employee(boss, ['mpesa'])
    jane = signed_in('jane', GIVEN)
    set_up(jane)
    # Their own M-Pesa PIN, set by them the first time.
    assert jane.post('/api/v1/auth/protected/unlock/', {'page': 'mpesa', 'pin': '573910'}, format='json').json()['code'] == 'pin_unset'
    assert jane.post('/api/v1/auth/lock-pin/', {'password': OWN, 'pin': '4826', 'page': 'mpesa'}, format='json').status_code == 400  # their lock PIN
    assert jane.post('/api/v1/auth/lock-pin/', {'password': OWN, 'pin': '7295', 'page': 'mpesa'}, format='json').status_code == 200
    assert jane.post('/api/v1/auth/protected/unlock/', {'page': 'mpesa', 'pin': '7295'}, format='json').status_code == 200

    outlets = jane.get('/api/v1/mpesa/outlets/').json()
    rows = outlets['results'] if isinstance(outlets, dict) else outlets
    assert set(rows[0]['money_in_operation']) == {'updated_on', 'due', 'open_session'}
    assert jane.post('/api/v1/mpesa/outlets/', {'display_name': 'Mine'}, format='json').status_code == 403
    opened = jane.post('/api/v1/mpesa/sessions/', {'outlet': rows[0]['id'], 'opening_cash': '5000', 'opening_float': '20000'}, format='json')
    assert opened.status_code == 201, opened.content
    assert 'opening_cash' not in opened.json() and 'current_float' not in opened.json()
    desk = jane.get('/api/v1/mpesa/dashboard/').json()
    assert desk['employee'] is True and desk['session']['id'] == opened.json()['id']
    assert not {'cash', 'float', 'in_operation', 'commission', 'commission_month', 'deposits'} & set(desk)
    assert all(set(source) == {'value', 'label'} for source in desk['sources'])
    for path in ['/api/v1/mpesa/analysis/', '/api/v1/mpesa/commission/', '/api/v1/mpesa/sessions/past/', '/api/v1/mpesa/reconciliation/',
                 f"/api/v1/mpesa/transactions/commission-advice/?session={opened.json()['id']}&type=CUSTOMER_DEPOSIT&amount=500"]:
        assert jane.get(path).status_code == 403, path
    # A blind count: a difference needs no reason from them; the owner sees it with what was expected.
    closed = jane.post(f"/api/v1/mpesa/sessions/{opened.json()['id']}/reconcile/", {'actual_cash': '4900', 'actual_float': '20000'}, format='json')
    assert closed.status_code == 201 and closed.json()['closed'] is True and 'cash_variance' not in closed.json()
    from apps.tenancy.context import organization_context
    with organization_context(Organization.objects.get()):
        record = MpesaReconciliation.objects.get()
    assert record.cash_variance == -100 and 'for the owner to check' in record.reason
    # Opening again, the difference from the last close is recorded, not asked about.
    again = jane.post('/api/v1/mpesa/sessions/', {'outlet': rows[0]['id'], 'opening_cash': '4000', 'opening_float': '20000'}, format='json')
    assert again.status_code == 201, again.content


def test_the_owner_resets_a_forgotten_sign_in_and_the_employee_sets_it_up_again(boss):
    member = add_employee(boss, ['sales']).json()
    jane = signed_in('jane', GIVEN)
    set_up(jane)
    reset = boss.post(f"/api/v1/tenancy/staff/{member['id']}/reset/", {'what': 'sign_in', 'password': 'Fresh-start-9031'}, format='json')
    assert reset.status_code == 200 and reset.json()['setup_pending'] is True and reset.json()['lock_pin_set'] is False
    assert jane.get('/api/v1/auth/me/').json()['authenticated'] is False or jane.get('/api/v1/inventory/dashboard/work/').status_code == 401
    again = signed_in('jane', 'Fresh-start-9031')
    assert again.get('/api/v1/inventory/dashboard/work/').json()['code'] == 'setup_required'
    assert set_up(again).status_code == 200
    # The owner keeps choosing their pages; employees cannot be given the owner's side.
    assert boss.patch(f"/api/v1/tenancy/staff/{member['id']}/", {'open_pages': ['profit']}, format='json').status_code == 400
    changed = boss.patch(f"/api/v1/tenancy/staff/{member['id']}/", {'open_pages': ['sales', 'products']}, format='json')
    assert changed.json()['open_pages'] == ['products', 'sales']
    assert 'catalog.add_product' in again.get('/api/v1/auth/me/').json()['permissions']
