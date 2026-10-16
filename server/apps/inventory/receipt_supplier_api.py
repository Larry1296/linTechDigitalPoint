"""Settling what a receipt says is owed to its supplier, from the opened receipt (see accounting.supplier_settlement)."""
from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounting import supplier_settlement as settlement
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from .api import _receipt_data
from .models import StockReceipt


def _receipt(pk):
    return StockReceipt.objects.filter(pk=pk).first()


def _run(request, pk, permission, action):
    if not has_business_permission(request.user, permission):
        return Response({"detail": "You are not allowed to make this correction."}, status=403)
    receipt = _receipt(pk)
    if not receipt:
        return Response({"detail": "Receipt not found."}, status=404)
    try:
        with transaction.atomic():
            action(receipt)
    except ValidationError as exc:
        return Response(exc.detail, status=400)
    receipt.refresh_from_db()
    return Response(_receipt_data(receipt), status=201)


class PaymentInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    source = serializers.ChoiceField(choices=list(settlement.SOURCES))
    paid_on = serializers.DateField(required=False, allow_null=True)
    investment_id = serializers.IntegerField(required=False, allow_null=True)
    via = serializers.ChoiceField(choices=["MPESA", "BANK"], required=False, allow_null=True)
    reference = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def pay_supplier(request, pk):
    form = PaymentInput(data=request.data)
    form.is_valid(raise_exception=True)
    d = form.validated_data
    return _run(request, pk, "accounting.add_purchasepayment", lambda receipt: settlement.pay_supplier(
        receipt=receipt, amount=d["amount"], source=d["source"], paid_on=d.get("paid_on"), investment_id=d.get("investment_id"),
        via=d.get("via"), reference=d["reference"], key=d["idempotency_key"], user=request.user))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def undo_supplier_payment(request, pk, entry_id):
    return _run(request, pk, "accounting.reverse_cashentry", lambda receipt: settlement.undo_payment(
        receipt=receipt, entry_id=entry_id, reason=request.data.get("reason"), user=request.user))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def already_owned(request, pk):
    return _run(request, pk, "inventory.change_stockreceipt", lambda receipt: settlement.mark_already_owned(
        receipt=receipt, reason=request.data.get("reason"), user=request.user))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def undo_already_owned(request, pk):
    return _run(request, pk, "inventory.change_stockreceipt", lambda receipt: settlement.undo_already_owned(
        receipt=receipt, reason=request.data.get("reason"), user=request.user))
