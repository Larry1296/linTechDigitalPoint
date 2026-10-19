"""Make a business's shelves match a layout written by export_shelf_layout: the same walls, racks, levels and
compartments, with the same codes, labels, sizes and rack categories.

    python manage.py import_shelf_layout lintech-digital-point shelves.json --dry-run   # only shows what would change
    python manage.py import_shelf_layout lintech-digital-point shelves.json

Running it again changes nothing. Places are matched by their code: missing ones are made, existing ones are set to
the layout's values, so whatever points at them (stock, sales, receipts) stays as it is.

With --replace, every other wall, rack, level and compartment of the business is removed as well, so the business ends
up with exactly the layout. A place that holds stock or appears in sales, receipts or stock counts is never removed:
the whole import stops and saves nothing. The automatic "Unplaced stock" place is always kept.
"""
import json
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from apps.catalog.models import Category
from apps.core.models import Store
from apps.commerce.models import SaleAllocation
from apps.inventory.models import (Movement, Shelf, ShelfHistory, ShelfLevel, ShelfStack, ShelfStackCategory, StockAdjustment,
                                   StockBalance, StockReceiptPlacement, VariantPreferredLocation, Zone)
from apps.inventory.services import _audit, _location_history, _shelf_snapshot, _stack_snapshot
from apps.tenancy.context import organization_context
from .export_shelf_layout import UNPLACED, LEVEL_FIELDS, SHELF_FIELDS, STACK_FIELDS, ZONE_FIELDS, business

DECIMALS = {"width", "height", "depth", "x", "y", "rotation", "y_position", "capacity"}


class DryRun(Exception):
    pass


def typed(field, value):
    return Decimal(value) if field in DECIMALS and value is not None else value


class Command(BaseCommand):
    help = "Create or update a business's shelves to match a layout file from export_shelf_layout."

    def add_arguments(self, parser):
        parser.add_argument("business", help="The business's slug or name on this server")
        parser.add_argument("file", help="The layout file written by export_shelf_layout")
        parser.add_argument("--branch", help="The branch to put the shelves in (default: the layout's branch name, "
                                             "or the business's only branch)")
        parser.add_argument("--replace", action="store_true", help="Also remove every place that is not in the layout")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving anything")

    def handle(self, *args, **options):
        with open(options["file"], encoding="utf-8") as handle:
            layout = json.load(handle)
        organization = business(options["business"])
        self.counts = {"made": 0, "updated": 0, "same": 0, "removed": 0}
        self.kept = {Zone: set(), ShelfStack: set(), ShelfLevel: set(), Shelf: set(), ShelfStackCategory: set()}
        try:
            with organization_context(organization), transaction.atomic():
                for zone in layout["zones"]:
                    self.import_zone(zone, self.branch(options.get("branch") or zone.get("branch")))
                if options["replace"]:
                    self.remove_the_rest()
                if options["dry_run"]:
                    raise DryRun
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run: nothing was saved."))
        c = self.counts
        self.stdout.write(self.style.SUCCESS(
            f"{organization.name}: {c['made']} places made, {c['updated']} updated, {c['same']} already matched"
            + (f", {c['removed']} removed." if options["replace"] else ".")))

    def branch(self, name):
        stores = list(Store.objects.order_by("pk"))
        named = [s for s in stores if name and s.name.strip().lower() == name.strip().lower()]
        if named:
            return named[0]
        if len(stores) == 1:
            return stores[0]
        raise CommandError(f"No branch named '{name}'. Choose one with --branch: {', '.join(s.name for s in stores)}.")

    def apply(self, model, lookup, data, label):
        """Find the row by ``lookup``, make it if missing, and set ``data`` on it. Returns (row, made)."""
        row = model.objects.filter(**lookup).first()
        if row is None:
            row = model(**lookup, **data)
            row.save()
            self.kept[model].add(row.pk)
            self.counts["made"] += 1
            self.stdout.write(f"  + {label}")
            return row, True
        self.kept[model].add(row.pk)
        changed = [f for f, v in data.items() if getattr(row, f"{f}_id" if f in ("zone", "level", "stack", "parent") else f)
                   != (v.pk if hasattr(v, "pk") else v)]
        if changed:
            for field in changed:
                setattr(row, field, data[field])
            row.save()
            self.counts["updated"] += 1
            self.stdout.write(f"  ~ {label}: {', '.join(changed)}")
        else:
            self.counts["same"] += 1
        return row, False

    def import_zone(self, data, store):
        fields = {f: typed(f, data[f]) for f in ZONE_FIELDS if f != "code"}
        zone, _ = self.apply(Zone, {"store": store, "code": data["code"]}, fields, f"wall {data['name']}")
        for stack_data in data["stacks"]:
            self.import_stack(zone, stack_data)
        for shelf_data in data["shelves"]:
            self.import_shelf(zone, None, shelf_data)
        for shelf_data in [s for st in data["stacks"] for lv in st["levels"] for s in lv["shelves"]] + data["shelves"]:
            if shelf_data.get("parent"):
                parent = Shelf.objects.get(zone=zone, code=shelf_data["parent"])
                self.apply(Shelf, {"zone": zone, "code": shelf_data["code"]}, {"parent": parent}, f"compartment {shelf_data['code']}")

    def import_stack(self, zone, data):
        fields = {f: typed(f, data[f]) for f in STACK_FIELDS if f != "code"}
        stack, made = self.apply(ShelfStack, {"code": data["code"]}, {**fields, "zone": zone}, f"rack {data['display_name']}")
        for level_data in data["levels"]:
            level_fields = {f: typed(f, level_data[f]) for f in LEVEL_FIELDS if f != "level_number"}
            level, level_made = self.apply(ShelfLevel, {"stack": stack, "level_number": level_data["level_number"]},
                                           level_fields, f"{stack.code} level {level_data['level_number']}")
            if level_made:
                _location_history(level, "LEVEL_ADDED", None)
            for shelf_data in level_data["shelves"]:
                self.import_shelf(zone, level, shelf_data)
        if made:
            _location_history(stack, "STACK_CREATED", None)
            _audit("STACK_CREATED", stack, None, after=_stack_snapshot(stack))
        primary = [c for c in data["categories"] if c["is_primary"]]
        if primary:
            stack.category_assignments.filter(is_primary=True).exclude(category=self.category(primary[0]["name"])).update(is_primary=False)
        for item in data["categories"]:
            self.apply(ShelfStackCategory, {"stack": stack, "category": self.category(item["name"])},
                       {"is_primary": item["is_primary"]}, f"{stack.code} category {item['name']}")

    def import_shelf(self, zone, level, data):
        fields = {f: typed(f, data[f]) for f in SHELF_FIELDS if f != "code"}
        shelf, made = self.apply(Shelf, {"zone": zone, "code": data["code"]}, {**fields, "level": level},
                                 f"compartment {data['code']} {data['physical_label']}".rstrip())
        if made:
            snapshot = _shelf_snapshot(shelf)
            ShelfHistory.objects.create(shelf=shelf, event="CREATED", snapshot=snapshot, changed_by=None)
            _audit("SHELF_CREATED", shelf, None, after=snapshot)

    def category(self, name):
        found = Category.objects.filter(name__iexact=name).order_by("parent_id", "pk").first()
        if found:
            return found
        base = slugify(name) or "category"
        slug, number = base, 1
        while Category.objects.filter(slug=slug).exists():
            number += 1
            slug = f"{base}-{number}"
        self.counts["made"] += 1
        self.stdout.write(f"  + category {name}")
        return Category.objects.create(name=name, slug=slug)

    def remove_the_rest(self):
        """Remove every wall, rack, level and compartment the layout does not have, unless business records use it."""
        shelves = Shelf.objects.filter(is_virtual=False).exclude(pk__in=self.kept[Shelf]).exclude(zone__code=UNPLACED)
        ids = list(shelves.values_list("pk", flat=True))
        used = {
            "holds stock": StockBalance.objects.filter(shelf__in=ids),
            "is in sales": SaleAllocation.objects.filter(shelf__in=ids),
            "is in stock movements": Movement.objects.filter(source__in=ids) | Movement.objects.filter(destination__in=ids),
            "is in received goods": StockReceiptPlacement.objects.filter(shelf__in=ids),
            "is in stock counts": StockAdjustment.objects.filter(shelf__in=ids),
            "has compartments inside it that stay": Shelf.objects.filter(parent__in=ids).exclude(pk__in=ids),
        }
        problems = [f"{name} ({query.count()})" for name, query in used.items() if query.exists()]
        if problems:
            codes = ", ".join(shelves.values_list("code", flat=True)[:20])
            raise CommandError("Nothing was changed. These places are not in the layout but cannot be removed because "
                               f"business records use them: {codes}. Each one {'; '.join(problems)}. Move that stock "
                               "in the app first, or add those places to the layout.")
        unshelved = VariantPreferredLocation.objects.filter(shelf__in=ids)
        if unshelved.exists():
            self.stdout.write(f"  - usual shelf cleared for {unshelved.count()} products (it is being removed)")
            unshelved.delete()
        for shelf in shelves.order_by("zone__code", "code"):
            self.stdout.write(f"  - compartment {shelf.code} {shelf.physical_label}".rstrip())
        ShelfHistory.objects.filter(shelf__in=ids).delete()
        Shelf.objects.filter(pk__in=ids).update(parent=None)
        self.counts["removed"] += Shelf.objects.filter(pk__in=ids).delete()[1].get(Shelf._meta.label, 0)
        ShelfStackCategory.objects.filter(stack__in=self.kept[ShelfStack]).exclude(pk__in=self.kept[ShelfStackCategory]).delete()
        for model, label, rows in [
            (ShelfLevel, "level", ShelfLevel.objects.exclude(pk__in=self.kept[ShelfLevel]).select_related("stack")),
            (ShelfStack, "rack", ShelfStack.objects.exclude(pk__in=self.kept[ShelfStack])),
            (Zone, "wall", Zone.objects.exclude(pk__in=self.kept[Zone]).exclude(code=UNPLACED)),
        ]:
            for row in rows:
                self.stdout.write(f"  - {label} {row.name if model is Zone else row}")
                if model is ShelfStack:
                    row.category_assignments.all().delete()
                row.delete()
                self.counts["removed"] += 1
