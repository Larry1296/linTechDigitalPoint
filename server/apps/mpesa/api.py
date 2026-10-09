from datetime import datetime, time, timedelta
from decimal import Decimal
from apps.tenancy.permissions import has_business_permission, is_business_manager
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import HasLinTechPermission

from .models import MpesaCommissionEntry, MpesaOutlet, MpesaReconciliation, MpesaSession, MpesaTransaction
from .services import add_provider_reference, correct_transaction, open_session, post_transaction, reconcile_session, reverse_transaction, session_balances


def money_in_operation(outlet):
    """The outlet's cash and float as last recorded, and whether today's figure is still due.

    A shift opened or closed today is today's update. Updates are expected every day except Sunday.
    """
    today = timezone.localdate()
    session = outlet.sessions.order_by("-opened_at", "-pk").first()
    if not session:
        cash = electronic_float = updated = None
    elif session.status == MpesaSession.OPEN:
        (cash, electronic_float), updated = session_balances(session), timezone.localdate(session.opened_at)
    else:
        cash, electronic_float, updated = session.closing_cash_actual, session.closing_float_actual, timezone.localdate(session.closed_at)
    return {"cash": cash, "float": electronic_float, "total": None if cash is None else cash + electronic_float,
            "updated_on": updated, "due": today.weekday() != 6 and updated != today}


class OutletSerializer(serializers.ModelSerializer):
    money_in_operation = serializers.SerializerMethodField()

    def get_money_in_operation(self, outlet):
        return money_in_operation(outlet)

    def validate(self, data):
        if self.instance and data.get("active") is False and self.instance.sessions.filter(status=MpesaSession.OPEN).exists():
            raise serializers.ValidationError("Close this outlet's open shift before deactivating it.")
        return data

    class Meta:
        model = MpesaOutlet
        fields = "__all__"
        extra_kwargs = {"store": {"required": False}}

    def create(self, data):
        # Default a new outlet to the branch the user is working in.
        if not data.get("store"):
            from apps.core.models import Store
            request = self.context["request"]
            data["store"] = getattr(request, "store", None) or Store.objects.order_by("created_at", "pk").first()
        return super().create(data)


class TransactionSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source="performed_by.get_full_name", read_only=True)

    class Meta:
        model = MpesaTransaction
        fields = "__all__"
        read_only_fields = ["internal_reference", "outlet", "cash_delta", "float_delta", "status", "reversal_of", "performed_by", "occurred_at", "created_at"]


class SessionSerializer(serializers.ModelSerializer):
    current_cash = serializers.SerializerMethodField()
    current_float = serializers.SerializerMethodField()
    operator_name = serializers.CharField(source="operator.get_full_name", read_only=True)

    class Meta:
        model = MpesaSession
        fields = "__all__"

    def get_current_cash(self, obj):
        return session_balances(obj)[0]

    def get_current_float(self, obj):
        return session_balances(obj)[1]


class ReconciliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MpesaReconciliation
        fields = "__all__"


class OutletViewSet(viewsets.ModelViewSet):
    serializer_class = OutletSerializer
    permission_classes = [HasLinTechPermission]
    queryset = MpesaOutlet.objects.select_related("store")

    def get_permissions(self):
        operation = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(self.action, "view")
        self.permission_required = f"mpesa.{operation}_mpesaoutlet"
        return [HasLinTechPermission()]

    def destroy(self, request, pk=None):
        outlet = self.get_object()
        # Shifts, transactions and commission are the agency's records; they are kept, so the outlet is too.
        if outlet.sessions.exists() or outlet.transactions.exists() or outlet.commissions.exists():
            return Response({"detail": "This outlet has shift history and cannot be deleted. Deactivate it instead."}, status=400)
        outlet.delete()
        return Response(status=204)


class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SessionSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesasession"
    queryset = MpesaSession.objects.select_related("outlet", "operator", "closed_by").prefetch_related("transactions")

    def get_queryset(self):
        rows = super().get_queryset()
        if is_business_manager(self.request.user):
            return rows
        return rows.filter(operator=self.request.user)

    def create(self, request):
        if not has_business_permission(request.user, "mpesa.add_mpesasession"):
            return Response({"detail": "M-Pesa session permission required."}, status=403)
        outlet = MpesaOutlet.objects.get(pk=request.data.get("outlet"), active=True)
        if request.data.get("commission") and not has_business_permission(request.user, "mpesa.add_mpesacommissionentry"):
            return Response({"detail": "Commission recording permission required."}, status=403)
        result = open_session(outlet=outlet, operator=request.user, opening_cash=request.data.get("opening_cash"), opening_float=request.data.get("opening_float"), notes=request.data.get("notes", ""), cash_count=request.data.get("cash_count"),
                              difference_reason=request.data.get("difference_reason", ""), commission=request.data.get("commission") or None)
        return Response(self.get_serializer(result).data, status=201)

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        if not has_business_permission(request.user, "mpesa.add_mpesareconciliation"):
            return Response({"detail": "M-Pesa reconciliation permission required."}, status=403)
        result = reconcile_session(session=self.get_object(), user=request.user, actual_cash=request.data.get("actual_cash"), actual_float=request.data.get("actual_float"), reason=request.data.get("reason", ""), notes=request.data.get("notes", ""), cash_count=request.data.get("cash_count"))
        return Response(ReconciliationSerializer(result).data, status=201)

    @action(detail=False)
    def past(self, request):
        # Closed shifts that hold records, newest first, each named by when it ran, so a cleared desk's records can be opened again.
        rows = (self.get_queryset().filter(status=MpesaSession.CLOSED).annotate(records=Count("transactions")).filter(records__gt=0)
                .prefetch_related(None).select_related("reconciliation").order_by("-opened_at", "-pk"))
        from .commission_learning import forecast, learn
        learned = learn() if rows else None
        return Response([{"id": s.pk, "outlet": s.outlet.display_name, "month_forecast": forecast(s.closed_at, learned), "operator": s.operator.get_full_name() or s.operator.username,
                          "opened_at": s.opened_at, "closed_at": s.closed_at, "records": s.records,
                          "opening_cash": s.opening_cash, "opening_float": s.opening_float,
                          "closing_cash": s.closing_cash_actual, "closing_float": s.closing_float_actual,
                          "cash_variance": getattr(getattr(s, "reconciliation", None), "cash_variance", None),
                          "float_variance": getattr(getattr(s, "reconciliation", None), "float_variance", None)} for s in rows])


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesatransaction"
    queryset = MpesaTransaction.objects.select_related("outlet", "session", "performed_by", "reversal_of")

    def get_queryset(self):
        rows = super().get_queryset()
        if self.request.query_params.get("shift") == "open":
            rows = rows.filter(session__status=MpesaSession.OPEN)
        if self.request.query_params.get("session", "").isdigit():
            rows = rows.filter(session_id=self.request.query_params["session"])
        if is_business_manager(self.request.user):
            return rows
        return rows.filter(session__operator=self.request.user)

    def list(self, request):
        """Each deposit, withdrawal and airtime sale with the commission it earned: measured from its reading, or learned."""
        from .commission_learning import earned, learn
        rows = list(self.filter_queryset(self.get_queryset()))
        data = self.get_serializer(rows, many=True).data
        outlet_ids = {row.outlet_id for row in rows if row.transaction_type in ("CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE")}
        results = earned(*learn(outlet_ids)) if outlet_ids else {}
        for item in data:
            value, source = results.get(item["id"], (None, None))
            item["commission_earned"], item["commission_source"] = value, source
        return Response(data)

    def create(self, request):
        if not has_business_permission(request.user, "mpesa.add_mpesatransaction"):
            return Response({"detail": "M-Pesa posting permission required."}, status=403)
        if request.data.get("transaction_type") == "INVESTMENT":
            return Response({"detail": "Move money to or from an investment on the Investments page."}, status=400)
        if request.data.get("transaction_type") == "COMMISSION":
            return Response({"detail": "Record Safaricom's commission on the Commission page."}, status=400)
        session = MpesaSession.objects.get(pk=request.data.get("session"))
        entry, created = post_transaction(session=session, transaction_type=request.data.get("transaction_type"), transaction_amount=request.data.get("amount"), user=request.user, idempotency_key=request.data.get("idempotency_key"), provider_reference=request.data.get("provider_reference"), customer_reference=request.data.get("customer_reference", ""), notes=request.data.get("notes", ""), cash_delta=request.data.get("cash_delta"), float_delta=request.data.get("float_delta"),
            customer_name=request.data.get("customer_name", ""), customer_phone=request.data.get("customer_phone", ""), customer_id_number=request.data.get("customer_id_number", ""), paid_by=request.data.get("paid_by", ""),
            commission_balance=request.data.get("commission_balance"))
        return Response(self.get_serializer(entry).data, status=201 if created else 200)

    @action(detail=False, methods=["get"], url_path="commission-advice")
    def commission_advice(self, request):
        """Whether the form should ask for the commission balance after this transaction, or already knows its commission."""
        from .commission_learning import advice
        session = MpesaSession.objects.filter(pk=request.query_params.get("session") or 0).first()
        try:
            value = Decimal(str(request.query_params.get("amount") or "")).quantize(Decimal("0.01"))
        except Exception:
            value = None
        if not session or value is None or value <= 0:
            return Response({"earned": None, "ask": True, "reason": "new"})
        return Response(advice(session.outlet_id, request.query_params.get("type", ""), value))

    @action(detail=True, methods=["post"])
    def reference(self, request, pk=None):
        if not has_business_permission(request.user, "mpesa.add_mpesatransaction"):
            return Response({"detail": "M-Pesa posting permission required."}, status=403)
        entry = add_provider_reference(entry=self.get_object(), reference=request.data.get("provider_reference"), user=request.user)
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        if not has_business_permission(request.user, "mpesa.reverse_mpesa_transaction"):
            return Response({"detail": "Only a manager or owner can correct an M-Pesa transaction."}, status=403)
        data = request.data
        entry = correct_transaction(original=self.get_object(), user=request.user, key=str(data.get("idempotency_key") or ""), reason=str(data.get("reason") or ""),
                                    amount=data.get("amount"), customer_phone=data.get("customer_phone"), customer_id_number=data.get("customer_id_number"),
                                    provider_reference=data.get("provider_reference"), paid_by=data.get("paid_by"),
                                    commission_balance=data.get("commission_balance"))
        return Response(self.get_serializer(entry).data, status=201)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        if not has_business_permission(request.user, "mpesa.reverse_mpesa_transaction"):
            return Response({"detail": "M-Pesa reversal permission required."}, status=403)
        original = self.get_object()
        commission = getattr(original, "commission", None)
        if commission:
            # Commission paid into the float or cash: undo the whole commission, so its income comes out of the books too.
            if not has_business_permission(request.user, "accounting.reverse_cashentry"):
                return Response({"detail": "Permission to correct the books is required to undo commission."}, status=403)
            from .commission import undo
            undo(entry=commission, user=request.user, reason=str(request.data.get("reason") or ""))
            original.refresh_from_db()
            return Response(self.get_serializer(original.reversal).data, status=201)
        entry, created = reverse_transaction(original=original, user=request.user, idempotency_key=request.data.get("idempotency_key"), reason=request.data.get("reason", ""))
        return Response(self.get_serializer(entry).data, status=201 if created else 200)


class ReconciliationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReconciliationSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesareconciliation"
    queryset = MpesaReconciliation.objects.select_related("session", "operator", "reviewed_by")


def commission_row(entry):
    return {"id": entry.pk, "outlet": entry.outlet_id, "outlet_name": entry.outlet.display_name, "period": entry.period,
            "month": entry.period.strftime("%B %Y"), "amount": entry.amount, "reference": entry.reference,
            "settlement_method": entry.settlement_method, "paid_on": timezone.localtime(entry.recognized_at).date(), "earned_on": entry.earned_on,
            "notes": entry.notes, "recorded_by": (entry.recorded_by.get_full_name() or entry.recorded_by.username) if entry.recorded_by_id else "",
            "reversed_at": entry.reversed_at, "reverse_reason": entry.reverse_reason}


def opening_shifts(outlet, opening_room):
    """Recent shifts that opened with more float than the shift before closed with: commission paid in between can be recorded against them."""
    rows = []
    for shift in outlet.sessions.order_by("-opened_at", "-pk")[:10]:
        room = opening_room(shift)
        if room > 0:
            rows.append({"id": shift.pk, "opened_on": timezone.localtime(shift.opened_at).date(), "opening_float": shift.opening_float,
                         "carried_float": shift.carried_float, "room": room})
    return rows


def commission_estimates():
    """This month's and last month's commission as the app works it out from the readings, to compare with Safaricom's payment."""
    from .commission_learning import for_month
    this = timezone.localdate().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    following = (this + timedelta(days=32)).replace(day=1)
    start = lambda day: timezone.make_aware(datetime.combine(day, time.min))
    paid = {row["period"]: row["v"] for row in MpesaCommissionEntry.objects.filter(reversed_at__isnull=True, period__in=[this, last])
            .values("period").annotate(v=Sum("amount"))}
    return [{"month": begin, "label": begin.strftime("%B %Y"), "paid": paid.get(begin), **for_month(start(begin), start(end))}
            for begin, end in [(this, following), (last, this)]]


class CommissionInput(serializers.Serializer):
    outlet = serializers.IntegerField()
    period = serializers.DateField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    settlement_method = serializers.CharField(max_length=40)
    paid_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    session_id = serializers.IntegerField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=100)


class CommissionViewSet(viewsets.ReadOnlyModelViewSet):
    """Safaricom's monthly commission: recorded when paid, counted in the month it was earned (see commission.py)."""
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesacommissionentry"
    queryset = MpesaCommissionEntry.objects.select_related("outlet", "recorded_by").order_by("-period", "-recognized_at", "-pk")

    def list(self, request):
        from .commission import PLACES, due_month, monthly_profit, opening_room
        from .commission_learning import forecast, learn
        due = due_month()
        rows = monthly_profit()
        return Response({"entries": [commission_row(e) for e in self.get_queryset()[:60]],
                         "months": [{**row, "label": row["month"].strftime("%B %Y")} for row in rows],
                         "totals": {key: sum((row[key] for row in rows), Decimal("0")) for key in ["commission", "expenses", "profit"]},
                         "due_month": due, "due_label": due.strftime("%B %Y") if due else None, "places": PLACES,
                         "outlets": [{"id": o.pk, "name": o.display_name, "open_session": o.sessions.filter(status=MpesaSession.OPEN).values_list("pk", flat=True).first(),
                                      "opening_shifts": opening_shifts(o, opening_room)} for o in MpesaOutlet.objects.all()],
                         "estimates": commission_estimates(), "learned": learn()[2].bands(), "forecast": forecast()})

    def retrieve(self, request, pk=None):
        return Response(commission_row(self.get_object()))

    def create(self, request):
        if not has_business_permission(request.user, "mpesa.add_mpesacommissionentry"):
            return Response({"detail": "Commission recording permission required."}, status=403)
        form = CommissionInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        from .commission import record
        entry = record(outlet=d["outlet"], user=request.user, period=d["period"], amount=d["amount"], reference=d["reference"],
                       settlement=d["settlement_method"], key=d["idempotency_key"], paid_on=d.get("paid_on"), notes=d["notes"],
                       session_id=d.get("session_id"))
        return Response(commission_row(entry), status=201)

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        if not has_business_permission(request.user, "accounting.reverse_cashentry"):
            return Response({"detail": "Permission to correct the books is required."}, status=403)
        from .commission import undo
        return Response(commission_row(undo(entry=self.get_object(), user=request.user, reason=str(request.data.get("reason") or ""))))


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def dashboard(request):
    if not has_business_permission(request.user, "mpesa.view_mpesasession"):
        return Response({"detail": "M-Pesa agency access required."}, status=403)
    today = timezone.localdate()
    sessions = MpesaSession.objects.filter(status="OPEN")
    if not (is_business_manager(request.user)):
        sessions = sessions.filter(operator=request.user)
    session = sessions.select_related("outlet", "operator").prefetch_related("transactions").first()
    cash, electronic_float = session_balances(session) if session else (0, 0)
    # The desk shows the open shift only: closing a shift starts the next one from zero. Closed shifts'
    # transactions are kept for reconciliation and the books; they are just not counted here.
    entries = session.transactions.all() if session else MpesaTransaction.objects.none()
    # A reversed transaction and its reversal cancel out: neither is counted.
    entries = entries.exclude(transaction_type="REVERSAL").filter(reversal__isnull=True)
    deposits = entries.filter(transaction_type="CUSTOMER_DEPOSIT").aggregate(value=Sum("amount"))["value"] or 0
    withdrawals = entries.filter(transaction_type="CUSTOMER_WITHDRAWAL").aggregate(value=Sum("amount"))["value"] or 0
    airtime = entries.filter(transaction_type="AIRTIME_SALE").aggregate(value=Sum("amount"))["value"] or 0
    commission = MpesaCommissionEntry.objects.filter(recognized_at__date=today).aggregate(value=Sum("amount"))["value"] or 0
    # Deposits, withdrawals, airtime paid in cash and float bought with cash only swap cash for float, so this total
    # stays put; cash brought in (rebalance), manager adjustments and airtime paid to another number change it.
    in_operation = {"total": cash + electronic_float,
                    "opening": (session.opening_cash + session.opening_float) if session else 0}
    from .commission_learning import for_shift, forecast
    return Response({"commission_shift": for_shift(session) if session else None, "commission_month": forecast(), "in_operation": in_operation, "session": SessionSerializer(session).data if session else None, "cash": cash, "float": electronic_float, "deposits": deposits, "withdrawals": withdrawals, "airtime": airtime, "transaction_count": entries.count(), "commission": commission, "principal_revenue": 0, "transaction_volume": deposits + withdrawals})


def _can_report(request):
    # The report lists every customer's phone and ID number, so it is for owners and managers.
    return has_business_permission(request.user, "mpesa.view_mpesareconciliation") and is_business_manager(request.user)


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def report_months(request):
    """Ended months with agency activity; the newest is the one whose report is due."""
    from .monthly_report import completed_months
    if not _can_report(request):
        return Response({"detail": "Only an owner or manager can generate M-Pesa reports."}, status=403)
    return Response(completed_months())


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def monthly_report(request):
    from django.http import HttpResponse
    from apps.core.models import AuditLog
    from .monthly_report import month_data, render_pdf
    if not _can_report(request):
        return Response({"detail": "Only an owner or manager can generate M-Pesa reports."}, status=403)
    month = request.query_params.get("month", "")
    pdf = render_pdf(month_data(month), request.organization)
    AuditLog.objects.create(action="MPESA_MONTHLY_REPORT", object_type="MpesaReport", object_id=month, user=request.user,
                            after={"month": month})
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="mpesa-report-{month}.pdf"'
    return response


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def customer_lookup(request):
    """A returning depositor's ID number from their last deposit, so the operator only types the phone number."""
    from rest_framework.exceptions import ValidationError
    from .services import normalise_phone
    if not has_business_permission(request.user, "mpesa.add_mpesatransaction"):
        return Response({"detail": "M-Pesa posting permission required."}, status=403)
    try:
        phone = normalise_phone(request.query_params.get("phone"))
    except ValidationError:
        return Response({"found": False})
    rows = MpesaTransaction.objects.filter(customer_phone=phone).exclude(customer_id_number="")
    last = rows.order_by("-occurred_at", "-pk").first()
    if not last:
        return Response({"found": False, "phone": phone})
    return Response({"found": True, "phone": phone, "id_number": last.customer_id_number, "visits": rows.count(), "last_seen": last.occurred_at})
