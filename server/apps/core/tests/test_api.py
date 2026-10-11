import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category,Product,ProductVariant
@pytest.mark.django_db
def test_locations_require_login():
    assert APIClient().get("/api/v1/locations/zones/").status_code in (401,403)
