"""Money lent to people and paid back.

Lending moves money out of cash into "Money lent out" (1150), an asset: the business is owed it, so it is
neither an expense nor a sale and profit does not change. A repayment moves it back into cash. Both appear in
the cash book (kind LOAN) so daily cash counts stay right. Mistakes are corrected by cancelling the loan or
reversing a repayment, which post the opposite entries; nothing is edited or deleted.
"""
from datetime import datetime, time
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .ledger import cash_code, money, paired, post_journal, resolve_branch, reverse_journal
from .models import CashEntry, JournalEntry, Loan, LoanRepayment
from .services import audit, post, reverse as reverse_cash

METHODS = {"CASH", "MPESA", "BANK", "OTHER"}


def _method(value):
    method = str(value or "").upper()
    if method not in METHODS:
        raise ValidationError("Choose cash, M-Pesa, bank or other.")
    return method


def repaid(loan):
    return loan.repayments.filter(reversed_at__isnull=True).aggregate(v=Sum("amount"))["v"] or Decimal("0")


def outstanding(loan):
    return Decimal("0") if loan.cancelled_at else loan.amount - repaid(loan)


def status(loan, today=None):
    if loan.cancelled_at:
        return "CANCELLED"
    left = outstanding(loan)
    if left <= 0:
        return "REPAID"
    if loan.due_date < (today or timezone.localdate()):
        return "OVERDUE"
    return "PARTLY_REPAID" if left < loan.amount else "OUTSTANDING"


@transaction.atomic
def lend(*, user, borrower_name, borrower_phone="", amount, method, due_date, lent_on=None, notes="", key):
    lock_business()
    existing = Loan.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    name = " ".join(str(borrower_name or "").split())
    if len(name) < 2:
        raise ValidationError("Enter the name of the person borrowing.")
    amount, method = money(amount), _method(method)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    lent_on = lent_on or timezone.localdate()
    if lent_on > timezone.localdate():
        raise ValidationError("The lending date cannot be in the future.")
    if not due_date or due_date < lent_on:
        raise ValidationError("Choose the agreed payback date, on or after the day the money was lent.")
    branch = resolve_branch()
    occurred = timezone.now() if lent_on == timezone.localdate() else timezone.make_aware(datetime.combine(lent_on, time(12)))
    entry = post(unit="SHOP", method=method, amount=-amount, kind="LOAN", reference=f"Lent to {name}"[:160], key=f"loan:{key}",
                 user=user, occurred_at=occurred, reason=notes, branch=branch, journal=False)
    loan = Loan.objects.create(borrower_name=name[:120], borrower_phone=str(borrower_phone or "").strip()[:30], amount=amount, method=method,
                               lent_on=lent_on, due_date=due_date, notes=notes, entry=entry, branch=branch, idempotency_key=key, created_by=user)
    post_journal(key=f"loan:{loan.pk}", description=f"Lent to {name}, due {due_date:%d %b %Y}"[:240], branch=branch, date=lent_on, user=user,
                 lines=paired("1150", cash_code(method), amount))
    audit(loan, user, f"Lent {amount} to {name}, due {due_date}")
    return loan


@transaction.atomic
def repay(*, loan, user, amount, method, reference="", key):
    lock_business()
    existing = LoanRepayment.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.cancelled_at:
        raise ValidationError("This loan was cancelled.")
    amount, method, reference = money(amount), _method(method), str(reference or "").strip().upper()
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    if amount > outstanding(loan):
        raise ValidationError(f"Only {outstanding(loan):,.2f} is still owed on this loan.")
    if method == "MPESA" and not reference:
        raise ValidationError("Enter the M-Pesa code so the repayment can be checked against your M-Pesa messages.")
    today = timezone.localdate()
    entry = post(unit="SHOP", method=method, amount=amount, kind="LOAN", reference=f"Repaid by {loan.borrower_name}"[:160],
                 key=f"loan-repayment:{key}", user=user, branch=loan.branch, journal=False)
    repayment = LoanRepayment.objects.create(loan=loan, amount=amount, method=method, reference=reference[:120], received_on=today,
                                             entry=entry, idempotency_key=key, created_by=user)
    post_journal(key=f"loan-repayment:{repayment.pk}", description=f"Repaid by {loan.borrower_name}"[:240], branch=loan.branch_id,
                 date=today, user=user, lines=paired(cash_code(method), "1150", amount))
    audit(repayment, user, f"{loan.borrower_name} repaid {amount}")
    return repayment


def _undo(entry, journal_key, *, user, reason, correction_key):
    """Reverses a loan cash entry and its journal together, so the cash book and ledger stay in step."""
    reverse_cash(entry=entry, user=user, reason=reason, allow_loan=True)
    journal = JournalEntry.objects.filter(source_key=journal_key).first()
    if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
        reverse_journal(journal, user=user, reason=reason, key=correction_key)


@transaction.atomic
def reverse_repayment(*, repayment, user, reason):
    """A repayment recorded by mistake (e.g. the money never arrived): the person owes it again."""
    lock_business()
    repayment = LoanRepayment.objects.select_for_update().get(pk=repayment.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the repayment is being reversed.")
    if repayment.reversed_at:
        return repayment
    _undo(repayment.entry, f"loan-repayment:{repayment.pk}", user=user, reason=reason, correction_key=f"loan-repayment-reversal:{repayment.pk}")
    LoanRepayment.objects.filter(pk=repayment.pk).update(reversed_at=timezone.now(), reverse_reason=reason.strip())
    repayment.refresh_from_db()
    return repayment


@transaction.atomic
def cancel_loan(*, loan, user, reason):
    """A loan recorded by mistake: the money goes back into cash. Only before anything was repaid."""
    lock_business()
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the loan is being cancelled.")
    if loan.cancelled_at:
        return loan
    if loan.repayments.filter(reversed_at__isnull=True).exists():
        raise ValidationError("Part of this loan has been repaid. Reverse those repayments first, or record the rest as it is paid back.")
    _undo(loan.entry, f"loan:{loan.pk}", user=user, reason=reason, correction_key=f"loan-cancel:{loan.pk}")
    Loan.objects.filter(pk=loan.pk).update(cancelled_at=timezone.now(), cancel_reason=reason.strip())
    loan.refresh_from_db()
    return loan
