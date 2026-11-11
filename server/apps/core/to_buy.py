"""The scratch list of things to buy now: add, tick off, change, remove, clear what is bought. Nothing here writes
stock, money or the books. A line leaves the list by itself once the item is recorded in the system: when stock is
received (or entered as opening stock) for the product it was linked to, or, for a line typed without a product, for a
product with the same name (the usual case for something new, added as a product when it arrives)."""
from decimal import Decimal

from django.db.models import Max, Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ToBuyItem
from .permissions import HasLinTechPermission


def variant_label(variant):
    return variant.product.name if variant.name in ("", "Standard") else f"{variant.product.name} {variant.name}"


class ItemInput(serializers.ModelSerializer):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    count = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"), required=False)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True)
    product = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = ToBuyItem
        fields = ["id", "name", "variant", "product", "count", "unit", "unit_price", "total", "note", "bought"]

    def get_product(self, item):
        return variant_label(item.variant) if item.variant_id else None

    def get_total(self, item):
        return item.total


def cleared_by(variant):
    """Lines on the list this variant's stock coming in records: those linked to it, and unlinked ones of its name."""
    names = {variant.product.name.strip().lower(), variant_label(variant).strip().lower()}
    unlinked = Q()
    for name in names:
        unlinked |= Q(name__iexact=name)
    return ToBuyItem.objects.filter(Q(variant=variant) | Q(variant__isnull=True) & unlinked)


@receiver(post_save, sender="inventory.Movement")
def clear_received(sender, instance, created, **kwargs):
    if created and instance.movement_type in ("PURCHASE_RECEIPT", "OPENING_STOCK") and instance.quantity > 0:
        cleared_by(instance.variant).delete()


def listing():
    items = list(ToBuyItem.objects.select_related("variant__product"))
    left = [item for item in items if not item.bought]
    bought = [item for item in items if item.bought]
    add = lambda rows: sum((item.total for item in rows if item.total is not None), Decimal("0"))
    return {"items": ItemInput(items, many=True).data, "left": len(left), "left_total": add(left),
            "unpriced": sum(1 for item in left if item.total is None), "bought": len(bought), "bought_total": add(bought),
            "all_total": add(items)}


class ToBuyView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.view_tobuyitem", "POST": "core.add_tobuyitem", "DELETE": "core.delete_tobuyitem"}

    def get(self, request):
        return Response(listing())

    def post(self, request):
        form = ItemInput(data=request.data)
        form.is_valid(raise_exception=True)
        last = ToBuyItem.objects.aggregate(v=Max("position"))["v"] or 0
        form.save(position=last + 1, created_by=request.user)
        return Response(listing(), status=201)

    def delete(self, request):
        """Clear the items already bought."""
        ToBuyItem.objects.filter(bought=True).delete()
        return Response(listing())


class ToBuyItemView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"PATCH": "core.change_tobuyitem", "DELETE": "core.delete_tobuyitem"}

    def patch(self, request, pk):
        form = ItemInput(get_object_or_404(ToBuyItem, pk=pk), data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
        return Response(listing())

    def delete(self, request, pk):
        get_object_or_404(ToBuyItem, pk=pk).delete()
        return Response(listing())
