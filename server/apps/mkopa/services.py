"""Recording M-KOPA phones, their plans, phones received, sales and the commission M-KOPA pays.

Only the commission touches the books. It counts as income on the day M-KOPA pays it (the owner's rule: commission is
profit only when paid), into the place it was paid to, as a cash-book entry of the M-KOPA part (unit MKOPA) and a
journal crediting 4050. What a sale is expected to earn is worked out from the sales, never booked, so the page can
say how much M-KOPA still owes without the books counting money that has not arrived.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.ledger import cash_code, money, paired, post_journal, resolve_branch, reverse_journal
from apps.accounting.models import JournalEntry
from apps.accounting.services import audit, post, reverse as reverse_cash
from apps.tenancy.transactions import lock_business
from .models import MkopaCommission, MkopaPhone, MkopaPlan, MkopaRound, MkopaSale, MkopaStock

ZERO = Decimal("0")
ROUND_DAYS = 10  # M-KOPA's usual time to sell a round of stock before the unsold phones go back
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
            "days": days, "commission": None if data.get("commission") in (None, "") else _amount(data["commission"], "your commission", allow_zero=True)}


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


def open_round():
    return MkopaRound.objects.filter(cleared_on__isnull=True).first()


def _return_by(value, given_on):
    day = value or given_on + timedelta(days=ROUND_DAYS)
    if day < given_on:
        raise ValidationError("The return date cannot be before the day the stock was given.")
    if day > given_on + timedelta(days=120):
        raise ValidationError("Choose a return date within 120 days of the day the stock was given.")
    return day


def _start_round(*, user, given_on, return_by=None, notes=""):
    """A new round of stock. The phones kept from the last round carry on into it, still in hand."""
    last = MkopaRound.objects.order_by("-given_on", "-pk").first()
    if last and last.cleared_on and given_on < last.cleared_on:
        raise ValidationError(f"The last stock was cleared on {last.cleared_on:%d %b %Y}, so new stock cannot be given before that day.")
    rnd = MkopaRound.objects.create(given_on=given_on, return_by=_return_by(return_by, given_on), notes=str(notes or "").strip()[:300], created_by=user)
    audit(rnd, user, f"M-KOPA stock given on {given_on:%d %b %Y}, to return by {rnd.return_by:%d %b %Y}")
    return rnd


def _receive(*, user, rnd, phone, quantity, moved_on, notes, key, kind=MkopaStock.RECEIVED, clearing=False):
    move = MkopaStock.objects.create(phone=phone, round=rnd, quantity=quantity, moved_on=moved_on, notes=str(notes or "").strip()[:300],
                                     idempotency_key=key, created_by=user, clearing=clearing)
    audit(move, user, f"{abs(quantity)} {phone.name} {'received from' if quantity > 0 else 'given back to'} M-KOPA")
    return move


def _counts(values, what):
    """{phone id: how many} from what was typed, leaving out the zeros."""
    counts = {}
    for pk, value in (values or {}).items():
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            raise ValidationError(f"Enter how many phones {what} as whole numbers.")
        if n < 0 or n > 10000:
            raise ValidationError(f"Enter how many phones {what} (0 or more).")
        if n:
            counts[int(pk)] = n
    return counts


@transaction.atomic
def give_stock(*, user, phones, given_on=None, return_by=None, notes="", key):
    """M-KOPA gave phones ({phone id: how many}): into the open round (more of this round's stock), else as a new round
    to sell until ``return_by`` (ten days on unless said)."""
    lock_business()
    if MkopaStock.objects.filter(idempotency_key__startswith=f"{key}:").exists():
        return open_round()
    counts = _counts(phones, "M-KOPA gave you")
    if not counts:
        raise ValidationError("Enter how many phones M-KOPA gave you of at least one model.")
    known = {phone.pk: phone for phone in MkopaPhone.objects.select_for_update().filter(pk__in=counts)}
    if len(known) != len(counts):
        raise ValidationError("One of those phones is not in your list. Refresh the page.")
    given_on = _day(given_on, "date the stock was given")
    rnd = open_round()
    if rnd:
        if given_on < rnd.given_on:
            raise ValidationError(f"This stock was given on {rnd.given_on:%d %b %Y}; phones added to it cannot be dated before that.")
        if return_by:
            rnd.return_by = _return_by(return_by, rnd.given_on)
            rnd.save(update_fields=["return_by"])
    else:
        rnd = _start_round(user=user, given_on=given_on, return_by=return_by, notes=notes)
    for pk, n in counts.items():
        _receive(user=user, rnd=rnd, phone=known[pk], quantity=n, moved_on=given_on, notes=notes, key=f"{key}:{pk}")
    return rnd


@transaction.atomic
def clear_round(*, user, rnd, returned, cleared_on=None, notes="", key, next_stock=None, next_return_by=None):
    """The round's time is up: the unsold phones go back to M-KOPA (``returned``, {phone id: how many}; any not given back
    are kept and carry on into the next round, still in hand) and the round closes. When M-KOPA gives the next stock at the
    same visit, ``next_stock`` ({phone id: how many}) starts the next round on the same day. Commission is not touched:
    phones sold keep earning what M-KOPA pays for them."""
    lock_business()
    rnd = MkopaRound.objects.select_for_update().get(pk=rnd.pk)
    if rnd.cleared_on:
        return rnd  # cleared already (the same clearing sent twice)
    cleared_on = _day(cleared_on, "date the stock was cleared")
    if cleared_on < rnd.given_on:
        raise ValidationError(f"This stock was given on {rnd.given_on:%d %b %Y}, so it cannot be cleared before that.")
    counts = _counts(returned, "given back")
    phones = {phone.pk: phone for phone in MkopaPhone.objects.select_for_update()}
    held = {pk: on_hand(phone) for pk, phone in phones.items()}
    for pk, n in counts.items():
        if pk not in phones:
            raise ValidationError("One of those phones is not in your list. Refresh the page.")
        if n > max(held[pk], 0):
            raise ValidationError(f"You have {max(held[pk], 0)} {phones[pk].name} in hand, so you cannot give back {n}.")
    for pk, n in counts.items():
        _receive(user=user, rnd=rnd, phone=phones[pk], quantity=-n, moved_on=cleared_on, notes=notes, key=f"{key}:{pk}",
                 kind=MkopaStock.RETURNED, clearing=True)
    rnd.cleared_on, rnd.cleared_by = cleared_on, user
    rnd.kept = {str(pk): held[pk] - counts.get(pk, 0) for pk in phones if held[pk] - counts.get(pk, 0) > 0}
    if notes:
        rnd.notes = (f"{rnd.notes} · {notes}" if rnd.notes else str(notes)).strip()[:300]
    rnd.save()
    audit(rnd, user, f"M-KOPA stock cleared on {cleared_on:%d %b %Y}: {sum(counts.values())} phone(s) given back")
    if next_stock and _counts(next_stock, "M-KOPA gave you"):
        give_stock(user=user, phones=next_stock, given_on=cleared_on, return_by=next_return_by, key=f"{key}:next")
    return rnd


@transaction.atomic
def reopen_round(*, user, rnd, reason):
    """Clearing recorded by mistake: the phones given back are in hand again and the round is open again. Only the last
    round, and only while no newer stock was given."""
    lock_business()
    rnd = MkopaRound.objects.select_for_update().get(pk=rnd.pk)
    reason = _words(reason, 500, "why the clearing is being undone")
    if not rnd.cleared_on:
        return rnd
    if MkopaRound.objects.filter(Q(given_on__gt=rnd.given_on) | Q(given_on=rnd.given_on, pk__gt=rnd.pk)).exists():
        raise ValidationError("Newer stock was given after this one was cleared. Undo the newer stock's phones first.")
    MkopaStock.objects.filter(round=rnd, clearing=True, reversed_at__isnull=True).update(reversed_at=timezone.now(), reverse_reason=reason)
    rnd.cleared_on, rnd.cleared_by, rnd.kept = None, None, {}
    rnd.save()
    audit(rnd, user, reason)
    return rnd


@transaction.atomic
def change_round(*, user, rnd, return_by):
    lock_business()
    rnd = MkopaRound.objects.select_for_update().get(pk=rnd.pk)
    if rnd.cleared_on:
        raise ValidationError("This stock is already cleared.")
    rnd.return_by = _return_by(return_by, rnd.given_on)
    rnd.save(update_fields=["return_by"])
    audit(rnd, user, f"M-KOPA stock to return by {rnd.return_by:%d %b %Y}")
    return rnd


def _drop_if_empty(rnd):
    """An open round left with no phones received and none sold (its stock undone) is no round at all."""
    if rnd and not rnd.cleared_on and not rnd.moves.filter(reversed_at__isnull=True).exists() and not rnd.sales.exists():
        rnd.moves.all().update(round=None)
        rnd.delete()


@transaction.atomic
def move_stock(*, user, phone, quantity, kind, moved_on=None, notes="", key):
    """One model received or given back. It belongs to the open round; phones received with no round open start one."""
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
    moved_on = _day(moved_on, "date")
    rnd = open_round()
    if kind == MkopaStock.RETURNED:
        held = on_hand(phone)
        if quantity > held:
            raise ValidationError(f"You have {max(held, 0)} {phone.name} in hand, so you cannot give back {quantity}.")
        quantity = -quantity
    elif not rnd:
        rnd = _start_round(user=user, given_on=moved_on)
    if rnd and moved_on < rnd.given_on:
        raise ValidationError(f"The stock now with you was given on {rnd.given_on:%d %b %Y}; phones added to it cannot be dated before that.")
    return _receive(user=user, rnd=rnd, phone=phone, quantity=quantity, moved_on=moved_on, notes=notes, key=key)


@transaction.atomic
def undo_stock(*, user, move, reason):
    lock_business()
    move = MkopaStock.objects.select_for_update().get(pk=move.pk)
    reason = _words(reason, 500, "why this is being undone")
    if move.reversed_at:
        return move
    if move.quantity > 0 and on_hand(move.phone) - move.quantity < 0:
        raise ValidationError(f"Those phones have been sold already, so the {move.quantity} received cannot be undone. Undo the sales first.")
    if move.clearing and move.round and move.round.cleared_on:
        raise ValidationError("These phones were given back when the stock was cleared. Undo the clearing instead.")
    MkopaStock.objects.filter(pk=move.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    move.refresh_from_db()
    audit(move, user, reason)
    _drop_if_empty(move.round)
    return move


def round_for(day):
    """The round a phone sold on ``day`` came from: the open one if the day is in it, else the one whose time covers it."""
    rnd = open_round()
    if rnd and day >= rnd.given_on:
        return rnd
    return (MkopaRound.objects.filter(given_on__lte=day).filter(Q(cleared_on__gte=day) | Q(cleared_on__isnull=True))
            .order_by("-given_on", "-pk").first())


def round_rows(rounds=None):
    """Each round in numbers: phones given (and kept from the round before), sold from it, given back, kept, and how
    well it sold (sold out of all it had), with what its sales earn. Newest first."""
    rounds = list(rounds if rounds is not None else MkopaRound.objects.order_by("-given_on", "-pk"))
    names = dict(MkopaPhone.objects.values_list("pk", "name"))
    moves = MkopaStock.objects.filter(round__in=rounds, reversed_at__isnull=True)
    sales = list(MkopaSale.objects.filter(round__in=rounds, reversed_at__isnull=True).select_related("plan", "paid_by"))
    ordered = sorted(rounds, key=lambda r: (r.given_on, r.pk))
    before = {r.pk: (ordered[i - 1] if i else None) for i, r in enumerate(ordered)}
    rows = []
    for rnd in rounds:
        per = {}
        def line(pk):
            return per.setdefault(pk, {"phone_id": pk, "phone": names.get(pk, "?"), "carried": 0, "given": 0, "sold": 0, "returned": 0, "kept": 0})
        last = before[rnd.pk]
        for pk, n in ((last.kept or {}) if last else {}).items():
            line(int(pk))["carried"] += n
        for move in moves:
            if move.round_id == rnd.pk:
                line(move.phone_id)["given" if move.quantity > 0 else "returned"] += abs(move.quantity)
        mine = [sale for sale in sales if sale.round_id == rnd.pk]
        for sale in mine:
            line(sale.phone_id)["sold"] += 1
        for pk, n in (rnd.kept or {}).items():
            line(int(pk))["kept"] = n
        lines = sorted(per.values(), key=lambda row: row["phone"])
        had = sum(row["carried"] + row["given"] for row in lines)
        sold = len(mine)
        earned = [expected(sale) for sale in mine]
        rows.append({"id": rnd.pk, "given_on": rnd.given_on, "return_by": rnd.return_by, "cleared_on": rnd.cleared_on, "open": not rnd.cleared_on,
                     "notes": rnd.notes, "lines": lines, "carried": sum(r["carried"] for r in lines), "given": sum(r["given"] for r in lines),
                     "had": had, "sold": sold, "returned": sum(r["returned"] for r in lines), "kept": sum(r["kept"] for r in lines),
                     "sold_share": round(sold * 100 / had) if had else None,
                     "days": ((rnd.cleared_on or timezone.localdate()) - rnd.given_on).days,
                     "commission": sum((value for value in earned if value is not None), ZERO),
                     "paid_phones": sum(1 for sale in mine if sale.paid_by_id and not sale.paid_by.reversed_at),
                     "commission_paid": sum((sale.commission_received or ZERO for sale in mine if sale.paid_by_id and not sale.paid_by.reversed_at), ZERO)})
    return rows


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
    rate = plan.rate
    sold_on = _day(sold_on, "date of the sale")
    sale = MkopaSale.objects.create(phone=phone, plan=plan, round=round_for(sold_on), customer_name=_words(customer_name, 120, "the customer's name"),
                                    customer_phone=str(customer_phone or "").strip()[:30], imei=imei, sold_on=sold_on,
                                    deposit=plan.deposit, daily_payment=plan.daily_payment, days=plan.days, commission=rate or ZERO,
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
    if sale.paid_by_id and not sale.paid_by.reversed_at:
        raise ValidationError(f"M-KOPA already paid this phone's commission (the payment of {sale.paid_by.paid_on:%d %b %Y}). Undo that payment first.")
    MkopaSale.objects.filter(pk=sale.pk).update(reversed_at=timezone.now(), reverse_reason=reason)
    sale.refresh_from_db()
    audit(sale, user, reason)
    return sale


# Commission ----------------------------------------------------------------------------------------------------------

@transaction.atomic
def unpaid_sales():
    """Phones sold whose commission M-KOPA has not paid yet, oldest first."""
    return MkopaSale.objects.filter(reversed_at__isnull=True).filter(Q(paid_by__isnull=True) | Q(paid_by__reversed_at__isnull=False)).order_by("sold_on", "pk")


def relearn():
    """Learn every plan's commission again from all payments, then split each payment between the phones it paid for."""
    from .learning import learn, split
    learn()
    MkopaSale.objects.filter(paid_by__reversed_at__isnull=False).update(paid_by=None, commission_received=None)
    for payment in MkopaCommission.objects.filter(reversed_at__isnull=True, itemised=False, sales__isnull=False).distinct():
        sales = list(payment.sales.select_related("plan"))
        for pk, part in split(payment.amount, sales).items():
            MkopaSale.objects.filter(pk=pk).update(commission_received=part)


@transaction.atomic
def record_commission(*, user, amount=None, method, paid_on=None, reference="", notes="", key, sales=None, amounts=None):
    """``sales``: the ids of the phones sold this payment is for; None means every phone sold up to the day it was paid
    whose commission is not paid yet. Or ``amounts``, {sale id: what M-KOPA paid for that phone}: the payment is their sum.
    Either way they teach the app each plan's commission (learning.py)."""
    lock_business()
    existing = MkopaCommission.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    each = None
    if amounts is not None:
        if not amounts:
            raise ValidationError("Choose the phones M-KOPA paid for and what it paid for each.")
        each = {int(pk): _amount(value, "what M-KOPA paid for each phone", allow_zero=True) for pk, value in amounts.items()}
        sales, total = list(each), sum(each.values(), ZERO)
        if amount not in (None, "") and money(amount) != total:
            raise ValidationError(f"The phones' amounts add up to {total:,.2f}, not {money(amount):,.2f}.")
        amount = total
    amount = _amount(amount, "the amount M-KOPA paid")
    method = str(method or "").upper()
    if method not in METHODS:
        raise ValidationError("Choose where M-KOPA paid it: cash, M-Pesa, bank or other.")
    paid_on = _day(paid_on, "date it was paid")
    waiting = unpaid_sales().select_for_update(of=("self",))
    if sales is None:
        covered = list(waiting.filter(sold_on__lte=paid_on))
    else:
        wanted = {int(pk) for pk in sales}
        covered = list(waiting.filter(pk__in=wanted))
        if len(covered) != len(wanted):
            raise ValidationError("Some of those phones are already paid for, undone, or not yours. Refresh the page and choose again.")
        if any(sale.sold_on > paid_on for sale in covered):
            raise ValidationError("A payment cannot be for a phone sold after the day it was paid.")
    reference = str(reference or "").strip().upper()[:120]
    if reference and MkopaCommission.objects.filter(reference=reference, reversed_at__isnull=True).exists():
        raise ValidationError(f"Commission with the reference {reference} is already recorded.")
    branch = resolve_branch()
    occurred = timezone.now() if paid_on == timezone.localdate() else timezone.make_aware(datetime.combine(paid_on, time(12)))
    words = "M-KOPA commission" + (f" ({reference})" if reference else "")
    entry = post(unit=UNIT, method=method, amount=amount, kind="INCOME", reference=words[:160], key=f"mkopa:{key}", user=user,
                 occurred_at=occurred, reason=str(notes or "").strip(), branch=branch, journal=False)
    payment = MkopaCommission.objects.create(amount=amount, paid_on=paid_on, method=method, reference=reference, notes=str(notes or "").strip()[:300],
                                             entry=entry, idempotency_key=key, created_by=user, itemised=each is not None)
    post_journal(key=f"mkopa-commission:{payment.pk}", description=words[:240], branch=branch, date=paid_on, user=user,
                 lines=paired(cash_code(method), ACCOUNT, amount))
    MkopaSale.objects.filter(pk__in=[sale.pk for sale in covered]).update(paid_by=payment)
    for pk, value in (each or {}).items():
        MkopaSale.objects.filter(pk=pk).update(commission_received=value)  # exactly what M-KOPA paid for that phone
    relearn()
    audit(payment, user, f"M-KOPA paid {amount} commission for {len(covered)} phone(s)")
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
    MkopaSale.objects.filter(paid_by=payment).update(paid_by=None, commission_received=None)  # waiting for M-KOPA again
    relearn()
    payment.refresh_from_db()
    return payment


# Figures -------------------------------------------------------------------------------------------------------------

def expected(sale):
    """What one phone sold earns: what M-KOPA paid for it once paid, else its plan's commission as now known (learned
    from M-KOPA's payments, else typed), else what was expected on the day it was sold; None when nothing is known."""
    if sale.paid_by_id and not sale.paid_by.reversed_at and sale.commission_received is not None:
        return sale.commission_received
    if sale.plan.rate is not None:
        return sale.plan.rate
    return sale.commission if sale.commission else None


def summary(today=None):
    """What the dealer has earned: what M-KOPA has paid, what the phones not paid for yet will earn, and this month."""
    today = today or timezone.localdate()
    sales = list(MkopaSale.objects.filter(reversed_at__isnull=True).select_related("plan", "paid_by"))
    waiting = [sale for sale in sales if not sale.paid_by_id or sale.paid_by.reversed_at]
    owed = [expected(sale) for sale in waiting]
    month = [sale for sale in sales if today.replace(day=1) <= sale.sold_on <= today]
    paid = MkopaCommission.objects.filter(reversed_at__isnull=True).aggregate(v=Sum("amount"))["v"] or ZERO
    known_owed = sum((value for value in owed if value is not None), ZERO)
    return {"phones_sold": len(sales), "commission_paid": paid, "commission_owed": known_owed, "commission_earned": paid + known_owed,
            "unpaid_phones": len(waiting), "unknown_phones": sum(1 for value in owed if value is None),
            "month_sold": len(month), "month_commission": sum((expected(sale) or ZERO for sale in month), ZERO)}
