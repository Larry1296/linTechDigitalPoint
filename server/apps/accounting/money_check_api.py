from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from .models import MoneyCheck
from .money_check import add_starting_money, check_row, kept_in_investments, places, record_check, starting_entries, undo_starting_money


class MoneyCheckView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_moneycheck"

    def get(self, request):
        from .money_mode import money_mode
        kept = kept_in_investments() if has_business_permission(request.user, "accounting.view_investment") else None
        return Response({"mode": money_mode(), "places": places(), "starting": starting_entries(), "investments": kept,
                         "history": [check_row(c) for c in MoneyCheck.objects.select_related("created_by")[:30]]})

    def post(self, request):
        if not has_business_permission(request.user, "accounting.add_moneycheck"):
            raise PermissionDenied()
        check = record_check(user=request.user, method=request.data.get("method"), actual=request.data.get("actual"),
                             cash_count=request.data.get("cash_count"), note=request.data.get("note", ""),
                             unit=request.data.get("unit") or None)
        return Response(check_row(check), status=201)


class StartingMoneyView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_cashentry"

    def post(self, request):
        key = str(request.data.get("idempotency_key") or "")
        if not key:
            return Response({"detail": "A request key is required."}, status=400)
        add_starting_money(user=request.user, method=request.data.get("method"), amount=request.data.get("amount"),
                           note=request.data.get("note", ""), key=key, unit=request.data.get("unit") or None)
        return Response({"places": places()}, status=201)




class StartingMoneyUndoView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.reverse_cashentry"

    def post(self, request, pk):
        undo_starting_money(user=request.user, entry_id=pk, reason=request.data.get("reason", ""))
        return Response({"places": places(), "starting": starting_entries()}, status=201)
