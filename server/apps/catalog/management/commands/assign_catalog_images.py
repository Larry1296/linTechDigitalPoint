from django.core.management.base import BaseCommand
from django.db import transaction
from apps.catalog.models import Product
from apps.catalog.image_library import assign_product_image


class Command(BaseCommand):
    help = "Assign matching AI images to products without photos or with seed placeholders."

    @transaction.atomic
    def handle(self, *args, **options):
        count = 0
        for product in Product.objects.select_for_update().select_related("category"):
            from apps.catalog.image_library import image_choices
            if not image_choices(product.category, product.name):
                continue
            product.images.filter(image_url__startswith="https://placehold.co/").delete()
            if assign_product_image(product):
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Assigned {count} product images."))
