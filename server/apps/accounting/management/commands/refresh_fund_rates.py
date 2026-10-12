"""Looks up the published rate of each fund that businesses' investments follow, when it is due (every 10 days).

    python manage.py refresh_fund_rates            only the funds that are due
    python manage.py refresh_fund_rates --force    look every fund up now

The scheduler service runs it every few hours; it does nothing until a fund is due, so running it often costs nothing.
A failed or unconfirmed look is tried again 6 hours later. See apps/accounting/fund_rates.py.
"""
from django.core.management.base import BaseCommand

from apps.accounting import fund_rates


class Command(BaseCommand):
    help = "Update the published interest rate of the money market funds businesses invest in (e.g. CIC)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Look the rates up now even if they are not due.")
        parser.add_argument("--fund", choices=sorted(fund_rates.FUNDS), help="Only this fund.")

    def handle(self, *args, force=False, fund=None, **options):
        for code in [fund] if fund else fund_rates.FUNDS:
            check = fund_rates.refresh(code, force=force)
            if check is None:
                current = fund_rates.latest(code)
                self.stdout.write(f"{code}: not due" + (f" ({current.annual_rate}% as of {current.as_of})" if current else " (no investment follows it)"))
            elif check.status == check.APPLIED:
                self.stdout.write(self.style.SUCCESS(f"{code}: {check.annual_rate}% a year as of {check.as_of} ({check.source_url})"))
            else:
                self.stdout.write(self.style.WARNING(f"{code}: {check.status.lower()}: {check.message}"))
