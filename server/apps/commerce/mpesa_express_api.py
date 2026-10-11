"""M-Pesa prompts (STK push) to a customer's phone: the business's setup, sending a prompt for a sale's waiting M-Pesa
payment, following it, and Safaricom's callback. See mpesa_express.py."""
import hmac

from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import HasLinTechPermission
from apps.tenancy.context import organization_context
from apps.tenancy.models import MpesaExpressSetup
from apps.tenancy.permissions import has_business_permission, is_business_manager, membership_for

from . import mpesa_express
from .models import Payment, StkPush


def _owner(request):
    membership = membership_for(request.user)
    return bool(membership and membership.role == "OWNER") or request.organization.owner_id == request.user.pk


@api_view(["GET", "PUT"])
@permission_classes([HasLinTechPermission])
def setup(request):
    """GET: whether prompts can be sent (anyone at the till), and the details for the owner and managers.
    PUT: the owner saves the till or paybill; Safaricom checks the keys straight away. Only the owner, because it decides
    where the business's money goes."""
    current = mpesa_express.setup_for(request.organization)
    if request.method == "PUT":
        if not _owner(request):
            return Response({"detail": "Only the business owner can change where M-Pesa payments go."}, status=403)
        current = mpesa_express.save(current, request.data, request.user)
    full = _owner(request) or is_business_manager(request.user)
    return Response({**mpesa_express.view(current, full=full), "can_change": _owner(request)})


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def test_prompt(request):
    """The owner's KES 1 prompt to their own phone: proves the passkey and the whole path end to end."""
    if not _owner(request):
        return Response({"detail": "Only the business owner can send a test prompt."}, status=403)
    push = mpesa_express.send(mpesa_express.setup_for(request.organization), phone=request.data.get("phone"), amount=1,
                              user=request.user, reference="Test")
    return Response(mpesa_express.push_data(push), status=201)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def prompt_payment(request, pk):
    """Sends the prompt for a sale's M-Pesa payment that is waiting, to the customer's phone."""
    if not (has_business_permission(request.user, "commerce.add_sale") or has_business_permission(request.user, "commerce.change_payment")):
        return Response({"detail": "You do not have permission to take payments."}, status=403)
    payment = get_object_or_404(Payment, pk=pk, sale__branch=request.store)
    if payment.method != "MPESA" or payment.status not in {"PENDING", "MANUAL_REVIEW"}:
        raise ValidationError("Only an M-Pesa payment that is still waiting can be prompted.")
    push = mpesa_express.send(mpesa_express.setup_for(request.organization), phone=request.data.get("phone"), amount=payment.amount,
                              user=request.user, payment=payment, reference=payment.sale.number[-12:])
    return Response(mpesa_express.push_data(push), status=201)


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def prompt_status(request, pk):
    """Where a prompt stands; asks Safaricom when its callback is late."""
    push = mpesa_express.check(get_object_or_404(StkPush, pk=pk))
    return Response(mpesa_express.push_data(push))


@csrf_exempt
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def callback(request, token):
    """Safaricom posts each prompt's result here. The secret in the address names the business; the checkout id, the prompt."""
    setup = MpesaExpressSetup.objects.filter(callback_token=str(token)).select_related("organization").first()
    if not setup or not hmac.compare_digest(setup.callback_token, str(token)):
        return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
    result = (request.data.get("Body") or {}).get("stkCallback") or {}
    with organization_context(setup.organization):
        push = StkPush.objects.filter(checkout_request_id=result.get("CheckoutRequestID") or "-").first()
        if push and push.status == StkPush.PENDING:
            mpesa_express.apply_result(push, result.get("ResultCode"), result.get("ResultDesc", ""), result.get("CallbackMetadata"))
    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
