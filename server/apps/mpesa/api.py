from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import HasLinTechPermission

from .models import MpesaCommissionEntry, MpesaOutlet, MpesaReconciliation, MpesaSession, MpesaTransaction
from .services import open_session, post_transaction, reconcile_session, record_commission, reverse_transaction, session_balances


class OutletSerializer(serializers.ModelSerializer):
    class Meta:
        model = MpesaOutlet
        fields = "__all__"


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


class CommissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MpesaCommissionEntry
        fields = "__all__"
        read_only_fields = ["recorded_by"]


class OutletViewSet(viewsets.ModelViewSet):
    serializer_class = OutletSerializer
    permission_classes = [HasLinTechPermission]
    queryset = MpesaOutlet.objects.select_related("store")

    def get_permissions(self):
        operation = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(self.action, "view")
        self.permission_required = f"mpesa.{operation}_mpesaoutlet"
        return [HasLinTechPermission()]


class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SessionSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesasession"
    queryset = MpesaSession.objects.select_related("outlet", "operator", "closed_by").prefetch_related("transactions")

    def get_queryset(self):
        rows = super().get_queryset()
        if self.request.user.is_superuser or self.request.user.groups.filter(name="Manager").exists():
            return rows
        return rows.filter(operator=self.request.user)

    def create(self, request):
        if not request.user.has_perm("mpesa.add_mpesasession"):
            return Response({"detail": "M-Pesa session permission required."}, status=403)
        outlet = MpesaOutlet.objects.get(pk=request.data.get("outlet"), active=True)
        result = open_session(outlet=outlet, operator=request.user, opening_cash=request.data.get("opening_cash"), opening_float=request.data.get("opening_float"), notes=request.data.get("notes", ""))
        return Response(self.get_serializer(result).data, status=201)

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        if not request.user.has_perm("mpesa.add_mpesareconciliation"):
            return Response({"detail": "M-Pesa reconciliation permission required."}, status=403)
        result = reconcile_session(session=self.get_object(), user=request.user, actual_cash=request.data.get("actual_cash"), actual_float=request.data.get("actual_float"), reason=request.data.get("reason", ""), notes=request.data.get("notes", ""))
        return Response(ReconciliationSerializer(result).data, status=201)


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesatransaction"
    queryset = MpesaTransaction.objects.select_related("outlet", "session", "performed_by", "reversal_of")

    def get_queryset(self):
        rows = super().get_queryset()
        if self.request.user.is_superuser or self.request.user.groups.filter(name="Manager").exists():
            return rows
        return rows.filter(session__operator=self.request.user)

    def create(self, request):
        if not request.user.has_perm("mpesa.add_mpesatransaction"):
            return Response({"detail": "M-Pesa posting permission required."}, status=403)
        session = MpesaSession.objects.get(pk=request.data.get("session"))
        entry, created = post_transaction(session=session, transaction_type=request.data.get("transaction_type"), transaction_amount=request.data.get("amount"), user=request.user, idempotency_key=request.data.get("idempotency_key"), provider_reference=request.data.get("provider_reference"), customer_reference=request.data.get("customer_reference", ""), notes=request.data.get("notes", ""), cash_delta=request.data.get("cash_delta"), float_delta=request.data.get("float_delta"))
        return Response(self.get_serializer(entry).data, status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        if not request.user.has_perm("mpesa.reverse_mpesa_transaction"):
            return Response({"detail": "M-Pesa reversal permission required."}, status=403)
        entry, created = reverse_transaction(original=self.get_object(), user=request.user, idempotency_key=request.data.get("idempotency_key"), reason=request.data.get("reason", ""))
        return Response(self.get_serializer(entry).data, status=201 if created else 200)


class ReconciliationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReconciliationSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesareconciliation"
    queryset = MpesaReconciliation.objects.select_related("session", "operator", "reviewed_by")


class CommissionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CommissionSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "mpesa.view_mpesacommissionentry"
    queryset = MpesaCommissionEntry.objects.select_related("outlet", "recorded_by")

    def create(self, request):
        if not request.user.has_perm("mpesa.add_mpesacommissionentry"):
            return Response({"detail": "Commission recording permission required."}, status=403)
        outlet = MpesaOutlet.objects.get(pk=request.data.get("outlet"))
        entry = record_commission(outlet=outlet, user=request.user, period=request.data.get("period"), commission_amount=request.data.get("amount"), reference=request.data.get("reference"), settlement_method=request.data.get("settlement_method"), recognized_at=request.data.get("recognized_at"), notes=request.data.get("notes", ""))
        return Response(self.get_serializer(entry).data, status=201)


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def dashboard(request):
    if not request.user.has_perm("mpesa.view_mpesasession"):
        return Response({"detail": "M-Pesa agency access required."}, status=403)
    today = timezone.localdate()
    sessions = MpesaSession.objects.filter(status="OPEN")
    if not (request.user.is_superuser or request.user.groups.filter(name="Manager").exists()):
        sessions = sessions.filter(operator=request.user)
    session = sessions.select_related("outlet", "operator").prefetch_related("transactions").first()
    cash, electronic_float = session_balances(session) if session else (0, 0)
    entries = MpesaTransaction.objects.filter(occurred_at__date=today)
    if not (request.user.is_superuser or request.user.groups.filter(name="Manager").exists()):
        entries = entries.filter(session__operator=request.user)
    deposits = entries.filter(transaction_type="CUSTOMER_DEPOSIT").aggregate(value=Sum("amount"))["value"] or 0
    withdrawals = entries.filter(transaction_type="CUSTOMER_WITHDRAWAL").aggregate(value=Sum("amount"))["value"] or 0
    commission = MpesaCommissionEntry.objects.filter(recognized_at__date=today).aggregate(value=Sum("amount"))["value"] or 0
    return Response({"session": SessionSerializer(session).data if session else None, "cash": cash, "float": electronic_float, "deposits": deposits, "withdrawals": withdrawals, "transaction_count": entries.exclude(transaction_type="REVERSAL").count(), "commission": commission, "principal_revenue": 0, "transaction_volume": deposits + withdrawals})
