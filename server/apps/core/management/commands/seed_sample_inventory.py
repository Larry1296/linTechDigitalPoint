from apps.tenancy.commands import LintechCommand
"""Seed sample catalog data and receive stock into existing exact compartments."""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import (
    Category, Product, ProductOptionType, ProductOptionValue,
    ProductVariant, ProductVariantOptionValue,
)
from apps.inventory.models import Shelf, ShelfStack, ShelfStackCategory, StockReceipt
from apps.inventory.services import complete_stock_receipt

IDEMPOTENCY_KEY = "seed-sample-inventory-v1"
# SKU, option values, selling price, unit cost, quantity, permanent compartment code.
COVERS = (
    ("SAMPLE-COVER-A15-BLK", ("Samsung Galaxy A15", "Black"), "350", "180", "12", "RIGHT-R01-L01-S01"),
    ("SAMPLE-COVER-A15-BLU", ("Samsung Galaxy A15", "Blue"), "375", "190", "8", "RIGHT-R01-L01-S01"),
    ("SAMPLE-COVER-IP13-CLR", ("iPhone 13", "Clear"), "500", "250", "6", "RIGHT-R01-L01-S02"),
    ("SAMPLE-COVER-SP20-RED", ("Tecno Spark 20", "Red"), "300", "150", "15", "RIGHT-R01-L01-S02"),
)
PADLOCKS = (
    ("SAMPLE-PADLOCK-40", ("40 mm",), "250", "130", "10", "BACKWALL-R01-L01-S01"),
    ("SAMPLE-PADLOCK-50", ("50 mm",), "400", "220", "7", "BACKWALL-R01-L01-S02"),
    ("SAMPLE-PADLOCK-60", ("60 mm",), "600", "350", "4", "BACKWALL-R01-L02-S01"),
)


class Command(LintechCommand):
    help = "Create sample covers and padlocks and receive stock once into existing racks."

    @transaction.atomic
    def handle(self, *args, **options):
        # Serialize concurrent invocations using existing racks in a stable order.
        racks = {rack.code: rack for rack in ShelfStack.objects.select_for_update().filter(
            code__in=["RIGHT-R01", "BACKWALL-R01"]
        ).order_by("code")}
        existing = StockReceipt.objects.filter(idempotency_key=IDEMPOTENCY_KEY).first()
        if existing:
            self.stdout.write(self.style.SUCCESS(f"Sample inventory already received: {existing.receipt_number}."))
            return
        for code in ("RIGHT-R01", "BACKWALL-R01"):
            if code not in racks or not racks[code].active or not racks[code].zone.active:
                raise CommandError(f"Required active rack {code} is missing or inactive; no sample data was written.")
        shelves = {}
        for *_, code in (*COVERS, *PADLOCKS):
            rack_code = code.split("-L")[0]
            shelf = Shelf.objects.filter(
                code=code, level__stack=racks[rack_code], zone_id=racks[rack_code].zone_id,
                active=True, level__active=True,
            ).first()
            if shelf is None:
                raise CommandError(f"Required active compartment {code} is missing or inactive; no sample data was written.")
            shelves[code] = shelf

        def category(name, slug, parent=None):
            # The unique slug identifies the category; retain its PK and all
            # product/rack references while reconciling editable metadata.
            obj, _ = Category.objects.select_for_update().get_or_create(
                slug=slug, defaults={"name": name, "parent": parent},
            )
            changes = {"name": name, "parent_id": parent.pk if parent else None, "active": True}
            changed_fields = [field for field, value in changes.items() if getattr(obj, field) != value]
            if changed_fields:
                for field in changed_fields:
                    setattr(obj, field, changes[field])
                obj.save(update_fields=[*changed_fields, "updated_at"])
            return obj

        phone = category("Phone Accessories", "phone-accessories")
        electrical = category("Electrical & Masonry Accessories", "electrical-masonry-accessories")
        category("Computer Accessories", "computer-accessories")
        covers = category("Smartphone Covers", "smartphone-covers", phone)
        padlocks = category("Padlocks", "padlocks", electrical)
        for rack_code, categories in (("RIGHT-R01", (phone, covers)), ("BACKWALL-R01", (electrical, padlocks))):
            for assigned in categories:
                # Adopting the category updates existing assignments through
                # their FK; preserve each assignment's identity and primary flag.
                ShelfStackCategory.objects.get_or_create(stack=racks[rack_code], category=assigned)

        lines = []
        for name, slug, assigned, option_names, variants in (
            ("Smartphone Cover", "sample-smartphone-cover", covers, ("Phone Model", "Colour"), COVERS),
            ("Padlock", "sample-padlock", padlocks, ("Size",), PADLOCKS),
        ):
            product, _ = Product.objects.get_or_create(slug=slug, defaults={"name": name, "category": assigned})
            if product.category_id != assigned.pk or not product.active or product.product_type != Product.STOCK_ITEM:
                raise CommandError(f"Existing product {slug} conflicts with sample data.")
            from apps.catalog.image_library import assign_product_image
            assign_product_image(product)
            for sku, values, price, cost, quantity, code in variants:
                variant, _ = ProductVariant.objects.get_or_create(
                    sku=sku, defaults={"product": product, "name": " / ".join(values), "selling_price": Decimal(price)},
                )
                if variant.product_id != product.pk or not variant.active:
                    raise CommandError(f"Existing SKU {sku} conflicts with sample data.")
                for option_name, value in zip(option_names, values):
                    option, _ = ProductOptionType.objects.get_or_create(product=product, name=option_name)
                    option_value, _ = ProductOptionValue.objects.get_or_create(option_type=option, value=value)
                    ProductVariantOptionValue.objects.get_or_create(variant=variant, value=option_value)
                lines.append({
                    "variant_id": variant.pk, "received_quantity": quantity, "unit_cost": cost,
                    "placements": [{"shelf_id": shelves[code].pk, "quantity": quantity}],
                })
        receipt = complete_stock_receipt(
            supplier_name="Sample Inventory Supplier", external_reference="SAMPLE-INVENTORY-V1",
            notes="Sample inventory seeded by seed_sample_inventory.", lines=lines,
            idempotency_key=IDEMPOTENCY_KEY,
        )
        self.stdout.write(self.style.SUCCESS(f"Sample inventory received: {receipt.receipt_number} ({len(lines)} variants)."))
