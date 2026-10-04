"""Legacy setup commands are intentionally restricted to the migrated business."""
from django.core.management.base import BaseCommand, CommandError
from .context import organization_context
from .models import Organization

class LintechCommand(BaseCommand):
    def execute(self, *args, **options):
        organization = Organization.objects.filter(slug="lintech-digital-point").first()
        if not organization:
            raise CommandError("Migrate the legacy linTech organization before running this command.")
        with organization_context(organization):
            return super().execute(*args, **options)
