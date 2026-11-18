"""Signed-out visitors behind Cloudflare each get their own rate limit, and the sign-in security token is never limited."""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_limits():
    cache.clear()
    yield
    cache.clear()


def test_the_security_token_is_never_rate_limited():
    client = APIClient()
    for _ in range(130):  # more than the 100 an hour signed-out visitors may make
        assert client.get("/api/v1/auth/csrf/", HTTP_CF_CONNECTING_IP="41.90.1.1").status_code == 200


def test_signing_in_is_limited_per_visitor_not_for_everyone():
    client = APIClient()
    wrong = {"username": "nobody@example.test", "password": "wrong"}
    for _ in range(10):
        client.post("/api/v1/auth/login/", wrong, format="json", HTTP_CF_CONNECTING_IP="41.90.1.1")
    assert client.post("/api/v1/auth/login/", wrong, format="json", HTTP_CF_CONNECTING_IP="41.90.1.1").status_code == 429
    other = client.post("/api/v1/auth/login/", wrong, format="json", HTTP_CF_CONNECTING_IP="105.160.2.2")
    assert other.status_code != 429  # someone else, from another address, can still sign in
