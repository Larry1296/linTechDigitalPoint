"""Write one business's shelves (walls, racks, levels, compartments) to a JSON file that import_shelf_layout reads.

    python manage.py export_shelf_layout lintech-digital-point shelves.json

Only the layout is written: no stock, products or people. The automatic "Unplaced stock" place is left out, since
every business gets its own.
"""
import json
from django.core.management.base import BaseCommand, CommandError
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization
from apps.inventory.models import Shelf, Zone

UNPLACED = "__UNPLACED__"
ZONE_FIELDS = ["code", "name", "active", "width", "height", "next_shelf_number"]
STACK_FIELDS = ["code", "display_name", "x", "y", "width", "height", "depth", "rotation", "number_of_levels", "active", "notes"]
LEVEL_FIELDS = ["level_number", "y_position", "height", "active"]
SHELF_FIELDS = ["code", "physical_label", "display_name", "position_in_level", "x", "y", "width", "height", "depth",
                "rotation", "sort_order", "capacity", "active", "notes"]


def business(key):
    found = Organization.objects.filter(slug=key).first() or Organization.objects.filter(name__iexact=key).first()
    if not found:
        names = ", ".join(f"{o.slug} ({o.name})" for o in Organization.objects.order_by("name"))
        raise CommandError(f"No business '{key}'. Businesses here: {names or 'none'}.")
    return found


def values(obj, fields):
    data = {}
    for field in fields:
        value = getattr(obj, field)
        data[field] = None if value is None else value if isinstance(value, (bool, int, str)) else str(value)
    return data


def shelf_data(shelf):
    return {**values(shelf, SHELF_FIELDS), "parent": shelf.parent.code if shelf.parent_id else None}


class Command(BaseCommand):
    help = "Write a business's shelf layout to a JSON file for import_shelf_layout."

    def add_arguments(self, parser):
        parser.add_argument("business", help="The business's slug or name")
        parser.add_argument("file", help="Where to write the layout (- for the screen)")

    def handle(self, *args, **options):
        organization = business(options["business"])
        with organization_context(organization):
            zones = []
            for zone in Zone.objects.exclude(code=UNPLACED).select_related("store").order_by("code"):
                stacks = []
                for stack in zone.stacks.order_by("code"):
                    levels = [{**values(level, LEVEL_FIELDS),
                               "shelves": [shelf_data(s) for s in level.shelves.order_by("position_in_level", "code")]}
                              for level in stack.levels.order_by("level_number")]
                    categories = [{"name": a.category.name, "is_primary": a.is_primary}
                                  for a in stack.category_assignments.select_related("category").order_by("-is_primary", "category__name")]
                    stacks.append({**values(stack, STACK_FIELDS), "categories": categories, "levels": levels})
                loose = Shelf.objects.filter(zone=zone, level__isnull=True, is_virtual=False).order_by("code")
                zones.append({**values(zone, ZONE_FIELDS), "branch": zone.store.name, "stacks": stacks,
                              "shelves": [shelf_data(s) for s in loose]})
        layout = {"business": organization.name, "zones": zones}
        text = json.dumps(layout, indent=2, ensure_ascii=False)
        if options["file"] == "-":
            self.stdout.write(text)
        else:
            with open(options["file"], "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
            compartments = sum(len(lv["shelves"]) for z in zones for st in z["stacks"] for lv in st["levels"])
            compartments += sum(len(z["shelves"]) for z in zones)
            self.stdout.write(self.style.SUCCESS(
                f"{organization.name}: {len(zones)} walls, {sum(len(z['stacks']) for z in zones)} racks, "
                f"{compartments} compartments written to {options['file']}."))
