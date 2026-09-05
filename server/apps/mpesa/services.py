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


def session_balances(session):
    totals = session.transactions.aggregate(cash=Sum("cash_delta"), float=Sum("float_delta"))
    return (
        session.opening_cash + (totals["cash"] or Decimal("0")),
        session.opening_float + (totals["float"] or Decimal("0")),
    )


@transaction.atomic
def open_session(*, outlet, operator, opening_cash, opening_float, notes=""):
    if MpesaSession.objects.select_for_update().filter(outlet=outlet, status=MpesaSession.OPEN).exists():
        raise ValidationError("This outlet already has an open M-Pesa session.")
    cash, electronic_float = Decimal(str(opening_cash)), Decimal(str(opening_float))
    if cash < 0 or electronic_float < 0:
        raise ValidationError("Opening balances cannot be negative.")
    session = MpesaSession.objects.create(outlet=outlet, operator=operator, opening_cash=cash, opening_float=electronic_float, opened_at=timezone.now(), notes=notes)
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
    if transaction_type == "ADJUSTMENT" and privileged:
        return Decimal(str(cash_delta)), Decimal(str(float_delta))
    raise ValidationError("Unsupported transaction type or insufficient permission.")


@transaction.atomic
def post_transaction(*, session, transaction_type, transaction_amount, user, idempotency_key, provider_reference=None, customer_reference="", notes="", cash_delta=None, float_delta=None):
    if not idempotency_key:
        raise ValidationError("An idempotency key is required.")
    existing = MpesaTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing, False
    session = MpesaSession.objects.select_for_update().select_related("outlet").get(pk=session.pk)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("This M-Pesa session is closed.")
    privileged = user.is_superuser or user.groups.filter(name="Manager").exists()
    if session.operator_id != user.id and not privileged:
        raise ValidationError("You can only post to your assigned M-Pesa session.")
    value = amount(transaction_amount)
    if transaction_type in ["FLOAT_TOPUP", "CASH_REBALANCE", "ADJUSTMENT"] and not privileged:
        raise ValidationError("Manager or Owner permission is required for balance adjustments.")
    if transaction_type == "ADJUSTMENT" and (not notes.strip() or not provider_reference):
        raise ValidationError("Adjustments require both a reason and reference.")
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
    action = {"CUSTOMER_DEPOSIT": "MPESA_DEPOSIT_POSTED", "CUSTOMER_WITHDRAWAL": "MPESA_WITHDRAWAL_POSTED", "FLOAT_TOPUP": "MPESA_FLOAT_TOPUP", "ADJUSTMENT": "MPESA_ADJUSTMENT"}.get(transaction_type, "MPESA_REBALANCE")
    audit(action, entry, user, after={"amount": str(value), "cash": str(current_cash + cash_effect), "float": str(current_float + float_effect)})
    return entry, True


@transaction.atomic
def reverse_transaction(*, original, user, idempotency_key, reason):
    if not reason.strip():
        raise ValidationError("A reversal reason is required.")
    original = MpesaTransaction.objects.select_for_update().select_related("session", "outlet").get(pk=original.pk)
    if hasattr(original, "reversal"):
        return original.reversal, False
    if original.transaction_type == "REVERSAL":
        raise ValidationError("A reversal cannot itself be reversed.")
    session = MpesaSession.objects.select_for_update().get(pk=original.session_id)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("Reversals must be posted before the session closes.")
    if not (user.is_superuser or user.groups.filter(name="Manager").exists()):
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
def reconcile_session(*, session, user, actual_cash, actual_float, reason="", notes=""):
    session = MpesaSession.objects.select_for_update().get(pk=session.pk)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("This M-Pesa session is already closed.")
    if session.operator_id != user.id and not (user.is_superuser or user.groups.filter(name="Manager").exists()):
        raise ValidationError("You can only reconcile your assigned M-Pesa session.")
    expected_cash, expected_float = session_balances(session)
    actual_cash, actual_float = Decimal(str(actual_cash)), Decimal(str(actual_float))
    if actual_cash < 0 or actual_float < 0:
        raise ValidationError("Actual cash and float cannot be negative.")
    cash_variance, float_variance = actual_cash - expected_cash, actual_float - expected_float
    if (cash_variance or float_variance) and not reason.strip():
        raise ValidationError("A reason is required when reconciliation has a variance.")
    reconciliation = MpesaReconciliation.objects.create(
        session=session, expected_cash=expected_cash, actual_cash=actual_cash, cash_variance=cash_variance,
        expected_float=expected_float, actual_float=actual_float, float_variance=float_variance,
        reason=reason, operator=user, reviewed_by=user if user.is_superuser else None, notes=notes,
    )
    session.status = MpesaSession.CLOSED
    session.closing_cash_actual = actual_cash
    session.closing_float_actual = actual_float
    session.closed_at = timezone.now()
    session.closed_by = user
    session.save(update_fields=["status", "closing_cash_actual", "closing_float_actual", "closed_at", "closed_by", "updated_at"])
    audit("MPESA_RECONCILIATION", reconciliation, user, after={"cash_variance": str(cash_variance), "float_variance": str(float_variance)})
    return reconciliation


@transaction.atomic
def record_commission(*, outlet, user, period, commission_amount, reference, settlement_method, recognized_at=None, notes=""):
    entry = MpesaCommissionEntry.objects.create(outlet=outlet, period=period, amount=amount(commission_amount), reference=reference, settlement_method=settlement_method, recognized_at=recognized_at or timezone.now(), recorded_by=user, notes=notes)
    audit("MPESA_COMMISSION_RECORDED", entry, user, after={"amount": str(entry.amount), "reference": reference})
    return entry
