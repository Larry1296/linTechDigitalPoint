"""M-KOPA phones: the phones and their plans with the commission each earns, phones in hand, sales and commission paid.

An employee who sells phones sees the plans the customer chooses from, but not the commission or what M-KOPA has paid:
that is the business's money, which only those allowed to see the commission get.
"""
from decimal import Decimal

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.core.pagination import page_or_list
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from . import services
from .models import MkopaCommission, MkopaPhone, MkopaPlan, MkopaSale, MkopaStock

MONEY = "mkopa.view_mkopacommission"


def _require(request, permission):
    if not has_business_permission(request.user, permission):
        raise PermissionDenied()


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def plan_row(plan, money):
    row = {"id": plan.pk, "deposit": plan.deposit, "daily_payment": plan.daily_payment, "days": plan.days,
           "total_price": services.total_price(plan), "active": plan.active}
    if money:
        # The commission used (learned from M-KOPA's payments once they pin it down, else what the owner typed), and both.
        row.update(commission=plan.rate, typed_commission=plan.commission, learned_commission=plan.learned_commission,
                   learned_from=plan.learned_from, commission_source="LEARNED" if plan.learned_commission is not None
                   else "TYPED" if plan.commission is not None else None)
    return row


def plan_figures(money):
    """Per plan: phones sold, how many M-KOPA has paid for and how much it paid for them."""
    figures = {}
    for sale in MkopaSale.objects.filter(reversed_at__isnull=True).select_related("paid_by"):
        row = figures.setdefault(sale.plan_id, {"sold": 0, "paid_phones": 0, "received": Decimal("0")})
        row["sold"] += 1
        if sale.paid_by_id and not sale.paid_by.reversed_at:
            row["paid_phones"] += 1
            row["received"] += sale.commission_received or Decimal("0")
    if not money:
        for row in figures.values():
            row.pop("received")
    return figures


def phone_row(phone, money, sold, figures=None):
    received = sum(move.quantity for move in phone.stock.all() if not move.reversed_at)
    figures = figures or {}
    empty = {"sold": 0, "paid_phones": 0, **({"received": Decimal("0")} if money else {})}
    plan = lambda p: {**plan_row(p, money), **figures.get(p.pk, empty)}
    return {"id": phone.pk, "name": phone.name, "active": phone.active,
            "plans": [plan(p) for p in phone.plans.all() if p.active],
            "old_plans": [plan(p) for p in phone.plans.all() if not p.active],
            "received": received, "sold": sold.get(phone.pk, 0), "in_hand": received - sold.get(phone.pk, 0),
            "tracks_stock": any(not move.reversed_at for move in phone.stock.all())}


def sale_row(sale, money):
    row = {"id": sale.pk, "phone": sale.phone.name, "phone_id": sale.phone_id, "plan_id": sale.plan_id, "customer_name": sale.customer_name,
           "customer_phone": sale.customer_phone, "imei": sale.imei, "sold_on": sale.sold_on, "deposit": sale.deposit,
           "daily_payment": sale.daily_payment, "days": sale.days, "total_price": sale.deposit + sale.daily_payment * sale.days,
           "notes": sale.notes, "sold_by": _name(sale.created_by), "reversed_at": sale.reversed_at, "reverse_reason": sale.reverse_reason}
    if money:
        paid = bool(sale.paid_by_id and not sale.paid_by.reversed_at)
        row.update(commission=services.expected(sale), commission_paid=paid, paid_on=sale.paid_by.paid_on if paid else None)
    return row


def stock_row(move):
    return {"id": move.pk, "phone": move.phone.name, "quantity": move.quantity, "moved_on": move.moved_on, "notes": move.notes,
            "recorded_by": _name(move.created_by), "reversed_at": move.reversed_at, "reverse_reason": move.reverse_reason}


def commission_row(payment):
    phones = [sale for sale in payment.sales.all()]
    return {"id": payment.pk, "phones": len(phones), "phone_names": sorted({sale.phone.name for sale in phones}), "itemised": payment.itemised,
            "for_phones": [{"sale": sale.pk, "phone": sale.phone.name, "customer_name": sale.customer_name, "amount": sale.commission_received}
                           for sale in sorted(phones, key=lambda sale: (sale.sold_on, sale.pk))], "amount": payment.amount, "paid_on": payment.paid_on, "method": payment.method,
            "method_name": services.METHODS.get(payment.method, payment.method), "reference": payment.reference, "notes": payment.notes,
            "recorded_by": _name(payment.created_by), "reversed_at": payment.reversed_at, "reverse_reason": payment.reverse_reason}


class OverviewView(APIView):
    """Everything the M-KOPA page shows."""
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.view_mkopasale"

    def get(self, request):
        money = has_business_permission(request.user, MONEY)
        sold = dict(MkopaSale.objects.filter(reversed_at__isnull=True).values("phone_id").annotate(n=Count("pk")).values_list("phone_id", "n"))
        phones = MkopaPhone.objects.prefetch_related("plans", "stock")
        figures = plan_figures(money)
        data = {"phones": [phone_row(phone, money, sold, figures) for phone in phones],
                # Phones sold grow every day: the page reads them a page at a time from GET /mkopa/sales/?page=N.
                "sold": MkopaSale.objects.filter(reversed_at__isnull=True).count(),
                "stock": [stock_row(move) for move in MkopaStock.objects.select_related("phone", "created_by")[:200]],
                "can_see_money": money, "methods": list(services.METHODS.items()),
                "can_set_up": has_business_permission(request.user, "mkopa.change_mkopaphone"),
                "can_undo": has_business_permission(request.user, "mkopa.change_mkopasale")}
        if money:
            data["summary"] = services.summary()
            data["commissions"] = [commission_row(p) for p in MkopaCommission.objects.select_related("created_by").prefetch_related("sales__phone")[:200]]
            # The phones a new payment can be for: sold, not undone, commission not paid yet.
            data["unpaid"] = [sale_row(sale, money) for sale in services.unpaid_sales().select_related("phone", "plan", "paid_by", "created_by")]
            data["can_record_commission"] = has_business_permission(request.user, "mkopa.add_mkopacommission")
        return Response(data)


class PlanInput(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    deposit = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    daily_payment = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    days = serializers.IntegerField(min_value=1, max_value=3650)
    commission = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True, default=None)


class PhoneInput(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    active = serializers.BooleanField(required=False)
    plans = PlanInput(many=True, required=False)


class PhonesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.add_mkopaphone"

    def post(self, request):
        form = PhoneInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        phone = services.add_phone(user=request.user, name=d.get("name", ""), plans=d.get("plans") or [])
        return Response({"id": phone.pk, "name": phone.name}, status=201)


class PhoneView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.change_mkopaphone"

    def patch(self, request, pk):
        form = PhoneInput(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        phone = services.change_phone(user=request.user, phone=get_object_or_404(MkopaPhone, pk=pk), name=d.get("name"),
                                      active=d.get("active"), plans=d.get("plans"))
        return Response({"id": phone.pk, "name": phone.name})


class StockInput(serializers.Serializer):
    phone = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=10000)
    kind = serializers.ChoiceField(choices=[MkopaStock.RECEIVED, MkopaStock.RETURNED])
    moved_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class StockView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.add_mkopastock"

    def post(self, request):
        form = StockInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        move = services.move_stock(user=request.user, phone=get_object_or_404(MkopaPhone, pk=d["phone"]), quantity=d["quantity"],
                                   kind=d["kind"], moved_on=d.get("moved_on"), notes=d["notes"], key=d["idempotency_key"])
        return Response(stock_row(move), status=201)


class StockUndoView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.change_mkopastock"

    def post(self, request, pk):
        move = services.undo_stock(user=request.user, move=get_object_or_404(MkopaStock, pk=pk), reason=request.data.get("reason"))
        return Response(stock_row(move))


class SaleInput(serializers.Serializer):
    plan = serializers.IntegerField()
    customer_name = serializers.CharField(max_length=120)
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    imei = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    sold_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class SalesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.add_mkopasale"

    def get_permissions(self):
        self.permission_required = "mkopa.view_mkopasale" if self.request.method == "GET" else "mkopa.add_mkopasale"
        return super().get_permissions()

    def get(self, request):
        """Phones sold, newest first: one page with ?page=N, else every one."""
        money = has_business_permission(request.user, MONEY)
        rows = MkopaSale.objects.select_related("phone", "plan", "paid_by", "created_by").order_by("-sold_on", "-pk")
        return page_or_list(request, rows, lambda sale: sale_row(sale, money))

    def post(self, request):
        form = SaleInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        sale = services.sell(user=request.user, plan=get_object_or_404(MkopaPlan, pk=d["plan"]), customer_name=d["customer_name"],
                             customer_phone=d["customer_phone"], imei=d["imei"], sold_on=d.get("sold_on"), notes=d["notes"],
                             key=d["idempotency_key"])
        return Response(sale_row(sale, has_business_permission(request.user, MONEY)), status=201)


class SaleUndoView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.change_mkopasale"

    def post(self, request, pk):
        sale = services.undo_sale(user=request.user, sale=get_object_or_404(MkopaSale, pk=pk), reason=request.data.get("reason"))
        return Response(sale_row(sale, has_business_permission(request.user, MONEY)))


class PhoneAmount(serializers.Serializer):
    sale = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class CommissionInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True)
    amounts = PhoneAmount(many=True, required=False, allow_null=True, default=None)
    method = serializers.ChoiceField(choices=list(services.METHODS))
    paid_on = serializers.DateField(required=False, allow_null=True)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    sales = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=None)
    idempotency_key = serializers.CharField(max_length=100)


class CommissionView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.add_mkopacommission"

    def post(self, request):
        form = CommissionInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        each = {row["sale"]: row["amount"] for row in d["amounts"]} if d["amounts"] is not None else None
        if each is not None and len(each) != len(d["amounts"]):
            raise serializers.ValidationError({"amounts": "Each phone once."})
        if each is None and d.get("amount") is None:
            raise serializers.ValidationError({"amount": "Enter the amount M-KOPA paid."})
        payment = services.record_commission(user=request.user, amount=d.get("amount"), method=d["method"], paid_on=d.get("paid_on"),
                                             reference=d["reference"], notes=d["notes"], key=d["idempotency_key"], sales=d["sales"], amounts=each)
        return Response(commission_row(payment), status=201)


class CommissionUndoView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "mkopa.change_mkopacommission"

    def post(self, request, pk):
        payment = services.undo_commission(user=request.user, payment=get_object_or_404(MkopaCommission, pk=pk), reason=request.data.get("reason"))
        return Response(commission_row(payment))
