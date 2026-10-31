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
    # The owner opens the shift; the employee cannot open one.
    assert jane.get('/api/v1/mpesa/dashboard/').json()['session'] is None
    assert jane.post('/api/v1/mpesa/sessions/', {'outlet': rows[0]['id'], 'opening_cash': '5000', 'opening_float': '20000'}, format='json').status_code == 403
    opened = boss.post('/api/v1/mpesa/sessions/', {'outlet': rows[0]['id'], 'opening_cash': '5000', 'opening_float': '20000'}, format='json')
    assert opened.status_code == 201, opened.content
    shift = opened.json()['id']
    # One shift for the whole business: no second one, even on another outlet.
    other = boss.post('/api/v1/mpesa/outlets/', {'display_name': 'Second line', 'agent_reference': '654321'}, format='json').json()
    second = boss.post('/api/v1/mpesa/sessions/', {'outlet': other['id'], 'opening_cash': '0', 'opening_float': '0'}, format='json')
    assert second.status_code == 400 and 'already open' in str(second.json())
    # The employee carries on with exactly that shift, without seeing its money.
    desk = jane.get('/api/v1/mpesa/dashboard/').json()
    assert desk['employee'] is True and desk['session']['id'] == shift and 'opening_cash' not in desk['session']
    assert not {'cash', 'float', 'in_operation', 'commission', 'commission_month', 'deposits'} & set(desk)
    assert all(set(source) == {'value', 'label'} for source in desk['sources'])
    deposit = jane.post('/api/v1/mpesa/transactions/', {'session': shift, 'transaction_type': 'CUSTOMER_DEPOSIT', 'amount': '500',
                                                      'customer_phone': '0712345678', 'idempotency_key': 'jane-1'}, format='json')
    assert deposit.status_code == 201, deposit.content
    listed = jane.get('/api/v1/mpesa/transactions/').json()
    assert [row['id'] for row in listed] == [deposit.json()['id']] and not any('commission' in key for key in listed[0])
    assert jane.get('/api/v1/inventory/dashboard/work/').json()['mpesa'] == {'shift_open': True, 'transactions': 1}
    for path in ['/api/v1/mpesa/analysis/', '/api/v1/mpesa/commission/', '/api/v1/mpesa/sessions/past/', '/api/v1/mpesa/reconciliation/',
                 f"/api/v1/mpesa/transactions/commission-advice/?session={shift}&type=CUSTOMER_DEPOSIT&amount=500"]:
        assert jane.get(path).status_code == 403, path
    # They close it at the end of the day with a blind count; the owner sees any difference with what was expected.
    closed = jane.post(f"/api/v1/mpesa/sessions/{shift}/reconcile/", {'actual_cash': '5400', 'actual_float': '19500'}, format='json')
    assert closed.status_code == 201 and closed.json()['closed'] is True and 'cash_variance' not in closed.json()
    from apps.tenancy.context import organization_context
    with organization_context(Organization.objects.get()):
        record = MpesaReconciliation.objects.get()
    assert record.cash_variance == -100 and record.float_variance == 0 and 'for the owner to check' in record.reason
    assert jane.get('/api/v1/mpesa/dashboard/').json()['session'] is None


def test_the_owner_can_give_an_employee_investments_too(boss):
    boss.post('/api/v1/auth/lock-pin/', {'password': OWNER_PASSWORD, 'pin': '573910', 'page': 'investments'}, format='json')
    pages = [page['key'] for page in boss.get('/api/v1/tenancy/staff/').json()['work_pages']]
    assert 'investments' in pages
    member = add_employee(boss, ['sales']).json()
    jane = signed_in('jane', GIVEN)
    set_up(jane)
    assert jane.post('/api/v1/auth/protected/unlock/', {'page': 'investments', 'pin': '573910'}, format='json').json()['code'] == 'owner_only'
    assert not any('investment' in key for key in jane.get('/api/v1/auth/me/').json()['permissions'])
    boss.patch(f"/api/v1/tenancy/staff/{member['id']}/", {'open_pages': ['sales', 'investments']}, format='json')
    assert {'accounting.view_investment', 'accounting.add_investmentmovement'} <= set(jane.get('/api/v1/auth/me/').json()['permissions'])
    # Their own Investments PIN, not the owner's.
    assert jane.post('/api/v1/auth/protected/unlock/', {'page': 'investments', 'pin': '573910'}, format='json').json()['code'] == 'pin_unset'
    jane.post('/api/v1/auth/lock-pin/', {'password': OWN, 'pin': '6183', 'page': 'investments'}, format='json')
    assert jane.post('/api/v1/auth/protected/unlock/', {'page': 'investments', 'pin': '6183'}, format='json').status_code == 200
    assert jane.get('/api/v1/accounting/investments/').status_code == 200


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
