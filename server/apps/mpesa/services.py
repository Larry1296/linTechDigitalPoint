from apps.tenancy.transactions import lock_business
from apps.tenancy.permissions import has_business_permission, is_business_manager
from decimal import Decimal
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog

from .models import MpesaCommissionEntry, MpesaReconciliation, MpesaSession, MpesaTransaction


def amount(value):
    parsed = Decimal(str(value)).quantize(Decimal("0.01"))
    if parsed <= 0:
        raise ValidationError("Amount must be positive.")
    return parsed


def audit(action, obj, user, before=None, after=None):
    AuditLog.objects.create(action=action, object_type=obj.__class__.__name__, object_id=str(obj.pk), user=user, before=before or {}, after=after or {})


# Kenyan notes counted one by one; coins are entered as a single amount.
NOTES = (1000, 500, 200, 100, 50)


def count_cash(count):
    """Validates a note-and-coin count and returns it normalised with its total."""
    if not isinstance(count, dict):
        raise ValidationError("Send the cash count as note counts and a coins amount.")
    unknown = set(count) - {str(note) for note in NOTES} - {"coins"}
    if unknown:
        raise ValidationError(f"Unknown cash denomination: {', '.join(sorted(unknown))}.")
    normalised, total = {}, Decimal("0")
    for note in NOTES:
        raw = count.get(str(note)) or 0
        try:
            pieces = int(str(raw))
        except ValueError:
            raise ValidationError(f"Enter a whole number of {note} notes.")
        if pieces < 0:
            raise ValidationError(f"The number of {note} notes cannot be negative.")
        normalised[str(note)] = pieces
        total += note * pieces
    try:
        coins = Decimal(str(count.get("coins") or 0)).quantize(Decimal("0.01"))
    except ArithmeticError:
        raise ValidationError("Enter the coins total as an amount.")
    if not coins.is_finite() or coins < 0:
        raise ValidationError("The coins total cannot be negative.")
    normalised["coins"] = str(coins)
    return normalised, total + coins


def counted_cash(cash, count):
    """The cash figure to record: the counted total when notes were counted, which must agree with any typed amount."""
    if not count:
        return Decimal(str(cash)), {}
    normalised, total = count_cash(count)
    if cash not in (None, "") and Decimal(str(cash)) != total:
        raise ValidationError(f"The notes and coins add up to {total}, not {cash}.")
    return total, normalised


def session_balances(session):
    totals = session.transactions.aggregate(cash=Sum("cash_delta"), float=Sum("float_delta"))
    return (
        session.opening_cash + (totals["cash"] or Decimal("0")),
        session.opening_float + (totals["float"] or Decimal("0")),
    )


@transaction.atomic
def open_session(*, outlet, operator, opening_cash, opening_float, notes="", cash_count=None):
    if MpesaSession.objects.select_for_update().filter(outlet=outlet, status=MpesaSession.OPEN).exists():
        raise ValidationError("This outlet already has an open M-Pesa session.")
    cash, count = counted_cash(opening_cash, cash_count)
    electronic_float = Decimal(str(opening_float))
    if cash < 0 or electronic_float < 0:
        raise ValidationError("Opening balances cannot be negative.")
    session = MpesaSession.objects.create(outlet=outlet, operator=operator, opening_cash=cash, opening_float=electronic_float, opened_at=timezone.now(), notes=notes,
                                     opening_cash_count=count)
    audit("MPESA_SESSION_OPENED", session, operator, after={"cash": str(cash), "float": str(electronic_float)})
    return session


def deltas(transaction_type, value, *, cash_delta=None, float_delta=None, privileged=False):
    if transaction_type == "CUSTOMER_DEPOSIT":
        return value, -value
    if transaction_type == "CUSTOMER_WITHDRAWAL":
        return -value, value
    if transaction_type == "FLOAT_TOPUP":
        return -value, value
    if transaction_type == "CASH_REBALANCE":
        return value, Decimal("0")
    if transaction_type in {"ADJUSTMENT", "INVESTMENT", "COMMISSION"} and privileged:
        return Decimal(str(cash_delta)), Decimal(str(float_delta))
    raise ValidationError("Unsupported transaction type or insufficient permission.")


def normalise_phone(value):
    """A Kenyan mobile number as 2547XXXXXXXX or 2541XXXXXXXX, from 07…, 01…, +254… or 254…."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if len(digits) != 12 or not digits.startswith(("2547", "2541")):
        raise ValidationError("Enter the customer's M-Pesa number, e.g. 0712 345 678.")
    return digits


def customer_details(transaction_type, name, phone, id_number):
    """A deposit may record the customer's number and ID (or passport) number; both are optional, but checked when
    given. A withdrawal records only its amount, with the confirmation code added afterwards. A name is kept only if given."""
    name, id_number = " ".join(str(name or "").split())[:120], str(id_number or "").replace(" ", "").upper()
    if transaction_type != "CUSTOMER_DEPOSIT":
        return name, "", ""
    if id_number and not (4 <= len(id_number) <= 20 and id_number.isalnum()):
        raise ValidationError("An ID or passport number has 4 to 20 letters and digits. Leave it empty if the customer has none.")
    return name, normalise_phone(phone) if str(phone or "").strip() else "", id_number


@transaction.atomic
def post_transaction(*, session, transaction_type, transaction_amount, user, idempotency_key, provider_reference=None, customer_reference="", notes="", cash_delta=None, float_delta=None,
                     customer_name="", customer_phone="", customer_id_number=""):
    lock_business()
    if not idempotency_key:
        raise ValidationError("An idempotency key is required.")
    existing = MpesaTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing, False
    session = MpesaSession.objects.select_for_update().select_related("outlet").get(pk=session.pk)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("This M-Pesa session is closed.")
    privileged = is_business_manager(user)
    if session.operator_id != user.id and not privileged:
        raise ValidationError("You can only post to your assigned M-Pesa session.")
    value = amount(transaction_amount)
    customer = customer_details(transaction_type, customer_name, customer_phone, customer_id_number)
    provider_reference = (provider_reference or "").strip().upper() or None
    if transaction_type in ["FLOAT_TOPUP", "CASH_REBALANCE", "ADJUSTMENT", "INVESTMENT", "COMMISSION"] and not privileged:
        raise ValidationError("Manager or Owner permission is required for balance adjustments.")
    # A correction to the money in operation: the reason is required, a reference only if there is one.
    if transaction_type == "ADJUSTMENT" and not notes.strip():
        raise ValidationError("Say why the money in operation is being corrected.")
    if transaction_type == "ADJUSTMENT" and (cash_delta is None or float_delta is None):
        raise ValidationError("Adjustments require explicit cash and float effects.")
    cash_effect, float_effect = deltas(transaction_type, value, cash_delta=cash_delta, float_delta=float_delta, privileged=privileged)
    current_cash, current_float = session_balances(session)
    if current_cash + cash_effect < 0:
        raise ValidationError("Insufficient physical cash for this operation.")
    if current_float + float_effect < 0:
        raise ValidationError("Insufficient electronic float for this operation.")
    try:
        with transaction.atomic():
            entry = MpesaTransaction.objects.create(
                internal_reference=f"MPA-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}",
                idempotency_key=idempotency_key,
                outlet=session.outlet,
                session=session,
                transaction_type=transaction_type,
                amount=value,
                cash_delta=cash_effect,
                float_delta=float_effect,
                provider_reference=provider_reference or None,
                customer_reference=customer_reference,
                customer_name=customer[0],
                customer_phone=customer[1],
                customer_id_number=customer[2],
                performed_by=user,
                occurred_at=timezone.now(),
                notes=notes,
            )
    except IntegrityError as exc:
        duplicate = MpesaTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if duplicate:
            return duplicate, False
        if provider_reference and MpesaTransaction.objects.filter(provider_reference=provider_reference).exists():
            raise ValidationError("That M-Pesa agency reference has already been posted.") from exc
        raise
    action = {"CUSTOMER_DEPOSIT": "MPESA_DEPOSIT_POSTED", "CUSTOMER_WITHDRAWAL": "MPESA_WITHDRAWAL_POSTED", "FLOAT_TOPUP": "MPESA_FLOAT_TOPUP", "ADJUSTMENT": "MPESA_ADJUSTMENT", "INVESTMENT": "MPESA_INVESTMENT_TRANSFER", "COMMISSION": "MPESA_COMMISSION_RECEIVED"}.get(transaction_type, "MPESA_REBALANCE")
    audit(action, entry, user, after={"amount": str(value), "cash": str(current_cash + cash_effect), "float": str(current_float + float_effect)})
    return entry, True


@transaction.atomic
def add_provider_reference(*, entry, reference, user):
    """The M-Pesa confirmation code for a transaction recorded before it was done on the line. Set once."""
    lock_business()
    entry = MpesaTransaction.objects.select_for_update().select_related("session").get(pk=entry.pk)
    reference = (reference or "").strip().upper()
    if not reference:
        raise ValidationError("Enter the M-Pesa confirmation code.")
    if entry.provider_reference:
        if entry.provider_reference == reference:
            return entry
        raise ValidationError("This transaction already has a confirmation code.")
    if entry.session.operator_id != user.id and not is_business_manager(user):
        raise ValidationError("You can only update transactions from your own M-Pesa session.")
    if MpesaTransaction.objects.filter(provider_reference=reference).exists():
        raise ValidationError("That M-Pesa confirmation code is already recorded on another transaction.")
    entry.provider_reference = reference
    entry.save(update_fields=["provider_reference"])
    audit("MPESA_REFERENCE_ADDED", entry, user, after={"reference": reference})
    return entry


@transaction.atomic
def reverse_transaction(*, original, user, idempotency_key, reason, allow_investment=False, allow_commission=False):
    lock_business()
    if not reason.strip():
        raise ValidationError("A reversal reason is required.")
    original = MpesaTransaction.objects.select_for_update().select_related("session", "outlet").get(pk=original.pk)
    if hasattr(original, "reversal"):
        return original.reversal, False
    if original.transaction_type == "REVERSAL":
        raise ValidationError("A reversal cannot itself be reversed.")
    if original.transaction_type == "INVESTMENT" and not allow_investment:
        raise ValidationError("Money moved to or from an investment is corrected on the Investments page, so the investment stays right.")
    if original.transaction_type == "COMMISSION" and not allow_commission:
        raise ValidationError("Commission is corrected on the Commission page, so the agency's income stays right.")
    session = MpesaSession.objects.select_for_update().get(pk=original.session_id)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("Reversals must be posted before the session closes.")
    if not (is_business_manager(user)):
        raise ValidationError("Manager or Owner permission is required to reverse an M-Pesa agency transaction.")
    current_cash, current_float = session_balances(session)
    if current_cash - original.cash_delta < 0 or current_float - original.float_delta < 0:
        raise ValidationError("The reversal would create a negative operational balance.")
    reversal = MpesaTransaction.objects.create(
        internal_reference=f"MPR-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}", idempotency_key=idempotency_key,
        outlet=original.outlet, session=session, transaction_type="REVERSAL", amount=original.amount,
        cash_delta=-original.cash_delta, float_delta=-original.float_delta, reversal_of=original,
        performed_by=user, occurred_at=timezone.now(), notes=reason,
    )
    audit("MPESA_TRANSACTION_REVERSED", reversal, user, after={"original": original.internal_reference, "reason": reason})
    return reversal, True


@transaction.atomic
def correct_transaction(*, original, user, key, reason, amount, customer_phone=None, customer_id_number=None, provider_reference=None):
    """Fixes a mistake in a recorded transaction (amount, customer details, transaction ID) in one step: the wrong
    entry is reversed and the right one recorded, linked to it. Nothing is overwritten, so cash, float, the books and
    the monthly report all show what happened and why. Managers and owners, while the shift is open."""
    lock_business()
    if not str(reason or "").strip():
        raise ValidationError("Say what was wrong, so the correction explains itself.")
    existing = MpesaTransaction.objects.filter(idempotency_key=f"{key}-corrected").first()
    if existing:
        return existing
    original = MpesaTransaction.objects.select_for_update().select_related("session").get(pk=original.pk)
    if original.transaction_type in {"REVERSAL", "ADJUSTMENT", "INVESTMENT", "COMMISSION"}:
        raise ValidationError("Only deposits, withdrawals, float top-ups and cash rebalances can be corrected.")
    if hasattr(original, "reversal"):
        raise ValidationError("This transaction was already reversed or corrected.")
    code = (original.provider_reference if provider_reference is None else str(provider_reference or "").strip().upper()) or None
    phone = original.customer_phone if customer_phone is None else customer_phone
    id_number = original.customer_id_number if customer_id_number is None else customer_id_number
    reverse_transaction(original=original, user=user, idempotency_key=f"{key}-reversal", reason=f"Corrected: {reason.strip()}")
    if code and code == original.provider_reference:
        # The transaction ID belongs to the corrected entry now; the reversed one keeps it in its notes and the audit log.
        MpesaTransaction.objects.filter(pk=original.pk).update(provider_reference=None,
                                                                notes=(original.notes + f" [Transaction ID {code} moved to its correction]").strip())
    corrected, _ = post_transaction(session=original.session, transaction_type=original.transaction_type, transaction_amount=amount, user=user,
                                    idempotency_key=f"{key}-corrected", provider_reference=code, customer_name=original.customer_name,
                                    customer_phone=phone, customer_id_number=id_number,
                                    notes=f"Correction of {original.internal_reference}: {reason.strip()}")
    MpesaTransaction.objects.filter(pk=corrected.pk).update(corrects=original)
    corrected.refresh_from_db()
    audit("MPESA_TRANSACTION_CORRECTED", corrected, user, before={"reference": original.internal_reference, "amount": str(original.amount),
          "phone": original.customer_phone, "id_number": original.customer_id_number, "code": original.provider_reference or ""},
          after={"amount": str(corrected.amount), "phone": corrected.customer_phone, "id_number": corrected.customer_id_number,
                 "code": corrected.provider_reference or "", "reason": reason.strip()})
    return corrected


@transaction.atomic
def reconcile_session(*, session, user, actual_cash, actual_float, reason="", notes="", cash_count=None):
    session = MpesaSession.objects.select_for_update().get(pk=session.pk)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("This M-Pesa session is already closed.")
    if session.operator_id != user.id and not (is_business_manager(user)):
        raise ValidationError("You can only reconcile your assigned M-Pesa session.")
    expected_cash, expected_float = session_balances(session)
    actual_cash, count = counted_cash(actual_cash, cash_count)
    actual_float = Decimal(str(actual_float))
    if actual_cash < 0 or actual_float < 0:
        raise ValidationError("Actual cash and float cannot be negative.")
    cash_variance, float_variance = actual_cash - expected_cash, actual_float - expected_float
    if (cash_variance or float_variance) and not reason.strip():
        raise ValidationError("A reason is required when reconciliation has a variance.")
    reconciliation = MpesaReconciliation.objects.create(
        session=session, expected_cash=expected_cash, actual_cash=actual_cash, cash_variance=cash_variance,
        expected_float=expected_float, actual_float=actual_float, float_variance=float_variance,
        reason=reason, operator=user, reviewed_by=user if is_business_manager(user) else None, notes=notes, cash_count=count,
    )
    session.status = MpesaSession.CLOSED
    session.closing_cash_actual = actual_cash
    session.closing_float_actual = actual_float
    session.closed_at = timezone.now()
    session.closed_by = user
    session.save(update_fields=["status", "closing_cash_actual", "closing_float_actual", "closed_at", "closed_by", "updated_at"])
    audit("MPESA_RECONCILIATION", reconciliation, user, after={"cash_variance": str(cash_variance), "float_variance": str(float_variance)})
    return reconciliation


def record_commission(*, outlet, user, period, commission_amount, reference, settlement_method, recognized_at=None, notes="", key=None, session_id=None):
    """Safaricom's commission for a month; see commission.py for how it is counted."""
    from .commission import record
    return record(outlet=outlet, user=user, period=period, amount=commission_amount, reference=reference, settlement=settlement_method,
                  key=key, paid_on=recognized_at, notes=notes, session_id=session_id)
