import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product
from apps.inventory.models import Zone, StockReceipt


@pytest.fixture
def owner(db):
    client = APIClient()
    user = User.objects.create(username="owner", is_staff=True, is_superuser=True)
    client.force_authenticate(user)
    return client


def test_owner_manually_creates_first_root_category(owner):
    assert not Category.objects.exists()
    response = owner.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories", "parent": None}, format="json")
    assert response.status_code == 201
    category = Category.objects.get()
    assert category.slug == "mobile-accessories" and category.parent is None
    assert not Product.objects.exists() and not Zone.objects.exists() and not StockReceipt.objects.exists()
    assert owner.post("/api/v1/catalog/categories/", {"name": " mobile accessories "}, format="json").status_code == 400


def test_editing_category_preserves_slug_and_rejects_cycles(owner):
    root = Category.objects.create(name="Mobile Accessories", slug="mobile-accessories")
    child = Category.objects.create(name="Cables", slug="cables", parent=root)
    response = owner.patch(f"/api/v1/catalog/categories/{root.pk}/", {"parent": child.pk}, format="json")
    assert response.status_code == 400
    response = owner.patch(f"/api/v1/catalog/categories/{child.pk}/", {"name": "USB cables", "active": False}, format="json")
    assert response.status_code == 200
    child.refresh_from_db()
    assert child.name == "USB cables" and child.slug == "cables" and not child.active
    other = Category.objects.create(name="Other", slug="other", parent=root)
    assert owner.patch(f"/api/v1/catalog/categories/{other.pk}/", {"name": "USB cables"}, format="json").status_code == 400


def test_category_creation_requires_staff_permission(db):
    client = APIClient()
    assert client.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories"}).status_code == 403
    client.force_authenticate(User.objects.create(username="staff", is_staff=True))
    assert client.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories"}).status_code == 403
    assert not Category.objects.exists()


def test_category_name_can_be_corrected(owner):
    category = Category.objects.create(name="Computer Acessories", slug="computer-acessories")
    response = owner.patch(f"/api/v1/catalog/categories/{category.pk}/", {"name": "Computer Accessories"}, format="json")
    assert response.status_code == 200, response.content
    assert Category.objects.get(pk=category.pk).name == "Computer Accessories"
    Category.objects.create(name="Electrical", slug="electrical")
    duplicate = owner.patch(f"/api/v1/catalog/categories/{category.pk}/", {"name": "electrical"}, format="json")
    assert duplicate.status_code == 400


def test_unused_category_is_deleted_and_released_from_racks(owner):
    from apps.core.models import Store
    from apps.inventory.models import ShelfStack, ShelfStackCategory
    from apps.inventory.services import create_shelf_stack
    category = Category.objects.create(name="Computer Accessories", slug="computer-accessories")
    zone = Zone.objects.create(store=Store.objects.create(name="Main branch"), code="A", name="Shop floor")
    rack = create_shelf_stack(zone=zone, user=None, display_name="Computer rack", x=0, y=0, width=100, height=100,
                              depth=30, level_definitions=[{"compartments": 1}])
    ShelfStackCategory.objects.create(stack=rack, category=category, is_primary=True)
    response = owner.delete(f"/api/v1/catalog/categories/{category.pk}/")
    assert response.status_code == 204, response.content
    assert not Category.objects.filter(pk=category.pk).exists()
    assert ShelfStack.objects.filter(pk=rack.pk).exists() and not ShelfStackCategory.objects.exists()


def test_category_with_products_or_subcategories_explains_why_it_stays(owner):
    root = Category.objects.create(name="Computer Accessories", slug="computer-accessories")
    Category.objects.create(name="Cables", slug="cables", parent=root)
    Product.objects.create(name="USB mouse", slug="usb-mouse", category=root)
    response = owner.delete(f"/api/v1/catalog/categories/{root.pk}/")
    assert response.status_code == 400
    assert response.json()["detail"] == ("Computer Accessories still has 1 product and 1 subcategory. Move them to "
                                         "another category first, or edit this category and untick Active to hide it.")
    assert Category.objects.filter(pk=root.pk).exists()


def test_category_list_shows_product_count_and_active_racks(owner):
    from apps.core.models import Store
    from apps.inventory.models import ShelfStackCategory
    from apps.inventory.services import create_shelf_stack
    category = Category.objects.create(name="Computer Accessories", slug="computer-accessories")
    Category.objects.create(name="Electrical", slug="electrical")
    Product.objects.create(name="USB mouse", slug="usb-mouse", category=category)
    Product.objects.create(name="Keyboard", slug="keyboard", category=category)
    zone = Zone.objects.create(store=Store.objects.create(name="Main branch"), code="A", name="Shop floor")
    for name, active in [("Right wall rack", True), ("Old rack", False)]:
        rack = create_shelf_stack(zone=zone, user=None, display_name=name, x=0, y=0, width=100, height=100,
                                  depth=30, level_definitions=[{"compartments": 1}])
        rack.active = active
        rack.save(update_fields=["active"])
        ShelfStackCategory.objects.create(stack=rack, category=category, is_primary=True)
    rows = {row["name"]: row for row in owner.get("/api/v1/catalog/categories/").json()}
    assert rows["Computer Accessories"]["product_count"] == 2
    assert rows["Computer Accessories"]["racks"] == ["Right wall rack"]
    assert rows["Electrical"]["product_count"] == 0 and rows["Electrical"]["racks"] == []
    created = owner.post("/api/v1/catalog/categories/", {"name": "Stationery"}, format="json").json()
    assert created["product_count"] == 0 and created["racks"] == []


def test_brands_are_listed_edited_and_deleted_only_when_unused(owner):
    from apps.catalog.models import Brand
    created = owner.post("/api/v1/catalog/brands/", {"name": " Oraimo "}, format="json")
    assert created.status_code == 201, created.content
    brand = created.json()
    assert brand["name"] == "Oraimo" and brand["product_count"] == 0
    assert owner.post("/api/v1/catalog/brands/", {"name": "oraimo"}, format="json").status_code == 400
    assert owner.patch(f"/api/v1/catalog/brands/{brand['id']}/", {"name": "Oraimo Kenya"}, format="json").json()["name"] == "Oraimo Kenya"
    category = Category.objects.create(name="Mobile", slug="mobile")
    Product.objects.create(name="Charger", slug="charger", category=category, brand_id=brand["id"])
    refused = owner.delete(f"/api/v1/catalog/brands/{brand['id']}/")
    assert refused.status_code == 400 and "used by 1 product" in refused.json()["detail"]
    spare = owner.post("/api/v1/catalog/brands/", {"name": "Tecno"}, format="json").json()
    assert owner.delete(f"/api/v1/catalog/brands/{spare['id']}/").status_code == 204
    assert list(Brand.objects.values_list("name", flat=True)) == ["Oraimo Kenya"]


def test_sub_categories_use_their_parents_rack_for_new_products_and_deliveries(owner):
    from apps.catalog.models import ProductVariant
    from apps.core.models import Store
    from apps.inventory.models import Shelf, ShelfStackCategory, StockBalance
    from apps.inventory.services import complete_stock_receipt, create_shelf_stack
    mobile = Category.objects.create(name="Mobile Accessories", slug="mobile-accessories")
    chargers = Category.objects.create(name="Wall Chargers", slug="wall-chargers", parent=mobile)
    Category.objects.create(name="Old cables", slug="old-cables", parent=mobile, active=False)
    Category.objects.create(name="Electrical", slug="electrical")
    zone = Zone.objects.create(store=Store.objects.create(name="Main branch"), code="L", name="Left wall")
    rack = create_shelf_stack(zone=zone, user=None, display_name="Phones rack", x=0, y=0, width=100, height=100,
                              depth=30, level_definitions=[{"compartments": 1}])
    ShelfStackCategory.objects.create(stack=rack, category=mobile, is_primary=True)
    rows = owner.get("/api/v1/inventory/categories/available/").json()
    assert [(r["name"], r["rack_names"], r["available"]) for r in rows] == [
        ("Electrical", [], False), ("Mobile Accessories", ["Phones rack"], True),
        ("Wall Chargers – Mobile Accessories", ["Phones rack"], True)]
    assert sorted(rows[1]["descendant_ids"]) == [mobile.pk, chargers.pk] and rows[2]["rack_ids"] == [rack.pk]
    variant = ProductVariant.objects.create(product=Product.objects.create(name="Normal Full Charger", slug="nfc", category=chargers),
                                            sku="NFC-IMITATION", selling_price=250)
    shelf = Shelf.objects.get(level__stack=rack)
    user = User.objects.get(username="owner")
    complete_stock_receipt(supplier_name="Wholesaler", external_reference="INV-1", user=user,
                           lines=[{"variant_id": variant.pk, "received_quantity": "4", "unit_cost": "110",
                                   "placements": [{"shelf_id": shelf.pk, "quantity": "4"}]}])
    assert StockBalance.objects.get(lot__variant=variant, shelf=shelf).quantity == 4


def test_product_list_follows_the_category_tree(owner):
    from apps.core.models import Store
    from apps.inventory.models import ShelfStackCategory
    from apps.inventory.services import create_shelf_stack
    electrical = Category.objects.create(name="Electrical", slug="electrical")
    mobile = Category.objects.create(name="Mobile Accessories", slug="mobile")
    chargers = Category.objects.create(name="Wall Chargers", slug="chargers", parent=mobile)
    zone = Zone.objects.create(store=Store.objects.create(name="Main branch"), code="A", name="Shop floor")
    rack = create_shelf_stack(zone=zone, user=None, display_name="Rack", x=0, y=0, width=100, height=100,
                              depth=30, level_definitions=[{"compartments": 1}])
    ShelfStackCategory.objects.create(stack=rack, category=mobile, is_primary=True)
    for name, category in [("Charger B", chargers), ("Bulb", electrical), ("Cable", mobile), ("Charger A", chargers)]:
        Product.objects.create(name=name, slug=name.lower().replace(" ", "-"), category=category)
    names = [row["name"] for row in owner.get("/api/v1/catalog/products/?page=1").json()["results"]]
    assert names == ["Bulb", "Cable", "Charger A", "Charger B"]


def test_products_can_be_browsed_one_category_at_a_time(owner):
    mobile = Category.objects.create(name="Mobile Accessories", slug="mobile")
    chargers = Category.objects.create(name="Wall Chargers", slug="chargers", parent=mobile)
    retired = Category.objects.create(name="Retired", slug="retired", active=False)
    for name, category in [("Charger A", chargers), ("Charger B", chargers), ("Cable", mobile), ("Old radio", retired)]:
        Product.objects.create(name=name, slug=name.lower().replace(" ", "-"), category=category)
    assert owner.get("/api/v1/catalog/products/category-counts/").json() == {
        "categories": {str(mobile.pk): 1, str(chargers.pk): 2}, "other": 1}
    names = lambda query: [row["name"] for row in owner.get(f"/api/v1/catalog/products/?page=1&{query}").json()["results"]]
    assert names(f"category={mobile.pk}") == ["Cable"]
    assert names(f"category={chargers.pk}") == ["Charger A", "Charger B"]
    assert names("category=other") == ["Old radio"]
    assert owner.get("/api/v1/catalog/products/?page=1&category=abc").status_code == 400


def test_a_category_created_from_the_product_form_goes_straight_onto_its_rack(owner):
    from django.contrib.auth.models import Permission
    from apps.catalog.models import category_tree
    from apps.core.models import AuditLog, Store
    from apps.inventory.models import ShelfStack, ShelfStackCategory
    zone = Zone.objects.create(store=Store.objects.create(name="Main"), code="L", name="Left wall")
    rack = ShelfStack.objects.create(zone=zone, code="L-R1", display_name="Phone accessories", x=0, y=0, width=1, height=1, depth=1, number_of_levels=1)
    response = owner.post("/api/v1/catalog/categories/", {"name": "Memory cards", "parent": None, "rack_id": rack.pk}, format="json")
    assert response.status_code == 201 and response.json()["racks"] == ["Phone accessories"]
    category = Category.objects.get(name="Memory cards")
    assert ShelfStackCategory.objects.filter(stack=rack, category=category).exists()
    assert next(row for row in category_tree() if row["id"] == category.pk)["rack_ids"] == [rack.pk]
    assert AuditLog.objects.filter(action="RACK_CATEGORY_ASSIGNED", object_id=str(rack.pk)).exists()
    # A rack that doesn't exist or is archived is refused, and no category is left behind.
    rack.active = False
    rack.save()
    assert owner.post("/api/v1/catalog/categories/", {"name": "Flash drives", "rack_id": rack.pk}, format="json").status_code == 400
    assert owner.post("/api/v1/catalog/categories/", {"name": "Flash drives", "rack_id": "abc"}, format="json").status_code == 400
    assert not Category.objects.filter(name="Flash drives").exists()
    # Someone who may add categories but not manage shelves can't put one on a rack.
    rack.active = True
    rack.save()
    clerk = User.objects.create(username="clerk", is_staff=True)
    clerk.user_permissions.add(Permission.objects.get(codename="add_category"))
    client = APIClient()
    client.force_authenticate(clerk)
    assert client.post("/api/v1/catalog/categories/", {"name": "Flash drives", "rack_id": rack.pk}, format="json").status_code == 403
    assert client.post("/api/v1/catalog/categories/", {"name": "Flash drives"}, format="json").status_code == 201
