"""A business's shelves copied to another server (the live site) come out exactly the same, and copying twice is safe."""
import json
from io import StringIO
import pytest
from django.core.management import call_command
from apps.catalog.models import Category
from apps.core.models import Store
from apps.inventory.models import ShelfStackCategory, Zone
from apps.inventory.services import create_shelf_stack
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db


def layout(path, business):
    call_command("export_shelf_layout", business, str(path), stdout=StringIO())
    data = json.loads(path.read_text())
    data.pop("business")
    return data


def test_the_layout_is_recreated_exactly_and_a_second_import_changes_nothing(tmp_path):
    Store.objects.create(name="Main branch")
    wall = Zone.objects.create(store=Store.objects.get(), code="LEFTWALL", name="LEFT WALL", width=8, height=7)
    rack = create_shelf_stack(zone=wall, user=None, display_name="PHONE ACCESSORIES", x=1, y=2, width=6, height=6, depth=1,
                              level_definitions=[{"compartments": 2, "physical_labels": ["A1", "A2"]}, {"compartments": 1}])
    ShelfStackCategory.objects.create(stack=rack, category=Category.objects.create(name="PHONE ACCESSORIES", slug="phone"), is_primary=True)
    source = layout(tmp_path / "source.json", "lintech-digital-point")

    live = Organization.objects.create(slug="live-shop", name="Live shop")
    OrganizationSubscription.objects.create(organization=live, status="ACTIVE")
    with organization_context(live):
        Store.objects.create(name="Main branch")
    call_command("import_shelf_layout", "live-shop", str(tmp_path / "source.json"), "--dry-run", stdout=StringIO())
    assert layout(tmp_path / "empty.json", "live-shop")["zones"] == []

    call_command("import_shelf_layout", "live-shop", str(tmp_path / "source.json"), stdout=StringIO())
    assert layout(tmp_path / "copy.json", "live-shop") == source

    again = StringIO()
    call_command("import_shelf_layout", "live-shop", str(tmp_path / "source.json"), stdout=again)
    assert "0 places made, 0 updated" in again.getvalue()


def live_shop_with_old_shelves():
    live = Organization.objects.create(slug="live-shop", name="Live shop")
    OrganizationSubscription.objects.create(organization=live, status="ACTIVE")
    with organization_context(live):
        Store.objects.create(name="Main branch")
        old = Zone.objects.create(store=Store.objects.get(), code="OLD", name="Old wall")
        rack = create_shelf_stack(zone=old, user=None, display_name="Old rack", x=0, y=0, width=2, height=2, depth=1,
                                  level_definitions=[{"compartments": 2}])
        ShelfStackCategory.objects.create(stack=rack, category=Category.objects.create(name="Old", slug="old"), is_primary=True)
    return live


def source_layout(tmp_path):
    Store.objects.create(name="Main branch")
    wall = Zone.objects.create(store=Store.objects.get(), code="LEFTWALL", name="LEFT WALL", width=8, height=7)
    create_shelf_stack(zone=wall, user=None, display_name="PHONE ACCESSORIES", x=1, y=2, width=6, height=6, depth=1,
                       level_definitions=[{"compartments": 2, "physical_labels": ["A1", "A2"]}])
    return layout(tmp_path / "source.json", "lintech-digital-point")


def test_replace_clears_the_shelves_that_were_there_and_leaves_exactly_the_layout(tmp_path):
    source = source_layout(tmp_path)
    live = live_shop_with_old_shelves()
    with organization_context(live):
        from apps.catalog.models import Product, ProductVariant
        from apps.inventory.models import Shelf, VariantPreferredLocation
        variant = ProductVariant.objects.create(product=Product.objects.create(name="Cable", slug="cable", category=Category.objects.get(slug="old")), sku="C1", selling_price=10)
        VariantPreferredLocation.objects.create(variant=variant, shelf=Shelf.objects.filter(zone__code="OLD").first())
    call_command("import_shelf_layout", "live-shop", str(tmp_path / "source.json"), "--replace", stdout=StringIO())
    assert layout(tmp_path / "copy.json", "live-shop") == source
    with organization_context(live):
        assert not Zone.objects.filter(code="OLD").exists()
        assert not VariantPreferredLocation.objects.exists() and ProductVariant.objects.filter(sku="C1").exists()


def test_replace_changes_nothing_when_an_old_shelf_holds_stock(tmp_path):
    source_layout(tmp_path)
    live = live_shop_with_old_shelves()
    with organization_context(live):
        from apps.catalog.models import Product, ProductVariant
        from apps.inventory.models import Shelf
        from apps.inventory.services import receive_stock
        variant = ProductVariant.objects.create(product=Product.objects.create(name="Cable", slug="cable", category=Category.objects.get(slug="old")), sku="C1", selling_price=10)
        receive_stock(variant=variant, placements=[{"shelf": Shelf.objects.filter(zone__code="OLD").first(), "quantity": 2}],
                      unit_cost=5, reference="R1", user=None)
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match="holds stock"):
        call_command("import_shelf_layout", "live-shop", str(tmp_path / "source.json"), "--replace", stdout=StringIO())
    assert [z["code"] for z in layout(tmp_path / "after.json", "live-shop")["zones"]] == ["OLD"]
