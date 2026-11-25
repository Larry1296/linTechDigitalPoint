"""Barcodes for every product: the shop's own for labels, or the maker's linked by scanning it once."""
import pytest
from apps.catalog.barcodes import check_digit, shop_code
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


def test_shop_code_is_an_in_store_ean13():
    assert check_digit("400638133393") == "1"  # a known EAN-13: 4006381333931
    code = shop_code(42)
    assert code == "210000000042" + check_digit("210000000042") and len(code) == 13


def test_labels_give_missing_barcodes_and_scans_link_makers_codes():
    from apps.assistant.tests.test_business_assistant import make_business
    shop = make_business("Barco", "BAR-1")
    charger = shop.charger
    made = shop.client.post("/api/v1/catalog/barcodes/labels/", {"variant_ids": [charger.pk]}, format="json")
    assert made.status_code == 200, made.content
    assert made.json()["labels"][0]["barcode"] == shop_code(charger.pk)
    again = shop.client.post("/api/v1/catalog/barcodes/labels/", {"variant_ids": [charger.pk]}, format="json").json()
    assert again["labels"][0]["barcode"] == shop_code(charger.pk)  # never changes, so printed labels keep working
    refused = shop.client.post(f"/api/v1/catalog/barcodes/link/{charger.pk}/", {"barcode": "6161101234567"}, format="json")
    assert refused.status_code == 400 and "already has the barcode" in str(refused.json())
    linked = shop.client.post(f"/api/v1/catalog/barcodes/link/{charger.pk}/", {"barcode": " 6161101234567 ", "replace": True}, format="json")
    assert linked.status_code == 200 and linked.json()["barcode"] == "6161101234567"
    rows = shop.client.get("/api/v1/commerce/pos/catalog/", {"q": "6161101234567"}).json()
    assert rows[0]["id"] == charger.pk
    with organization_context(shop.org):
        from apps.catalog.models import Product, ProductVariant
        other = ProductVariant.objects.create(product=Product.objects.first(), name="Other", sku="OTHER-1")
    taken = shop.client.post(f"/api/v1/catalog/barcodes/link/{other.pk}/", {"barcode": "6161101234567"}, format="json")
    assert taken.status_code == 400 and "already belongs to" in str(taken.json())
