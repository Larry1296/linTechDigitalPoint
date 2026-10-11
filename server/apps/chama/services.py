"""The chama's rules: when contributions are owed, who is late and fined, whose turn it is, and the money held.

All of it is the chama's own record. Nothing here touches the shop's cash book, ledger or reports: the money is
the members', held by the treasurer, never the shop's.

Schedule: contributions fall on the start date and then every day, week or month after it (a monthly chama
starting on the 31st falls on the last day of shorter months). A daily chama rests on Sunday: it contributes Monday to
Saturday, and a deadline that would fall on a Sunday moves to Monday, so a week's turn ends on Saturday and the next
member's turn starts on Monday. A round is `periods_per_round` contributions;
in a rotating chama one member receives the money at the end of each round, in turn order.

Fines: once a contribution's deadline (period date + grace days, or the date the member promised in an excuse)
has passed, the fine rule is applied to it exactly once: if what was paid on or before the deadline is short, the
chama's fine at that moment is charged. Contributions entered for days before the chama was set up here, or before
a member was added, are never fined, because nobody could have paid them through this record in time.
"""
import calendar
import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog
from .models import LEADERSHIP, ROLES, Chama, ChamaAllocation, ChamaDue, ChamaMember, ChamaPayment, ChamaPayout

ZERO = Decimal("0")
ROLE_LABELS = dict(ROLES)
MAX_AHEAD = 12  # contributions a member may pay or be excused for in advance
MAX_EXCUSE_DAYS = 90
STEP = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month"}


def money(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        raise ValidationError("Enter an amount such as 500 or 250.50.")


def _sum(expression, **filters):
    return Coalesce(Sum(expression, **filters), Value(ZERO), output_field=DecimalField(max_digits=14, decimal_places=2))


def _log(action, obj, user, **after):
    AuditLog.objects.create(action=action, object_type=type(obj).__name__, object_id=str(obj.pk), user=user,
                            after={key: str(value) for key, value in after.items()})


# --- Schedule ---------------------------------------------------------------------------------------------------

SUNDAY = 6


def _working_day(start, index):
    """The working day (Monday to Saturday) `index` working days after `start`, itself a working day."""
    weeks, rest = divmod(index, 6)
    day = start + timedelta(weeks=weeks)
    while rest:
        day += timedelta(days=1)
        rest -= day.weekday() != SUNDAY
    return day


def _working_days_through(start, day):
    """How many working days there are from `start` through `day`, both included."""
    weeks, rest = divmod((day - start).days, 7)
    return weeks * 6 + sum((start + timedelta(days=offset)).weekday() != SUNDAY for offset in range(rest + 1))


def deadline_for(chama, day):
    """The last day to pay a contribution without a fine: the grace days after it, never a Sunday for a daily chama."""
    deadline = day + timedelta(days=chama.grace_days)
    return deadline + timedelta(days=1) if chama.frequency == "DAILY" and deadline.weekday() == SUNDAY else deadline


def period_date(chama, index):
    start = chama.start_date
    if chama.frequency == "DAILY":
        return _working_day(start, index)
    if chama.frequency == "WEEKLY":
        return start + timedelta(weeks=index)
    months = start.month - 1 + index
    year, month = start.year + months // 12, months % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def period_index(chama, day):
    """The latest contribution on or before `day` (0 is the first), or -1 before the first."""
    start = chama.start_date
    if day < start:
        return -1
    if chama.frequency == "DAILY":
        return _working_days_through(start, day) - 1
    if chama.frequency == "WEEKLY":
        return (day - start).days // 7
    months = (day.year - start.year) * 12 + day.month - start.month
    return months if period_date(chama, months) <= day else months - 1


def is_period_date(chama, day):
    index = period_index(chama, day)
    return index >= 0 and period_date(chama, index) == day


def periods_between(chama, after, through):
    """Contribution dates later than `after` (None: from the start) and on or before `through`."""
    first = 0 if after is None else period_index(chama, after) + 1
    return [period_date(chama, index) for index in range(first, period_index(chama, through) + 1)]


def round_of(chama, day):
    return period_index(chama, day) // chama.periods_per_round + 1


def round_dates(chama, number):
    first = (number - 1) * chama.periods_per_round
    return [period_date(chama, index) for index in range(first, first + chama.periods_per_round)]


def owes_on(member, day):
    return member.joined_on <= day and (member.left_on is None or day < member.left_on)


# --- Contributions owed and fines ---------------------------------------------------------------------------------

def _create_dues(chama, members, after, through, fines):
    """Owed contributions for these members from after `after` through `through`. Existing ones are kept."""
    dates = periods_between(chama, after, through)
    if not dates or not members:
        return
    today = timezone.localdate()
    existing = set(ChamaDue.objects.filter(chama=chama, period_date__gte=dates[0], period_date__lte=dates[-1])
                   .values_list("member_id", "period_date"))
    rows = []
    for day in dates:
        deadline = deadline_for(chama, day)
        for member in members:
            if owes_on(member, day) and (member.pk, day) not in existing:
                # Days that passed before they could be recorded here are never fined.
                rows.append(ChamaDue(chama=chama, member=member, period_date=day, amount=chama.contribution_amount,
                                     deadline=deadline, fine_checked=not fines and deadline < today))
    ChamaDue.objects.bulk_create(rows)


def _due_for(chama, member, day):
    """The member's contribution for one date, created if it is not owed yet (paying or excusing ahead)."""
    due = ChamaDue.objects.filter(member=member, period_date=day).first()
    if due:
        return due
    return ChamaDue.objects.create(chama=chama, member=member, period_date=day, amount=chama.contribution_amount,
                                   deadline=deadline_for(chama, day))


def with_totals(dues):
    live = Q(allocations__payment__reversed_at__isnull=True)
    return dues.annotate(paid=_sum("allocations__amount", filter=live & Q(allocations__part="CONTRIBUTION")),
                         fine_paid=_sum("allocations__amount", filter=live & Q(allocations__part="FINE")))


def fine_owed(due):
    return ZERO if due.fine_waived_at else max(ZERO, due.fine_amount - due.fine_paid)


def _paid_by_deadline(due):
    return ChamaAllocation.objects.filter(due=due, part="CONTRIBUTION", payment__reversed_at__isnull=True,
                                          payment__paid_on__lte=due.pay_by).aggregate(v=_sum("amount"))["v"]


def _apply_fines(chama, today):
    late = Q(excused_until__isnull=True, deadline__lt=today) | Q(excused_until__lt=today)
    for due in ChamaDue.objects.filter(chama=chama, fine_checked=False).filter(late):
        changes = {"fine_checked": True}
        if chama.fine_amount > 0 and _paid_by_deadline(due) < due.amount:
            changes.update(fine_amount=chama.fine_amount, fined_on=due.pay_by + timedelta(days=1))
        ChamaDue.objects.filter(pk=due.pk).update(**changes)


@transaction.atomic
def sync(chama, today=None):
    """Bring the chama up to today: contributions owed so far, and fines for deadlines that have passed."""
    today = today or timezone.localdate()
    chama = Chama.objects.select_for_update().get(pk=chama.pk)
    if chama.dues_through is None or chama.dues_through < today:
        _create_dues(chama, list(chama.members.all()), chama.dues_through, today, fines=True)
        Chama.objects.filter(pk=chama.pk).update(dues_through=today)
        chama.dues_through = today
    _apply_fines(chama, today)
    return chama


# --- Setting up and members ---------------------------------------------------------------------------------------

def clean_name(value):
    name = " ".join(str(value or "").split())
    if len(name.split(" ")) < 2 or len(name) < 4:
        raise ValidationError(f"Enter the member's full name, at least two names{f' (not just “{name}”)' if name else ''}.")
    return name[:120]


def clean_id(value):
    number = re.sub(r"[\s-]", "", str(value or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,20}", number):
        raise ValidationError("Enter the member's ID number: 4 to 20 letters or digits, such as 12345678.")
    return number


def clean_phone(value):
    phone = re.sub(r"[\s()-]", "", str(value or ""))
    if not re.fullmatch(r"\+?\d{9,15}", phone):
        raise ValidationError("Enter the member's phone number, such as 0712 345 678.")
    return phone


def _role(value):
    role = str(value or "MEMBER").upper()
    if role not in ROLE_LABELS:
        raise ValidationError("Choose the member's role in the chama.")
    return role


def _rules(data, today, chama=None):
    """Check the chama's rules. On an existing chama only the fields sent are checked."""
    values = {}
    if "name" in data:
        values["name"] = " ".join(str(data["name"] or "").split())[:120]
        if len(values["name"]) < 2:
            raise ValidationError("Enter the chama's name.")
    if "contribution_amount" in data:
        values["contribution_amount"] = money(data["contribution_amount"])
        if values["contribution_amount"] <= 0:
            raise ValidationError("Enter how much each member contributes, above zero.")
    if "fine_amount" in data:
        values["fine_amount"] = money(data["fine_amount"] or 0)
        if values["fine_amount"] < 0:
            raise ValidationError("The fine cannot be below zero. Enter 0 for no fine.")
    if "grace_days" in data:
        try:
            values["grace_days"] = int(data["grace_days"] or 0)
        except (TypeError, ValueError):
            raise ValidationError("Enter the days allowed after the contribution date as a whole number.")
        if not 0 <= values["grace_days"] <= 60:
            raise ValidationError("Allow between 0 and 60 days to pay after the contribution date.")
    if "frequency" in data:
        values["frequency"] = str(data["frequency"] or "").upper()
        if values["frequency"] not in STEP:
            raise ValidationError("Choose how often members contribute: every day, week or month.")
    if "payout_mode" in data:
        values["payout_mode"] = str(data["payout_mode"] or "").upper()
        if values["payout_mode"] not in {"ROTATION", "SAVINGS"}:
            raise ValidationError("Choose whether members take turns to receive the money or save it together.")
    if "turn_choice" in data:
        values["turn_choice"] = str(data["turn_choice"] or "ORDER").upper()
        if values["turn_choice"] not in {"ORDER", "AGREED"}:
            raise ValidationError("Choose whether turns follow the members' order or the members agree who receives next.")
    if "periods_per_round" in data:
        try:
            values["periods_per_round"] = int(data["periods_per_round"] or 1)
        except (TypeError, ValueError):
            raise ValidationError("Enter how many contributions make one turn as a whole number.")
        if not 1 <= values["periods_per_round"] <= 60:
            raise ValidationError("A turn is between 1 and 60 contributions.")
    if "start_date" in data:
        values["start_date"] = data["start_date"]
        if not values["start_date"]:
            raise ValidationError("Choose the date of the first contribution to record.")
        if values["start_date"] < today - timedelta(days=31):
            raise ValidationError("Start from the current or next contribution, within the last month. "
                                  "Contributions before that are not entered here.")
        if values["start_date"] > today + timedelta(days=366):
            raise ValidationError("The first contribution must be within the next year.")
    if "notes" in data:
        values["notes"] = str(data["notes"] or "")[:2000]
    frequency = values.get("frequency", chama.frequency if chama else None)
    start = values.get("start_date", chama.start_date if chama else None)
    if frequency == "DAILY" and start and start.weekday() == SUNDAY:
        raise ValidationError("Sunday is the chama's rest day: a daily chama contributes Monday to Saturday. Start on Monday instead.")
    return values


@transaction.atomic
def create_chama(*, user, data):
    """A new chama with its leaders and members, listed in the order they will receive the money."""
    today = timezone.localdate()
    required = ["name", "contribution_amount", "frequency", "start_date"]
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        raise ValidationError("Enter the chama's name, the contribution, how often it is paid and the first contribution date.")
    first_receiver = data.get("first_receiver")
    values = _rules({"grace_days": 0, "fine_amount": 0, "payout_mode": "ROTATION", "periods_per_round": 1, "turn_choice": "ORDER",
                     **{key: value for key, value in data.items() if key not in {"members", "first_receiver"}}}, today)
    people = list(data.get("members") or [])
    if len(people) < 2:
        raise ValidationError("A chama needs at least two members. Add every member, including yourself if you contribute.")
    if len(people) > 500:
        raise ValidationError("A chama can have up to 500 members.")
    members, seen, offices = [], set(), {}
    for position, person in enumerate(people, start=1):
        name = clean_name(person.get("full_name"))
        number, phone, role = clean_id(person.get("id_number")), clean_phone(person.get("phone")), _role(person.get("role"))
        if number in seen:
            raise ValidationError(f"ID number {number} is entered for more than one member.")
        seen.add(number)
        if role in LEADERSHIP:
            if role in offices:
                raise ValidationError(f"Only one member can be {ROLE_LABELS[role].lower()}: {offices[role]} and {name} are both chosen.")
            offices[role] = name
        members.append((name, number, phone, role, position))
    if "TREASURER" not in offices:
        raise ValidationError("Choose the chama's treasurer: the member who keeps the money and records it here.")
    chama = Chama.objects.create(**values, created_by=user)
    rows = [ChamaMember.objects.create(chama=chama, full_name=name, id_number=number, phone=phone, role=role, turn_position=position,
                                       joined_on=chama.start_date) for name, number, phone, role, position in members]
    # Contributions already due today are owed straight away, but not fined: they were not recorded here in time.
    if first_receiver is not None and chama.payout_mode == "ROTATION":
        if not 0 <= first_receiver < len(rows):
            raise ValidationError("Choose who receives the first turn from the members listed.")
        Chama.objects.filter(pk=chama.pk).update(next_receiver=rows[first_receiver], next_receiver_note="Agreed when the chama was set up",
                                                 next_receiver_set_at=timezone.now())
    _create_dues(chama, rows, None, today, fines=False)
    Chama.objects.filter(pk=chama.pk).update(dues_through=today)
    chama.dues_through = today
    _log("CHAMA_CREATED", chama, user, name=chama.name, members=len(rows), contribution=chama.contribution_amount, frequency=chama.frequency)
    return chama


@transaction.atomic
def update_rules(*, chama, user, data):
    chama = sync(chama)
    values = _rules(data, timezone.localdate(), chama)
    started = chama.dues.exists()
    for field in ("frequency", "start_date"):
        if field in values and values[field] != getattr(chama, field) and started:
            raise ValidationError("How often members contribute and the first contribution date cannot change once contributions "
                                  "have started, because past contributions depend on them. Start a new chama for a new schedule.")
    paid_out = chama.payouts.filter(reversed_at__isnull=True).exists()
    for field in ("payout_mode", "periods_per_round"):
        if field in values and values[field] != getattr(chama, field) and paid_out:
            raise ValidationError("Turns cannot be changed after money has been given out. Reverse those payouts first if they were mistakes.")
    before = {field: str(getattr(chama, field)) for field in values}
    for field, value in values.items():
        setattr(chama, field, value)
    chama.save()
    if "start_date" in values and not started:
        Chama.objects.filter(pk=chama.pk).update(dues_through=None)
        chama.members.update(joined_on=chama.start_date)
        sync(chama)
    AuditLog.objects.create(action="CHAMA_RULES_CHANGED", object_type="Chama", object_id=str(chama.pk), user=user,
                            before=before, after={field: str(value) for field, value in values.items()})
    return chama


def _take_office(chama, member, role):
    """Giving someone an office moves it from whoever held it; the treasurer's office is never left empty."""
    if member.role == "TREASURER" and role != "TREASURER":
        raise ValidationError(f"{member.full_name} is the treasurer. Make another member treasurer first; the role then moves to them.")
    if role in LEADERSHIP:
        chama.members.filter(role=role, left_on__isnull=True).exclude(pk=member.pk).update(role="MEMBER")


@transaction.atomic
def add_member(*, chama, user, data):
    chama = sync(chama)
    today = timezone.localdate()
    name, number, phone = clean_name(data.get("full_name")), clean_id(data.get("id_number")), clean_phone(data.get("phone"))
    role = _role(data.get("role"))
    if chama.members.filter(id_number=number).exists():
        raise ValidationError(f"A member with ID number {number} is already in this chama.")
    joined = data.get("joined_on") or today
    if joined > today:
        raise ValidationError("The joining date cannot be in the future.")
    joined = max(joined, chama.start_date)
    position = (chama.members.aggregate(v=Max("turn_position"))["v"] or 0) + 1
    member = ChamaMember(chama=chama, full_name=name, id_number=number, phone=phone, role="MEMBER", turn_position=position, joined_on=joined)
    member.save()
    if role != "MEMBER":
        _take_office(chama, member, role)
        ChamaMember.objects.filter(pk=member.pk).update(role=role)
        member.role = role
    if chama.dues_through:
        # Owes from the joining date; contributions from before today are not fined.
        _create_dues(chama, [member], joined - timedelta(days=1), chama.dues_through, fines=False)
    _log("CHAMA_MEMBER_ADDED", member, user, chama=chama.name, name=name, role=role, joined_on=joined)
    return member


@transaction.atomic
def update_member(*, member, user, data):
    sync(member.chama)
    member = ChamaMember.objects.select_for_update().get(pk=member.pk)
    before = {"full_name": member.full_name, "id_number": member.id_number, "phone": member.phone, "role": member.role}
    if "full_name" in data:
        member.full_name = clean_name(data["full_name"])
    if "phone" in data:
        member.phone = clean_phone(data["phone"])
    if "id_number" in data:
        number = clean_id(data["id_number"])
        if ChamaMember.objects.filter(chama_id=member.chama_id, id_number=number).exclude(pk=member.pk).exists():
            raise ValidationError(f"A member with ID number {number} is already in this chama.")
        member.id_number = number
    if "role" in data:
        role = _role(data["role"])
        if role != member.role:
            if member.left_on:
                raise ValidationError(f"{member.full_name} has left the chama and cannot hold an office.")
            _take_office(member.chama, member, role)
            member.role = role
    member.save()
    AuditLog.objects.create(action="CHAMA_MEMBER_CHANGED", object_type="ChamaMember", object_id=str(member.pk), user=user, before=before,
                            after={"full_name": member.full_name, "id_number": member.id_number, "phone": member.phone, "role": member.role})
    return member


@transaction.atomic
def member_leaves(*, member, user, reason):
    sync(member.chama)
    member = ChamaMember.objects.select_for_update().get(pk=member.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the member is leaving.")
    if member.left_on:
        return member
    if member.role == "TREASURER":
        raise ValidationError(f"{member.full_name} is the treasurer. Make another member treasurer before they leave.")
    today = timezone.localdate()
    # Nothing more is owed from tomorrow; what is already owed (including today) stays owed.
    member.left_on = today + timedelta(days=1)
    member.leave_reason = str(reason).strip()
    member.save(update_fields=["left_on", "leave_reason"])
    Chama.objects.filter(pk=member.chama_id, next_receiver=member).update(next_receiver=None, next_receiver_note="", next_receiver_set_at=None)
    ChamaDue.objects.filter(member=member, period_date__gte=member.left_on).filter(allocations__isnull=True).delete()
    _log("CHAMA_MEMBER_LEFT", member, user, name=member.full_name, reason=member.leave_reason)
    return member


@transaction.atomic
def remove_member(*, member, user, reason):
    """A member added by mistake: deleted completely, with what they were said to owe. Only while they have no money
    history (no payment in or out, even undone): anyone with money history leaves instead, so the record stays."""
    sync(member.chama)
    member = ChamaMember.objects.select_for_update().get(pk=member.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the member is being removed.")
    if member.payments.exists() or member.payouts.exists():
        raise ValidationError(f"{member.full_name} has payments on record, so they cannot be deleted. "
                              "Use \"Leaves the chama\" instead: they stop owing and their record is kept.")
    if member.role == "TREASURER":
        raise ValidationError(f"{member.full_name} is the treasurer. Make another member treasurer first.")
    chama = member.chama
    if chama.members.filter(left_on__isnull=True).exclude(pk=member.pk).count() < 2:
        raise ValidationError("A chama needs at least two members. Add the right member before removing this one.")
    Chama.objects.filter(pk=chama.pk, next_receiver=member).update(next_receiver=None, next_receiver_note="", next_receiver_set_at=None)
    ChamaDue.objects.filter(member=member).delete()
    _log("CHAMA_MEMBER_REMOVED", member, user, chama=chama.name, name=member.full_name, id_number=member.id_number,
         reason=str(reason).strip())
    member.delete()


@transaction.atomic
def member_rejoins(*, member, user):
    """A member who left comes back: they owe from today again (no fines for the days they were away) and take the
    last turn."""
    chama = sync(member.chama)
    member = ChamaMember.objects.select_for_update().get(pk=member.pk)
    if member.left_on is None:
        return member
    if chama.members.filter(left_on__isnull=True, id_number=member.id_number).exclude(pk=member.pk).exists():
        raise ValidationError(f"A member with ID number {member.id_number} is already in this chama.")
    today = timezone.localdate()
    away_from = member.left_on
    member.left_on = None
    member.leave_reason = ""
    member.turn_position = (chama.members.aggregate(v=Max("turn_position"))["v"] or 0) + 1
    member.save(update_fields=["left_on", "leave_reason", "turn_position"])
    if chama.dues_through:
        # Owes again from today; the contributions while away are not owed.
        _create_dues(chama, [member], max(today, away_from) - timedelta(days=1), chama.dues_through, fines=False)
    _log("CHAMA_MEMBER_REJOINED", member, user, chama=chama.name, name=member.full_name, rejoined_on=today)
    return member


@transaction.atomic
def set_turn_order(*, chama, user, member_ids):
    chama = sync(chama)
    active = list(chama.members.filter(left_on__isnull=True).values_list("pk", flat=True))
    try:
        ids = [int(value) for value in member_ids]
    except (TypeError, ValueError):
        raise ValidationError("Send the members in their new turn order.")
    if sorted(ids) != sorted(active):
        raise ValidationError("List every current member exactly once in the new turn order.")
    for position, pk in enumerate(ids, start=1):
        ChamaMember.objects.filter(pk=pk).update(turn_position=position)
    left = chama.members.filter(left_on__isnull=False).order_by("turn_position", "pk")
    for offset, member in enumerate(left, start=len(ids) + 1):
        ChamaMember.objects.filter(pk=member.pk).update(turn_position=offset)
    _log("CHAMA_TURNS_CHANGED", chama, user, order=",".join(map(str, ids)))
    return chama


# --- Money in ---------------------------------------------------------------------------------------------------

def _member_of(chama, member_id):
    member = ChamaMember.objects.filter(chama=chama, pk=member_id).first()
    if not member:
        raise ValidationError("Choose a member of this chama.")
    return member


def _method(method, reference):
    method = str(method or "").upper()
    if method not in {"CASH", "MPESA", "BANK", "OTHER"}:
        raise ValidationError("Choose cash, M-Pesa, bank or other.")
    reference = str(reference or "").strip().upper()[:120]
    if method == "MPESA" and not reference:
        raise ValidationError("Enter the M-Pesa code so the payment can be checked against the M-Pesa message.")
    return method, reference


@transaction.atomic
def record_payment(*, chama, member_id, amount, paid_on, method, reference="", key, user):
    """Money from a member, shared out to their oldest unpaid contributions, then fines, then contributions ahead."""
    chama = sync(chama)
    existing = ChamaPayment.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    today = timezone.localdate()
    member = _member_of(chama, member_id)
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    paid_on = paid_on or today
    if paid_on > today:
        raise ValidationError("The payment date cannot be in the future.")
    method, reference = _method(method, reference)
    payment = ChamaPayment.objects.create(chama=chama, member=member, amount=amount, paid_on=paid_on, method=method, reference=reference,
                                          idempotency_key=key, created_by=user)
    remaining = amount
    touched = []

    def allocate(due, part, owed):
        nonlocal remaining
        take = min(remaining, owed)
        if take > 0:
            ChamaAllocation.objects.create(payment=payment, due=due, part=part, amount=take)
            remaining -= take
            if part == "CONTRIBUTION":
                touched.append(due)

    owed = list(with_totals(ChamaDue.objects.filter(member=member, period_date__lte=today)).order_by("period_date", "pk"))
    for due in owed:
        allocate(due, "CONTRIBUTION", due.amount - due.paid)
    for due in owed:
        allocate(due, "FINE", fine_owed(due))
    if remaining > 0 and not member.left_on:
        first = period_index(chama, today) + 1
        for index in range(first, first + MAX_AHEAD):
            if remaining <= 0:
                break
            due = with_totals(ChamaDue.objects.filter(pk=_due_for(chama, member, period_date(chama, index)).pk)).get()
            allocate(due, "CONTRIBUTION", due.amount - due.paid)
    if remaining > 0:
        raise ValidationError(f"{member.full_name} owes less than {amount:,.2f}, even counting the next {MAX_AHEAD} contributions. "
                              f"Record {amount - remaining:,.2f} or less.")
    # A fine charged because the payment was entered after the deadline is cancelled when it was paid on time.
    for due in touched:
        due.refresh_from_db()
        if due.fine_amount > 0 and not due.fine_waived_at and not due.allocations.filter(part="FINE", payment__reversed_at__isnull=True).exists() \
                and _paid_by_deadline(due) >= due.amount:
            ChamaDue.objects.filter(pk=due.pk).update(fine_waived_at=timezone.now(), fine_waived_by=user,
                                                      fine_waive_reason="Paid on time; the payment was recorded after the deadline.")
    _log("CHAMA_PAYMENT", payment, user, chama=chama.name, member=member.full_name, amount=amount, method=method, reference=reference)
    return payment


@transaction.atomic
def reverse_payment(*, payment, user, reason):
    """A payment recorded by mistake: the member owes it again, and the fine rule is applied again where late."""
    sync(payment.chama)
    payment = ChamaPayment.objects.select_for_update().get(pk=payment.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the payment is being reversed.")
    if payment.reversed_at:
        return payment
    payment.reversed_at, payment.reverse_reason, payment.reversed_by = timezone.now(), str(reason).strip(), user
    payment.save(update_fields=["reversed_at", "reverse_reason", "reversed_by"])
    due_ids = payment.allocations.filter(part="CONTRIBUTION").values_list("due_id", flat=True)
    ChamaDue.objects.filter(pk__in=list(due_ids), fine_amount=0).update(fine_checked=False)
    sync(payment.chama)
    _log("CHAMA_PAYMENT_REVERSED", payment, user, amount=payment.amount, reason=payment.reverse_reason)
    return payment


@transaction.atomic
def excuse(*, chama, member_id, period, pay_by, reason, user):
    """A member says in advance (or before the deadline) that they will pay late, and promises a date."""
    chama = sync(chama)
    today = timezone.localdate()
    member = _member_of(chama, member_id)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Enter the reason the member gave for paying late.")
    if not period or not is_period_date(chama, period):
        raise ValidationError("Choose one of the chama's contribution dates.")
    if period > period_date(chama, period_index(chama, today) + MAX_AHEAD):
        raise ValidationError(f"An excuse can be given for at most the next {MAX_AHEAD} contributions.")
    if not owes_on(member, period):
        raise ValidationError(f"{member.full_name} does not owe a contribution on that date.")
    due = with_totals(ChamaDue.objects.filter(pk=_due_for(chama, member, period).pk)).get()
    if due.paid >= due.amount:
        raise ValidationError(f"{member.full_name} has already paid this contribution.")
    if due.fine_amount > 0:
        raise ValidationError("This contribution was already fined because its deadline passed. Waive the fine instead if the members agree.")
    if due.fine_checked or due.pay_by < today:
        raise ValidationError("The deadline for this contribution has already passed.")
    if not pay_by or pay_by <= due.deadline or pay_by < today:
        raise ValidationError(f"Choose the date the member promises to pay, after the usual deadline ({due.deadline:%d %b %Y}).")
    if pay_by > due.deadline + timedelta(days=MAX_EXCUSE_DAYS):
        raise ValidationError(f"An excuse can delay a contribution by at most {MAX_EXCUSE_DAYS} days.")
    ChamaDue.objects.filter(pk=due.pk).update(excused_until=pay_by, excuse_reason=reason[:1000], excused_by=user, excused_at=timezone.now())
    _log("CHAMA_EXCUSE", due, user, member=member.full_name, period=period, pay_by=pay_by, reason=reason)
    return due


@transaction.atomic
def waive_fine(*, due, user, reason):
    sync(due.chama)
    due = with_totals(ChamaDue.objects.filter(pk=due.pk)).get()
    if not str(reason or "").strip():
        raise ValidationError("Explain why the fine is being waived.")
    if due.fine_amount <= 0 or due.fine_waived_at:
        raise ValidationError("There is no fine to waive on this contribution.")
    if due.fine_paid > 0:
        raise ValidationError("Part of this fine has been paid. Reverse that payment first if the fine should not have been charged.")
    ChamaDue.objects.filter(pk=due.pk).update(fine_waived_at=timezone.now(), fine_waived_by=user, fine_waive_reason=str(reason).strip())
    _log("CHAMA_FINE_WAIVED", due, user, amount=due.fine_amount, reason=reason)
    return due


# --- Money out and turns ------------------------------------------------------------------------------------------

def held(chama):
    """The chama's money the treasurer is holding: everything paid in less everything given out."""
    paid_in = chama.payments.filter(reversed_at__isnull=True).aggregate(v=_sum("amount"))["v"]
    paid_out = chama.payouts.filter(reversed_at__isnull=True).aggregate(v=_sum("amount"))["v"]
    return paid_in - paid_out


def _round_money(chama, number, members):
    """What a round should collect and what has been collected for it so far."""
    dates = round_dates(chama, number)
    dues = {(due.member_id, due.period_date): due for due in with_totals(ChamaDue.objects.filter(chama=chama, period_date__in=dates))}
    expected = collected = ZERO
    for day in dates:
        for member in members:
            due = dues.get((member.pk, day))
            if due:
                expected += due.amount
                collected += due.paid
            elif owes_on(member, day):
                expected += chama.contribution_amount
    return expected, collected


def cycle(chama):
    """The turns given out so far, the members in turn order, and who has not yet received in this round of turns."""
    order = list(chama.members.filter(left_on__isnull=True))
    payouts = list(chama.payouts.filter(reversed_at__isnull=True, round_number__isnull=False).select_related("member").order_by("round_number"))
    received = set()
    for payout in payouts:
        received.add(payout.member_id)
        if order and all(m.pk in received for m in order):
            received = set()  # everyone has had a turn: a new cycle starts
    return payouts, order, [m for m in order if m.pk not in received]


def agreed_next(chama, waiting):
    """The member the members agreed receives next, while that agreement still applies."""
    return next((m for m in waiting if m.pk == chama.next_receiver_id), None)


def schedule(chama, today=None, ahead=None):
    """Every turn: those already given out, then who receives next for one full cycle.

    In turn order, the agreed next receiver (if any) goes first and the rest follow the list. When the members agree
    each turn, only the agreed next receiver is known; later turns show as still to be agreed.
    """
    today = today or timezone.localdate()
    members = list(chama.members.all())
    payouts, order, waiting = cycle(chama)
    agreed = agreed_next(chama, waiting)
    if chama.turn_choice == "AGREED":
        queue = [agreed] + [None] * (len(order) * 2)
    else:
        queue = ([agreed] if agreed else []) + [m for m in waiting if m != agreed] + order * 2
    rows = [{"round": p.round_number, "date": round_dates(chama, p.round_number)[-1], "member_id": p.member_id, "member": p.member.full_name,
             "amount": p.amount, "paid_on": p.paid_on, "payout_id": p.pk, "status": "GIVEN"} for p in payouts]
    next_round = (payouts[-1].round_number if payouts else 0) + 1
    for offset in range(ahead if ahead is not None else len(order)):
        if not order:
            break
        number, member = next_round + offset, queue[offset]
        day = round_dates(chama, number)[-1]
        expected, collected = _round_money(chama, number, members) if offset < 2 else (None, None)
        rows.append({"round": number, "date": day, "member_id": member.pk if member else None, "member": member.full_name if member else "",
                     "agreed": bool(offset == 0 and agreed), "expected": expected, "collected": collected,
                     "status": "DUE" if day <= today else "UPCOMING"})
    return rows


@transaction.atomic
def set_next_receiver(*, chama, member_id, note, user):
    """Record who the members agreed receives the next turn, or clear it (member_id None)."""
    chama = sync(chama)
    if chama.payout_mode != "ROTATION":
        raise ValidationError("This chama saves its money together; members do not take turns.")
    if member_id is None:
        Chama.objects.filter(pk=chama.pk).update(next_receiver=None, next_receiver_note="", next_receiver_set_at=None)
        _log("CHAMA_NEXT_RECEIVER_CLEARED", chama, user)
        return chama
    member = _member_of(chama, member_id)
    _, _, waiting = cycle(chama)
    if member.left_on:
        raise ValidationError(f"{member.full_name} has left the chama.")
    if member not in waiting:
        names = ", ".join(m.full_name for m in waiting)
        raise ValidationError(f"{member.full_name} has already received in this round of turns. Each member receives once before anyone "
                              f"receives again. Still to receive: {names}.")
    note = str(note or "").strip()[:500]
    Chama.objects.filter(pk=chama.pk).update(next_receiver=member, next_receiver_note=note, next_receiver_set_at=timezone.now())
    _log("CHAMA_NEXT_RECEIVER_AGREED", chama, user, member=member.full_name, note=note)
    return chama


@transaction.atomic
def record_payout(*, chama, member_id=None, amount, paid_on=None, method, reference="", notes="", key, user):
    chama = sync(chama)
    existing = ChamaPayout.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    today = timezone.localdate()
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Enter the amount given out, above zero.")
    paid_on = paid_on or today
    if paid_on > today:
        raise ValidationError("The payout date cannot be in the future.")
    method, reference = _method(method, reference)
    round_number, scheduled = None, None
    if chama.payout_mode == "ROTATION":
        upcoming = [row for row in schedule(chama, today, ahead=1) if row["status"] != "GIVEN"]
        if not upcoming:
            raise ValidationError("There are no members to receive the money.")
        round_number, scheduled = upcoming[0]["round"], upcoming[0]["member_id"]
        if not (member_id or scheduled):
            raise ValidationError("The members have not agreed who receives this turn yet. Choose the member they agreed on.")
    member = _member_of(chama, member_id or scheduled)
    if member.left_on:
        raise ValidationError(f"{member.full_name} has left the chama.")
    if round_number and member not in cycle(chama)[2]:
        raise ValidationError(f"{member.full_name} has already received in this round of turns. Each member receives once before anyone receives again.")
    available = held(chama)
    if amount > available:
        raise ValidationError(f"The chama holds only {available:,.2f}, so {amount:,.2f} cannot be given out.")
    payout = ChamaPayout.objects.create(chama=chama, member=member, round_number=round_number, amount=amount, paid_on=paid_on, method=method,
                                        reference=reference, notes=str(notes or "")[:1000], idempotency_key=key, created_by=user)
    if round_number:  # the agreement was for this turn
        Chama.objects.filter(pk=chama.pk).update(next_receiver=None, next_receiver_note="", next_receiver_set_at=None)
    _log("CHAMA_PAYOUT", payout, user, chama=chama.name, member=member.full_name, amount=amount, round=round_number or "",
         instead_of=scheduled if scheduled and scheduled != member.pk else "")
    return payout


@transaction.atomic
def reverse_payout(*, payout, user, reason):
    sync(payout.chama)
    payout = ChamaPayout.objects.select_for_update().get(pk=payout.pk)
    if not str(reason or "").strip():
        raise ValidationError("Explain why the payout is being reversed.")
    if payout.reversed_at:
        return payout
    if payout.round_number and ChamaPayout.objects.filter(chama_id=payout.chama_id, reversed_at__isnull=True,
                                                           round_number__gt=payout.round_number).exists():
        raise ValidationError("Later turns have already been given out. Reverse the latest one first.")
    payout.reversed_at, payout.reverse_reason, payout.reversed_by = timezone.now(), str(reason).strip(), user
    payout.save(update_fields=["reversed_at", "reverse_reason", "reversed_by"])
    _log("CHAMA_PAYOUT_REVERSED", payout, user, amount=payout.amount, reason=payout.reverse_reason)
    return payout
