"""Rooms, guests and their bills (see models.py).

Nights. A night is charged when the guest checks in, and one more each time they are still in after the hotel's check-out
time (10:00 unless the owner sets another). A guest who checks in on Monday afternoon and leaves on Wednesday at 09:00
pays two nights; one still in at 10:30 on Wednesday pays three. Nights are brought up to date whenever the rooms are
looked at and by the scheduler, each night once, so they are never charged twice and never missed.

Money. Every payment a guest makes, in advance or during the stay, is first held for them (a guest deposit: owed to the
guest until used) and is then used against what they owe, oldest charge first. What is still held at check-out is given
back, or kept as the price of a cancelled booking.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomerProfile
from apps.catalog.models import Product
from apps.commerce.models import Payment, Sale

from .catalog import new_variant, rename
from .models import Room, RoomType, Stay, StayCharge, StayDeposit

CENT = Decimal("0.01")
DEFAULT_CHECKOUT_TIME = "10:00"
OCCUPYING = (Stay.BOOKED, Stay.IN)


def money(value, label="the amount"):
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except Exception:
        raise ValidationError(f"Enter {label} as a number.")
    if not amount.is_finite():
        raise ValidationError(f"Enter {label} as a number.")
    return amount


# Setting up --------------------------------------------------------------------------------------------------------

@transaction.atomic
def add_room_type(*, name, rate, sleeps=2, extra=False):
    rate = money(rate or 0, "the price a night")
    if rate < 0:
        raise ValidationError("A price cannot be negative.")
    variant = new_variant(name=name, kind=Product.SERVICE, group="Guest extras" if extra else "Rooms", price=rate, prefix="ROOM")
    return RoomType.objects.create(variant=variant, sleeps=max(int(sleeps or 1), 1), extra=extra)


@transaction.atomic
def change_room_type(room_type, *, name=None, rate=None, sleeps=None, active=None):
    if rate is not None:
        rate = money(rate, "the price a night")
        if rate < 0:
            raise ValidationError("A price cannot be negative.")
    rename(room_type.variant, name=name, price=rate)
    if sleeps is not None:
        room_type.sleeps = max(int(sleeps), 1)
    if active is not None:
        room_type.active = bool(active)
    room_type.save(update_fields=["sleeps", "active", "updated_at"])
    return room_type


def extras_type():
    """What guests are charged for besides their nights, sold like a night so it reaches the rooms' books."""
    return RoomType.objects.filter(extra=True).first() or add_room_type(name="Guest extras", rate=0, extra=True)


@transaction.atomic
def add_room(*, number, room_type, floor="", note=""):
    number = " ".join(str(number or "").split())[:20]
    if not number:
        raise ValidationError("Enter the room's number or name.")
    if room_type.extra:
        raise ValidationError("Choose a kind of room.")
    if Room.objects.filter(number__iexact=number).exists():
        raise ValidationError(f"There is already a room {number}.")
    return Room.objects.create(number=number, room_type=room_type, floor=str(floor or "")[:40], note=str(note or "")[:255])


@transaction.atomic
def change_room(room, **changes):
    if "number" in changes:
        number = " ".join(str(changes["number"] or "").split())[:20]
        if not number:
            raise ValidationError("Enter the room's number or name.")
        if Room.objects.filter(number__iexact=number).exclude(pk=room.pk).exists():
            raise ValidationError(f"There is already a room {number}.")
        room.number = number
    if changes.get("room_type") is not None:
        room.room_type = changes["room_type"]
    for field in ("floor", "note"):
        if field in changes:
            setattr(room, field, str(changes[field] or "")[:255 if field == "note" else 40])
    if "condition" in changes:
        if changes["condition"] not in dict(Room._meta.get_field("condition").choices):
            raise ValidationError("Choose ready, needs cleaning or out of order.")
        room.condition = changes["condition"]
    if "active" in changes:
        if not changes["active"] and room.stays.filter(status__in=OCCUPYING).exists():
            raise ValidationError("This room has a guest or a booking. Move them to another room first.")
        room.active = bool(changes["active"])
    room.save()
    return room


def checkout_time(organization=None):
    from apps.tenancy.context import organization_id
    from apps.tenancy.models import Organization
    organization = organization or Organization.objects.filter(pk=organization_id()).first()
    value = ((organization.settings or {}) if organization else {}).get("checkout_time") or DEFAULT_CHECKOUT_TIME
    try:
        return time.fromisoformat(value)
    except ValueError:
        return time.fromisoformat(DEFAULT_CHECKOUT_TIME)


# Guests and bookings ------------------------------------------------------------------------------------------------

def guest_for(*, guest_id=None, name="", phone=""):
    """The guest as a customer of the business: the one chosen, one already known by this phone number, or a new one."""
    if guest_id:
        profile = CustomerProfile.objects.select_related("user").filter(user_id=guest_id).first()
        if not profile:
            raise ValidationError("Choose a customer in this business.")
        return profile.user
    name, phone = " ".join(str(name or "").split())[:150], "".join(str(phone or "").split())[:30]
    if not name:
        raise ValidationError("Enter the guest's name.")
    if phone:
        known = CustomerProfile.objects.select_related("user").filter(phone=phone).first()
        if known:
            return known.user
    user = User.objects.create_user(username="customer-" + uuid4().hex, first_name=name, is_active=False)
    CustomerProfile.objects.create(user=user, phone=phone)
    return user


def _occupied_until(stay, today):
    """A guest still in after their expected day keeps the room until they leave."""
    return max(stay.departure, today + timedelta(days=1)) if stay.status == Stay.IN else stay.departure


def clash(room, arrival, departure, *, exclude=None):
    """The stay already holding ``room`` for any night from ``arrival`` up to ``departure``, or None."""
    today = timezone.localdate()
    for stay in room.stays.filter(status__in=OCCUPYING, arrival__lt=departure).exclude(pk=getattr(exclude, "pk", None)):
        if _occupied_until(stay, today) > arrival:
            return stay
    return None


def _check_free(room, arrival, departure, exclude=None):
    taken = clash(room, arrival, departure, exclude=exclude)
    if taken:
        word = "is in" if taken.status == Stay.IN else f"is booked from {taken.arrival:%d %b}"
        raise ValidationError(f"Room {room.number} is taken: {taken.guest_name} {word} until {_occupied_until(taken, timezone.localdate()):%d %b}.")


def _dates(arrival, departure):
    if not arrival or not departure:
        raise ValidationError("Enter the arrival and leaving dates.")
    if departure <= arrival:
        raise ValidationError("The guest leaves at least one night after arriving.")
    return arrival, departure


@transaction.atomic
def book(*, user, room, arrival, departure, guest_id=None, guest_name="", phone="", id_number="", guests=1, rate=None, note="",
         check_in_now=False):
    """A booking for a room, or a walk-in checked in at once (``check_in_now``)."""
    room = Room.objects.select_for_update().get(pk=room.pk)
    if not room.active:
        raise ValidationError(f"Room {room.number} is not in use.")
    today = timezone.localdate()
    if check_in_now:
        arrival = today
    arrival, departure = _dates(arrival, departure)
    if arrival < today:
        raise ValidationError("A booking cannot start in the past.")
    _check_free(room, arrival, departure)
    guest = guest_for(guest_id=guest_id, name=guest_name, phone=phone)
    profile = CustomerProfile.objects.filter(user=guest).first()
    rate = money(rate if rate not in (None, "") else room.room_type.variant.selling_price, "the price a night")
    if rate < 0:
        raise ValidationError("A price cannot be negative.")
    stay = Stay.objects.create(number=f"ST-{today:%y%m%d}-{uuid4().hex[:4].upper()}", room=room, guest=guest,
                               guest_name=" ".join(str(guest_name or "").split())[:160] or guest.get_full_name() or guest.first_name,
                               phone=("".join(str(phone or "").split()) or getattr(profile, "phone", ""))[:30],
                               id_number=str(id_number or "").strip()[:40], guests=max(int(guests or 1), 1), arrival=arrival,
                               departure=departure, rate=rate, note=str(note or "")[:255], created_by=user)
    if check_in_now:
        check_in(stay, user=user)
    return stay


def _locked(stay):
    return Stay.objects.select_for_update().select_related("room__room_type__variant").get(pk=stay.pk)


@transaction.atomic
def check_in(stay, *, user, id_number=None):
    stay = _locked(stay)
    if stay.status != Stay.BOOKED:
        raise ValidationError("Only a booked guest can be checked in.")
    today = timezone.localdate()
    if stay.arrival > today:
        _check_free(stay.room, today, stay.arrival, exclude=stay)  # coming early: the room must be free until then too
    stay.arrival = today  # the stay runs from the day the guest actually came
    stay.departure = max(stay.departure, today + timedelta(days=1))
    if stay.room.condition == Room.OUT_OF_ORDER:
        raise ValidationError(f"Room {stay.room.number} is out of order. Move the guest to another room first.")
    occupant = stay.room.stays.filter(status=Stay.IN).exclude(pk=stay.pk).first()
    if occupant:
        raise ValidationError(f"{occupant.guest_name} is still in room {stay.room.number}. Check them out or move this guest.")
    if id_number is not None:
        stay.id_number = str(id_number).strip()[:40]
    stay.status, stay.checked_in_at = Stay.IN, timezone.now()
    stay.save()
    charge_due_nights(stay)
    return stay


def first_night(stay):
    """The night a guest's first charge is for: the day they came, or the night before for one who came in the small hours."""
    came = timezone.localtime(stay.checked_in_at)
    return came.date() - timedelta(days=1) if came.time() < checkout_time() else came.date()


def nights_due(stay, at=None):
    """Nights a checked-in guest owes by ``at``: the first on arrival, then one each time the check-out time passes."""
    if stay.status not in (Stay.IN, Stay.OUT) or not stay.checked_in_at:
        return 0
    at = timezone.localtime(at or (stay.checked_out_at if stay.status == Stay.OUT else None) or timezone.now())
    leave_by = checkout_time()
    first = first_night(stay) + timedelta(days=1)  # the first check-out time after they came
    last = at.date() if at.time() >= leave_by else at.date() - timedelta(days=1)  # the latest one already passed
    return 1 + max((last - first).days + 1, 0)


def _sale_for(stay, *, variant, price, number, key, user, quantity=1):
    from apps.inventory.services import complete_sale
    from apps.tenancy.context import branch_context
    with branch_context(stay.branch_id):
        return complete_sale(lines=[{"variant": variant, "quantity": quantity, "unit_price": price}], channel=Sale.ROOMS, number=number,
                             user=user, customer=stay.guest, paid_amount=0, idempotency_key=key)


@transaction.atomic
def charge_due_nights(stay, at=None):
    """Charges the nights owed and not yet charged, each once. Returns how many were charged now."""
    stay = _locked(stay)
    due = nights_due(stay, at)
    if not due:
        return 0
    charged = stay.charges.filter(kind=StayCharge.NIGHT).count()
    start = first_night(stay)
    added = 0
    for index in range(charged, due):
        night = start + timedelta(days=index)
        sale = _sale_for(stay, variant=stay.room.room_type.variant, price=stay.rate, number=f"{stay.number}-N{index + 1}",
                         key=f"stay-night:{stay.pk}:{night}", user=stay.created_by)
        StayCharge.objects.create(stay=stay, sale=sale, kind=StayCharge.NIGHT, night=night)
        added += 1
    if added:
        use_deposits(stay)
    return added


def bring_up_to_date():
    """Charges every checked-in guest's nights that are due (the rooms page and the scheduler call this)."""
    for stay in Stay.objects.filter(status=Stay.IN):
        charge_due_nights(stay)


def stay_for_till(stay_id):
    stay = Stay.objects.select_related("room").filter(pk=stay_id).first() if stay_id else None
    if not stay:
        raise ValidationError("Choose the guest's room.")
    if stay.status != Stay.IN:
        raise ValidationError("Only a guest who is checked in can charge to their room.")
    return stay


@transaction.atomic
def charge_till_sale(stay_id, sale):
    """A sale at the till charged to a guest's room: it joins their bill."""
    stay = stay_for_till(stay_id)
    StayCharge.objects.get_or_create(sale=sale, defaults={"stay": stay, "kind": StayCharge.TILL})
    use_deposits(stay)


@transaction.atomic
def add_extra(stay, *, user, description, amount, key=None):
    """Something else on the guest's bill: laundry, an extra bed, a late check-out."""
    stay = _locked(stay)
    if stay.status not in (Stay.IN, Stay.BOOKED):
        raise ValidationError("Add charges while the guest is booked or in.")
    description = " ".join(str(description or "").split())[:120]
    amount = money(amount)
    if not description or amount <= 0:
        raise ValidationError("Say what it is for and enter an amount above zero.")
    variant = extras_type().variant
    count = stay.charges.filter(kind=StayCharge.EXTRA).count() + 1
    sale = _sale_for(stay, variant=variant, price=amount, number=f"{stay.number}-X{count}", key=key or f"stay-extra:{stay.pk}:{uuid4().hex}",
                     user=user)
    charge = StayCharge.objects.create(stay=stay, sale=sale, kind=StayCharge.EXTRA, description=description)
    use_deposits(stay)
    return charge


# Money ---------------------------------------------------------------------------------------------------------------

def _owing(sale):
    from apps.commerce.returns import sale_balance
    return max(sale_balance(sale), Decimal("0"))


@transaction.atomic
def receive(stay, *, user, amount, method, reference=""):
    """Money from the guest: held for them, then used against what they owe."""
    from apps.accounting.ledger import cash_code, paired, post_journal
    from apps.accounting.services import post
    stay = _locked(stay)
    if stay.status in (Stay.CANCELLED, Stay.NO_SHOW):
        raise ValidationError("This booking is closed.")
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    if method not in ("CASH", "MPESA", "BANK"):
        raise ValidationError("Choose cash, M-Pesa or bank.")
    reference = " ".join(str(reference or "").split()).upper()[:100]
    if method in ("MPESA", "BANK") and not reference:
        raise ValidationError("Enter the M-Pesa code or the bank reference.")
    if method == "MPESA" and (StayDeposit.objects.filter(method="MPESA", reference=reference).exists()
                              or Payment.objects.filter(provider_transaction_id=reference).exists()):
        raise ValidationError(f"The M-Pesa code {reference} is already recorded. Check the code in the message.")
    deposit = StayDeposit.objects.create(stay=stay, amount=amount, method=method, reference=reference, received_by=user)
    post(unit="CYBER", method=method, amount=amount, kind="INCOME", reference=f"Guest {stay.number}", key=f"stay-deposit:{deposit.pk}",
         user=user, branch=stay.branch, journal=False)
    post_journal(key=f"stay-deposit:{deposit.pk}", description=f"Paid by guest {stay.guest_name} ({stay.number})",
                 lines=paired(cash_code(method), "2300", amount), branch=stay.branch_id, user=user)
    use_deposits(stay)
    return deposit


def use_deposits(stay):
    """Uses what the guest has paid against what they owe, oldest charge first. Caller holds the stay lock."""
    deposits = list(StayDeposit.objects.select_for_update().filter(stay=stay).order_by("pk"))
    if not any(d.held > 0 for d in deposits):
        return
    for charge in stay.charges.select_related("sale").order_by("pk"):
        owing = _owing(charge.sale)
        for deposit in deposits:
            if owing <= 0:
                break
            if deposit.held <= 0:
                continue
            part = min(owing, deposit.held)
            count = Payment.objects.filter(sale=charge.sale, method="DEPOSIT").count()
            Payment.objects.create(sale=charge.sale, method="DEPOSIT", amount=part, status="COMPLETED", reference=stay.number,
                                   idempotency_key=f"stay-deposit:{deposit.pk}:{charge.sale_id}:{count}")
            deposit.used += part
            deposit.save(update_fields=["used", "updated_at"])
            owing -= part


def _give_back(stay, *, user, method):
    """Gives back what is still held for the guest."""
    from apps.accounting.ledger import cash_code, paired, post_journal
    from apps.accounting.services import post
    if method not in ("CASH", "MPESA", "BANK"):
        raise ValidationError("Choose how the money is given back: cash, M-Pesa or bank.")
    total = Decimal("0")
    for deposit in StayDeposit.objects.select_for_update().filter(stay=stay).order_by("pk"):
        held = deposit.held
        if held <= 0:
            continue
        deposit.refunded += held
        deposit.save(update_fields=["refunded", "updated_at"])
        post(unit="CYBER", method=method, amount=-held, kind="INCOME", reference=f"Given back to guest {stay.number}",
             key=f"stay-refund:{deposit.pk}", user=user, branch=stay.branch, journal=False)
        post_journal(key=f"stay-refund:{deposit.pk}", description=f"Given back to guest {stay.guest_name} ({stay.number})",
                     lines=paired("2300", cash_code(method), held), branch=stay.branch_id, user=user)
        total += held
    return total


def bill(stay):
    """The guest's bill: every charge with what is paid and owed, the money held for them, and what is left."""
    charges, owed = [], Decimal("0")
    for charge in stay.charges.select_related("sale").prefetch_related("sale__items__variant__product", "sale__payments").order_by("pk"):
        sale = charge.sale
        left = _owing(sale)
        owed += left
        lines = [{"name": charge.description or item.variant.product.name, "quantity": item.quantity, "amount": item.net_amount + item.tax_amount}
                 for item in sale.items.all()]
        if charge.kind == StayCharge.NIGHT:
            lines = [{"name": f"Night of {charge.night:%a %d %b}", "quantity": Decimal("1"), "amount": sale.total}]
        charges.append({"id": charge.pk, "kind": charge.kind, "sale_id": sale.pk, "number": sale.number, "at": sale.created_at,
                        "night": charge.night, "lines": lines, "total": sale.total, "owing": left})
    deposits = list(stay.deposits.order_by("pk"))
    held = sum((d.held for d in deposits), Decimal("0"))
    total = sum((c["total"] for c in charges), Decimal("0"))
    return {"charges": charges, "total": total, "owing": owed, "held": held, "balance": owed - held,
            "payments": [{"id": d.pk, "amount": d.amount, "method": d.method, "reference": d.reference, "used": d.used,
                          "refunded": d.refunded, "at": d.created_at} for d in deposits],
            "paid": sum((d.amount - d.refunded for d in deposits), Decimal("0"))}


@transaction.atomic
def check_out(stay, *, user, payment=None, give_back_by=None, leave_owing=False):
    """The guest leaves: nights brought up to date, their payment taken, anything left over given back, the room to clean."""
    stay = _locked(stay)
    if stay.status != Stay.IN:
        raise ValidationError("Only a guest who is in can check out.")
    charge_due_nights(stay)
    if payment and payment.get("amount") not in (None, "", 0, "0"):
        receive(stay, user=user, amount=payment["amount"], method=payment.get("method"), reference=payment.get("reference", ""))
    state = bill(stay)
    if state["owing"] > 0 and not leave_owing:
        raise ValidationError(f"{stay.guest_name} still owes {state['owing']:,.2f}. Take the payment, or let them leave owing it "
                              "on their customer account.")
    if state["held"] > 0:
        if not give_back_by:
            raise ValidationError(f"{stay.guest_name} has {state['held']:,.2f} left from what they paid. Say how it is given back.")
        _give_back(stay, user=user, method=give_back_by)
    now = timezone.now()
    stay.status, stay.checked_out_at = Stay.OUT, now
    stay.departure = max(timezone.localdate(), stay.arrival + timedelta(days=1))
    stay.save()
    Room.objects.filter(pk=stay.room_id).update(condition=Room.DIRTY, updated_at=now)
    return stay


@transaction.atomic
def cancel(stay, *, user, reason="", no_show=False, keep_paid=False, give_back_by=None):
    """A booking called off, or a guest who never came. What they paid is given back, or kept as the booking's price."""
    stay = _locked(stay)
    if stay.status != Stay.BOOKED:
        raise ValidationError("Only a booking not yet checked in can be cancelled.")
    held = sum((d.held for d in stay.deposits.all()), Decimal("0"))
    if held > 0:
        if keep_paid:
            sale = _sale_for(stay, variant=stay.room.room_type.variant, price=held, number=f"{stay.number}-K",
                             key=f"stay-kept:{stay.pk}", user=user)
            StayCharge.objects.create(stay=stay, sale=sale, kind=StayCharge.EXTRA,
                                      description="Booking kept after it was " + ("not taken up" if no_show else "cancelled"))
            use_deposits(stay)
        else:
            _give_back(stay, user=user, method=give_back_by)
    stay.status = Stay.NO_SHOW if no_show else Stay.CANCELLED
    stay.note = (f"{stay.note} · {reason}" if stay.note and reason else reason or stay.note)[:255]
    stay.save()
    return stay


@transaction.atomic
def change_stay(stay, *, user, room=None, departure=None, rate=None, guests=None, id_number=None, phone=None, arrival=None):
    """Moves a guest to another room, extends or shortens their stay, or corrects their details."""
    stay = _locked(stay)
    if stay.status not in OCCUPYING:
        raise ValidationError("This stay is closed.")
    new_arrival = arrival if (arrival and stay.status == Stay.BOOKED) else stay.arrival
    new_departure = departure or stay.departure
    if new_departure <= new_arrival:
        raise ValidationError("The guest leaves at least one night after arriving.")
    if stay.status == Stay.IN and departure and departure <= timezone.localdate():
        raise ValidationError("To leave today, check the guest out.")
    target = Room.objects.select_for_update().get(pk=room.pk) if room else stay.room
    if not target.active or target.condition == Room.OUT_OF_ORDER:
        raise ValidationError(f"Room {target.number} is not available.")
    _check_free(target, max(new_arrival, timezone.localdate()) if stay.status == Stay.IN else new_arrival, new_departure, exclude=stay)
    if room and stay.status == Stay.IN and target.pk != stay.room_id:
        Room.objects.filter(pk=stay.room_id).update(condition=Room.DIRTY, updated_at=timezone.now())
    stay.room, stay.arrival, stay.departure = target, new_arrival, new_departure
    if rate not in (None, ""):
        stay.rate = money(rate, "the price a night")  # nights from now on; nights already charged keep their price
    if guests:
        stay.guests = max(int(guests), 1)
    if id_number is not None:
        stay.id_number = str(id_number).strip()[:40]
    if phone is not None:
        stay.phone = "".join(str(phone).split())[:30]
    stay.save()
    return stay


# The front desk's view ------------------------------------------------------------------------------------------------

def board(day=None):
    """Every room on ``day``: who is in, who arrives and leaves, and which are free, with the day's counts."""
    today = timezone.localdate()
    day = day or today
    rooms = list(Room.objects.filter(active=True).select_related("room_type__variant__product").order_by("number"))
    stays = list(Stay.objects.filter(status__in=OCCUPYING, arrival__lte=day + timedelta(days=1)).select_related("room"))
    result = []
    for room in rooms:
        here = [s for s in stays if s.room_id == room.pk]
        current = next((s for s in here if s.status == Stay.IN), None) if day == today else None
        if current is None:
            current = next((s for s in here if s.arrival <= day < _occupied_until(s, today)), None)
        arriving = next((s for s in here if s.status == Stay.BOOKED and s.arrival == day), None)
        state = ("OCCUPIED" if current and current.status == Stay.IN else "BOOKED" if current else
                 "OUT_OF_ORDER" if room.condition == Room.OUT_OF_ORDER else "FREE")
        result.append({"id": room.pk, "number": room.number, "floor": room.floor, "type": room.room_type.variant.product.name,
                       "type_id": room.room_type_id, "rate": room.room_type.variant.selling_price, "sleeps": room.room_type.sleeps,
                       "condition": room.condition, "note": room.note, "state": state,
                       "stay": _brief(current) if current else None, "arriving": _brief(arriving) if arriving and arriving != current else None,
                       "leaving": bool(current and current.status == Stay.IN and current.departure <= day)})
    counts = {key: sum(1 for r in result if r["state"] == key) for key in ("OCCUPIED", "BOOKED", "FREE", "OUT_OF_ORDER")}
    counts["to_clean"] = sum(1 for r in result if r["condition"] == Room.DIRTY)
    counts["arrivals"] = sum(1 for s in stays if s.status == Stay.BOOKED and s.arrival == day)
    counts["departures"] = sum(1 for s in stays if s.status == Stay.IN and s.departure <= day)
    return {"date": day, "rooms": result, "counts": counts}


def _brief(stay):
    return {"id": stay.pk, "number": stay.number, "guest": stay.guest_name, "phone": stay.phone, "arrival": stay.arrival,
            "departure": stay.departure, "status": stay.status, "guests": stay.guests}


def in_house():
    """Guests who are in, for charging to their room at the till."""
    return [{"id": s.pk, "number": s.number, "room": s.room.number, "guest": s.guest_name}
            for s in Stay.objects.filter(status=Stay.IN).select_related("room").order_by("room__number")]


def find(query):
    query = " ".join(str(query or "").split())
    rows = Stay.objects.select_related("room")
    if query:
        rows = rows.filter(Q(guest_name__icontains=query) | Q(phone__icontains=query) | Q(number__icontains=query)
                           | Q(room__number__iexact=query) | Q(id_number__iexact=query))
    return rows
