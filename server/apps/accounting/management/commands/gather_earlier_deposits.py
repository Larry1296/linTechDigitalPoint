"""The business's money put in from one place while its other places held money not invested yet, before every place
went in together (2026-11-18): that money is taken from the other places instead (investments.gather_earlier).

    manage.py gather_earlier_deposits --business <id> --since 2026-11-14            (shows what it would do)
    manage.py gather_earlier_deposits --business <id> --since 2026-11-14 --apply    (records it)
"""
from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Deposits of the business's money take what the other places held at the time, not unseen money."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, required=True)
        parser.add_argument("--since", required=True, help="First day to look at (YYYY-MM-DD).")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, business, since, apply, **options):
        from apps.accounting.investments import gather_earlier
        from apps.accounting.money_check import places
        from apps.tenancy.context import organization_context
        from apps.tenancy.models import Organization
        org = Organization.objects.filter(pk=business).first()
        if not org:
            raise CommandError("No such business.")
        show = lambda: ", ".join(f"{p['label']} {p['expected']}" for p in places())
        with organization_context(org):
            with transaction.atomic():
                self.stdout.write(f"{org.name}: {show()}")
                for movement, taken in gather_earlier(since=date.fromisoformat(since), user=org.owner):
                    self.stdout.write(f"  {movement.occurred_on} {movement.amount:,.2f} into {movement.investment.name}: "
                                      f"{taken:,.2f} of it from the other places")
                self.stdout.write(f"After: {show()}")
                if not apply:
                    transaction.set_rollback(True)
                    self.stdout.write("Nothing recorded (add --apply to record it).")
                else:
                    self.stdout.write(self.style.SUCCESS("Recorded."))
