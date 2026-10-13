import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category,PriceHistory,Product,ProductVariant
from apps.inventory.models import StockBalance,VariantPreferredLocation
@pytest.mark.django_db
def test_product_and_price_history():
    user=User.objects.create_user("manager"); cat=Category.objects.create(name="Accessories",slug="accessories"); product=Product.objects.create(name="Cable",slug="cable",category=cat); variant=ProductVariant.objects.create(product=product,sku="CAB-1",selling_price=250); PriceHistory.objects.create(variant=variant,price=250,changed_by=user); variant.selling_price=300; variant.save(); PriceHistory.objects.create(variant=variant,price=300,changed_by=user); assert list(variant.price_history.values_list("price",flat=True))==[250,300]

@pytest.mark.django_db
def test_software_service_creation_has_cost_but_no_physical_stock():
    owner=User.objects.create_superuser("service-owner","owner@example.test","Strong-pass-1296");category=Category.objects.create(name="Software Services",slug="software-services");client=APIClient();client.force_authenticate(owner)
    response=client.post("/api/v1/catalog/products/create-with-stock/",{"name":"Windows Installation","category_id":category.id,"product_type":"SERVICE","variant_name":"Windows 11","sku":"SVC-WIN11","selling_price":"1500","service_cost":"200","opening_quantity":"10","ecommerce_visible":False},format="json")
    assert response.status_code==201
    variant=ProductVariant.objects.get(pk=response.json()["variant_id"])
    assert variant.service_cost==200 and variant.product.product_type==Product.SERVICE
    assert not StockBalance.objects.filter(lot__variant=variant).exists()
    assert not VariantPreferredLocation.objects.filter(variant=variant).exists()

@pytest.mark.django_db
def test_product_does_not_receive_a_category_illustration():
    category = Category.objects.create(name="Phone Accessories", slug="phones")
    product = Product.objects.create(name="USB cable", slug="usb-cable", category=category)
    assert not product.images.exists()
    product.description = "Updated"
    product.save()
    assert not product.images.exists()


@pytest.mark.django_db
def test_ai_image_does_not_guess_unrelated_product():
    category = Category.objects.create(name="Computer Accessories", slug="computers")
    product = Product.objects.create(name="External hard drive", slug="drive", category=category)
    assert not product.images.exists()


@pytest.mark.django_db
def test_custom_upload_is_stored(settings, tmp_path):
    from io import BytesIO
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile
    settings.MEDIA_ROOT = tmp_path
    output = BytesIO()
    Image.new("RGB", (100, 200), "white").save(output, "PNG")
    upload = SimpleUploadedFile("padlock.png", output.getvalue(), content_type="image/png")
    owner = User.objects.create_superuser("image-owner", "images@example.test", "Strong-pass-1296")
    category = Category.objects.create(name="Padlocks", slug="locks")
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post("/api/v1/catalog/products/create-with-stock/", {
        "name": "Brass padlock", "category_id": category.pk, "sku": "LOCK-IMG",
        "selling_price": "100", "display_image": upload,
    }, format="multipart")
    assert response.status_code == 201
    product = Product.objects.get(pk=response.json()["product_id"])
    assert product.images.get().file.name.endswith(".webp")


@pytest.mark.django_db
def test_image_backfill_is_idempotent_and_preserves_custom_photos():
    from django.core.management import call_command
    category = Category.objects.create(name="Padlocks", slug="locks")
    product = Product.objects.create(name="Padlock", slug="lock", category=category)
    product.images.all().delete()
    product.images.create(image_url="https://example.test/photo.jpg")
    call_command("assign_catalog_images")
    call_command("assign_catalog_images")
    assert product.images.get().image_url == "https://example.test/photo.jpg"


@pytest.mark.django_db
def test_paper_sold_two_sheets_for_five_is_counted_and_sold_in_packs():
    from decimal import Decimal
    owner = User.objects.create_superuser("paper-owner", "paper@example.test", "Strong-pass-1296")
    from apps.core.models import Store
    Store.objects.create(name="Main")
    category = Category.objects.create(name="Cyber Essentials", slug="cyber-essentials")
    client = APIClient()
    client.force_authenticate(owner)
    # One ream of 500 sheets bought at 450 = 250 packs of 2 at 1.80 each; the form converts sheets to packs.
    made = client.post("/api/v1/catalog/products/create-with-stock/", {"name": "A4 Printing Paper", "category_id": category.id,
        "variant_name": "Pack of 2 sheets", "sku": "PAPER-A4-2", "selling_price": "5", "pack_size": "2", "piece_name": "sheet",
        "opening_quantity": "250", "opening_unit_cost": "1.80"}, format="json")
    assert made.status_code == 201, made.content
    paper = ProductVariant.objects.get(pk=made.json()["variant_id"])
    assert (paper.pack_size, paper.piece_name) == (2, "sheet")
    assert sum(b.quantity for b in StockBalance.objects.filter(lot__variant=paper)) == Decimal("250")
    found = client.get("/api/v1/inventory/variants/search/", {"q": "PAPER-A4"}).json()[0]
    assert (found["pack_size"], found["piece_name"]) == (2, "sheet")
    sold = client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": paper.pk, "quantity": 3}]}, format="json")
    assert sold.status_code == 201 and Decimal(str(sold.json()["total"])) == Decimal("15")  # 3 packs = 6 sheets = 15 bob
    assert sum(b.quantity for b in StockBalance.objects.filter(lot__variant=paper)) == Decimal("247")
    bad = client.post("/api/v1/catalog/products/create-with-stock/", {"name": "Clips", "category_id": category.id, "sku": "CLIP-0",
        "selling_price": "20", "pack_size": "0"}, format="json")
    assert bad.status_code == 400 and "pack" in str(bad.json()).lower()


@pytest.mark.django_db
def test_search_finds_what_is_meant_not_only_the_exact_wording():
    from apps.catalog.search import search_variants
    phone = Category.objects.create(name="Phone Accessories", slug="phone-acc")
    phone_chargers = Category.objects.create(name="Chargers", slug="phone-chargers", parent=phone)
    computer = Category.objects.create(name="Computer Accessories", slug="computer-acc")
    laptop_chargers = Category.objects.create(name="Laptop Chargers", slug="laptop-chargers", parent=computer)
    phones = Category.objects.create(name="Mobile Phones", slug="mobile-phones", parent=phone)

    def item(name, category, sku, description=""):
        product = Product.objects.create(name=name, slug=sku.lower(), category=category, description=description)
        return ProductVariant.objects.create(product=product, sku=sku, selling_price=100)

    amaya = item("AMAYA 10W MICROUSB CHARGER", phone_chargers, "AMY-MICRO-10W")
    car = item("ORIGINAL CAR CHARGER", phone_chargers, "OCC-1")
    laptop = item("HP BLUE PIN CHARGER (65W)", laptop_chargers, "HP-CHG")
    handset = item("KHK MOBILE PHONE", phones, "KHK-1")
    cable = item("CHEAP MICROUSB CABLE", phone, "MICRO-CHEAP", "Cheap USB to Micro-USB cable")
    found = lambda query: list(search_variants(ProductVariant.objects.all(), query))

    assert set(found("charger")) == {amaya, car, laptop}
    assert set(found("mobile charger")) == {amaya, car}  # "mobile" = phone: the phone chargers, not the laptop one
    assert set(found("phone chargers")) == {amaya, car}  # plural
    assert set(found("chager")) == {amaya, car, laptop}  # a small typo
    assert set(found("micro usb")) == {amaya, cable}  # "micro usb", "micro-usb" and "MICROUSB" are the same
    assert set(found("laptop charger")) == {laptop}
    assert found("mobile phone")[0] == handset  # its own name holds the words, so it comes before what is only filed under phones
    assert found("micro-cheap") == [cable]  # an item code
    assert found("") != [] and found("xyzzy") == []
