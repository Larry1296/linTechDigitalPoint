from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from apps.core.permissions import IsInternalStaff
from apps.catalog.identity import display_name
from apps.catalog.models import ProductVariant
from .adjustments import adjust_stock, authorize
from .models import Movement, StockAdjustment, StockBalance, StockLot


class AdjustmentInput(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    shelf_id = serializers.IntegerField(min_value=1)
    expected_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    counted_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    reason = serializers.ChoiceField(choices=StockAdjustment.REASONS)
    notes = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=120)
    confirmed = serializers.BooleanField()
    lot_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    new_lot_unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0, required=False, allow_null=True
    )


def movement_data(m):
    a = m.adjustment
    return {
        "id": m.pk,
        "movement_type": m.movement_type,
        "quantity": str(m.quantity),
        "quantity_before": m.quantity_before,
        "quantity_after": m.quantity_after,
        "lot_id": m.lot_id,
        "shelf": (m.destination or m.source).physical_label or (m.destination or m.source).code
        if m.destination or m.source
        else "",
        "reason": a.reason if a else "",
        "notes": m.notes,
        "reference": m.reference,
        "administrator": m.performed_by.get_username() if m.performed_by else "",
        "created_at": m.created_at,
        "adjustment_id": m.adjustment_id,
    }


def adjustment_data(a):
    return {
        "id": a.pk,
        "display_name": display_name(a.variant.product.name, a.variant.name),
        "sku": a.variant.sku,
        "shelf": a.shelf.physical_label or a.shelf.code,
        "quantity_before": a.quantity_before,
        "amount": a.amount,
        "quantity_after": a.quantity_after,
        "reason": a.reason,
        "notes": a.notes,
        "reference": a.reference,
        "administrator": a.performed_by.get_username(),
        "created_at": a.created_at,
        "movements": [
            movement_data(m) for m in a.movements.select_related("adjustment", "performed_by", "source", "destination")
        ],
    }


@api_view(["GET", "POST"])
@permission_classes([IsInternalStaff])
def adjustments(request):
    authorize(request.user)
    if request.method == "POST":
        data = AdjustmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(adjustment_data(adjust_stock(user=request.user, **data.validated_data)))
    return Response(
        [
            adjustment_data(a)
            for a in StockAdjustment.objects.select_related("variant__product", "shelf", "performed_by").order_by(
                "-pk"
            )[:200]
        ]
    )


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def adjustment_context(request, pk):
    authorize(request.user)
    variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=pk)
    return Response(
        {
            "display_name": display_name(variant.product.name, variant.name),
            "sku": variant.sku,
            "balances": list(
                StockBalance.objects.filter(lot__variant=variant).values("shelf_id", "quantity", "reserved", "lot_id")
            ),
            # Every place this item is stocked (including "Not assigned to a shelf"), so the page can prefill the count.
            "locations": [
                {"shelf_id": row["shelf_id"], "code": row["shelf__code"], "label": row["shelf__physical_label"] or row["shelf__code"],
                 "name": row["shelf__display_name"], "virtual": row["shelf__is_virtual"],
                 "quantity": row["quantity"], "reserved": row["reserved"]}
                for row in StockBalance.objects.filter(lot__variant=variant)
                .values("shelf_id", "shelf__code", "shelf__physical_label", "shelf__display_name", "shelf__is_virtual")
                .annotate(quantity=Sum("quantity"), reserved=Sum("reserved"))
                .filter(quantity__gt=0)
                .order_by("-quantity", "shelf_id")
            ],
            "lots": [{'id':row['lot_id'],'reference':row['lot__reference'],'remaining_quantity':row['remaining_quantity']}
                for row in StockBalance.objects.filter(lot__variant=variant).values('lot_id','lot__reference').annotate(remaining_quantity=__import__('django.db.models',fromlist=['Sum']).Sum('quantity'))],
            # Where stock goes when there is none yet (its usual shelf, or "Not assigned to a shelf"), and the delivery
            # whose buying price extra units take, so a quantity can be raised straight from the product's details.
            "default_shelf_id": default_shelf_id(variant),
            "latest_lot_id": StockLot.objects.filter(variant=variant, cost_status=StockLot.COSTED).order_by("-received_at", "-id").values_list("id", flat=True).first(),
            "history": [
                movement_data(m)
                for m in Movement.objects.filter(variant=variant)
                .select_related("adjustment", "performed_by", "source", "destination")
                .order_by("-pk")[:200]
            ],
        }
    )


def default_shelf_id(variant):
    from .models import VariantPreferredLocation
    from .unplaced import unplaced_shelf
    preferred = VariantPreferredLocation.objects.filter(variant=variant, shelf__active=True).values_list("shelf_id", flat=True).first()
    return preferred or unplaced_shelf().pk
