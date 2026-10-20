"""Checkout at the till: charge the basket, take the payments, and only then make the sale.

1. The cashier charges the basket (``start``). Its lines, agreed prices and exact amount are frozen in a Checkout after a
   rehearsal of the real sale (complete_sale run and rolled back), so stock, prices and the below-cost rule are checked
   now and the amount is exactly what the sale will charge. No stock leaves and nothing reaches the books.
2. The customer pays (``add_payment``), in one way or several: cash (the cashier confirms it and the change is worked
   out), the till (a payment Safaricom reported, see below), an M-Pesa prompt (confirmed by Safaricom's answer to that
   very prompt), bank (the cashier confirms it with its reference), or owed on credit by a named customer.
3. Once the payments cover the amount the sale is made, exactly once, from the frozen basket by the same complete_sale
   as every sale, and each payment is recorded on it; the books follow from those as for any sale (``_complete``).

Till payments (Buy Goods). Safaricom tells the business each time a customer pays its till (``till_notice``), with the
M-Pesa code, amount, time and the customer's masked number and first name, but with nothing that names the basket: two
customers paying KSh 850 at the same moment look alike. So a till payment is never matched by its amount. Every payment
Safaricom reports is kept in one ledger (IncomingMpesaPayment), and the cashier attaches the customer's own payment to
the checkout: by tapping it among the payments that just arrived, or by entering the code from the customer's SMS, which
must be one Safaricom reported. A payment can be attached once; one nobody claims stays in the ledger for the owner. A
paybill payment whose account number is the checkout's number names the checkout, so it is attached by itself.

A business that has not connected its till to Safaricom can still take the code from the customer's SMS; it is then
recorded as typed in, the way M-Pesa was always recorded, and shown as not checked with Safaricom.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.catalog.models import ProductVariant
from apps.tenancy.context import branch_context
from apps.tenancy.permissions import has_business_permission, is_business_manager

from .models import Checkout, CheckoutPayment as Tender, IncomingMpesaPayment as Incoming, Payment

CENT = Decimal("0.01")
EXPIRE_AFTER = timedelta(minutes=30)  # an unpaid basket left alone stops holding the till
SALE_METHOD = {Tender.CASH: "CASH", Tender.TILL: "MPESA", Tender.PROMPT: "MPESA", Tender.BANK: "BANK"}


class _Rehearsal(Exception):
    """Rolls back the rehearsed sale."""


def money(value, label="amount"):
    try:
        value = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"Enter the {label} as a number.")
    if not value.is_finite():
        raise ValidationError(f"Enter the {label} as a number.")
    return value


def _quantity(value):
    try:
        number = Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal("0")
    return number if number.is_finite() else Decimal("0")


def read_basket(user, organization, data):
    """The basket as the till sent it, with the price rules a till follows. Returns (basket, lines, customer, below_floor).

    Bargaining: anyone may agree any price up to the asking price. The only floor is what the item cost to buy (checked
    by complete_sale from the stock layers actually sold), never the product's lowest price: going below that is allowed
    but logged for the owner. A price above the asking price, a line discount or a whole-sale discount needs a manager."""
    decimal = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    lines, saved = [], []
    for raw in data.get("items", []):
        variant = ProductVariant.objects.select_related("product").filter(pk=raw.get("variant_id"), active=True, product__active=True).first()
        if not variant:
            raise ValidationError("Invalid product variant.")
        line = {"variant": variant, "quantity": raw.get("quantity"), "discount_reason": str(raw.get("discount_reason") or "")[:160]}
        if raw.get("unit_price") not in (None, ""):
            line["unit_price"] = decimal.run_validation(raw.get("unit_price"))
        if raw.get("discount") not in (None, "", 0, "0"):
            line["discount"] = decimal.run_validation(raw.get("discount"))
        lines.append(line)
    discount = decimal.run_validation(data.get("discount") or 0)
    manager = has_business_permission(user, "commerce.change_sale")
    below_floor = []
    for line in lines:
        variant, quantity = line["variant"], _quantity(line["quantity"])
        price = line.get("unit_price", variant.selling_price)
        effective = price - (line.get("discount") or 0) / quantity if quantity > 0 else price
        if variant.minimum_price and effective < variant.minimum_price:
            below_floor.append(variant.pk)
        if line.get("discount") or price > variant.selling_price:
            line["needs_manager"] = True
    if not manager and (discount or any(line.get("needs_manager") for line in lines)):
        raise PermissionDenied("A price above the asking price, or a discount, needs a manager's approval.")
    customer = None
    if data.get("customer_id"):
        customer = get_user_model().objects.filter(customer_profiles__organization_id=organization.pk, pk=data.get("customer_id")).first()
        if not customer:
            raise ValidationError("Choose a customer in this business.")
    for line in lines:
        # The price is frozen with the basket, so a catalogue change while the customer pays changes nothing.
        saved.append({"variant_id": line["variant"].pk, "quantity": str(_quantity(line["quantity"])),
                      "unit_price": str(line.get("unit_price", line["variant"].selling_price)),
                      "discount": str(line.get("discount") or 0), "discount_reason": line["discount_reason"]})
    basket = {"lines": saved, "discount": str(discount), "discount_reason": str(data.get("discount_reason") or "")[:160],
              "allow_below_cost": bool(data.get("allow_below_cost")), "below_floor": below_floor}
    return basket, lines, customer, below_floor


def _sale_lines(basket):
    variants = {v.pk: v for v in ProductVariant.objects.select_related("product").filter(pk__in=[line["variant_id"] for line in basket["lines"]])}
    return [{"variant": variants[line["variant_id"]], "quantity": Decimal(line["quantity"]), "unit_price": Decimal(line["unit_price"]),
             **({"discount": Decimal(line["discount"])} if Decimal(line["discount"]) else {}), "discount_reason": line["discount_reason"]}
            for line in basket["lines"]]


def _sale(basket, *, number, user, customer, key, due_date=None):
    from apps.inventory.services import complete_sale
    return complete_sale(lines=_sale_lines(basket), channel="POS", number=number, user=user, customer=customer,
                         discount=Decimal(basket["discount"]), discount_reason=basket["discount_reason"],
                         allow_below_cost=basket["allow_below_cost"], payment_method="CASH", paid_amount=0, idempotency_key=key,
                         due_date=due_date)


@transaction.atomic
def start(*, user, organization, store, data, key):
    """Charges the basket: checks it as the real sale would, freezes it and its amount, and waits for payment."""
    if not has_business_permission(user, "commerce.add_sale"):
        raise PermissionDenied("You do not have permission to complete sales.")
    if not key:
        raise ValidationError("A checkout needs its request key.")
    existing = Checkout.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    basket, lines, customer, _ = read_basket(user, organization, data)
    if not lines:
        raise ValidationError("Add at least one item to the sale.")
    rehearsal = uuid4().hex
    try:
        with transaction.atomic():
            total = _sale(basket, number=f"REHEARSAL-{rehearsal[:12]}", user=user, customer=customer, key=f"rehearsal:{rehearsal}").total
            raise _Rehearsal()
    except _Rehearsal:
        pass
    return Checkout.objects.create(number=f"POS-{uuid4().hex[:10].upper()}", branch=store, cashier=user, customer=customer, basket=basket,
                                   total=total, idempotency_key=key)


def can_handle(user, checkout):
    """Each cashier's checkouts are their own; a manager may take over one, for example when a cashier steps away."""
    return checkout.cashier_id == user.pk or is_business_manager(user)


def _locked(checkout, user=None):
    checkout = Checkout.objects.select_for_update().get(pk=checkout.pk)
    if user is not None and not can_handle(user, checkout):
        raise PermissionDenied("This checkout belongs to another cashier.")
    return checkout


def totals(checkout):
    tenders = checkout.payments.all()
    confirmed = sum((t.amount for t in tenders if t.status == Tender.CONFIRMED), Decimal("0"))
    waiting = sum((t.amount for t in tenders if t.status == Tender.PENDING), Decimal("0"))
    return {"paid": confirmed, "waiting": waiting, "left": max(checkout.total - confirmed, Decimal("0")),
            "open": max(checkout.total - confirmed - waiting, Decimal("0"))}


def expire_stale():
    """Unpaid baskets left alone stop holding the till. One with money already on it is never expired."""
    stale = Checkout.objects.filter(status=Checkout.AWAITING, created_at__lt=timezone.now() - EXPIRE_AFTER).exclude(payments__status__in=[Tender.CONFIRMED, Tender.PENDING])
    return stale.update(status=Checkout.EXPIRED, updated_at=timezone.now())


def record_incoming(*, transaction_id, source, amount, paid_at, shortcode="", account_reference="", payer_phone="", payer_name=""):
    """Keeps a payment Safaricom reported, once: the till notice and a prompt's answer may both report the same one."""
    code = "".join(str(transaction_id or "").split()).upper()
    if not code:
        raise ValidationError("A payment without its M-Pesa code cannot be recorded.")
    incoming, created = Incoming.objects.get_or_create(transaction_id=code, defaults={
        "source": source, "amount": money(amount), "paid_at": paid_at, "shortcode": str(shortcode)[:12],
        "account_reference": str(account_reference or "").strip()[:40], "payer_phone": str(payer_phone or "")[:20],
        "payer_name": " ".join(str(payer_name or "").split())[:120]})
    return incoming, created


def _attach(checkout, incoming, *, user=None, method=Tender.TILL, tender=None):
    """Uses a payment Safaricom reported for this checkout. Caller holds the checkout lock."""
    incoming = Incoming.objects.select_for_update().get(pk=incoming.pk)
    if incoming.status != Incoming.UNMATCHED or Tender.objects.filter(incoming=incoming).exists():
        raise ValidationError(f"The M-Pesa payment {incoming.transaction_id} is already used for another sale.")
    # A prompt's payment counts up to what is still owed (a prompt is in whole shillings, so it can be cents more); a till
    # payment up to what no prompt is waiting for.
    left = totals(checkout)["left" if tender else "open"]
    if left <= 0:
        raise ValidationError("This sale is already paid.")
    applied = min(incoming.amount, left)
    extra = incoming.amount - applied
    incoming.status, incoming.used_amount = Incoming.USED, applied
    incoming.note = (f"Paid {extra:,.2f} more than sale {checkout.number} needed: give it back to the customer." if extra else f"Sale {checkout.number}")[:255]
    incoming.save(update_fields=["status", "used_amount", "note", "updated_at"])
    if tender is None:
        tender = Tender(checkout=checkout, method=method, recorded_by=user)
    tender.amount, tender.incoming, tender.reference, tender.status = applied, incoming, incoming.transaction_id, Tender.CONFIRMED
    tender.detail = (f"Paid {extra:,.2f} more: give it back to the customer." if extra else "")
    tender.save()
    return tender


@transaction.atomic
def add_payment(checkout, *, user, method, amount=None, cash_given=None, reference="", phone="", incoming_id=None, code="", due_date=None):
    """One way the customer pays. Returns the payment; the sale is made as soon as the payments cover the amount."""
    from . import mpesa_express
    checkout = _locked(checkout, user)
    if checkout.status not in (Checkout.AWAITING, Checkout.PART_PAID):
        raise ValidationError("This checkout is not waiting for payment.")
    open_amount = totals(checkout)["open"]
    if open_amount <= 0:
        raise ValidationError("Nothing is left to pay. Wait for the prompt that is still out, or cancel it.")
    wanted = open_amount if amount in (None, "") else money(amount)
    if method != Tender.TILL and not (0 < wanted <= open_amount):
        raise ValidationError(f"Enter an amount up to the {open_amount:,.2f} still to pay.")
    if method == Tender.CASH:
        given = money(cash_given if cash_given not in (None, "") else wanted, "cash given")
        if given <= 0:
            raise ValidationError("Enter the cash the customer gave.")
        tender = Tender.objects.create(checkout=checkout, method=method, amount=min(given, wanted), cash_given=given, status=Tender.CONFIRMED, recorded_by=user)
    elif method == Tender.BANK:
        if not str(reference).strip():
            raise ValidationError("Enter the bank transfer's reference.")
        tender = Tender.objects.create(checkout=checkout, method=method, amount=wanted, reference=str(reference).strip()[:100], status=Tender.CONFIRMED, recorded_by=user)
    elif method == Tender.OWED:
        if not checkout.customer_id:
            raise ValidationError("Choose the customer who will owe it before leaving anything to pay later.")
        tender = Tender.objects.create(checkout=checkout, method=method, amount=wanted, status=Tender.CONFIRMED, recorded_by=user,
                                       detail=f"Due {due_date}" if due_date else "")
        if due_date:
            checkout.basket = {**checkout.basket, "due_date": str(due_date)}
            checkout.save(update_fields=["basket", "updated_at"])
    elif method == Tender.PROMPT:
        push = mpesa_express.send(mpesa_express.setup_for(checkout.organization), phone=phone, amount=wanted, user=user,
                                  reference=checkout.number[-12:])
        tender = Tender.objects.create(checkout=checkout, method=method, amount=mpesa_express.whole_shillings(wanted), prompt=push,
                                       status=Tender.PENDING, recorded_by=user, detail=push.detail[:255])
    elif method == Tender.TILL:
        tender = _till(checkout, user=user, incoming_id=incoming_id, code=code)
    else:
        raise ValidationError("Choose cash, the till, a prompt, bank or owed.")
    _settle(checkout)
    return tender


def _till(checkout, *, user, incoming_id, code):
    from . import mpesa_express
    code = "".join(str(code or "").split()).upper()
    if incoming_id:
        incoming = Incoming.objects.filter(pk=incoming_id).first()
        if not incoming:
            raise ValidationError("That M-Pesa payment is not one Safaricom reported to this business.")
        return _attach(checkout, incoming, user=user)
    if not code:
        raise ValidationError("Choose the customer's payment, or enter the code from their M-Pesa message.")
    incoming = Incoming.objects.filter(transaction_id=code).first()
    if incoming:
        return _attach(checkout, incoming, user=user)
    setup = mpesa_express.setup_for(checkout.organization)
    if setup.till_registered_at:
        raise ValidationError(f"Safaricom has not reported a payment with the code {code} to your till. Check the code with the customer's "
                              "message; if the customer has just paid, wait a few seconds and try again.")
    # Not connected to Safaricom: the code from the SMS is all there is. Kept as typed, and shown as not checked.
    if Payment.objects.filter(provider_transaction_id=code).exists() or Tender.objects.filter(reference=code, status=Tender.CONFIRMED).exists():
        raise ValidationError(f"The M-Pesa code {code} is already recorded on another payment. Check the code in the message.")
    left = totals(checkout)["open"]
    return Tender.objects.create(checkout=checkout, method=Tender.TILL, amount=left, reference=code, status=Tender.CONFIRMED, recorded_by=user,
                                 detail="Code typed in from the customer's message; not checked with Safaricom.")


def _settle(checkout):
    """Moves the checkout on: partly paid, or paid and made into the sale. Caller holds the checkout lock."""
    paid = totals(checkout)["paid"]
    if paid >= checkout.total:
        _complete(checkout)
        return
    status = Checkout.PART_PAID if paid > 0 else Checkout.AWAITING
    if checkout.status != status:
        checkout.status = status
        checkout.save(update_fields=["status", "updated_at"])


def _complete(checkout):
    """Makes the sale from the frozen basket and records each payment on it, once. A sale that cannot be made now (an
    item sold out while the customer paid) leaves the checkout PAID with the reason, its money kept, for a manager."""
    from apps.core.models import AuditLog
    if checkout.sale_id:
        return checkout
    basket = checkout.basket
    try:
        with transaction.atomic(), branch_context(checkout.branch_id):
            if checkout.kind == Checkout.CYBER:
                from apps.cyber.checkout import make_sale
                sale = make_sale(checkout)
            else:
                sale = _sale(basket, number=checkout.number, user=checkout.cashier, customer=checkout.customer, key=f"checkout:{checkout.pk}",
                             due_date=basket.get("due_date") or None)
            if sale.total != checkout.total:
                raise ValidationError(f"The sale came to {sale.total:,.2f}, not the {checkout.total:,.2f} charged.")
            for tender in checkout.payments.filter(status=Tender.CONFIRMED).exclude(method=Tender.OWED).select_related("incoming").order_by("pk"):
                code = tender.incoming.transaction_id if tender.incoming_id else (tender.reference if tender.method == Tender.TILL else None)
                tender.payment = Payment.objects.create(sale=sale, method=SALE_METHOD[tender.method], amount=tender.amount, status="COMPLETED",
                                                        reference=tender.reference, provider_transaction_id=code or None,
                                                        idempotency_key=f"checkout-payment:{tender.pk}")
                tender.save(update_fields=["payment", "updated_at"])
            for variant in basket.get("below_floor", []):
                AuditLog.objects.create(action="SALE_BELOW_MINIMUM_PRICE", object_type="Sale", object_id=str(sale.pk), user=checkout.cashier,
                                        after={"variant": variant, "checkout": checkout.number})
    except ValidationError as problem:
        detail = problem.detail
        message = detail.get("detail") if isinstance(detail, dict) else detail[0] if isinstance(detail, list) else detail
        checkout.status, checkout.problem = Checkout.PAID, f"Paid, but the sale could not be made: {message}"[:255]
        checkout.save(update_fields=["status", "problem", "updated_at"])
        return checkout
    checkout.sale, checkout.status, checkout.problem, checkout.completed_at = sale, Checkout.COMPLETED, "", timezone.now()
    checkout.save(update_fields=["sale", "status", "problem", "completed_at", "updated_at"])
    return checkout


@transaction.atomic
def retry(checkout, *, user):
    """A paid checkout whose sale could not be made (for example stock was received since): try again."""
    checkout = _locked(checkout, user)
    if checkout.status != Checkout.PAID:
        raise ValidationError("Only a paid checkout waiting to become a sale can be tried again.")
    return _complete(checkout)


@transaction.atomic
def cancel(checkout, *, user, reason):
    """The customer leaves without buying. Cash handed back is simply not taken. M-Pesa or bank money already received
    is not lost: a manager cancels, and each M-Pesa payment goes back to the payments not matched to a sale, marked to
    be refunded or used for the customer's next sale."""
    checkout = _locked(checkout, user)
    if checkout.status not in Checkout.OPEN:
        raise ValidationError("This checkout is already finished.")
    received = checkout.payments.filter(status=Tender.CONFIRMED, method__in=[Tender.TILL, Tender.PROMPT, Tender.BANK])
    if received.exists() and not is_business_manager(user):
        raise PermissionDenied("Money has already reached the business for this checkout. Ask a manager to cancel it and refund the customer.")
    for tender in checkout.payments.filter(status__in=[Tender.CONFIRMED, Tender.PENDING]).select_related("incoming"):
        if tender.incoming_id:
            Incoming.objects.filter(pk=tender.incoming_id).update(status=Incoming.UNMATCHED, used_amount=0, updated_at=timezone.now(),
                                                                  note=f"From cancelled checkout {checkout.number}: refund the customer or use it for their sale."[:255])
        tender.status, tender.incoming = Tender.VOID, None
        tender.save(update_fields=["status", "incoming", "updated_at"])
    checkout.status, checkout.cancelled_by, checkout.cancel_reason = Checkout.CANCELLED, user, str(reason or "")[:200]
    checkout.save(update_fields=["status", "cancelled_by", "cancel_reason", "updated_at"])
    return checkout


@transaction.atomic
def void_payment(checkout, tender, *, user):
    """Takes back a payment entered by mistake before the sale is made, e.g. the wrong till payment or a prompt to give up on."""
    checkout = _locked(checkout, user)
    tender = Tender.objects.select_for_update().get(pk=tender.pk, checkout=checkout)
    if checkout.status not in (Checkout.AWAITING, Checkout.PART_PAID) or tender.status not in (Tender.CONFIRMED, Tender.PENDING):
        raise ValidationError("This payment can no longer be taken back.")
    if tender.incoming_id:
        Incoming.objects.filter(pk=tender.incoming_id).update(status=Incoming.UNMATCHED, used_amount=0, note="", updated_at=timezone.now())
    tender.status, tender.incoming = Tender.VOID, None
    tender.save(update_fields=["status", "incoming", "updated_at"])
    _settle(checkout)
    return tender


def prompt_answered(push):
    """Safaricom answered a checkout's prompt (callback or status check). Paid: the payment joins the ledger and the checkout
    by Safaricom's own match of prompt to payment. Paid after the checkout was cancelled: kept in the ledger, unmatched."""
    from .models import StkPush
    tender = Tender.objects.filter(prompt=push).first()
    if tender is None:
        return
    with transaction.atomic():
        checkout = Checkout.objects.select_for_update().get(pk=tender.checkout_id)
        tender = Tender.objects.select_for_update().get(pk=tender.pk)
        if push.status == StkPush.COMPLETED and push.receipt_number:
            incoming, _ = record_incoming(transaction_id=push.receipt_number, source=Incoming.PROMPT, amount=push.amount,
                                          paid_at=push.updated_at or timezone.now(), payer_phone=mask(push.phone))
            if tender.status == Tender.PENDING and checkout.status in (Checkout.AWAITING, Checkout.PART_PAID) and incoming.status == Incoming.UNMATCHED:
                _attach(checkout, incoming, tender=tender)
                _settle(checkout)
            elif incoming.status == Incoming.UNMATCHED:
                Incoming.objects.filter(pk=incoming.pk).update(note=f"Prompt paid after checkout {checkout.number} was closed: refund the customer or use it for their sale."[:255])
        elif push.status in (StkPush.FAILED, StkPush.CANCELLED) and tender.status == Tender.PENDING:
            tender.status, tender.detail = Tender.FAILED, push.detail[:255]
            tender.save(update_fields=["status", "detail", "updated_at"])
            _settle(checkout)


def mask(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return f"{digits[:4]}****{digits[-3:]}" if len(digits) >= 9 else digits


def till_notice(setup, data):
    """Safaricom's notice that a customer paid the business's till or paybill. Kept in the ledger once (Safaricom may send
    it again). A paybill payment whose account number is a waiting checkout's number is attached to it straight away;
    every other payment waits for the cashier to say whose it is."""
    try:
        paid_at = datetime.strptime(str(data.get("TransTime") or ""), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Africa/Nairobi"))
    except ValueError:
        paid_at = timezone.now()
    with transaction.atomic():
        incoming, created = record_incoming(transaction_id=data.get("TransID"), source=Incoming.TILL_NOTICE, amount=data.get("TransAmount"),
                                            paid_at=paid_at, shortcode=data.get("BusinessShortCode") or "", account_reference=data.get("BillRefNumber") or "",
                                            payer_phone=data.get("MSISDN") or "", payer_name=data.get("FirstName") or "")
        reference = incoming.account_reference.upper()
        if created and reference.startswith(("POS-", "CYB-")):
            checkout = Checkout.objects.select_for_update().filter(number=reference, status__in=[Checkout.AWAITING, Checkout.PART_PAID]).first()
            if checkout and totals(checkout)["open"] > 0:
                _attach(checkout, incoming)
                _settle(checkout)
    return incoming


def candidates(checkout):
    """Till payments the cashier may be looking for: not yet used, arrived around this checkout, the exact amount first.
    Shown with Safaricom's code, time, the customer's masked number and first name so the cashier can tell them apart."""
    left = totals(checkout)["left"]
    # A customer often pays while still in the queue, before the basket is charged: look back a little.
    rows = Incoming.objects.filter(status=Incoming.UNMATCHED, paid_at__gte=checkout.created_at - timedelta(minutes=15),
                                   paid_at__lte=timezone.now() + timedelta(minutes=1))
    return sorted(rows[:30], key=lambda row: (row.amount != left, -row.paid_at.timestamp()))


def incoming_data(row):
    return {"id": row.pk, "code": row.transaction_id, "source": row.source, "amount": row.amount, "paid_at": row.paid_at,
            "payer_phone": row.payer_phone, "payer_name": row.payer_name, "account_reference": row.account_reference, "status": row.status,
            "used_amount": row.used_amount, "note": row.note}


def tender_data(tender):
    from . import mpesa_express
    change = tender.cash_given - tender.amount if tender.method == Tender.CASH and tender.cash_given is not None else None
    return {"id": tender.pk, "method": tender.method, "amount": tender.amount, "status": tender.status, "reference": tender.reference,
            "cash_given": tender.cash_given, "change": change, "detail": tender.detail, "checked_with_safaricom": bool(tender.incoming_id),
            "prompt": mpesa_express.push_data(tender.prompt) if tender.prompt_id else None}


def checkout_data(checkout, *, user=None, with_candidates=False):
    numbers = totals(checkout)
    data = {"id": checkout.pk, "kind": checkout.kind, "number": checkout.number, "status": checkout.status, "total": checkout.total, "paid": numbers["paid"],
            "waiting": numbers["waiting"], "left": numbers["left"], "open": numbers["open"], "problem": checkout.problem,
            "customer_id": checkout.customer_id, "cashier_id": checkout.cashier_id, "cashier": checkout.cashier.get_full_name() or checkout.cashier.username,
            "created_at": checkout.created_at, "sale_id": checkout.sale_id, "job_id": checkout.basket.get("job_id"), "items": len(checkout.basket.get("lines", [])),
            "payments": [tender_data(t) for t in checkout.payments.exclude(status=Tender.VOID).select_related("prompt").order_by("pk")]}
    if checkout.sale_id:
        sale = checkout.sale
        data["receipt"] = {"sale_id": sale.pk, "receipt_number": sale.number, "subtotal": sale.subtotal, "discount": sale.discount,
                           "tax": sale.tax_total, "total": sale.total}
        if user is not None and has_business_permission(user, "accounting.view_profit"):
            data["receipt"].update(net_revenue=sale.net_total, cogs=sale.cogs, gross_profit=sale.gross_profit, loss=sale.gross_profit < 0,
                                   cost_pending=sale.cost_pending)
    if with_candidates and checkout.status in (Checkout.AWAITING, Checkout.PART_PAID):
        data["till_payments"] = [incoming_data(row) for row in candidates(checkout)]
    return data
