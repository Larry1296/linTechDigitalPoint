"""Repairs commission undone before the fix that dates an undo on the day the commission was counted.

Before it, undoing commission earned in one month and paid in the next took its income out on the day of the undo:
the month it was earned kept it, and that day's sales fell by it (e.g. 780 of sales showed as -240). Nothing is edited
or deleted: for each such undo, one correcting entry takes the income out of the day it was counted and another puts
the same amount back on the day of the undo, so each month shows what really happened. Skipped when either day's books
are closed. Safe to run more than once. Without --apply it only lists what it would correct.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

KEYS = ("commission-earned-reversal:", "commission-reversal:")


def misdated(JournalEntry):
    """Commission undos posted on a later day than the entry they cancel, and not corrected yet."""
    rows = []
    wanted = Q(source_key__startswith=KEYS[0]) | Q(source_key__startswith=KEYS[1])
    for undo in JournalEntry.objects.filter(wanted).select_related("reversal_of").order_by("pk"):
        original = undo.reversal_of
        if original and undo.posting_date != original.posting_date and \
                not JournalEntry.objects.filter(source_key=f"redate:{undo.pk}:counted").exists():
            rows.append((undo, original))
    return rows


def correct(undo, original, user=None):
    from apps.accounting.ledger import post_journal
    lines = [(line.account.code, line.debit, line.credit) for line in undo.lines.select_related("account")]
    why = f"Correction: undo of {original.description} belongs on {original.posting_date:%d %b %Y}, not {undo.posting_date:%d %b %Y}"
    post_journal(key=f"redate:{undo.pk}:counted", description=why[:240], branch=undo.branch_id, date=original.posting_date,
                 user=user, lines=lines)
    post_journal(key=f"redate:{undo.pk}:undone", description=why[:240], branch=undo.branch_id, date=undo.posting_date,
                 user=user, lines=[(code, credit, debit) for code, debit, credit in lines])


class Command(BaseCommand):
    help = "Move commission undone on the wrong day back to the month it was counted in (add --apply to correct)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Post the correcting entries. Without it, only list them.")

    def handle(self, *args, **options):
        from apps.accounting.models import FinancialPeriod, JournalEntry
        from apps.core.models import AuditLog
        from apps.tenancy.context import organization_context
        from apps.tenancy.models import Organization
        total = 0
        for org in Organization.objects.all():
            with organization_context(org):
                closed = lambda day: FinancialPeriod.objects.filter(start__lte=day, end__gte=day, closed=True).exists()  # noqa: E731
                for undo, original in misdated(JournalEntry):
                    amount = sum((line.debit for line in undo.lines.all()), 0)
                    note = f"{org.name}: {original.description} ({amount}) undone {undo.posting_date}, counted {original.posting_date}"
                    if closed(undo.posting_date) or closed(original.posting_date):
                        self.stdout.write(f"SKIPPED, books closed: {note}")
                        continue
                    total += 1
                    if not options["apply"]:
                        self.stdout.write(f"Would correct: {note}")
                        continue
                    with transaction.atomic():
                        correct(undo, original, user=org.owner)
                        AuditLog.objects.create(action="LEDGER_CORRECTION", object_type="JournalEntry", object_id=str(undo.pk), user=org.owner,
                                                after={"moved": str(amount), "from": str(undo.posting_date), "to": str(original.posting_date)})
                    self.stdout.write(self.style.SUCCESS(f"Corrected: {note}"))
        if not options["apply"] and total:
            self.stdout.write("Run again with --apply to correct these.")
        elif not total:
            self.stdout.write("Nothing to correct.")
