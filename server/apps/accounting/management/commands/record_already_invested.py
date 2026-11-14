"""Record that the money the app expects in a business's place is already in one of its investments.

    manage.py record_already_invested --business <id> --place CASH --fund "CIC MMF"            (shows what it would do)
    manage.py record_already_invested --business <id> --place CASH --fund "CIC MMF" --apply    (records it)

For an owner who keeps all the business's money in an investment: the place is brought to zero and the investment,
sales and profit stay as they are (see investments.already_invested)."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Bring a place to zero: its money is already in an investment."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, required=True)
        parser.add_argument("--place", choices=["CASH", "MPESA", "BANK", "OTHER"], required=True)
        parser.add_argument("--fund", required=True, help="The investment the money is in, by name.")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, business, place, fund, apply, **options):
        from apps.accounting.investments import already_invested, business_value
        from apps.accounting.models import Investment
        from apps.accounting.money_check import expected, kept_in_investments
        from apps.tenancy.context import organization_context
        from apps.tenancy.models import Organization
        org = Organization.objects.filter(pk=business).first()
        if not org:
            raise CommandError("No such business.")
        with organization_context(org):
            investment = Investment.objects.filter(name=fund, removed_at__isnull=True).first()
            if not investment:
                raise CommandError(f"{org.name} has no investment named {fund!r}.")
            before = expected(place)[0]
            self.stdout.write(f"{org.name}: {place} expected {before}; business money in {fund} {business_value(investment)}; "
                              f"in all investments {kept_in_investments()['total']}")
            with transaction.atomic():
                made = already_invested(method=place, fund=fund, user=org.owner)
                for entry in made:
                    self.stdout.write(f"  {entry.business_unit} {entry.account.payment_method} {entry.amount}  {entry.reference}")
                self.stdout.write(f"{place} expected after: {expected(place)[0]}; business money in {fund}: {business_value(investment)}")
                if not apply:
                    transaction.set_rollback(True)
                    self.stdout.write("Nothing recorded (add --apply to record it).")
                else:
                    self.stdout.write(self.style.SUCCESS("Recorded."))
