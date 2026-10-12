"""Legacy domain regressions run inside an explicit migrated-business fixture.

The tenancy suite intentionally opts out and provisions memberships explicitly.
No production authentication or tenant fallback is enabled by this fixture.
"""
import pytest

@pytest.fixture(autouse=True)
def legacy_business_context(request, monkeypatch):
    if '/tenancy/' in str(request.fspath):
        yield
        return
    if not (request.node.get_closest_marker('django_db') or 'db' in request.fixturenames or 'transactional_db' in request.fixturenames):
        yield
        return
    request.getfixturevalue('db')
    from django.contrib.auth.models import User
    from django.db.models.signals import post_save, m2m_changed
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Organization, Membership, OrganizationSubscription
    organization, _ = Organization.objects.get_or_create(slug='lintech-digital-point', defaults={'name':'linTech Digital Point'})
    OrganizationSubscription.objects.get_or_create(organization=organization, defaults={'status':'ACTIVE'})

    def sync_user(sender, instance, **kwargs):
        if not isinstance(instance, User):
            return
        Membership.objects.update_or_create(user=instance, organization=organization, defaults={
            'role':'OWNER' if instance.is_superuser else 'CUSTOM',
            'status':'ACTIVE' if instance.is_staff and instance.is_active else 'SUSPENDED',
            'permissions':sorted(instance.get_all_permissions()),
        })

    def sync_permissions(sender, instance, action, **kwargs):
        if action.startswith('post_') and isinstance(instance, User):
            for key in ['_perm_cache','_user_perm_cache','_group_perm_cache']:
                instance.__dict__.pop(key, None)
            sync_user(sender,instance)

    def authenticate_session(client, user=None, token=None):
        if user is None:
            client.logout()
        else:
            sync_user(User, user)
            client.force_login(user)

    post_save.connect(sync_user, sender=User, weak=False)
    m2m_changed.connect(sync_permissions, sender=User.groups.through, weak=False)
    m2m_changed.connect(sync_permissions, sender=User.user_permissions.through, weak=False)
    monkeypatch.setattr(APIClient,'force_authenticate',authenticate_session)
    try:
        with organization_context(organization):
            yield
    finally:
        post_save.disconnect(sync_user, sender=User)
        m2m_changed.disconnect(sync_permissions, sender=User.groups.through)
        m2m_changed.disconnect(sync_permissions, sender=User.user_permissions.through)

@pytest.fixture(autouse=True)
def protected_pages_open(request, monkeypatch, settings):
    """Tests of M-Pesa and investments run as if the protected pages password was entered; tests marked
    ``protected_pages`` check that password itself."""
    settings.PROTECTED_PASSWORD_ITERATIONS = 1000
    if not request.node.get_closest_marker('protected_pages'):
        monkeypatch.setattr('apps.accounts.protected_pages.guard', lambda request: None)


@pytest.fixture(autouse=True)
def fast_test_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def no_machine_specific_addresses(settings):
    """Tests behave the same on every machine and in CI: a developer's .env (its public web address, the M-Pesa
    callback address) never changes what they expect. A test that needs one sets it itself."""
    settings.PUBLIC_APP_URL = ""
    settings.MPESA_CALLBACK_BASE_URL = ""


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Each test starts with no requests counted: the login and registration limits (a few a minute) are kept in the
    cache, and would otherwise trip in whichever test happens to run after others that logged in."""
    from django.core.cache import cache
    cache.clear()


@pytest.fixture(autouse=True)
def api_test_device_login(monkeypatch):
    """Model the browser's device credentials when legacy API fixtures force-login.

    Django's Client/admin sessions are unchanged; production API auth never falls
    back to them. Security contract tests call real login endpoints themselves.
    """
    from rest_framework.test import APIClient
    original = APIClient.force_login
    def force_device(client, user, backend=None):
        original(client, user, backend=backend)
        from apps.accounts.device_auth import create_device, access_token, COOKIE
        device, raw = create_device(user)
        client.cookies[COOKIE] = raw
        client.credentials(HTTP_AUTHORIZATION='Bearer '+access_token(device))
    monkeypatch.setattr(APIClient, 'force_login', force_device)
