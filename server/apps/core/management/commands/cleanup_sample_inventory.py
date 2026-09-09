"""Deliberate development-only exception; normal receipt APIs stay immutable."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from apps.catalog.models import Product, ProductVariant, ProductVariantOptionValue
from apps.core.models import Store
from apps.inventory.models import (
    Movement,
    StockReceipt,
    StockReceiptPlacement,
    StockReceiptLine,
    StockBalance,
    StockLot,
    VariantPreferredLocation,
    Zone,
    ShelfHistory,
    LocationHistory,
)
from apps.core.management.commands.seed_sample_inventory import COVERS, PADLOCKS, IDEMPOTENCY_KEY


def assert_references(objects, allowed):
    """Reject even CASCADE/SET_NULL references outside the explicit deletion plan."""
    for obj in objects:
        for relation in obj._meta.related_objects:
            model = relation.related_model
            for pk in model.objects.filter(**{relation.field.name: obj}).values_list("pk", flat=True):
                if (model, pk) not in allowed:
                    raise CommandError(
                        f"Unsafe genuine reference: {model.__name__} {pk} uses {obj._meta.label} {obj.pk}."
                    )


class Command(BaseCommand):
    help = "Preview or explicitly remove only unchanged seed_sample_inventory records."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--remove-test-layout",
            action="store_true",
            help="Additionally assert RIGHT/BACKWALL are disposable test structures.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["execute"] and options["dry_run"]:
            raise CommandError("Choose --execute or --dry-run.")
        list(Store.objects.select_for_update())
        receipts = list(
            StockReceipt.objects.select_for_update().filter(
                Q(idempotency_key=IDEMPOTENCY_KEY) | Q(external_reference="SAMPLE-INVENTORY-V1")
            )
        )
        products = list(
            Product.objects.select_for_update().filter(slug__in=["sample-smartphone-cover", "sample-padlock"])
        )
        variants = list(
            ProductVariant.objects.select_for_update().filter(Q(product__in=products) | Q(sku__startswith="SAMPLE-"))
        )
        if not receipts and (products or variants):
            raise CommandError("Sample receipt missing; cannot prove sample ownership.")
        plan = []
        if receipts:
            if (
                len(receipts) != 1
                or receipts[0].idempotency_key != IDEMPOTENCY_KEY
                or receipts[0].external_reference != "SAMPLE-INVENTORY-V1"
            ):
                raise CommandError("Sample receipt identity conflict.")
            receipt = receipts[0]
            expected = {row[0]: row for row in (*COVERS, *PADLOCKS)}
            if {v.sku for v in variants} != set(expected) or len(products) != 2:
                raise CommandError("Sample catalog conflict.")
            lines = list(receipt.lines.all())
            if len(lines) != 7 or {line.variant_id for line in lines} != {v.pk for v in variants}:
                raise CommandError("Sample lines conflict.")
            placements, balances, movements, lots = [], [], [], []
            for line in lines:
                variant = next(v for v in variants if v.pk == line.variant_id)
                row = expected[variant.sku]
                expected_slug = (
                    "sample-smartphone-cover" if variant.sku.startswith("SAMPLE-COVER-") else "sample-padlock"
                )
                if variant.product.slug != expected_slug:
                    raise CommandError("Sample product conflict.")
                lot = line.lot
                ps = list(line.placements.select_related("balance", "shelf"))
                ms = list(Movement.objects.filter(lot=lot))
                from decimal import Decimal

                qty, cost = Decimal(row[4]), Decimal(row[3])
                if (
                    not lot
                    or line.received_quantity != qty
                    or line.unit_cost != cost
                    or lot.received_quantity != qty
                    or lot.remaining_quantity != qty
                    or lot.unit_cost != cost
                    or lot.variant_id != variant.pk
                    or len(ps) != 1
                    or len(ms) != 1
                ):
                    raise CommandError(
                        f"Unsafe sample lot or receipt changes for {variant.sku}; expected quantity {qty}, original cost {cost}. No cleanup performed."
                    )
                p, m = ps[0], ms[0]
                if (
                    p.quantity != qty
                    or p.shelf.code != row[5]
                    or not p.balance
                    or p.balance.lot_id != lot.pk
                    or p.balance.shelf_id != p.shelf_id
                    or p.balance.quantity != qty
                    or p.balance.reserved
                    or m.quantity != qty
                    or m.variant_id != variant.pk
                    or m.movement_type != "PURCHASE_RECEIPT"
                    or m.reference != receipt.receipt_number
                    or m.source_id
                    or m.destination_id != p.shelf_id
                ):
                    raise CommandError("Unsafe sample movement, reservation or balance changes.")
                placements.append(p)
                balances.append(p.balance)
                movements.append(m)
                lots.append(lot)
            assignments = list(ProductVariantOptionValue.objects.filter(variant__in=variants))
            values = [
                value for product in products for option in product.option_types.all() for value in option.values.all()
            ]
            types = [option for product in products for option in product.option_types.all()]
            images = [img for product in products for img in product.images.all()]
            if any(
                not (img.image_url.startswith("/images/catalog/") and img.alt_text.startswith("AI illustration"))
                for img in images
            ):
                raise CommandError("Product has non-placeholder images; preserve for review.")
            preferred = list(VariantPreferredLocation.objects.filter(variant__in=variants))
            if any(
                p.shelf_id not in {s.shelf_id for s in placements if s.line.variant_id == p.variant_id}
                for p in preferred
            ):
                raise CommandError("Preferred location changed; preserve for review.")
            plan = [
                *placements,
                *movements,
                *lines,
                *balances,
                *lots,
                *preferred,
                *assignments,
                *values,
                *types,
                *images,
                *variants,
                *products,
                receipt,
            ]
        # Categories and rack assignments were adopted by the old seeder, with no
        # ownership marker. Preserve them rather than guessing they were created by it.
        allowed = {(type(obj), obj.pk) for obj in plan}
        assert_references(plan, allowed)
        if options["remove_test_layout"]:
            layout = []
            for zone in Zone.objects.select_for_update().filter(code__in=["RIGHT", "BACKWALL"]):
                if zone.stacks.count() != 1:
                    raise CommandError("Test zone structure cannot be identified safely.")
                rack = zone.stacks.get()
                if rack.code != f"{zone.code}-R01":
                    raise CommandError("Unexpected test rack identity.")
                shelves = list(zone.shelves.all())
                levels = list(rack.levels.all())
                histories = list(ShelfHistory.objects.filter(shelf__in=shelves))
                lh = list(
                    LocationHistory.objects.filter(
                        Q(object_type="ShelfStack", object_id=rack.pk)
                        | Q(object_type="ShelfLevel", object_id__in=[l.pk for l in levels])
                    )
                )
                if any(h.changed_by_id or h.event != "CREATED" for h in histories) or any(
                    h.changed_by_id or h.event not in ("STACK_CREATED", "LEVEL_ADDED") for h in lh
                ):
                    raise CommandError("Test layout has genuine edit history.")
                # Assignments may predate the sample seeder: never remove them implicitly.
                if rack.category_assignments.exists():
                    raise CommandError(
                        "Rack category assignments have no sample provenance; retain layout for manual review."
                    )
                layout.extend([*histories, *lh, *shelves, *levels, rack, zone])
            assert_references(layout, allowed | {(type(obj), obj.pk) for obj in layout})
            plan.extend(layout)
        from collections import Counter

        for model, count in sorted(Counter(obj._meta.label for obj in plan).items()):
            self.stdout.write(f"{model}: {count}")
        self.stdout.write("Shared/unproven categories, rack assignments and audit logs are preserved.")
        if options["execute"]:
            for obj in plan:
                obj.delete()
            self.stdout.write("Sample cleanup completed.")
        else:
            self.stdout.write("Dry run: no records removed. Pass --execute to delete.")
