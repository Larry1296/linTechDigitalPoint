"""The till's checkout: charge the basket, take the payments, then the sale is made (see checkout.py)."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission, is_business_manager

from . import checkout as service
from . import mpesa_express
from .models import Checkout, CheckoutPayment, IncomingMpesaPayment, StkPush


# Who takes payments at each kind of checkout: the till's cashiers, or the Cyber desk's.
TAKES_PAYMENT = {Checkout.POS: "commerce.add_sale", Checkout.CYBER: "cyber.complete_cyber_job"}


def _till_staff(request, kind=Checkout.POS):
    if not has_business_permission(request.user, TAKES_PAYMENT[kind]):
        raise PermissionDenied("You do not have permission to take payments.")


def _kind(request):
    return Checkout.CYBER if request.query_params.get("kind", "").upper() == Checkout.CYBER else Checkout.POS


def _checkouts(request):
    """Checkouts at the branch the person is working in."""
    rows = Checkout.objects.select_related("cashier", "sale")
    return rows.filter(branch=request.store) if request.store else rows


def _get(request, pk):
    checkout = get_object_or_404(_checkouts(request), pk=pk)
    _till_staff(request, checkout.kind)
    if not service.can_handle(request.user, checkout):
        raise PermissionDenied("This checkout belongs to another cashier.")
    return checkout


@api_view(["GET", "POST"])
@permission_classes([HasLinTechPermission])
def checkouts(request):
    """GET: this cashier's checkouts still open (all of the branch's, for a manager), so a reloaded till picks up where it
    was (``?kind=cyber``: the Cyber desk's). POST: charge a basket."""
    kind = _kind(request) if request.method == "GET" else Checkout.POS
    _till_staff(request, kind)
    if request.method == "GET":
        service.expire_stale()
        rows = _checkouts(request).filter(kind=kind, status__in=Checkout.OPEN).order_by("-created_at")
        if not is_business_manager(request.user):
            rows = rows.filter(cashier=request.user)
        return Response({"checkouts": [service.checkout_data(row) for row in rows[:20]]})
    try:
        checkout = service.start(user=request.user, organization=request.organization, store=request.store, data=request.data,
                                 key=str(request.data.get("idempotency_key") or ""))
    except ValidationError as problem:
        detail = problem.detail if isinstance(problem.detail, dict) else {}
        if "below_cost" in detail and not has_business_permission(request.user, "accounting.view_profit"):
            names = ", ".join(sorted({str(row).split(": sold for")[0] for row in detail["below_cost"]}))
            return Response({"code": "below_cost_hidden", "detail": f"{names}: this price is below what the item cost to buy. Agree a higher price."}, status=400)
        raise
    return Response(service.checkout_data(checkout, user=request.user, with_candidates=True), status=201)


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def checkout_detail(request, pk):
    """Where the checkout stands, with the till payments that just arrived. A prompt whose answer is late is asked about."""
    checkout = _get(request, pk)
    for push in StkPush.objects.filter(checkout_payment__checkout=checkout, status=StkPush.PENDING):
        mpesa_express.check(push)
    checkout.refresh_from_db()
    return Response(service.checkout_data(checkout, user=request.user, with_candidates=True))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def checkout_pay(request, pk):
    checkout = _get(request, pk)
    data = request.data
    service.add_payment(checkout, user=request.user, method=str(data.get("method") or ""), amount=data.get("amount"),
                        cash_given=data.get("cash_given"), reference=str(data.get("reference") or ""), phone=str(data.get("phone") or ""),
                        incoming_id=data.get("incoming_id"), code=str(data.get("code") or ""), due_date=data.get("due_date") or None,
                        customer_id=data.get("customer_id") or None, stay_id=data.get("stay_id") or None)
    checkout.refresh_from_db()
    return Response(service.checkout_data(checkout, user=request.user, with_candidates=True), status=201)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def checkout_void_payment(request, pk, payment_pk):
    checkout = _get(request, pk)
    service.void_payment(checkout, get_object_or_404(CheckoutPayment, pk=payment_pk, checkout=checkout), user=request.user)
    checkout.refresh_from_db()
    return Response(service.checkout_data(checkout, user=request.user, with_candidates=True))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def checkout_cancel(request, pk):
    checkout = service.cancel(_get(request, pk), user=request.user, reason=request.data.get("reason"))
    return Response(service.checkout_data(checkout, user=request.user))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def checkout_retry(request, pk):
    checkout = service.retry(_get(request, pk), user=request.user)
    return Response(service.checkout_data(checkout, user=request.user))


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def till_payments(request):
    """The M-Pesa payments Safaricom reported to the business's own till: those not used for a sale (to match or settle),
    or all of them. For the owner and managers."""
    if not is_business_manager(request.user):
        raise PermissionDenied("Only the owner and managers see all the till's payments.")
    rows = IncomingMpesaPayment.objects.all()
    if request.query_params.get("show") != "all":
        rows = rows.filter(status=IncomingMpesaPayment.UNMATCHED) | rows.filter(status=IncomingMpesaPayment.USED, note__startswith="Paid ")
    return Response({"payments": [service.incoming_data(row) for row in rows.order_by("-paid_at")[:200]]})


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
@transaction.atomic
def till_payment_settle(request, pk):
    """The owner or a manager records what became of a payment no sale used: refunded, or not a sale at all."""
    if not is_business_manager(request.user):
        raise PermissionDenied("Only the owner and managers settle the till's payments.")
    row = get_object_or_404(IncomingMpesaPayment.objects.select_for_update(), pk=pk)
    note = " ".join(str(request.data.get("note") or "").split())
    if not note:
        raise ValidationError("Say what happened to this payment, for example refunded to the customer.")
    if row.status == IncomingMpesaPayment.USED and row.used_amount >= row.amount:
        raise ValidationError("This payment was used for a sale; there is nothing left to settle.")
    row.status, row.note, row.settled_by = IncomingMpesaPayment.SETTLED, note[:255], request.user
    row.save(update_fields=["status", "note", "settled_by", "updated_at"])
    return Response(service.incoming_data(row))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def till_register(request):
    """The owner asks Safaricom again to send the till's payment notices (after fixing what stopped it)."""
    from .mpesa_express_api import _owner
    if not _owner(request):
        raise PermissionDenied("Only the business owner can connect the till.")
    setup = mpesa_express.register_till(mpesa_express.setup_for(request.organization))
    return Response(mpesa_express.view(setup))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def till_simulate(request):
    """Development only: a customer paying the till, to try the checkout without Safaricom."""
    if not any(has_business_permission(request.user, p) for p in TAKES_PAYMENT.values()):
        raise PermissionDenied("You do not have permission to take payments.")
    row = mpesa_express.simulate_till_payment(mpesa_express.setup_for(request.organization), amount=request.data.get("amount"),
                                              name=str(request.data.get("name") or "Test"), account=str(request.data.get("account") or ""))
    return Response(service.incoming_data(row), status=201)
