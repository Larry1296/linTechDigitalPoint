"""Spare money kept in an investment such as a money market fund (MMF), and taken back out.

Putting money in moves it from cash, M-Pesa, bank or the agency's cash or float into "Investments" (1400), an
asset: it is still the business's money, so it is neither an expense nor income and profit does not change.
Taking it out moves it back. Interest is income (4910) and fees are an expense (6200); both are usually worked
out from the fund's statement balance. Business money appears in the cash book (kind INVESTMENT); agency money
goes through the open agency shift (type INVESTMENT) so the desk's cash and float stay right. The owner's own money
from outside the business (OWNER) is owner capital (3000) put straight into the investment, so no till, drawer or
bank changes and any amount can be put in; taken out to the owner, it is the owner taking capital back. Mistakes are
undone, never edited or deleted.
"""
from datetime import datetime, time
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .ledger import cash_code, money, paired, post_journal, resolve_branch, reverse_journal
from .models import Investment, InvestmentMovement, JournalEntry
from .services import audit, post, reverse as reverse_cash

BUSINESS = {"CASH", "MPESA", "BANK", "OTHER"}
AGENCY = {"AGENCY_CASH", "AGENCY_FLOAT"}
OWNER = "OWNER"
SOURCES = BUSINESS | AGENCY | {OWNER}
SIGN = {InvestmentMovement.DEPOSIT: 1, InvestmentMovement.INTEREST: 1, InvestmentMovement.WITHDRAWAL: -1, InvestmentMovement.FEE: -1}


def _live(investment):
    return investment.movements.filter(reversed_at__isnull=True)


def totals(investment):
    """{kind: total} of everything not undone."""
    rows = _live(investment).values("kind").annotate(v=Sum("amount"))
    result = {kind: Decimal("0") for kind in SIGN}
    result.update({row["kind"]: row["v"] for row in rows})
    return result


def value(investment):
    """What the investment holds now, as far as the app knows: put in, less taken out, plus interest, less fees."""
    return sum((SIGN[kind] * amount for kind, amount in totals(investment).items()), Decimal("0"))


def _amount(raw):
    amount = money(raw)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    return amount


def _day(occurred_on):
    day = occurred_on or timezone.localdate()
    if day > timezone.localdate():
        raise ValidationError("The date cannot be in the future.")
    return day


def _moment(day):
    return timezone.now() if day == timezone.localdate() else timezone.make_aware(datetime.combine(day, time(12)))


def _agency_session(session_id):
    from apps.mpesa.models import MpesaSession
    sessions = MpesaSession.objects.filter(status=MpesaSession.OPEN).select_related("outlet")
    if session_id:
        sessions = sessions.filter(pk=session_id)
    found = list(sessions[:2])
    if not found:
        raise ValidationError("Open the M-Pesa agency shift first: agency cash and float can only move while a shift is open.")
    if len(found) > 1:
        raise ValidationError("Choose which M-Pesa outlet the money comes from or goes to.")
    return found[0]


@transaction.atomic
def open_investment(*, user, name, account_number="", notes="", tax_rate=Decimal("15")):
    lock_business()
    name = " ".join(str(name or "").split())
    if len(name) < 2:
        raise ValidationError("Enter the name of the fund or account, e.g. Sanlam MMF.")
    if Investment.objects.filter(name__iexact=name).exists():
        raise ValidationError("You already have an investment with this name.")
    investment = Investment.objects.create(name=name[:120], account_number=str(account_number or "").strip()[:60],
                                           notes=str(notes or "").strip(), tax_rate=tax_rate, created_by=user)
    audit(investment, user, f"Investment account {name} added")
    return investment


@transaction.atomic
def move(*, investment, user, kind, amount, source, key, occurred_on=None, reference="", note="", session_id=None, purchase=None):
    """Money put in (DEPOSIT) or taken out (WITHDRAWAL); a withdrawal may name the stock purchase it paid for."""
    lock_business()
    existing = InvestmentMovement.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    investment = Investment.objects.select_for_update().get(pk=investment.pk)
    if kind not in {InvestmentMovement.DEPOSIT, InvestmentMovement.WITHDRAWAL}:
        raise ValidationError("Choose money put in or money taken out.")
    source = str(source or "").upper()
    if source not in SOURCES:
        raise ValidationError("Choose cash, M-Pesa, bank, other, agency cash, agency float or your own money.")
    amount, day = _amount(amount), _day(occurred_on)
    putting_in = kind == InvestmentMovement.DEPOSIT
    if not putting_in and amount > value(investment):
        raise ValidationError(f"{investment.name} only holds {value(investment):,.2f} as far as the app knows. "
                              "If the statement shows more, record the interest first.")
    reference = str(reference or "").strip().upper()[:120]
    words = f"{'Put into' if putting_in else 'Taken out of'} {investment.name}"
    entry = agency = None
    if source == OWNER:
        branch = resolve_branch()
        lines = paired("1400", "3000", amount) if putting_in else paired("3000", "1400", amount)
    elif source in AGENCY:
        if day != timezone.localdate():
            raise ValidationError("Agency cash and float can only be moved today, through the open shift.")
        from apps.mpesa.services import post_transaction
        session = _agency_session(session_id)
        change = -amount if putting_in else amount
        agency, _ = post_transaction(session=session, transaction_type="INVESTMENT", transaction_amount=amount, user=user,
                                     idempotency_key=f"investment:{key}", notes=words,
                                     cash_delta=change if source == "AGENCY_CASH" else 0, float_delta=change if source == "AGENCY_FLOAT" else 0)
        branch = session.outlet.store
        # The agency side already posted against owner capital (3000); this moves it from there into the investment.
        lines = paired("1400", "3000", amount) if putting_in else paired("3000", "1400", amount)
    else:
        branch = resolve_branch()
        entry = post(unit="SHOP", method=source, amount=-amount if putting_in else amount, kind="INVESTMENT", reference=words[:160],
                     key=f"investment:{key}", user=user, occurred_at=_moment(day), reason=note, branch=branch, journal=False)
        lines = paired("1400", cash_code(source), amount) if putting_in else paired(cash_code(source), "1400", amount)
    movement = InvestmentMovement.objects.create(investment=investment, kind=kind, amount=amount, occurred_on=day, source=source,
                                                 reference=reference, note=str(note or "").strip(), entry=entry, agency_transaction=agency, purchase=purchase,
                                                 branch=branch, idempotency_key=key, created_by=user)
    post_journal(key=f"investment:{movement.pk}", description=words[:240], branch=branch, date=day, user=user, lines=lines)
    audit(movement, user, f"{words}: {amount}")
    return movement


@transaction.atomic
def pay_supplier(*, investment_id, purchase, amount, via, key, user, reference=""):
    """Stock paid for with invested money: it is taken out into M-Pesa or the bank and paid straight on to the supplier.

    Both are recorded together, so the till or bank is unchanged, the investment goes down and the supplier is paid.
    """
    from apps.tenancy.permissions import has_business_permission
    from .services import pay_purchase
    lock_business()
    if not user or not has_business_permission(user, "accounting.add_investmentmovement"):
        raise ValidationError("You are not allowed to take money out of investments. Pay from cash, M-Pesa or bank instead.")
    via = str(via or "").upper()
    if via not in BUSINESS:
        raise ValidationError("Choose where the money from the investment lands before it is paid: M-Pesa or bank.")
    investment = Investment.objects.filter(pk=investment_id).first()
    if not investment:
        raise ValidationError("Choose which investment the money comes out of.")
    receipt = purchase.receipt.receipt_number
    supplier = purchase.supplier.name if purchase.supplier_id else "the supplier"
    move(investment=investment, user=user, kind=InvestmentMovement.WITHDRAWAL, amount=amount, source=via, key=f"{key}:investment",
         reference=reference or receipt, note=f"To pay {supplier} for stock {receipt}", purchase=purchase)
    return pay_purchase(purchase=purchase, amount=amount, method=via, key=key, user=user, reference=reference)


@transaction.atomic
def record_statement(*, investment, user, balance, key, occurred_on=None, note=""):
    """The balance on the fund's statement: the difference from what the app expects is interest (or fees, if lower)."""
    lock_business()
    existing = InvestmentMovement.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    investment = Investment.objects.select_for_update().get(pk=investment.pk)
    balance, day = money(balance), _day(occurred_on)
    if balance < 0:
        raise ValidationError("A statement balance cannot be below zero.")
    difference = balance - value(investment)
    if not difference:
        raise ValidationError(f"The statement agrees with the app: {investment.name} holds {balance:,.2f}. Nothing to record.")
    kind = InvestmentMovement.INTEREST if difference > 0 else InvestmentMovement.FEE
    amount = abs(difference)
    branch = resolve_branch()
    movement = InvestmentMovement.objects.create(investment=investment, kind=kind, amount=amount, occurred_on=day,
                                                 note=str(note or "").strip(), statement_balance=balance, branch=branch,
                                                 idempotency_key=key, created_by=user)
    words = f"{'Interest earned on' if kind == InvestmentMovement.INTEREST else 'Fees or loss on'} {investment.name}"
    post_journal(key=f"investment:{movement.pk}", description=words[:240], branch=branch, date=day, user=user,
                 lines=paired("1400", "4910", amount) if kind == InvestmentMovement.INTEREST else paired("6200", "1400", amount))
    audit(movement, user, f"{words}: {amount} (statement {balance})")
    return movement


@transaction.atomic
def undo(*, movement, user, reason):
    """A movement recorded by mistake: its money goes back where it was and the investment's value follows."""
    lock_business()
    movement = InvestmentMovement.objects.select_for_update(of=("self",)).select_related("investment").get(pk=movement.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Say why this is being undone.")
    if movement.reversed_at:
        return movement
    if SIGN[movement.kind] > 0 and value(movement.investment) - movement.amount < 0:
        raise ValidationError("Money has since been taken out of this investment. Undo that first.")
    if movement.agency_transaction_id:
        from apps.mpesa.services import reverse_transaction
        reverse_transaction(original=movement.agency_transaction, user=user, idempotency_key=f"investment-undo:{movement.pk}",
                            reason=reason, allow_investment=True)
    if movement.entry_id:
        reverse_cash(entry=movement.entry, user=user, reason=reason, allow_investment=True)
    journal = JournalEntry.objects.filter(source_key=f"investment:{movement.pk}").first()
    if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
        reverse_journal(journal, user=user, reason=reason, key=f"investment-undo:{movement.pk}")
    InvestmentMovement.objects.filter(pk=movement.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    movement.refresh_from_db()
    return movement
