"""What a stock receipt says is owed to its supplier, and the corrections that settle it the right way.

A receipt saved as "owe the supplier" is corrected without returning or re-entering the stock:

- Paid later (or paid at the time but not recorded): a supplier payment on the day it was paid, from the shop's
  cash, M-Pesa, bank, an investment, or the owner's own money (owner money put in and paid straight on).
- Stock the business already owned before it started recording: the receipt becomes opening stock. The debt
  moves to opening equity, the stock and its cost layers stay exactly as they are.

Each one can be undone, and every step keeps its journal and audit record.
"""
from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from apps.tenancy.transactions import lock_business
from .models import CashEntry, PurchasePayment, SupplierPurchase

ZERO = Decimal("0")
SOURCES = {"CASH": "Shop cash drawer", "MPESA": "M-Pesa (Lipa na M-Pesa till)", "BANK": "Bank",
           "OWNER": "Owner's own money", "INVESTMENT": "Investment (MMF)"}


def _opening(receipt):
    from apps.inventory.models import StockReceipt
    return receipt.document_status == StockReceipt.OPENING_BALANCE


def _supplier(purchase):
    return purchase.supplier.name if purchase.supplier_id else purchase.receipt.supplier_name or "the supplier"


def _source(entry):
    """Where a supplier payment's money came from, from the entries recorded beside it."""
    key = entry.source_key.partition(":")[2] or entry.source_key  # older payments were saved without a "kind:" prefix
    if CashEntry.objects.filter(source_key=f"owner-pays:{key}").exists():
        return "OWNER"
    from .models import InvestmentMovement
    if InvestmentMovement.objects.filter(idempotency_key=f"{key}:investment").exists():
        return "INVESTMENT"
    return entry.account.payment_method


def receipt_balance(receipt):
    """The supplier side of a receipt: bought, returned, paid, still owed, and each payment. None for opening stock
    entered as opening stock from the start (it never had a supplier debt)."""
    from apps.inventory.models import PurchaseReturn
    purchase = SupplierPurchase.objects.filter(receipt=receipt).select_related("supplier", "receipt").first()
    if not purchase:
        return None
    from .services import purchase_outstanding
    undone = set(CashEntry.objects.filter(reversal_of__purchasepayment__purchase=purchase).values_list("reversal_of_id", flat=True))
    payments = [{"id": p.entry_id, "amount": -p.entry.amount, "paid_on": timezone.localtime(p.entry.occurred_at).date(),
                 "source": _source(p.entry), "source_label": SOURCES.get(_source(p.entry), p.entry.account.payment_method.title()),
                 "undone": p.entry_id in undone}
                for p in PurchasePayment.objects.filter(purchase=purchase).select_related("entry__account").order_by("entry__occurred_at", "pk")]
    returned = PurchaseReturn.objects.filter(receipt=receipt).aggregate(v=Sum("total_cost"))["v"] or ZERO
    opening = _opening(receipt)
    return {"purchase_id": purchase.pk, "supplier": _supplier(purchase), "amount": purchase.amount, "returned": returned,
            "paid": sum((p["amount"] for p in payments if not p["undone"]), ZERO), "owed": purchase_outstanding(purchase),
            "already_owned": opening, "payments": payments,
            "can_mark_already_owned": not opening and not returned and not receipt.landed_cost_total
                                      and not any(not p["undone"] for p in payments)}


def _paid_on(receipt, day):
    today = timezone.localdate()
    day = day or today
    if day > today:
        raise ValidationError({"paid_on": "The payment date cannot be in the future."})
    if day < timezone.localtime(receipt.received_at).date():
        raise ValidationError({"paid_on": "The supplier cannot have been paid before the stock was received."})
    from .investments import _moment
    return _moment(day)


@transaction.atomic
def pay_supplier(*, receipt, amount, source, user, key, paid_on=None, investment_id=None, via=None, reference=""):
    """Records money paid to the supplier of a receipt, on the day it was really paid."""
    from .services import pay_purchase, post
    lock_business()
    purchase = SupplierPurchase.objects.select_for_update().filter(receipt=receipt).first()
    if not purchase or _opening(receipt):
        raise ValidationError("This receipt is stock you already owned; there is no supplier to pay.")
    source = str(source or "").upper()
    if source not in SOURCES:
        raise ValidationError({"source": "Choose where the money came from."})
    occurred_at = _paid_on(receipt, paid_on)
    replay = CashEntry.objects.filter(source_key=f"purchase:{key}").first()
    if replay:
        return replay
    reference = (reference or receipt.receipt_number)[:160]
    if source == "INVESTMENT":
        from .investments import pay_supplier as from_investment
        return from_investment(investment_id=investment_id, purchase=purchase, amount=amount, via=via, key=key, user=user, reference=reference)
    if source == "OWNER":
        # The owner paid out of their own pocket: owner money put into the business and paid straight on to the
        # supplier. Recorded as "other money", so the shop drawer and till are unchanged.
        from .services import purchase_outstanding
        if Decimal(str(amount)) > purchase_outstanding(purchase):
            raise ValidationError("Payment exceeds what is still owed to the supplier for this receipt.")
        post(unit=purchase.business_unit, method="OTHER", amount=Decimal(str(amount)).quantize(Decimal("0.01")), kind="OPENING",
             reference=f"Owner's own money to pay {_supplier(purchase)} for {receipt.receipt_number}"[:160], key=f"owner-pays:{key}",
             user=user, occurred_at=occurred_at, branch=receipt.branch)
        return pay_purchase(purchase=purchase, amount=amount, method="OTHER", key=key, user=user, reference=reference, occurred_at=occurred_at)
    return pay_purchase(purchase=purchase, amount=amount, method=source, key=key, user=user, reference=reference, occurred_at=occurred_at)


@transaction.atomic
def undo_payment(*, receipt, entry_id, reason, user):
    """A supplier payment recorded by mistake: the money goes back where it came from and the supplier is owed again."""
    from .investments import undo as undo_investment
    from .models import InvestmentMovement
    from .services import reverse
    lock_business()
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why this payment is being undone."})
    payment = PurchasePayment.objects.filter(purchase__receipt=receipt, entry_id=entry_id).select_related("entry").first()
    if not payment:
        raise ValidationError("Choose a payment recorded on this receipt.")
    if CashEntry.objects.filter(reversal_of=payment.entry).exists():
        return payment.entry
    key = payment.entry.source_key.split(":", 1)[1]
    reverse(entry=payment.entry, user=user, reason=reason)
    owner = CashEntry.objects.filter(source_key=f"owner-pays:{key}").first()
    if owner:
        reverse(entry=owner, user=user, reason=reason)
    movement = InvestmentMovement.objects.filter(idempotency_key=f"{key}:investment").first()
    if movement:
        undo_investment(movement=movement, user=user, reason=reason)
    return payment.entry


@transaction.atomic
def mark_already_owned(*, receipt, reason, user):
    """Stock entered through Receive stock that the business already owned: it becomes opening stock.

    Nothing was bought, so nothing is owed: the supplier balance moves to opening equity on the receipt's date.
    The stock, its shelves and its buying prices stay as they are.
    """
    from apps.inventory.models import StockReceipt
    from .ledger import paired, post_journal
    lock_business()
    receipt = StockReceipt.objects.select_for_update().get(pk=receipt.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why this stock was already yours (for example: bought before I started using the app)."})
    state = receipt_balance(receipt)
    if not state or state["already_owned"]:
        raise ValidationError("This receipt is already opening stock.")
    if not state["can_mark_already_owned"]:
        raise ValidationError("This receipt has a payment, a return or delivery costs, so it was a real purchase. "
                              "Undo the payment first if it was recorded by mistake.")
    if state["amount"]:
        post_journal(key=f"already-owned:{receipt.pk}:{uuid4().hex[:12]}", description=f"Stock already owned, entered as received: {receipt.receipt_number}",
                     branch=receipt.branch_id, date=timezone.localtime(receipt.received_at).date(), user=user,
                     lines=paired("2000", "3000", state["amount"]))
    AuditLog.objects.create(action="RECEIPT_MARKED_ALREADY_OWNED", object_type="StockReceipt", object_id=str(receipt.pk), user=user,
                            before={"document_status": receipt.document_status, "owed": str(state["owed"])},
                            after={"document_status": StockReceipt.OPENING_BALANCE, "reason": reason})
    StockReceipt.objects.filter(pk=receipt.pk).update(document_status=StockReceipt.OPENING_BALANCE, updated_at=timezone.now())
    receipt.refresh_from_db()
    return receipt


@transaction.atomic
def undo_already_owned(*, receipt, reason, user):
    """It was a real purchase after all: the receipt owes its supplier again."""
    from apps.inventory.models import StockReceipt
    from .ledger import paired, post_journal
    lock_business()
    receipt = StockReceipt.objects.select_for_update().get(pk=receipt.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why this was a purchase after all."})
    purchase = SupplierPurchase.objects.filter(receipt=receipt).first()
    marked = AuditLog.objects.filter(action="RECEIPT_MARKED_ALREADY_OWNED", object_type="StockReceipt", object_id=str(receipt.pk)).order_by("-pk").first()
    if not purchase or not _opening(receipt) or not marked:
        raise ValidationError("Only a receipt marked as stock you already owned can be turned back into a purchase.")
    # Price corrections made meanwhile kept the purchase amount up to date, so it is what is owed again.
    if purchase.amount:
        post_journal(key=f"already-owned-undo:{receipt.pk}:{uuid4().hex[:12]}", description=f"Purchase after all: {receipt.receipt_number}. {reason}"[:240],
                     branch=receipt.branch_id, date=timezone.localtime(receipt.received_at).date(), user=user,
                     lines=paired("3000", "2000", purchase.amount))
    status = (marked.before or {}).get("document_status") or StockReceipt.SUPPLIER_DOCUMENT
    AuditLog.objects.create(action="RECEIPT_ALREADY_OWNED_UNDONE", object_type="StockReceipt", object_id=str(receipt.pk), user=user,
                            before={"document_status": receipt.document_status}, after={"document_status": status, "reason": reason})
    StockReceipt.objects.filter(pk=receipt.pk).update(document_status=status, updated_at=timezone.now())
    receipt.refresh_from_db()
    return receipt


def real_purchases(queryset=None):
    """Supplier purchases that were really bought: receipts later marked as stock already owned are left out."""
    from apps.inventory.models import StockReceipt
    return (queryset if queryset is not None else SupplierPurchase.objects.all()).exclude(receipt__document_status=StockReceipt.OPENING_BALANCE)



BUSINESS_MONEY = {"CASH", "MPESA", "BANK"}


def restocking(start, end):
    """Money paid to suppliers for stock between ``start`` and ``end`` (days), by where it came from: the business's
    own money (cash, M-Pesa, bank: money the profit made), the owner's own pocket, or an investment. Buying stock never
    changes the profit earned (the stock is still there; its cost counts when it is sold), but money from the business
    is profit put back into stock, so it is shown taken off the profit in hand. A payment undone in the dates counts back."""
    totals = {"business": ZERO, "own_money": ZERO, "investment": ZERO}
    payments = PurchasePayment.objects.select_related("entry__account")
    sources = {p.entry_id: _source(p.entry) for p in payments}
    rows = CashEntry.objects.filter(occurred_at__date__range=(start, end), kind="PURCHASE").filter(
        models.Q(pk__in=sources.keys()) | models.Q(reversal_of_id__in=sources.keys()))
    for entry in rows.only("pk", "amount", "reversal_of_id"):
        source = sources.get(entry.reversal_of_id or entry.pk)
        part = "business" if source in BUSINESS_MONEY else "own_money" if source in {"OWNER", "OTHER"} else "investment"
        totals[part] -= entry.amount
    return totals
