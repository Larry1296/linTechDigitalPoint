from datetime import timedelta
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import DeviceSession, RefreshCredential, SessionAudit
from apps.accounts.device_auth import COOKIE
from apps.tenancy.tests.test_isolation import businesses

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def isolate_throttle_cache():
    from django.core.cache import cache
    cache.clear()



def login(business):
    client=APIClient(enforce_csrf_checks=True)
    csrf=client.get('/api/v1/auth/csrf/').json()['csrfToken']
    response=client.post('/api/v1/auth/login/',{'credential':business['user'].username,'password':'Safe-pass-1848'},format='json',HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code==200,response.content
    data=response.json()
    client.credentials(HTTP_AUTHORIZATION='Bearer '+data['access_token'],HTTP_X_CSRFTOKEN=csrf)
    return client,data


def test_a_lock_denies_copied_unexpired_token_and_unlocks(businesses):
    client,data=login(businesses[0])
    session=DeviceSession.objects.get(pk=data['session']['id'])
    assert client.get('/api/v1/catalog/categories/').status_code==200
    DeviceSession.objects.filter(pk=session.pk).update(locked_at=timezone.now())
    assert client.get('/api/v1/catalog/categories/').status_code==423
    assert client.post('/api/v1/auth/refresh/').status_code==423
    assert client.post('/api/v1/auth/activity/').status_code==423
    assert client.post('/api/v1/auth/unlock/',{'password':'wrong'},format='json').status_code==400
    response=client.post('/api/v1/auth/unlock/',{'password':'Safe-pass-1848'},format='json')
    assert response.status_code==200,response.content
    # Unlock rotates the device version; a copied pre-lock access token stays invalid.
    assert client.get('/api/v1/catalog/categories/').status_code==401
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'])
    assert client.get('/api/v1/catalog/categories/').status_code==200
    assert SessionAudit.objects.filter(session=session,event='UNLOCK_FAILED').count()==1


def test_rotation_is_not_activity_and_replay_revokes_family(businesses):
    client,data=login(businesses[0])
    original=client.cookies[COOKIE].value
    session=DeviceSession.objects.get(pk=data['session']['id'])
    before=session.last_user_activity_at
    response=client.post('/api/v1/auth/refresh/')
    assert response.status_code==200,response.content
    assert client.cookies[COOKIE].value != original
    session.refresh_from_db();assert session.last_user_activity_at==before
    second=client.cookies[COOKIE].value
    assert client.post('/api/v1/auth/refresh/').status_code==200  # the second credential is used: the first is now a copy
    client.cookies[COOKIE]=original
    RefreshCredential.objects.filter(session=session,consumed_at__isnull=False).update(consumed_at=timezone.now()-timedelta(seconds=4))
    assert client.post('/api/v1/auth/refresh/').status_code==401
    assert second
    session.refresh_from_db();assert session.revoked_at is not None
    assert client.get('/api/v1/catalog/categories/').status_code==401


def test_absolute_expiry_and_missing_cookie_require_full_login(businesses):
    client,data=login(businesses[0])
    DeviceSession.objects.filter(pk=data['session']['id']).update(expires_at=timezone.now()-timedelta(seconds=1))
    assert client.post('/api/v1/auth/unlock/',{'password':'Safe-pass-1848'},format='json').status_code==401
    assert client.get('/api/v1/catalog/categories/').status_code==401
    client.cookies.pop(COOKIE,None)
    assert client.post('/api/v1/auth/unlock/',{'password':'Safe-pass-1848','credential':businesses[0]['user'].username},format='json').status_code==401


@pytest.mark.parametrize('endpoint',['refresh','lock','unlock','logout'])
def test_cookie_actions_require_csrf(businesses,endpoint):
    client,data=login(businesses[0])
    client.credentials(HTTP_AUTHORIZATION='Bearer '+data['access_token'])
    assert client.post(f'/api/v1/auth/{endpoint}/',{},format='json').status_code==403


def test_admin_cookie_alone_cannot_authenticate_api(businesses):
    client=APIClient()
    # Real Django session login, deliberately not the test helper force_login.
    assert client.login(username=businesses[0]['user'].username,password='Safe-pass-1848')
    assert client.get('/api/v1/catalog/categories/').status_code in {401,403}


def test_password_change_and_membership_removal_take_effect_immediately(businesses):
    from apps.tenancy.models import Membership
    client,data=login(businesses[0])
    Membership.objects.filter(user=businesses[0]['user']).update(status='SUSPENDED')
    assert client.get('/api/v1/catalog/categories/').status_code==403
    user=businesses[0]['user'];user.set_password('new-password');user.save()
    assert client.get('/api/v1/catalog/categories/').status_code==401


@pytest.mark.django_db(transaction=True)
def test_simultaneous_refresh_issues_one_successor(businesses):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    client, data = login(businesses[0])
    cookie = client.cookies[COOKIE].value
    csrf_cookie = client.cookies['csrftoken'].value
    csrf = client._credentials['HTTP_X_CSRFTOKEN']
    barrier = Barrier(2)

    def rotate():
        close_old_connections()
        try:
            tab = APIClient(enforce_csrf_checks=True)
            tab.cookies[COOKIE] = cookie
            tab.cookies['csrftoken'] = csrf_cookie
            barrier.wait(timeout=10)
            result = tab.post('/api/v1/auth/refresh/', HTTP_X_CSRFTOKEN=csrf)
            return result.status_code, result.json()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert sorted(status for status, _ in results) == [200, 409]
    rejected = next(body for status, body in results if status == 409)
    assert 'access_token' not in rejected
    assert RefreshCredential.objects.filter(session_id=data['session']['id'], consumed_at=None).count() == 1
    assert DeviceSession.objects.get(pk=data['session']['id']).revoked_at is None


@pytest.mark.parametrize('path', [
    'inventory/dashboard/', 'inventory/receipts/', 'commerce/pos/catalog/',
    'commerce/sales/', 'accounting/ledger/reports/', 'accounting/expenses/',
    'locations/shelves/', 'tenancy/branches/',
])
def test_locked_token_denied_across_business_resources(businesses, path):
    client, data = login(businesses[0])
    DeviceSession.objects.filter(pk=data['session']['id']).update(locked_at=timezone.now())
    assert client.get('/api/v1/'+path).status_code == 423


def test_an_idle_workspace_stays_open_for_the_whole_session(businesses):
    client,data=login(businesses[0])
    DeviceSession.objects.filter(pk=data['session']['id']).update(last_user_activity_at=timezone.now()-timedelta(hours=11))
    assert client.get('/api/v1/catalog/categories/').status_code==200
    response=client.post('/api/v1/auth/refresh/')
    assert response.status_code==200 and response.json()['session']['locked'] is False
    assert response.json()['session']['expires_at'] > timezone.now().timestamp()+settings.DEVICE_ABSOLUTE_SECONDS-700


def set_pin(client, pin='4826'):
    return client.post('/api/v1/auth/lock-pin/',{'password':'Safe-pass-1848','pin':pin},format='json')


def test_a_lock_the_person_made_opens_with_their_pin(businesses):
    client,data=login(businesses[0])
    assert client.post('/api/v1/auth/lock-pin/',{'password':'wrong','pin':'4826'},format='json').status_code==400
    assert set_pin(client,'1111').status_code==400
    assert set_pin(client,'12a4').status_code==400
    assert set_pin(client).json()['pin']['length']==4
    session=DeviceSession.objects.get(pk=data['session']['id'])
    expires=session.expires_at
    locked=client.post('/api/v1/auth/lock/')
    assert locked.status_code==200 and locked.json()['session']['pin_length']==4
    assert client.get('/api/v1/auth/me/').json()['session']['pin_length']==4
    wrong=client.post('/api/v1/auth/unlock/',{'pin':'0000'},format='json')
    assert wrong.status_code==400 and wrong.json()['detail']=='Wrong PIN. 4 tries left.'
    response=client.post('/api/v1/auth/unlock/',{'pin':'4826'},format='json')
    assert response.status_code==200,response.content
    assert response.json()['session']['locked'] is False
    session.refresh_from_db()
    # A PIN opens the lock but never lengthens the session: only the password does.
    assert session.expires_at==expires and session.failed_unlocks==0
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'],HTTP_X_CSRFTOKEN=client._credentials['HTTP_X_CSRFTOKEN'])
    assert client.get('/api/v1/catalog/categories/').status_code==200


def test_too_many_wrong_pins_or_the_session_end_need_the_password(businesses):
    client,data=login(businesses[0])
    set_pin(client)
    client.post('/api/v1/auth/lock/')
    for _ in range(5):
        assert client.post('/api/v1/auth/unlock/',{'pin':'0000'},format='json').status_code==400
    refused=client.post('/api/v1/auth/unlock/',{'pin':'4826'},format='json')
    assert refused.status_code==400 and refused.json()['code']=='password_required'
    assert refused.json()['session']['pin_length'] is None
    assert client.post('/api/v1/auth/unlock/',{'password':'Safe-pass-1848'},format='json').status_code==200
    # Near the session's end the workspace locks by itself, and only the password (which starts it afresh) opens it.
    DeviceSession.objects.filter(pk=data['session']['id']).update(expires_at=timezone.now()+timedelta(minutes=5))
    state=client.get('/api/v1/auth/session/').json()['session']
    assert state['locked'] is True and state['pin_length'] is None
    assert client.post('/api/v1/auth/unlock/',{'pin':'4826'},format='json').json()['code']=='password_required'


def test_without_a_pin_a_lock_opens_with_the_password(businesses):
    client,data=login(businesses[0])
    assert client.get('/api/v1/auth/lock-pin/').json()['pin']['set'] is False
    assert client.post('/api/v1/auth/lock/').json()['session']['pin_length'] is None
    assert client.post('/api/v1/auth/unlock/',{'pin':'4826'},format='json').json()['code']=='password_required'


def test_a_renewal_whose_reply_was_lost_keeps_the_session(businesses):
    client,data=login(businesses[0])
    original=client.cookies[COOKIE].value
    assert client.post('/api/v1/auth/refresh/').status_code==200
    # The reply never arrived: the browser still holds the credential before it.
    client.cookies[COOKIE]=original
    assert client.post('/api/v1/auth/refresh/').status_code==409  # at the same moment: another tab's renewal
    RefreshCredential.objects.filter(consumed_at__isnull=False).update(consumed_at=timezone.now()-timedelta(seconds=4))
    response=client.post('/api/v1/auth/refresh/')
    assert response.status_code==200,response.content
    assert DeviceSession.objects.get(pk=data['session']['id']).revoked_at is None
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'],HTTP_X_CSRFTOKEN=client._credentials['HTTP_X_CSRFTOKEN'])
    assert client.get('/api/v1/catalog/categories/').status_code==200
    assert client.post('/api/v1/auth/refresh/').status_code==200
