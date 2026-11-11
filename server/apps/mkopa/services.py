"""Recording M-KOPA phones, their plans, phones received, sales and the commission M-KOPA pays.

Only the commission touches the books. It counts as income on the day M-KOPA pays it (the owner's rule: commission is
profit only when paid), into the place it was paid to, as a cash-book entry of the M-KOPA part (unit MKOPA) and a
journal crediting 4050. What a sale is expected to earn is worked out from the sales, never booked, so the page can
say how much M-KOPA still owes without the books counting money that has not arrived.
"""
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.ledger import cash_code, money, paired, post_journal, resolve_branch, reverse_journal
from apps.accounting.models import JournalEntry
from apps.accounting.services import audit, post, reverse as reverse_cash
from apps.tenancy.transactions import lock_business
from .models import MkopaCommission, MkopaPhone, MkopaPlan, MkopaSale, MkopaStock

ZERO = Decimal("0")
UNIT, ACCOUNT = "MKOPA", "4050"
METHODS = {"CASH": "Cash", "MPESA": "M-Pesa", "BANK": "Bank", "OTHER": "Other"}


def _words(value, limit, what, required=True):
    text = " ".join(str(value or "").split())
    if required and len(text) < 2:
        raise ValidationError(f"Enter {what}.")
    return text[:limit]


def _day(value, what):
    day = value or timezone.localdate()
    if day > timezone.localdate():
        raise ValidationError(f"The {what} cannot be in the future.")
    return day


def _amount(value, what, allow_zero=False):
    amount = money(value)
    if amount < 0 or amount == 0 and not allow_zero:
        raise ValidationError(f"Enter {what} above zero." if not allow_zero else f"{what.capitalize()} cannot be below zero.")
    return amount


def total_price(plan):
    """What the customer pays M-KOPA for the phone in all: the deposit and every daily payment."""
    return plan.deposit + plan.daily_payment * plan.days


# Phones and plans ---------------------------------------------------------------------------------------------------

def _plan_terms(data):
    days = data.get("days")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValidationError("Enter how many days the customer pays for.")
    if days < 1 or days > 3650:
        raise ValidationError("Enter how many days the customer pays for (1 to 3650).")
    return {"deposit": _amount(data.get("deposit"), "the deposit", allow_zero=True),
            "daily_payment": _amount(data.get("daily_payment"), "the daily payment"),
            "days": days, "commission": _amount(data.get("commission") or 0, "your commission", allow_zero=True)}


@transaction.atomic
def add_phone(*, user, name, plans):
    lock_business()
    name = _words(name, 80, "the phone's name, such as X30")
    if MkopaPhone.objects.filter(name__iexact=name).exists():
        raise ValidationError(f"{name} is already in your list of M-KOPA phones.")
    if not plans:
        raise ValidationError("Add at least one plan: the deposit, the daily payment and for how many days.")
    terms = [_plan_terms(plan) for plan in plans]
    _no_repeats(terms)
    phone = MkopaPhone.objects.create(name=name)
    for plan in terms:
        MkopaPlan.objects.create(phone=phone, **plan)
    audit(phone, user, f"M-KOPA phone {name} added with {len(terms)} plan(s)")
    return phone


def _no_repeats(terms):
    seen = set()
    for plan in terms:
        key = (plan["deposit"], plan["daily_payment"], plan["days"])
        if key in seen:
            raise ValidationError("Two plans have the same deposit, daily payment and days.")
        seen.add(key)


@transaction.atomic
def change_phone(*, user, phone, name=None, active=None, plans=None):
    """Rename the phone, stop or start selling it, and set its plans. A plan is changed in place (sales already made keep
    their own terms and commission), added when it has no id, and stopped when left out (kept for the sales made on it)."""
    lock_business()
    phone = MkopaPhone.objects.select_for_update().get(pk=phone.pk)
    if name is not None:
        name = _words(name, 80, "the phone's name")
        if MkopaPhone.objects.filter(name__iexact=name).exclude(pk=phone.pk).exists():
            raise ValidationError(f"{name} is already in your list of M-KOPA phones.")
        phone.name = name
    if active is not None:
        phone.active = bool(active)
    phone.save()
    if plans is not None:
        if not plans:
            raise ValidationError("Keep at least one plan, or stop selling the phone instead.")
        terms = [_plan_terms(plan) for plan in plans]
        _no_repeats(terms)
        existing = {plan.pk: plan for plan in phone.plans.all()}
        kept = set()
        for given, plan_terms in zip(plans, terms):
            pk = given.get("id")
            if pk:
                plan = existing.get(int(pk))
                if not plan:
                    raise ValidationError("That plan belongs to another phone.")
                for field, value in plan_terms.items():
                    setattr(plan, field, value)
                plan.active = True
                plan.save()
                kept.add(plan.pk)
            else:
                kept.add(MkopaPlan.objects.create(phone=phone, **plan_terms).pk)
        phone.plans.exclude(pk__in=kept).update(active=False)
    audit(phone, user, f"M-KOPA phone {phone.name} changed")
    return phone


# Phones received and given back --------------------------------------------------------------------------------------

def on_hand(phone):
    received = MkopaStock.objects.filter(phone=phone, reversed_at__isnull=True).aggregate(v=Sum("quantity"))["v"] or 0
    sold = MkopaSale.objects.filter(phone=phone, reversed_at__isnull=True).count()
    return received - sold


@transaction.atomic
def move_stock(*, user, phone, quantity, kind, moved_on=None, notes="", key):
    lock_business()
    existing = MkopaStock.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValidationError("Enter how many phones.")
    if quantity < 1 or quantity > 10000:
        raise ValidationError("Enter how many phones (1 or more).")
    if kind not in (MkopaStock.RECEIVED, MkopaStock.RETURNED):
        raise ValidationError("Say whether the phones were received from M-KOPA or given back.")
    phone = MkopaPhone.objects.select_for_update().get(pk=phone.pk)
    if kind == MkopaStock.RETURNED:
        held = on_hand(phone)
        if quantity > held:
            raise ValidationError(f"You have {max(held, 0)} {phone.name} in hand, so you cannot give back {quantity}.")
        quantity = -quantity
    move = MkopaStock.objects.create(phone=phone, quantity=quantity, moved_on=_day(moved_on, "date"), notes=str(notes or "").strip()[:300],
                                     idempotency_key=key, created_by=user)
    audit(move, user, f"{abs(quantity)} {phone.name} {'received from' if quantity > 0 else 'given back to'} M-KOPA")
    return move


@transaction.atomic
def undo_stock(*, user, move, reason):
    lock_business()
    move = MkopaStock.objects.select_for_update().get(pk=move.pk)
    reason = _words(reason, 500, "why this is being undone")
    if move.reversed_at:
        return move
    if move.quantity > 0 and on_hand(move.phone) - move.quantity < 0:
        raise ValidationError(f"Those phones have been sold already, so the {move.quantity} received cannot be undone. Undo the sales first.")
    MkopaStock.objects.filter(pk=move.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    move.refresh_from_db()
    audit(move, user, reason)
    return move


# Sales ---------------------------------------------------------------------------------------------------------------

@transaction.atomic
def sell(*, user, plan, customer_name, customer_phone="", imei="", sold_on=None, notes="", key):
    lock_business()
    existing = MkopaSale.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    plan = MkopaPlan.objects.select_related("phone").get(pk=plan.pk)
    phone = MkopaPhone.objects.select_for_update().get(pk=plan.phone_id)
    if not plan.active or not phone.active:
        raise ValidationError(f"{phone.name} on that plan is no longer sold. Choose another plan.")
    imei = "".join(str(imei or "").split())[:30]
    if imei and MkopaSale.objects.filter(imei=imei, reversed_at__isnull=True).exists():
        raise ValidationError(f"A phone with IMEI {imei} is already recorded as sold.")
    received = MkopaStock.objects.filter(phone=phone, reversed_at__isnull=True).exists()
    if received and on_hand(phone) < 1:
        raise ValidationError(f"You have no {phone.name} in hand. Record the phones M-KOPA gave you first.")
    sale = MkopaSale.objects.create(phone=phone, plan=plan, customer_name=_words(customer_name, 120, "the customer's name"),
                                    customer_phone=str(customer_phone or "").strip()[:30], imei=imei, sold_on=_day(sold_on, "date of the sale"),
                                    deposit=plan.deposit, daily_payment=plan.daily_payment, days=plan.days, commission=plan.commission,
                                    notes=str(notes or "").strip()[:300], idempotency_key=key, created_by=user)
    audit(sale, user, f"{phone.name} sold to {sale.customer_name}")
    return sale


@transaction.atomic
def undo_sale(*, user, sale, reason):
    """A sale recorded by mistake, or the phone came back before M-KOPA counted it: it no longer earns commission and the
    phone is in hand again."""
    lock_business()
    sale = MkopaSale.objects.select_for_update().get(pk=sale.pk)
    reason = _words(reason, 500, "why this sale is being undone")
    if sale.reversed_at:
        return sale
    MkopaSale.objects.filter(pk=sale.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    sale.refresh_from_db()
    audit(sale, user, reason)
    return sale


# Commission ----------------------------------------------------------------------------------------------------------

@transaction.atomic
def record_commission(*, user, amount, method, paid_on=None, reference="", notes="", key):
    lock_business()
    existing = MkopaCommission.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    amount = _amount(amount, "the amount M-KOPA paid")
    method = str(method or "").upper()
    if method not in METHODS:
        raise ValidationError("Choose where M-KOPA paid it: cash, M-Pesa, bank or other.")
    paid_on = _day(paid_on, "date it was paid")
    reference = str(reference or "").strip().upper()[:120]
    if reference and MkopaCommission.objects.filter(reference=reference, reversed_at__isnull=True).exists():
        raise ValidationError(f"Commission with the reference {reference} is already recorded.")
    branch = resolve_branch()
    occurred = timezone.now() if paid_on == timezone.localdate() else timezone.make_aware(datetime.combine(paid_on, time(12)))
    words = "M-KOPA commission" + (f" ({reference})" if reference else "")
    entry = post(unit=UNIT, method=method, amount=amount, kind="INCOME", reference=words[:160], key=f"mkopa:{key}", user=user,
                 occurred_at=occurred, reason=str(notes or "").strip(), branch=branch, journal=False)
    payment = MkopaCommission.objects.create(amount=amount, paid_on=paid_on, method=method, reference=reference, notes=str(notes or "").strip()[:300],
                                             entry=entry, idempotency_key=key, created_by=user)
    post_journal(key=f"mkopa-commission:{payment.pk}", description=words[:240], branch=branch, date=paid_on, user=user,
                 lines=paired(cash_code(method), ACCOUNT, amount))
    audit(payment, user, f"M-KOPA paid {amount} commission")
    return payment


@transaction.atomic
def undo_commission(*, user, payment, reason):
    """Commission recorded by mistake: its income and the money both come back out; M-KOPA owes it again."""
    lock_business()
    payment = MkopaCommission.objects.select_for_update().get(pk=payment.pk)
    reason = _words(reason, 500, "why this commission is being undone")
    if payment.reversed_at:
        return payment
    reverse_cash(entry=payment.entry, user=user, reason=reason, allow_mkopa=True)
    journal = JournalEntry.objects.filter(source_key=f"mkopa-commission:{payment.pk}").first()
    if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
        reverse_journal(journal, user=user, reason=reason, key=f"mkopa-commission-undo:{payment.pk}")
    MkopaCommission.objects.filter(pk=payment.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    payment.refresh_from_db()
    return payment


# Figures -------------------------------------------------------------------------------------------------------------

def summary(today=None):
    """What the dealer has earned: commission the sales earn, what M-KOPA has paid, what it still owes, and this month."""
    today = today or timezone.localdate()
    sales = MkopaSale.objects.filter(reversed_at__isnull=True)
    earned = sales.aggregate(v=Sum("commission"), n=Count("pk"))
    month = sales.filter(sold_on__gte=today.replace(day=1), sold_on__lte=today).aggregate(v=Sum("commission"), n=Count("pk"))
    paid = MkopaCommission.objects.filter(reversed_at__isnull=True).aggregate(v=Sum("amount"))["v"] or ZERO
    expected = earned["v"] or ZERO
    return {"phones_sold": earned["n"], "commission_earned": expected, "commission_paid": paid,
            "commission_owed": max(expected - paid, ZERO), "paid_beyond": max(paid - expected, ZERO),
            "month_sold": month["n"], "month_commission": month["v"] or ZERO}
