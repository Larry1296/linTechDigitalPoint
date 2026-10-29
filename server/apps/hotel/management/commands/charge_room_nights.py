"""Charges every checked-in guest the nights that are due, in every business with rooms (the scheduler runs this)."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Charge checked-in hotel guests the nights that are due."

    def handle(self, *args, **options):
        from apps.hotel import rooms
        from apps.tenancy.middleware import effective_modules
        for organization in Organization.objects.filter(active=True):
            if "rooms" not in effective_modules(organization):
                continue
            try:
                with organization_context(organization), timezone.override(ZoneInfo(organization.timezone)):
                    rooms.bring_up_to_date()
            except Exception as error:  # one business's problem never stops the others
                self.stderr.write(f"{organization.pk}: {error}")
