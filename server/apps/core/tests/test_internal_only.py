import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_retired_customer_api_routes_are_removed():
    client = APIClient()
    for path in (
        "/api/v1/commerce/cart/",
        "/api/v1/commerce/checkout/",
        "/api/v1/commerce/orders/",
        "/api/v1/auth/register/",
    ):
        assert client.get(path).status_code == 404


@pytest.mark.django_db
def test_catalog_lookup_requires_internal_staff():
    client = APIClient()
    assert client.get("/api/v1/store/products/").status_code in {401, 403}
    assert client.get("/api/v1/store/search-suggestions/?q=ca").status_code in {401, 403}
