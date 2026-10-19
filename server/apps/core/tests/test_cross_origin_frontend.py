"""The web app served as its own static site (https://dukaflow.co.ke) calling the API on https://api.dukaflow.co.ke."""
import pytest
from django.test import override_settings

FRONTEND = "https://dukaflow.co.ke"
pytestmark = pytest.mark.django_db


@override_settings(CORS_ALLOWED_ORIGINS=[FRONTEND, "https://www.dukaflow.co.ke"])
def test_the_frontend_origins_may_call_the_api_with_credentials_and_business_headers(client):
    preflight = client.options("/api/v1/auth/login/", HTTP_ORIGIN=FRONTEND, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                               HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken,authorization,x-organization-id,x-branch-id")
    assert preflight["Access-Control-Allow-Origin"] == FRONTEND
    assert preflight["Access-Control-Allow-Credentials"] == "true"
    allowed = preflight["Access-Control-Allow-Headers"].lower()
    assert all(h in allowed for h in ("x-csrftoken", "authorization", "x-organization-id", "x-branch-id"))
    csrf = client.get("/api/v1/auth/csrf/", HTTP_ORIGIN="https://www.dukaflow.co.ke")
    assert csrf["Access-Control-Allow-Origin"] == "https://www.dukaflow.co.ke"


@override_settings(CORS_ALLOWED_ORIGINS=[FRONTEND])
def test_any_other_origin_gets_no_cors_permission(client):
    response = client.get("/api/v1/auth/csrf/", HTTP_ORIGIN="https://evil.example")
    assert "Access-Control-Allow-Origin" not in response


@override_settings(CORS_ALLOWED_ORIGINS=[FRONTEND], CSRF_TRUSTED_ORIGINS=[FRONTEND, "https://api.dukaflow.co.ke"],
                   ALLOWED_HOSTS=["api.dukaflow.co.ke"])
def test_csrf_protection_still_applies_to_the_frontend(client):
    from django.test import Client
    strict = Client(enforce_csrf_checks=True)
    https = {"HTTP_HOST": "api.dukaflow.co.ke", "secure": True}
    token = strict.get("/api/v1/auth/csrf/", **https).json()["csrfToken"]
    refused = strict.post("/api/v1/auth/login/", {"username": "x", "password": "y"}, content_type="application/json",
                          HTTP_ORIGIN=FRONTEND, **https)
    assert refused.status_code == 403
    accepted = strict.post("/api/v1/auth/login/", {"username": "x", "password": "y"}, content_type="application/json",
                           HTTP_ORIGIN=FRONTEND, HTTP_X_CSRFTOKEN=token, **https)
    assert accepted.status_code in (400, 401)  # the wrong password, not a CSRF refusal
    foreign = strict.post("/api/v1/auth/login/", {"username": "x", "password": "y"}, content_type="application/json",
                          HTTP_ORIGIN="https://evil.example", HTTP_X_CSRFTOKEN=token, **https)
    assert foreign.status_code == 403


@override_settings(PUBLIC_APP_URL=FRONTEND, PUBLIC_API_URL="https://api.dukaflow.co.ke/")
def test_receipt_links_open_the_web_app_and_logos_load_from_the_api(rf):
    from types import SimpleNamespace
    from apps.commerce.receipts import app_url, logo_url
    request = rf.get("/")
    organization = SimpleNamespace(logo=SimpleNamespace(name="logos/1/shop.png"), logo_url="")
    assert app_url(request) == FRONTEND
    assert logo_url(organization, request) == "https://api.dukaflow.co.ke/api/v1/tenancy/public/logos/shop.png"
