"""Loans recorded as the business's money that were all the owner's own (2026-11-25, owner: "all the loans were my own
money"): each is moved over with loans.make_own, as the Money lent page's "It was my own money" does.

    manage.py make_loans_own --business <id>            (shows what it would do)
    manage.py make_loans_own --business <id> --apply    (records it)
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Move every loan of the business's money to the owner's own money."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, business, apply, **options):
        from apps.accounting.loans import business_loans, make_own, still_owed
        from apps.accounting.money_check import places
        from apps.tenancy.context import organization_context
        from apps.tenancy.models import Organization
        org = Organization.objects.filter(pk=business).first()
        if not org:
            raise CommandError("No such business.")
        show = lambda: ", ".join(f"{p['label']} {p['expected']}" for p in places())
        with organization_context(org), transaction.atomic():
            self.stdout.write(f"{org.name}: {show()}; lent, owed to the business {sum(r['owed'] for r in still_owed())}")
            for loan in business_loans().order_by("pk"):
                make_own(loan=loan, user=org.owner)
                self.stdout.write(f"  loan {loan.pk} {loan.borrower_name} {loan.amount:,.2f} -> own money")
            self.stdout.write(f"After: {show()}; lent, owed to the business {sum(r['owed'] for r in still_owed())}")
            if not apply:
                transaction.set_rollback(True)
                self.stdout.write("Nothing recorded (add --apply to record it).")
            else:
                self.stdout.write(self.style.SUCCESS("Recorded."))
