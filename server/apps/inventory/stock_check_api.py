from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from .stock_check import products, record_difference

REASONS = {"lost": "Lost item", "damaged": "Damaged item", "found": "Found stock"}


class StockCheckView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "inventory.adjust_stock"

    def get(self, request):
        return Response(products(has_business_permission(request.user, "accounting.view_profit")))

    def post(self, request):
        kind = request.data.get("kind")
        if kind not in REASONS:
            return Response({"detail": "Choose lost, damaged or found."}, status=400)
        from decimal import Decimal, InvalidOperation
        try:
            quantity = abs(Decimal(str(request.data.get("quantity") or 0)))
        except InvalidOperation:
            return Response({"detail": "Enter how many."}, status=400)
        record_difference(user=request.user, variant_id=request.data.get("variant_id"), quantity=quantity if kind == "found" else -quantity,
                          reason=REASONS[kind], unit_cost=request.data.get("unit_cost"), note=str(request.data.get("note") or ""))
        return Response(products(has_business_permission(request.user, "accounting.view_profit")), status=201)
