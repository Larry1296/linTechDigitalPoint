"""Money kept in an investment such as a money market fund (MMF), and taken back out.

Each time money is put in or taken out the owner says whose it is:
- The business's money (BUSINESS): taken from one of its places (cash drawer, Lipa na M-Pesa till, bank, other) and
  kept in the investment until it is needed, e.g. for stock, then taken back to a place or paid to a supplier. It is
  still the business's money, only kept somewhere else: the place goes down and "Investments" (1400) goes up by the same
  amount, so its money, net worth, sales, costs and each part's figures stay as they are.
- The owner's own money (OWNER): never in the books, and never from or into the business's places.
The interest each statement shows (its balance less what the app expects: put in, less taken out, plus interest and
less fees recorded before) is all the business's profit ("Interest earned on investments", 4910) and adds to the
business's money in the investment; fees or a loss lower both (6200). The Investments page shows how much of each
investment is the business's and how much the owner's own. Mistakes are undone, never edited or deleted.

Records from before (money moved through the business's places with a business share, from before 2026-10-25) were
separated once by settle_books() and stay as the owner's own. The M-Pesa agency's cash and float are never used.
"""
from datetime import datetime, time
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .ledger import money, paired, post_journal, resolve_branch, reverse_journal
from .models import CashEntry, Investment, InvestmentMovement, JournalEntry
from .services import audit, post, reverse as reverse_cash

BUSINESS = {"CASH", "MPESA", "BANK", "OTHER"}
AGENCY = {"AGENCY_CASH", "AGENCY_FLOAT"}
OWNER = "OWNER"
EARLIER = "EARLIER"
# Where money once came from or went before investments were kept apart from the business; only OWNER is used now.
WORDS = {"CASH": "the cash drawer", "MPESA": "the Lipa na M-Pesa till", "BANK": "the bank", "OTHER": "other money",
         "AGENCY_CASH": "the agency's cash", "AGENCY_FLOAT": "the agency's float", EARLIER: "business money put in earlier"}
BUSINESS_MONEY = "BUSINESS"
SOURCES = {OWNER, BUSINESS_MONEY}
PLACE_WORDS = {"CASH": "the cash drawer", "MPESA": "the Lipa na M-Pesa till", "BANK": "the bank", "OTHER": "other money"}
APART = ("Say whose money it is: the business's, from or back to its cash drawer, till, bank or other money, or your own. "
         "The M-Pesa agency's cash and float are never used.")
# Kinds of investment and how risky each is, from 1 (safest) to 5. A money market fund lends short term to the
# government and banks, so its value rarely falls; shares can fall a lot. It is the kind's risk, not a rating of the
# fund manager: a fund's own fact sheet gives its risk profile.
KINDS = {
    "MMF": {"label": "Money market fund", "risk": 1, "risk_label": "Low",
            "risk_note": "Short-term loans to the government and banks. The value rarely falls and you can usually withdraw in a few days."},
    "TBILL": {"label": "Treasury bills or bonds", "risk": 1, "risk_label": "Low",
              "risk_note": "Lent to the Government of Kenya. Bills are safe if held to the end; bonds sold early can lose value."},
    "FIXED_DEPOSIT": {"label": "Bank fixed deposit", "risk": 1, "risk_label": "Low",
                      "risk_note": "Kept at a bank for a fixed time. Taking it out early can cost the interest."},
    "SACCO": {"label": "Sacco deposits", "risk": 2, "risk_label": "Low to medium",
              "risk_note": "Safe in a well-run Sacco licensed by SASRA; it depends on how the Sacco is managed. Deposits are often slow to withdraw."},
    "FIXED_INCOME": {"label": "Fixed income or bond fund", "risk": 2, "risk_label": "Low to medium",
                     "risk_note": "Longer loans to the government and companies. The value can dip when interest rates rise."},
    "BALANCED": {"label": "Balanced fund", "risk": 3, "risk_label": "Medium",
                 "risk_note": "Part bonds, part shares. The value goes up and down; best left for a few years."},
    "EQUITY": {"label": "Shares or equity fund", "risk": 4, "risk_label": "High",
               "risk_note": "Shares in companies. The value can fall a lot in a bad year; only money you will not need for years."},
    "OTHER": {"label": "Other", "risk": None, "risk_label": "Unknown",
              "risk_note": "Ask where the money is kept and whether the scheme is licensed by the CMA, CBK or SASRA."},
}


def kind_row(kind):
    return {"code": kind, **KINDS.get(kind, KINDS["OTHER"])}


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


def _business(movement):
    return movement.amount if movement.business_amount is None else movement.business_amount


def business_value(investment):
    """The part of what the investment holds that is the business's money, as in the books (1400)."""
    return sum((SIGN[m.kind] * _business(m) for m in _live(investment)), Decimal("0"))


def shares(investment):
    """How the investment splits between the business and the owner's own money from outside it:
    {shop, owner}: the money put in and not taken out, by where it came from (together, the total invested);
    {shop_interest, owner_interest}: each one's share of the interest less fees; {shop_value, owner_value}: what each holds now."""
    put = {"shop": Decimal("0"), "owner": Decimal("0")}
    earned = {"shop": Decimal("0"), "owner": Decimal("0")}
    for m in _live(investment):
        mine = _business(m)
        target = put if m.kind in (InvestmentMovement.DEPOSIT, InvestmentMovement.WITHDRAWAL) else earned
        target["shop"] += SIGN[m.kind] * mine
        target["owner"] += SIGN[m.kind] * (m.amount - mine)
    held = {side: put[side] + earned[side] for side in put}
    # Interest taken out shows as less put in; what was put in never shows below zero.
    principal = {side: min(max(put[side], Decimal("0")), max(held[side], Decimal("0"))) for side in put}
    return {"shop": principal["shop"], "owner": principal["owner"], "shop_interest": earned["shop"], "owner_interest": earned["owner"],
            "shop_value": held["shop"], "owner_value": held["owner"]}


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


@transaction.atomic
def open_investment(*, user, name, account_number="", notes="", tax_rate=Decimal("15"), kind="MMF"):
    lock_business()
    name = " ".join(str(name or "").split())
    if kind not in KINDS:
        raise ValidationError("Choose what kind of investment it is.")
    if len(name) < 2:
        raise ValidationError("Enter the name of the fund or account, e.g. Sanlam MMF.")
    if Investment.objects.filter(name__iexact=name, removed_at__isnull=True).exists():
        raise ValidationError("You already have an investment with this name.")
    # A removed account keeps its history under its old name; the name is freed by renaming it.
    for old in Investment.objects.filter(name__iexact=name, removed_at__isnull=False):
        Investment.objects.filter(pk=old.pk).update(name=f"{old.name[:90]} (removed #{old.pk})")
    investment = Investment.objects.create(name=name[:120], account_number=str(account_number or "").strip()[:60],
                                           notes=str(notes or "").strip(), tax_rate=tax_rate, kind=kind, created_by=user)
    audit(investment, user, f"Investment account {name} added")
    return investment


def own_value(investment):
    """What the investment holds of the owner's own money."""
    return value(investment) - business_value(investment)


@transaction.atomic
def move(*, investment, user, kind, amount, source=OWNER, place=None, unit=None, key, occurred_on=None, reference="", note="",
         session_id=None, purchase=None):
    """Money put in (DEPOSIT) or taken out (WITHDRAWAL). source BUSINESS: the business's money, from or back to ``place``
    (CASH, MPESA, BANK or OTHER), moved in the books between that place and Investments (1400). source OWNER: the
    owner's own money, which never reaches the books. A withdrawal may name the stock purchase it paid for."""
    from .ledger import cash_code
    from .money_check import _drawer, expected
    lock_business()
    existing = InvestmentMovement.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    investment = Investment.objects.select_for_update().get(pk=investment.pk)
    if investment.removed_at:
        raise ValidationError(f"{investment.name} was removed. Add it again to record money in it.")
    if kind not in {InvestmentMovement.DEPOSIT, InvestmentMovement.WITHDRAWAL}:
        raise ValidationError("Choose money put in or money taken out.")
    source = str(source or OWNER).upper()
    if source not in SOURCES:
        raise ValidationError(APART)
    business = source == BUSINESS_MONEY
    place = str(place or "").upper()
    if business and place not in BUSINESS:
        raise ValidationError("Choose where the business's money " + ("comes from" if kind == InvestmentMovement.DEPOSIT else "goes")
                              + ": the cash drawer, Lipa na M-Pesa till, bank or other money.")
    amount, day = _amount(amount), _day(occurred_on)
    putting_in = kind == InvestmentMovement.DEPOSIT
    unit = (_drawer(place, unit) or (unit if unit else "SHOP")) if business else None
    if business and putting_in:
        has = expected(place, unit if place == "CASH" and _drawer(place, unit) else None)[0]
        if amount > has:
            raise ValidationError(f"{PLACE_WORDS[place].capitalize()} only has {has:,.2f} of the business's money as far as the app knows. "
                                  "Put in what is there, or record the rest as your own money.")
    if not putting_in:
        holds = business_value(investment) if business else own_value(investment)
        if amount > holds:
            whose_words = "of the business's money" if business else "of your own money"
            raise ValidationError(f"{investment.name} only holds {holds:,.2f} {whose_words} as far as the app knows. "
                                  "If the statement shows more, record the interest first.")
    words = f"{'Put into' if putting_in else 'Taken out of'} {investment.name}"
    entry = None
    if business:
        from .services import post as post_cash
        entry = post_cash(unit=unit, method=place, amount=-amount if putting_in else amount, kind="INVESTMENT",
                          reference=f"{words}{' from' if putting_in else ' to'} {PLACE_WORDS[place]}"[:160], key=f"investment:{key}",
                          user=user, occurred_at=_moment(day), branch=resolve_branch(), journal=False)
    movement = InvestmentMovement.objects.create(investment=investment, kind=kind, amount=amount, business_amount=amount if business else Decimal("0"),
                                                 whose=source, occurred_on=day, source=place if business else OWNER, entry=entry,
                                                 reference=str(reference or "").strip().upper()[:120], note=str(note or "").strip(),
                                                 purchase=purchase, branch=resolve_branch(), idempotency_key=key, created_by=user)
    if business:
        lines = paired("1400", cash_code(place), amount) if putting_in else paired(cash_code(place), "1400", amount)
        post_journal(key=f"{MOVED}:{movement.pk}", description=f"{words}: the business's money, {'from' if putting_in else 'back to'} {PLACE_WORDS[place]}"[:255],
                     lines=lines, branch=movement.branch, date=day, user=user)
    audit(movement, user, f"{words}: {amount} ({'the business' + chr(39) + 's money' if business else 'own money'})")
    return movement


@transaction.atomic
def pay_supplier(*, investment_id, purchase, amount, key, user, reference="", via=None, occurred_at=None):
    """Stock paid for with investment money. The business's money in it pays first: taken out as the business's and
    paid on to the supplier, so it is the business's money put back into stock. Any rest is the owner's own money,
    taken out to the owner and paid on as the owner's own ("Owner's own money"). The till, drawer and bank are untouched."""
    from apps.tenancy.permissions import has_business_permission
    from .services import pay_purchase, purchase_outstanding
    from .supplier_settlement import owner_pays
    lock_business()
    if not user or not has_business_permission(user, "accounting.add_investmentmovement"):
        raise ValidationError("You are not allowed to take money out of investments. Pay from cash, M-Pesa or bank instead.")
    investment = Investment.objects.filter(pk=investment_id).first()
    if not investment:
        raise ValidationError("Choose which investment the money comes out of.")
    amount = _amount(amount)
    if amount > purchase_outstanding(purchase):
        raise ValidationError("Payment exceeds what is still owed to the supplier for this receipt.")
    receipt = purchase.receipt.receipt_number
    supplier = purchase.supplier.name if purchase.supplier_id else "the supplier"
    day = timezone.localtime(occurred_at).date() if occurred_at else None
    note = f"To pay {supplier} for stock {receipt}"
    business = min(amount, max(business_value(investment), Decimal("0")))
    own = amount - business
    if own > own_value(investment):
        raise ValidationError(f"{investment.name} only holds {value(investment):,.2f} as far as the app knows. "
                              "If the statement shows more, record the interest first.")
    paid = None
    if business:
        # Taken out to "other money" and paid straight on, so no place changes: only the investment and the debt go down.
        move(investment=investment, user=user, kind=InvestmentMovement.WITHDRAWAL, amount=business, source=BUSINESS_MONEY, place="OTHER",
             key=f"{key}:investment", occurred_on=day, reference=reference or receipt, note=note, purchase=purchase)
        paid = pay_purchase(purchase=purchase, amount=business, method="OTHER", key=key, user=user, reference=reference or receipt, occurred_at=occurred_at)
    if own:
        own_key = f"{key}-own" if business else key
        move(investment=investment, user=user, kind=InvestmentMovement.WITHDRAWAL, amount=own, key=f"{own_key}:investment",
             occurred_on=day, reference=reference or receipt, note=note, purchase=purchase)
        paid = owner_pays(purchase=purchase, amount=own, key=own_key, user=user, reference=reference or receipt, occurred_at=occurred_at,
                          words=f"Owner's own money from {investment.name} to pay {supplier} for {receipt}")
    return paid


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
    # The app's own prediction for the same date is kept beside it, so each statement shows how close the estimate was.
    from .investment_interest import estimate
    guess = estimate(investment, today=day)
    # All of what it earned (or lost) is the business's: its profit, kept in the investment as the business's money.
    movement = InvestmentMovement.objects.create(investment=investment, kind=kind, amount=amount, business_amount=amount, whose=BUSINESS_MONEY, occurred_on=day,
                                                 note=str(note or "").strip(), statement_balance=balance, branch=resolve_branch(),
                                                 predicted_interest=guess["net"] if guess else None,
                                                 predicted_since=guess["since"] if guess else None,
                                                 idempotency_key=key, created_by=user)
    words = f"{'Interest earned on' if kind == InvestmentMovement.INTEREST else 'Fees or loss on'} {investment.name}"
    audit(movement, user, f"{words}: {amount} (statement {balance})")
    book_earned(movement, user)
    return movement


MOVED = "investment-business"  # the business's money moved between a place and the investment
EARNED = "investment-interest"  # interest or fees: the business's profit, in the business's money in the investment
OWNER_HELD = "investment-earned"  # 2026-10-31 only: interest counted as profit but held as the owner's money (3000)


def book_earned(movement, user=None):
    """Interest a statement showed goes into profit and into the business's money in the investment; fees or a loss come
    out of both. Counted on the statement's date, or today when that month's books are closed."""
    from .models import FinancialPeriod
    day = movement.occurred_on
    if FinancialPeriod.objects.filter(start__lte=day, end__gte=day, closed=True).exists():
        day = timezone.localdate()
    name = movement.investment.name
    if movement.kind == InvestmentMovement.INTEREST:
        lines, words = paired("1400", "4910", movement.amount), f"Interest earned on {name}, kept in it as the business's money"
    else:
        lines, words = paired("6200", "1400", movement.amount), f"Fees or loss on {name}, from the business's money in it"
    return post_journal(key=f"{EARNED}:{movement.pk}", description=words[:255], lines=lines, branch=movement.branch, date=day, user=user)


def _reverse(key, user, reason, undo_key):
    """Reverses the journal posted under ``key`` (if any, and not reversed yet), in its own month unless that month is closed."""
    from .models import FinancialPeriod
    journal = JournalEntry.objects.filter(source_key=key).first()
    if not journal or JournalEntry.objects.filter(reversal_of=journal).exists():
        return
    day = journal.posting_date
    if FinancialPeriod.objects.filter(start__lte=day, end__gte=day, closed=True).exists():
        day = timezone.localdate()
    reverse_journal(journal, user=user, reason=reason, date=day, key=undo_key)


@transaction.atomic
def book_earnings():
    """Interest and fees recorded before they counted as the business's are counted once: profit, and the business's
    money in the investment. Those counted on 2026-10-31 as held by the owner (3000) are moved to the investment."""
    live = InvestmentMovement.objects.filter(kind__in=[InvestmentMovement.INTEREST, InvestmentMovement.FEE], reversed_at__isnull=True)
    booked = {int(key.rpartition(":")[2]) for key in JournalEntry.objects.filter(source_key__startswith=f"{EARNED}:").values_list("source_key", flat=True)
              if key.rpartition(":")[2].isdigit()}
    missing = [pk for pk in live.values_list("pk", flat=True) if pk not in booked]
    if not missing:
        return
    lock_business()
    for movement in live.filter(pk__in=missing).select_related("investment").order_by("occurred_on", "pk"):
        _reverse(f"{OWNER_HELD}:{movement.pk}", None, "Interest is the business's money in the investment", f"{OWNER_HELD}-moved:{movement.pk}")
        InvestmentMovement.objects.filter(pk=movement.pk).update(business_amount=movement.amount, whose=BUSINESS_MONEY)
        book_earned(movement)


@transaction.atomic
def undo(*, movement, user, reason):
    """A movement recorded by mistake: the investment's value follows, the business's money goes back to its place, and
    interest or fees it put into profit come out."""
    lock_business()
    settle_books()
    movement = InvestmentMovement.objects.select_for_update(of=("self",)).select_related("investment").get(pk=movement.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Say why this is being undone.")
    if movement.reversed_at:
        return movement
    if SIGN[movement.kind] > 0 and value(movement.investment) - movement.amount < 0:
        raise ValidationError("Money has since been taken out of this investment. Undo that first.")
    mine = movement.business_amount or Decimal("0")
    if SIGN[movement.kind] > 0 and mine and business_value(movement.investment) - mine < 0:
        raise ValidationError("The business's money has since been taken out of this investment. Undo that first.")
    InvestmentMovement.objects.filter(pk=movement.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    # The business's money goes back where it was, and interest or fees leave profit, in the month they were counted.
    if movement.whose == BUSINESS_MONEY and movement.entry_id and not CashEntry.objects.filter(reversal_of=movement.entry).exists():
        reverse_cash(entry=movement.entry, user=user, reason=reason, allow_investment=True)
    for prefix in (MOVED, EARNED, OWNER_HELD):
        _reverse(f"{prefix}:{movement.pk}", user, reason, f"{prefix}-undo:{movement.pk}")
    movement.refresh_from_db()
    return movement


def claim(*, movement, user, note=""):
    """Whose money it is is chosen when it is recorded; a wrong choice is undone and recorded again."""
    raise ValidationError(APART)


@transaction.atomic
def remove(*, investment, user, reason):
    """An investment account recorded by mistake: everything in it is undone, newest first, and the account no longer
    shows. Its history is kept, never deleted."""
    lock_business()
    investment = Investment.objects.select_for_update().get(pk=investment.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Say why this investment is being removed.")
    if investment.removed_at:
        return investment
    live = list(_live(investment).select_related("purchase__receipt").order_by("-occurred_on", "-pk"))
    paid = next((m for m in live if m.purchase_id), None)
    if paid:
        raise ValidationError(f"{investment.name} paid for stock {paid.purchase.receipt.receipt_number}. "
                              "Undo that supplier payment first, then remove the investment.")
    for movement in live:
        undo(movement=movement, user=user, reason=f"{investment.name} removed: {reason}")
    Investment.objects.filter(pk=investment.pk).update(removed_at=timezone.now(), removed_reason=reason, fund="")
    investment.refresh_from_db()
    audit(investment, user, f"Investment account {investment.name} removed: {reason}")
    return investment


SEPARATED = "Investment money kept apart from the business"


@transaction.atomic
def settle_books():
    """Records from before investment money was kept apart from the business, separated once: every journal they
    posted is reversed, money they moved into or out of the till, drawer, bank or "other" money is taken back out of
    it (so those places hold only the business's own money), and each record stays as the owner's own. Money taken
    out to pay a supplier becomes the owner's own money paying that supplier, so the supplier stays paid. Money moved
    through the M-Pesa agency stays as the agency recorded it: on the agency side it was already the owner's money
    coming in or going out. Afterwards there is nothing left to do."""
    _separate()
    book_earnings()  # then interest and fees count in profit


def _separate():
    from django.db.models import Q
    from .models import CashEntry
    pending = InvestmentMovement.objects.filter(whose="").filter(Q(business_amount__isnull=True) | ~Q(business_amount=0)
                                                | (Q(kind__in=[InvestmentMovement.DEPOSIT, InvestmentMovement.WITHDRAWAL]) & ~Q(source=OWNER)))
    if not pending.exists():
        return
    lock_business()
    for m in pending.select_related("investment", "entry__account", "purchase__receipt", "purchase__supplier").order_by("occurred_on", "pk"):
        if not m.reversed_at:
            for journal in JournalEntry.objects.filter(Q(source_key__in=[f"investment:{m.pk}", f"investment-share:{m.pk}"])
                                                       | Q(source_key__startswith=f"investment-reshare:{m.pk}:"), reversal_of__isnull=True):
                if not JournalEntry.objects.filter(reversal_of=journal).exists():
                    reverse_journal(journal, user=None, reason=SEPARATED, key=f"investment-apart:{journal.pk}")
            entry = m.entry
            if entry and not CashEntry.objects.filter(reversal_of=entry).exists():
                if m.purchase_id and m.kind == InvestmentMovement.WITHDRAWAL:
                    supplier = m.purchase.supplier.name if m.purchase.supplier_id else "the supplier"
                    post(unit=entry.business_unit, method=entry.account.payment_method, amount=entry.amount, kind="OPENING",
                         reference=f"Owner's own money from {m.investment.name} to pay {supplier} for {m.purchase.receipt.receipt_number}"[:160],
                         key=f"owner-pays:{m.idempotency_key.removesuffix(':investment')}", reason=SEPARATED, branch=entry.branch)
                reverse_cash(entry=entry, user=None, reason=SEPARATED, allow_investment=True)
        changes = {"business_amount": Decimal("0")}
        if m.kind in (InvestmentMovement.DEPOSIT, InvestmentMovement.WITHDRAWAL) and m.source != OWNER:
            first = "from" if m.kind == InvestmentMovement.DEPOSIT else "into"
            changes.update(source=OWNER, note=f"{m.note} · first recorded {first} {WORDS.get(m.source, m.source)}; kept apart from the business".lstrip(" ·")[:1000])
        InvestmentMovement.objects.filter(pk=m.pk).update(**changes)
