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
