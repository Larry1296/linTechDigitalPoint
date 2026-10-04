from apps.tenancy.commands import LintechCommand
"""Confirmed Zone A structure; geometry is schematic until measured."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.core.models import Store
from apps.catalog.models import Category
from apps.inventory.models import Zone, ShelfStackCategory
from apps.inventory.services import create_shelf_stack


class Command(LintechCommand):
    help = "Create the confirmed Zone A mobile accessories layout idempotently."

    @transaction.atomic
    def handle(self, *args, **options):
        stores = list(Store.objects.select_for_update())
        if len(stores) != 1:
            raise CommandError("Exactly one store must exist before setup.")
        zone, created = Zone.objects.get_or_create(store=stores[0], code="A", defaults={"name": "Zone A — Right Wall"})
        if zone.name != "Zone A — Right Wall" or not zone.active:
            raise CommandError("Zone A conflicts with confirmed layout.")
        category, _ = Category.objects.get_or_create(slug="mobile-accessories", defaults={"name": "Mobile Accessories"})
        if category.name != "Mobile Accessories" or category.parent_id or not category.active:
            raise CommandError("Mobile Accessories category conflicts with confirmed layout.")
        if created or not zone.stacks.exists():
            if zone.shelves.exists():
                raise CommandError("Zone A contains conflicting shelves.")
            create_shelf_stack(
                zone=zone,
                user=None,
                display_name="Mobile Accessories Rack",
                x=0,
                y=0,
                width=6,
                height=6,
                depth=1,
                notes="Schematic dimensions; physical measurements pending.",
                level_definitions=[
                    {"compartments": 2, "physical_labels": [f"AL{i}C{j}S1" for j in (1, 2)]} for i in (1, 2, 3)
                ],
            )
        racks = list(zone.stacks.all())
        if len(racks) != 1:
            raise CommandError("Zone A has conflicting racks.")
        rack = racks[0]
        if rack.display_name != "Mobile Accessories Rack" or not rack.active or rack.number_of_levels != 3:
            raise CommandError("Rack conflicts with confirmed layout.")
        levels = list(rack.levels.order_by("level_number"))
        if [level.level_number for level in levels] != [1, 2, 3] or zone.shelves.count() != 6:
            raise CommandError("Levels conflict with confirmed layout.")
        for level in levels:
            shelves = list(level.shelves.order_by("position_in_level"))
            if not level.active or [(s.position_in_level, s.physical_label, s.active, s.zone_id) for s in shelves] != [
                (j, f"AL{level.level_number}C{j}S1", True, zone.pk) for j in (1, 2)
            ]:
                raise CommandError("Compartments conflict with confirmed layout.")
        if rack.category_assignments.filter(is_primary=True).exclude(category=category).exists():
            raise CommandError("Rack primary category conflicts with confirmed layout.")
        assignment, _ = ShelfStackCategory.objects.get_or_create(
            stack=rack, category=category, defaults={"is_primary": True}
        )
        if not assignment.is_primary:
            raise CommandError("Existing category assignment is not primary.")
        self.stdout.write("Zone A ready: three levels, top to bottom; two compartments, left to right.")
