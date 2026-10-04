"""Re-crops stored business logos to their design, for logos uploaded before trimming ignored border lines."""
from django.core.management.base import BaseCommand
from PIL import Image

from apps.tenancy.logos import fit, png, trim
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Crop the empty margins off every stored business logo (light and dark versions)."

    def handle(self, *args, **options):
        for organization in Organization.objects.exclude(logo="").order_by("pk"):
            for field in (organization.logo, organization.logo_dark):
                if not field:
                    continue
                with field.open("rb") as stored, Image.open(stored) as source:
                    image = source.convert("RGBA")
                cropped = fit(trim(image))
                if cropped.size == image.size and trim(image).size == image.size:
                    continue
                with field.storage.open(field.name, "wb") as target:
                    target.write(png(cropped, "logo.png").read())
                self.stdout.write(f"{organization.name}: {field.name} {image.size} -> {cropped.size}")
