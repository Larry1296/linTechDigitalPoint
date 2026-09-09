from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.core.shop_stock import ROUNDS
from apps.inventory.models import Shelf, ShelfStackCategory, StockReceipt
from apps.inventory.services import complete_stock_receipt


class Command(BaseCommand):
    help = "Receive only new permanent real-shop receipt rounds."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        for round in ROUNDS:
            try:
                with transaction.atomic():
                    # Serialize this command before checking permanent receipt keys.
                    if len(list(Store.objects.select_for_update())) != 1:
                        raise CommandError("Exactly one store is required.")
                    if StockReceipt.objects.filter(idempotency_key=round["key"]).exists():
                        self.stdout.write(f"{round['key']}: already present")
                        continue
                    quantity = sum(Decimal(str(line[2])) for line in round["lines"])
                    cost = sum(Decimal(str(line[2])) * Decimal(str(line[3])) for line in round["lines"])
                    if (len(round["lines"]), quantity, cost) != (
                        round["expected_lines"],
                        Decimal(str(round["expected_quantity"])),
                        Decimal(str(round["expected_cost"])),
                    ):
                        raise CommandError(
                            f"Source totals disagree with expected totals: {len(round['lines'])} lines, {quantity} units, KSh {cost}; expected {round['expected_lines']} lines, {round['expected_quantity']} units, KSh {round['expected_cost']}. Reconcile source receipt before reception."
                        )
                    category = Category.objects.select_for_update().filter(slug=round["category"], active=True).first()
                    if not category:
                        raise CommandError("Required active category is absent.")
                    shelves = {}
                    for *_, label in round["lines"]:
                        matches = list(
                            Shelf.objects.select_for_update().filter(
                                physical_label=label,
                                zone__code="A",
                                active=True,
                                zone__active=True,
                                level__active=True,
                                level__stack__active=True,
                            )
                        )
                        if (
                            len(matches) != 1
                            or not ShelfStackCategory.objects.filter(
                                stack=matches[0].level.stack, category=category
                            ).exists()
                        ):
                            raise CommandError(f"Location {label} absent, inactive, ambiguous or category unassigned.")
                        shelves[label] = matches[0]
                    lines = []
                    for identifier, name, quantity, cost, label in round["lines"]:
                        sku = f"LINTECH-{identifier}"
                        variant = ProductVariant.objects.select_for_update().filter(sku=sku).first()
                        if variant is None:
                            slug = sku.lower()
                            if Product.objects.filter(slug=slug).exists():
                                raise CommandError(f"Product identifier conflict: {slug}")
                            product = Product.objects.create(
                                slug=slug,
                                name=name,
                                category=category,
                                ecommerce_visible=False,
                                online_orderable=False,
                                description="Opening stock: selling price and physical photos pending confirmation.",
                            )
                            variant = ProductVariant.objects.create(product=product, sku=sku)
                        if (
                            not variant.active
                            or not variant.product.active
                            or variant.product.category_id != category.pk
                            or variant.product.product_type != Product.STOCK_ITEM
                        ):
                            raise CommandError(f"SKU conflict: {sku}")
                        lines.append(
                            {
                                "variant_id": variant.pk,
                                "received_quantity": quantity,
                                "unit_cost": cost,
                                "placements": [{"shelf_id": shelves[label].pk, "quantity": quantity}],
                            }
                        )
                    complete_stock_receipt(
                        supplier_name=round["supplier"],
                        external_reference=round["reference"],
                        received_at=datetime.fromisoformat(round["date"]).replace(tzinfo=ZoneInfo("Africa/Nairobi")),
                        notes=round["notes"],
                        idempotency_key=round["key"],
                        lines=lines,
                    )
                    if options["dry_run"]:
                        transaction.set_rollback(True)
                    self.stdout.write(
                        f"{round['key']}: {'would receive' if options['dry_run'] else 'received'} ({len(lines)} lines)"
                    )
            except (CommandError, ValidationError) as exc:
                raise CommandError(f"{round['key']}: rejected: {exc}") from exc
