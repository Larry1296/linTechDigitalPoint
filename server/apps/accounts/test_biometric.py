"""Fingerprint or face unlock, with a software key standing in for the phone's own fingerprint or face check."""
import hashlib
import json
from datetime import timedelta

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.utils import timezone
from webauthn.helpers import bytes_to_base64url

from apps.accounts.models import BiometricKey, DeviceSession, SessionAudit
from apps.tenancy.tests.test_device_auth import login
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db
ORIGIN = 'http://localhost:5173'
RP_ID = 'localhost'


@pytest.fixture(autouse=True)
def isolate_throttle_cache():
    from django.core.cache import cache
    cache.clear()


class Phone:
    """A device whose fingerprint or face check always passes (flags UP and UV)."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = bytes(range(16)) + hashlib.sha256(str(id(self)).encode()).digest()[:16]
        self.count = 0

    def client_data(self, kind, challenge, origin=ORIGIN):
        return json.dumps({'type': kind, 'challenge': challenge, 'origin': origin}).encode()

    def register(self, options, origin=ORIGIN):
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
        auth = (hashlib.sha256(options['rp']['id'].encode()).digest() + bytes([0x45]) + (0).to_bytes(4, 'big')
                + bytes(16) + len(self.credential_id).to_bytes(2, 'big') + self.credential_id + cose)
        raw = bytes_to_base64url(self.credential_id)
        return {'id': raw, 'rawId': raw, 'type': 'public-key', 'response': {
            'clientDataJSON': bytes_to_base64url(self.client_data('webauthn.create', options['challenge'], origin)),
            'attestationObject': bytes_to_base64url(cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth}))}}

    def sign(self, options, flags=0x05):
        self.count += 1
        auth = hashlib.sha256(options['rpId'].encode()).digest() + bytes([flags]) + self.count.to_bytes(4, 'big')
        data = self.client_data('webauthn.get', options['challenge'])
        signature = self.key.sign(auth + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256()))
        raw = bytes_to_base64url(self.credential_id)
        return {'id': raw, 'rawId': raw, 'type': 'public-key', 'response': {
            'clientDataJSON': bytes_to_base64url(data), 'authenticatorData': bytes_to_base64url(auth),
            'signature': bytes_to_base64url(signature)}}


def turn_on(client, phone):
    start = client.post('/api/v1/auth/biometric/start/', {'password': 'Safe-pass-1848'}, format='json', HTTP_ORIGIN=ORIGIN)
    assert start.status_code == 200, start.content
    finish = client.post('/api/v1/auth/biometric/finish/', {'credential': phone.register(start.json()['options']), 'label': 'Android phone'},
                         format='json', HTTP_ORIGIN=ORIGIN)
    assert finish.status_code == 201, finish.content
    return finish.json()


def unlock_with(client, phone, **sign):
    options = client.post('/api/v1/auth/biometric/unlock/', format='json', HTTP_ORIGIN=ORIGIN)
    assert options.status_code == 200, options.content
    return client.post('/api/v1/auth/unlock/', {'biometric': phone.sign(options.json()['options'], **sign)}, format='json', HTTP_ORIGIN=ORIGIN)


def test_a_lock_the_person_made_opens_with_their_fingerprint_or_face(businesses):  # noqa: F811
    client, data = login(businesses[0])
    phone = Phone()
    assert client.post('/api/v1/auth/biometric/start/', {'password': 'wrong'}, format='json', HTTP_ORIGIN=ORIGIN).status_code == 400
    assert client.get('/api/v1/auth/session/').json()['session']['lock_biometric'] is False
    key = turn_on(client, phone)
    assert key['label'] == 'Android phone' and key['credential_id'] == bytes_to_base64url(phone.credential_id)
    assert client.get('/api/v1/auth/session/').json()['session']['lock_biometric'] is True
    session = DeviceSession.objects.get(pk=data['session']['id'])
    expires = session.expires_at
    assert client.post('/api/v1/auth/lock/').json()['session']['biometric'] is True
    response = unlock_with(client, phone)
    assert response.status_code == 200, response.content
    assert response.json()['session']['locked'] is False
    session.refresh_from_db()
    # Like the PIN it never lengthens the session, and each request is good once.
    assert session.expires_at == expires and session.biometric_challenge == ''
    assert SessionAudit.objects.filter(session=session, event='UNLOCK_BIOMETRIC').exists()
    assert BiometricKey.objects.get().last_used_at is not None


def test_a_wrong_or_reused_answer_is_refused_and_counts_as_a_try(businesses):  # noqa: F811
    client, data = login(businesses[0])
    phone = Phone()
    turn_on(client, phone)
    client.post('/api/v1/auth/lock/')
    options = client.post('/api/v1/auth/biometric/unlock/', format='json', HTTP_ORIGIN=ORIGIN).json()['options']
    answer = phone.sign(options, flags=0x01)  # the device did not check the fingerprint or face
    refused = client.post('/api/v1/auth/unlock/', {'biometric': answer}, format='json', HTTP_ORIGIN=ORIGIN)
    assert refused.status_code == 400 and refused.json()['code'] == 'wrong_biometric'
    good = phone.sign(options)
    # The request was used up by the refused try.
    assert client.post('/api/v1/auth/unlock/', {'biometric': good}, format='json', HTTP_ORIGIN=ORIGIN).status_code == 400
    stranger = Phone()
    assert unlock_with(client, stranger).status_code == 400
    assert DeviceSession.objects.get(pk=data['session']['id']).failed_unlocks == 3
    assert unlock_with(client, phone).status_code == 200


def test_the_session_end_and_other_sites_need_the_password(businesses):  # noqa: F811
    client, data = login(businesses[0])
    phone = Phone()
    turn_on(client, phone)
    assert client.post('/api/v1/auth/biometric/start/', {'password': 'Safe-pass-1848'}, format='json',
                       HTTP_ORIGIN='https://elsewhere.example').json()['code'] == 'biometric_unavailable'
    DeviceSession.objects.filter(pk=data['session']['id']).update(expires_at=timezone.now() + timedelta(minutes=5))
    state = client.get('/api/v1/auth/session/').json()['session']
    assert state['locked'] is True and state['biometric'] is False
    assert client.post('/api/v1/auth/biometric/unlock/', format='json', HTTP_ORIGIN=ORIGIN).json()['code'] == 'biometric_unavailable'


def test_removing_a_device_turns_it_off(businesses):  # noqa: F811
    client, _ = login(businesses[0])
    key = turn_on(client, Phone())
    assert [k['id'] for k in client.get('/api/v1/auth/biometric/').json()['keys']] == [key['id']]
    assert client.delete(f"/api/v1/auth/biometric/{key['id']}/").status_code == 204
    assert not BiometricKey.objects.exists()


def sign_in_with(phone, credential_id=None):
    from rest_framework.test import APIClient
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get('/api/v1/auth/csrf/').json()['csrfToken']
    start = client.post('/api/v1/auth/biometric/sign-in/start/', {'credential_id': credential_id or bytes_to_base64url(phone.credential_id)},
                        format='json', HTTP_ORIGIN=ORIGIN, HTTP_X_CSRFTOKEN=csrf)
    if start.status_code != 200:
        return client, start
    answer = phone.sign(start.json()['options'])
    return client, client.post('/api/v1/auth/biometric/sign-in/', {'credential': answer}, format='json', HTTP_ORIGIN=ORIGIN, HTTP_X_CSRFTOKEN=csrf)


def test_signing_in_with_the_fingerprint_or_face_starts_a_fresh_session(businesses):  # noqa: F811
    client, _ = login(businesses[0])
    phone = Phone()
    turn_on(client, phone)
    signed_in, response = sign_in_with(phone)
    assert response.status_code == 200, response.content
    data = response.json()
    assert data['authenticated'] is True and data['access_token'] and data['session']['locked'] is False
    session = DeviceSession.objects.get(pk=data['session']['id'])
    assert SessionAudit.objects.filter(session=session, event='LOGIN_BIOMETRIC').exists()
    assert (session.expires_at - timezone.now()).total_seconds() > 11 * 3600
    signed_in.credentials(HTTP_AUTHORIZATION='Bearer ' + data['access_token'])
    assert signed_in.get('/api/v1/auth/biometric/').status_code == 200


def test_sign_in_refuses_an_unknown_key_a_replayed_answer_and_a_removed_device(businesses):  # noqa: F811
    client, _ = login(businesses[0])
    phone = Phone()
    key = turn_on(client, phone)
    _, unknown = sign_in_with(Phone())
    assert unknown.status_code == 400 and unknown.json()['code'] == 'biometric_unknown'
    signed_in, first = sign_in_with(phone)
    assert first.status_code == 200
    # The same request signed again (a copied answer) is refused: each request is good once.
    from rest_framework.test import APIClient
    again = APIClient()
    start = again.post('/api/v1/auth/biometric/sign-in/start/', {'credential_id': key['credential_id']}, format='json', HTTP_ORIGIN=ORIGIN).json()['options']
    answer = phone.sign(start)
    assert again.post('/api/v1/auth/biometric/sign-in/', {'credential': answer}, format='json', HTTP_ORIGIN=ORIGIN).status_code == 200
    assert again.post('/api/v1/auth/biometric/sign-in/', {'credential': answer}, format='json', HTTP_ORIGIN=ORIGIN).json()['code'] == 'wrong_biometric'
    client.delete(f"/api/v1/auth/biometric/{key['id']}/")
    assert sign_in_with(phone)[1].json()['code'] == 'biometric_unknown'
