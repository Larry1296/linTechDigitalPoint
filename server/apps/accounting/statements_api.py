"""Report endpoints. Every figure is computed from posted journals and recorded cost layers."""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.context import branch_context
from .ledger_api import report_scope
from . import statements


class PeriodInput(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(default=timezone.localdate)
    branch = serializers.IntegerField(min_value=1, required=False)
    view = serializers.ChoiceField(choices=["owner", "units", "accounting"], default="owner")
    page = serializers.IntegerField(min_value=1, default=1)

    def validate(self, data):
        data.setdefault("start", data["end"].replace(day=1))
        if data["start"] > data["end"]:
            raise serializers.ValidationError("Start must be on or before end.")
        return data


class ReportBase(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_profit"

    def period(self, request):
        form = PeriodInput(data=request.query_params)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        with branch_context(None):
            branch = report_scope(request, data)
        return data, branch


class StatementsView(ReportBase):

    def get(self, request):
        data, branch = self.period(request)
        start, end = data["start"], data["end"]
        with branch_context(branch):
            result = {"basis": "Accrual basis, FIFO stock costing, double-entry journals. Figures come only from posted transactions.",
                      "currency": request.organization.currency, "branch": branch, "start": start, "end": end, "view": data["view"]}
            if data["view"] == "owner":
                result["summary"] = statements.owner_summary(start, end)
            elif data["view"] == "units":
                result["profit_and_loss"] = statements.profit_and_loss(start, end)
                result["warnings"] = statements.warnings_for(start, end)
            else:
                result.update(profit_and_loss=statements.profit_and_loss(start, end), balance_sheet=statements.balance_sheet(end),
                              trial_balance=statements.trial_balance(start, end), cash_flow=statements.cash_flow(start, end),
                              reconciliation=statements.reconciliation(), receivables=statements.receivables(),
                              payables=statements.payables(), stock_valuation=statements.stock_valuation(),
                              warnings=statements.warnings_for(start, end),
                              # Reconciliation, receivables, payables and stock value are today's figures, whatever the end date.
                              subledgers_as_of=timezone.localdate())
        return Response(result)


class AccountLedgerView(ReportBase):

    def get(self, request, code):
        data, branch = self.period(request)
        with branch_context(branch):
            ledger = statements.account_ledger(code, data["start"], data["end"], data["page"])
        if not ledger:
            raise NotFound("Account not found.")
        return Response(ledger)


class ExplainSaleItemView(ReportBase):

    def get(self, request, pk):
        result = statements.explain_sale_item(pk)
        if not result:
            raise NotFound("Sale line not found.")
        return Response(result)
