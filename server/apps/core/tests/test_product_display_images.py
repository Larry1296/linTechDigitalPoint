from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant, ProductImage
from apps.core.models import Store
from apps.inventory.models import Zone, ShelfStackCategory, StockReceipt, StockLot, StockBalance, Movement
from apps.inventory.services import create_shelf_stack, complete_stock_receipt
from apps.catalog.display_images import variant_images


def photo(name="cable.png", size=(2000, 1000), colour="white"):
    data = BytesIO()
    Image.new("RGB", size, colour).save(data, "PNG")
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/png")


@pytest.fixture
def catalog(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    category = Category.objects.create(name="Charging Cables", slug="charging-cables")
    store = Store.objects.create(name="Shop")
    zone = Zone.objects.create(store=store, code="A", name="A")
    rack = create_shelf_stack(zone=zone, user=None, display_name="Cables", x=0, y=0, width=2, height=2, depth=1, level_definitions=[{"compartments": 1}])
    ShelfStackCategory.objects.create(stack=rack, category=category)
    client = APIClient()
    client.force_authenticate(User.objects.create(username="owner", is_staff=True, is_superuser=True))
    return client, category, zone.shelves.get(), tmp_path


def create(client, category, **extra):
    return client.post("/api/v1/catalog/products/create-inline/", {"name": "Amaya cable", "category_id": category.pk, "sku": "TYPE-B", "variant_name": "Type-B", "selling_price": "250", **extra}, format="multipart")


def test_customer_visible_requires_photo_without_partial_catalog(catalog):
    client, category, _, _ = catalog
    response = create(client, category)
    assert response.status_code == 400 and "Product display image" in str(response.data)
    assert not Product.objects.exists() and not ProductVariant.objects.exists()
    response = create(client, category, ecommerce_visible="false")
    assert response.status_code == 201
    assert not Product.objects.get().ecommerce_visible and not ProductImage.objects.exists()


def test_upload_optimised_and_returned_without_stock_writes(catalog):
    client, category, _, root = catalog
    response = create(client, category, display_image=photo())
    assert response.status_code == 201
    image = ProductImage.objects.get()
    assert image.file.name.endswith(".webp") and Path(image.file.path).is_relative_to(root)
    with Image.open(image.file.path) as saved:
        assert saved.size == (1600, 800)
    assert not StockReceipt.objects.exists() and not StockLot.objects.exists() and not Movement.objects.exists()
    public = APIClient().get(f'/api/v1/store/products/{response.data["variant_id"]}/').data
    assert public["images"][0]["url"] == image.file.url


@pytest.mark.parametrize("upload", [b"not an image", b"<svg></svg>"])
def test_invalid_upload_rejected(catalog, upload):
    client, category, _, root = catalog
    response = create(client, category, display_image=SimpleUploadedFile("bad.png", upload, content_type="image/png"))
    assert response.status_code == 400
    assert not Product.objects.exists() and not list(root.rglob("*.webp"))


def test_dedicated_variant_overrides_primary_and_can_explicitly_reuse(catalog):
    client, category, shelf, _ = catalog
    result = create(client, category, display_image=photo())
    product = Product.objects.get()
    type_b = ProductVariant.objects.get(pk=result.data["variant_id"])
    main_url = variant_images(type_b)[0]["url"]
    response = client.post(f"/api/v1/catalog/products/{product.pk}/variants/", {"variant_name": "Type-C", "sku": "TYPE-C", "selling_price": "300", "use_product_image": "false", "display_image": photo("type-c.png", colour="black")}, format="multipart")
    assert response.status_code == 201
    type_c = ProductVariant.objects.get(sku="TYPE-C")
    type_c_url = variant_images(type_c)[0]["url"]
    assert type_c_url != main_url
    complete_stock_receipt(external_reference="REAL", lines=[{"variant_id": type_b.pk, "received_quantity": 2, "unit_cost": 100, "placements": [{"shelf_id": shelf.pk, "quantity": 2}]}])
    before = [list(model.objects.values()) for model in (StockReceipt, StockLot, StockBalance, Movement)]
    response = client.post(f"/api/v1/catalog/products/{product.pk}/display-image/", {"variant_id": type_b.pk, "display_image": photo("type-b.png", colour="red")}, format="multipart")
    assert response.status_code == 200
    type_b.refresh_from_db()
    assert variant_images(type_b)[0]["url"] not in (main_url, type_c_url)
    assert before == [list(model.objects.values()) for model in (StockReceipt, StockLot, StockBalance, Movement)]
    assert client.post(f"/api/v1/catalog/products/{product.pk}/display-image/", {"variant_id": type_c.pk, "use_product_image": "true"}, format="multipart").status_code == 200
    type_c.refresh_from_db()
    assert variant_images(type_c)[0]["url"] == main_url


def test_no_category_illustration_fallback_and_legacy_photo_can_be_added(catalog):
    client, category, _, _ = catalog
    product = Product.objects.create(name="Cable", category=category, slug="cable")
    variant = ProductVariant.objects.create(product=product, sku="OLD", use_product_image=False)
    product.images.create(image_url="/images/catalog/cable-white.png", alt_text="AI illustration of Cable")
    assert variant_images(variant) == []
    assert client.post(f"/api/v1/catalog/products/{product.pk}/display-image/", {"variant_id": variant.pk, "display_image": photo()}, format="multipart").status_code == 200
    assert variant_images(variant)[0]["url"].startswith("/media/")


def test_other_product_variant_rejected(catalog):
    client, category, _, _ = catalog
    product = Product.objects.create(name="One", category=category, slug="one")
    other = Product.objects.create(name="Two", category=category, slug="two")
    variant = ProductVariant.objects.create(product=other, sku="TWO")
    response = client.post(f"/api/v1/catalog/products/{product.pk}/display-image/", {"variant_id": variant.pk, "display_image": photo()}, format="multipart")
    assert response.status_code == 400 and not ProductImage.objects.exists()


def test_cart_checkout_and_order_snapshot_use_variant_photo(catalog):
    client, category, shelf, _ = catalog
    result = create(client, category, display_image=photo())
    variant = ProductVariant.objects.get(pk=result.data["variant_id"])
    complete_stock_receipt(external_reference="REAL", lines=[{"variant_id": variant.pk, "received_quantity": 2, "unit_cost": 100, "placements": [{"shelf_id": shelf.pk, "quantity": 2}]}])
    url = variant_images(variant)[0]["url"]
    buyer = APIClient()
    buyer.force_authenticate(User.objects.create(username="buyer"))
    cart = buyer.post("/api/v1/commerce/cart/", {"variant_id": variant.pk, "quantity": 1}, format="json")
    assert cart.data["items"][0]["images"][0]["url"] == url
    order = buyer.post("/api/v1/commerce/checkout/", {"fulfillment_method": "PICKUP"}, format="json")
    assert order.status_code == 201 and order.data["items"][0]["images"][0]["url"] == url
    client.post(f"/api/v1/catalog/products/{variant.product_id}/display-image/", {"display_image": photo("new.png")}, format="multipart")
    detail = buyer.get(f'/api/v1/commerce/orders/{order.data["id"]}/').data
    assert detail["items"][0]["images"][0]["url"] == url


def test_upload_requires_staff_permission(catalog):
    _, category, _, _ = catalog
    product = Product.objects.create(name="Cable", category=category, slug="cable")
    client = APIClient()
    client.force_authenticate(User.objects.create(username="customer"))
    assert client.post(f"/api/v1/catalog/products/{product.pk}/display-image/", {"display_image": photo()}, format="multipart").status_code == 403


def test_upload_with_opening_stock_preserves_price_quantity_and_shelf(catalog):
    client, category, shelf, _ = catalog
    response = client.post("/api/v1/catalog/products/create-with-stock/", {
        "name": "Type-B cable", "category_id": category.pk, "sku": "OPENING-B", "selling_price": "275",
        "preferred_shelf_id": shelf.pk, "opening_quantity": "3", "opening_unit_cost": "125",
        "display_image": photo(),
    }, format="multipart")
    assert response.status_code == 201
    variant = ProductVariant.objects.get(sku="OPENING-B")
    assert variant.selling_price == 275 and variant.preferred_location.shelf == shelf
    balance = StockBalance.objects.get()
    assert balance.quantity == 3 and balance.lot.unit_cost == 125 and balance.shelf == shelf
    assert variant_images(variant)[0]["url"].startswith("/media/")


def test_generic_creation_also_requires_customer_image(catalog):
    client, category, _, _ = catalog
    response = client.post("/api/v1/catalog/products/", {"name": "No image", "slug": "no-image", "category": category.pk}, format="json")
    assert response.status_code == 400
    assert not Product.objects.exists()


def test_new_variant_cannot_reuse_missing_primary(catalog):
    client, category, _, _ = catalog
    product = Product.objects.create(name="Cable", slug="cable", category=category)
    response = client.post(f"/api/v1/catalog/products/{product.pk}/variants/", {"variant_name": "Type-C", "sku": "TYPE-C", "use_product_image": "true"}, format="multipart")
    assert response.status_code == 400 and not ProductVariant.objects.exists()
