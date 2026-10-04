from apps.tenancy.permissions import has_business_permission, is_business_manager
from django.db import models, transaction
from django.db.models import F, OuterRef, Q, Subquery, Sum
from django.utils.text import slugify
from rest_framework import filters, permissions, serializers, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from apps.catalog.identity import display_name
from apps.catalog.display_images import variant_images
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from apps.catalog.models import Category, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Movement, Shelf, ShelfLevel, ShelfStack, ShelfStackCategory, StockBalance, Zone
from apps.inventory.services import (
    archive_shelf,
    archive_shelf_stack,
    create_shelf,
    create_shelf_stack,
    update_shelf,
    update_shelf_stack,
)
from apps.cyber.models import CyberServiceProfile
from .permissions import HasLinTechPermission, IsInternalStaff


class PublicVariantSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name")
    product_id = serializers.IntegerField(read_only=True)
    variant_id = serializers.IntegerField(source="pk", read_only=True)
    variant_name = serializers.CharField(source="name", read_only=True)
    display_name = serializers.SerializerMethodField()
    attributes = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    slug = serializers.CharField(source="product.slug")
    description = serializers.CharField(source="product.description")
    category = serializers.CharField(source="product.category.name")
    brand = serializers.CharField(source="product.brand.name", allow_null=True)
    images = serializers.SerializerMethodField()
    available = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "product_name", "product_id", "variant_id", "variant_name", "display_name", "sku", "attributes", "variant_count",
            "slug",
            "description",
            "category",
            "brand",
            "images",
            "name",
            "selling_price",
            "available",
        ]


    def get_display_name(self, obj):
        return display_name(obj.product.name, obj.name)

    def get_attributes(self, obj):
        return [{"name": a.value.option_type.name, "value": a.value.value} for a in obj.option_assignments.all()]

    def get_variant_count(self, obj):
        return sum(v.active for v in obj.product.variants.all())

    def get_images(self, obj):
        return variant_images(obj)

    def get_available(self, obj):
        if obj.product.product_type == "SERVICE":
            return None
        if hasattr(obj, "available_total"):
            return obj.available_total or 0
        return StockBalance.objects.filter(lot__variant=obj).aggregate(v=Sum(F("quantity") - F("reserved")))["v"] or 0


class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsInternalStaff]
    serializer_class = PublicVariantSerializer
    queryset = (
        ProductVariant.objects.select_related("product", "product__category", "product__brand")
        .prefetch_related("product__images", "product__variants", "option_assignments__value__option_type")
        .filter(active=True, product__active=True)
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["product__category", "product__brand"]

    def get_queryset(self):
        if self.action == "list" and self.request.query_params.get("in_stock") == "true":
            return in_stock_public_variants().order_by("-created_at", "-id")
        return super().get_queryset()

    def retrieve(self, request, *args, **kwargs):
        variant = self.get_object()
        data = self.get_serializer(variant).data
        data["variants"] = self.get_serializer(self.get_queryset().filter(product_id=variant.product_id).order_by("id"), many=True).data
        return Response(data)
    search_fields = ["product__name", "product__description", "name", "product__category__name", "product__brand__name", "sku", "option_assignments__value__value"]


def in_stock_public_variants():
    # A correlated aggregate avoids multiplying balances when matching option details.
    availability = (
        StockBalance.objects.filter(lot__variant_id=OuterRef("pk"))
        .order_by().values("lot__variant_id")
        .annotate(total=Sum(F("quantity") - F("reserved"))).values("total")
    )
    return PublicProductViewSet.queryset.filter(
        product__product_type="STOCK_ITEM",
    ).annotate(available_total=Subquery(availability)).filter(available_total__gt=0)


class PublicSuggestionSerializer(PublicVariantSerializer):
    class Meta(PublicVariantSerializer.Meta):
        fields = ["id", "display_name", "category", "selling_price", "available", "images"]


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def public_search_suggestions(request):
    query = request.query_params.get("q", "").strip()
    if len(query) < 2:
        return Response([])
    matches = Q()
    for field in ("product__name", "name", "product__category__name",
                  "product__brand__name", "sku", "option_assignments__value__value"):
        matches |= Q(**{f"{field}__icontains": query})
    products = in_stock_public_variants().filter(matches).distinct().order_by(
        "product__name", "name", "id"
    )[:8]
    return Response(PublicSuggestionSerializer(products, many=True).data)


def public_category_sections():
    products = in_stock_public_variants().filter(product__category__active=True).order_by(
        "product__category__name", "product__category_id", "product__name", "name", "id"
    )
    sections = {}
    for product in products:
        category = product.product.category
        if category.id not in sections:
            sections[category.id] = {
                "id": category.id, "name": category.name, "slug": category.slug,
                "total_available": 0, "products": [],
            }
        sections[category.id]["products"].append(PublicVariantSerializer(product).data)
        sections[category.id]["total_available"] += 1
    return list(sections.values())


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def public_home(request):
    categories = list(Category.objects.filter(active=True).values("id", "name", "slug", "parent_id").order_by("name"))
    store = Store.objects.first()
    store_data = (
        {"name": store.name, "phone": store.phone, "email": store.email, "address": store.address}
        if store
        else {"name": request.organization.name, "phone": "", "email": "", "address": ""}
    )
    category_sections = public_category_sections()
    services = PublicVariantSerializer(
        PublicProductViewSet.queryset.filter(product__product_type="SERVICE")[:6], many=True
    ).data
    cyber_services = [
        {"name": profile.variant.product.name, "price": profile.variant.selling_price, "billing_unit": profile.billing_unit}
        for profile in CyberServiceProfile.objects.filter(active=True, publicly_advertised=True, variant__active=True, variant__product__active=True).select_related("variant__product")[:8]
    ]
    return Response(
        {"store": store_data, "categories": categories, "category_sections": category_sections, "services": services, "cyber_services": cyber_services}
    )


class ShelfSerializer(serializers.ModelSerializer):
    total_quantity = serializers.SerializerMethodField()
    contents = serializers.SerializerMethodField()
    stack_id = serializers.IntegerField(source="level.stack_id", read_only=True)
    stack_name = serializers.CharField(source="level.stack.display_name", read_only=True)
    level_number = serializers.IntegerField(source="level.level_number", read_only=True)

    class Meta:
        model = Shelf
        fields = [
            "id",
            "code",
            "physical_label",
            "display_name",
            "zone",
            "level",
            "stack_id",
            "stack_name",
            "level_number",
            "position_in_level",
            "parent",
            "x",
            "y",
            "width",
            "height",
            "depth",
            "rotation",
            "sort_order",
            "capacity",
            "active",
            "notes",
            "total_quantity",
            "contents",
        ]
        read_only_fields = ["code", "zone", "level", "position_in_level"]

    def get_total_quantity(self, obj):
        return obj.balances.aggregate(v=Sum("quantity"))["v"] or 0

    def get_contents(self, obj):
        rows = (
            obj.balances.filter(quantity__gt=0)
            .values("lot__variant_id", "lot__variant__product__name", "lot__variant__name")
            .annotate(quantity=Sum("quantity"), reserved=Sum("reserved"))
        )
        return list(rows)

    def create(self, data):
        # "zone" is read-only for updates, so read it from the request when creating.
        zone = Zone.objects.filter(pk=self.initial_data.get("zone"), active=True).first()
        if not zone:
            raise serializers.ValidationError({"zone": "Choose a zone in this business."})
        return create_shelf(zone=zone, user=self.context["request"].user, **data)

    def update(self, instance, data):
        return update_shelf(shelf=instance, user=self.context["request"].user, **data)


class ZoneSerializer(serializers.ModelSerializer):
    stacks = serializers.SerializerMethodField()
    unassigned_shelves = serializers.SerializerMethodField()
    shelves = ShelfSerializer(many=True, read_only=True)

    class Meta:
        model = Zone
        fields = ["id", "code", "name", "width", "height", "active", "stacks", "unassigned_shelves", "shelves"]
        read_only_fields = ["code"]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Enter the area name.")
        return value.strip()

    def validate(self, attrs):
        for field in ("width", "height"):
            if field in attrs and attrs[field] is not None and attrs[field] <= 0:
                raise serializers.ValidationError({field: "Enter a size greater than zero."})
        return attrs

    def get_stacks(self, obj):
        return ShelfStackSerializer(
            obj.stacks.filter(active=True).prefetch_related("levels__shelves__balances__lot__variant__product"), many=True
        ).data

    def get_unassigned_shelves(self, obj):
        return ShelfSerializer(obj.shelves.filter(level__isnull=True), many=True).data

    def create(self, validated_data):
        store = Store.objects.first() or Store.objects.create(name=self.context["request"].organization.name, currency=self.context["request"].organization.currency, timezone=self.context["request"].organization.timezone, measurement_unit="ft")
        base = (slugify(validated_data["name"]).replace("-", "")[:16] or "AREA").upper()
        code = base
        suffix = 2
        while Zone.objects.filter(store=store, code=code).exists():
            code = f"{base[:15]}{suffix}"
            suffix += 1
        return Zone.objects.create(store=store, code=code, **validated_data)


class ShelfLevelSerializer(serializers.ModelSerializer):
    shelves = ShelfSerializer(many=True, read_only=True)

    class Meta:
        model = ShelfLevel
        fields = ["id", "stack", "level_number", "y_position", "height", "active", "shelves"]
        read_only_fields = ["stack", "level_number"]


class ShelfStackSerializer(serializers.ModelSerializer):
    levels = ShelfLevelSerializer(many=True, read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    measurement_unit = serializers.CharField(source="zone.store.measurement_unit", read_only=True)
    categories = serializers.SerializerMethodField()
    category_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    primary_category_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = ShelfStack
        fields = [
            "id",
            "zone",
            "zone_name",
            "code",
            "display_name",
            "x",
            "y",
            "width",
            "height",
            "depth",
            "rotation",
            "number_of_levels",
            "active",
            "notes",
            "measurement_unit",
            "categories",
            "category_ids",
            "primary_category_id",
            "levels",
        ]
        read_only_fields = ["code", "number_of_levels"]

    def get_categories(self, obj):
        return [{"id": a.category_id, "name": a.category.name, "primary": a.is_primary} for a in obj.category_assignments.select_related("category").filter(category__active=True)]


class ShelfStackViewSet(viewsets.ModelViewSet):
    serializer_class = ShelfStackSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "inventory.change_shelfstack"
    queryset = ShelfStack.objects.select_related("zone__store").prefetch_related(
        "levels__shelves__balances__lot__variant__product"
    )

    def create(self, request):
        if not has_business_permission(request.user, "inventory.add_shelfstack"):
            return Response({"detail": "Rack setup permission required."}, status=403)
        zone = Zone.objects.filter(pk=request.data.get("zone"), active=True).first()
        if not zone:
            return Response({"zone": "Choose a zone in this business."}, status=400)
        with transaction.atomic():
            stack = create_shelf_stack(
                zone=zone,
                user=request.user,
                display_name=request.data.get("display_name"),
                x=request.data.get("x"),
                y=request.data.get("y"),
                width=request.data.get("width"),
                height=request.data.get("height"),
                depth=request.data.get("depth"),
                rotation=request.data.get("rotation", 0),
                notes=request.data.get("notes", ""),
                level_definitions=request.data.get("levels", []),
            )
            self._save_categories(stack, request.data.get("category_ids", []), request.data.get("primary_category_id"), allow_empty=True)
        return Response(self.get_serializer(stack).data, status=201)

    def _save_categories(self, stack, category_ids, primary_id=None, allow_empty=False):
        ids={int(value) for value in category_ids if value}
        if primary_id: ids.add(int(primary_id))
        if not ids:
            if allow_empty: return
            incompatible=StockBalance.objects.filter(shelf__level__stack=stack,quantity__gt=0).first()
            if incompatible: raise serializers.ValidationError({"category_ids":"Move existing stock before removing all rack categories."})
            ShelfStackCategory.objects.filter(stack=stack).delete()
            return
        categories=list(Category.objects.filter(pk__in=ids,active=True))
        if len(categories)!=len(ids): raise serializers.ValidationError({"category_ids":"Every assigned category must be active."})
        incompatible=StockBalance.objects.filter(shelf__level__stack=stack,quantity__gt=0).exclude(lot__variant__product__category_id__in=ids).select_related("lot__variant__product").first()
        if incompatible: raise serializers.ValidationError({"category_ids":f"Move existing stock for {incompatible.lot.variant.product.name} before removing its rack category."})
        primary=int(primary_id) if primary_id else categories[0].id
        ShelfStackCategory.objects.filter(stack=stack).exclude(category_id__in=ids).delete()
        for category in categories: ShelfStackCategory.objects.update_or_create(stack=stack,category=category,defaults={"is_primary":category.id==primary})

    def perform_update(self, serializer):
        data=dict(serializer.validated_data); ids=data.pop("category_ids",None); primary=data.pop("primary_category_id",None)
        with transaction.atomic():
            serializer.instance = update_shelf_stack(stack=serializer.instance, user=self.request.user, **data)
            if ids is not None or primary is not None: self._save_categories(serializer.instance, ids or list(ShelfStackCategory.objects.filter(stack=serializer.instance).values_list("category_id",flat=True)), primary)

    def perform_destroy(self, instance):
        archive_shelf_stack(stack=instance, user=self.request.user)


class ShelfLevelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ShelfLevelSerializer
    permission_classes = [IsInternalStaff]
    queryset = ShelfLevel.objects.select_related("stack").prefetch_related("shelves")


class ZoneViewSet(viewsets.ModelViewSet):
    permission_classes = [IsInternalStaff]
    serializer_class = ZoneSerializer
    queryset = Zone.objects.prefetch_related(
        "stacks__levels__shelves__balances__lot__variant__product", "shelves__balances__lot__variant__product"
    )

    def get_permissions(self):
        if self.action == "create":
            self.permission_required = "inventory.add_zone"
            return [HasLinTechPermission()]
        if self.action in ["update", "partial_update", "destroy"]:
            self.permission_required = "inventory.change_zone"
            return [HasLinTechPermission()]
        return [IsInternalStaff()]

    def get_queryset(self):
        # Removed areas leave the shop map; their history stays in the database.
        rows = super().get_queryset()
        return rows.filter(active=True) if self.action == "list" else rows

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        from apps.core.models import AuditLog
        zone = Zone.objects.select_for_update().get(pk=self.get_object().pk)
        racks = list(zone.stacks.filter(active=True).order_by("display_name").values_list("display_name", flat=True))
        if racks:
            return Response({"detail": f"{zone.name} still has {len(racks)} rack{'s' if len(racks) != 1 else ''}: "
                             f"{', '.join(racks)}. Remove them or move them to another area first."}, status=400)
        if StockBalance.objects.filter(shelf__zone=zone, quantity__gt=0).exists():
            return Response({"detail": f"{zone.name} still holds stock. Transfer it to another shelf first."}, status=400)
        before = {"name": zone.name, "code": zone.code}
        if not zone.stacks.exists() and not zone.shelves.exists():
            zone.delete()
        else:
            # Removed racks keep their layout history, so the area is hidden rather than erased.
            zone.active = False
            zone.save(update_fields=["active", "updated_at"])
        AuditLog.objects.create(action="AREA_REMOVED", object_type="Zone", object_id=str(before["code"]),
                                user=request.user, before=before)
        return Response(status=204)


class ShelfViewSet(viewsets.ModelViewSet):
    permission_classes = [IsInternalStaff]
    serializer_class = ShelfSerializer
    queryset = Shelf.objects.select_related("zone").prefetch_related("balances__lot__variant__product")

    def get_permissions(self):
        if self.action in ["create"]:
            self.permission_required = "inventory.add_shelf"
            return [HasLinTechPermission()]
        if self.action in ["update", "partial_update", "destroy"]:
            self.permission_required = "inventory.change_shelf"
            return [HasLinTechPermission()]
        return [IsInternalStaff()]

    def perform_destroy(self, instance):
        archive_shelf(shelf=instance, user=self.request.user)

    @__import__("rest_framework.decorators", fromlist=["action"]).action(detail=True, methods=["get"])
    def contents(self, request, pk=None):
        """Everything on one physical shelf, one row per item, with its place in the shop."""
        shelf = self.get_object()
        show_cost = has_business_permission(request.user, "accounting.view_profit")
        balances = (shelf.balances.filter(quantity__gt=0)
                    .select_related("lot__variant__product__category").order_by("lot__received_at"))
        items = {}
        for b in balances:
            variant = b.lot.variant
            row = items.setdefault(variant.pk, {
                "variant_id": variant.pk, "product_id": variant.product_id, "product": variant.product.name,
                "variant": variant.name, "sku": variant.sku, "category": variant.product.category.name,
                "image": (variant_images(variant) or [{}])[0].get("url"), "selling_price": variant.selling_price,
                "quantity": 0, "reserved": 0, "retail_value": 0, "cost_value": 0, "batches": 0, "last_received": None})
            row["quantity"] += b.quantity
            row["reserved"] += b.reserved
            row["retail_value"] += b.quantity * variant.selling_price
            row["cost_value"] += b.quantity * b.lot.unit_cost
            row["batches"] += 1
            row["last_received"] = b.lot.received_at
        rows = sorted(items.values(), key=lambda row: (row["product"].lower(), row["variant"].lower()))
        for row in rows:
            row["available"] = row["quantity"] - row["reserved"]
            if not show_cost:
                row.pop("cost_value")
        level = shelf.level
        stack = level.stack if level else None
        movements = (Movement.objects.filter(models.Q(source=shelf) | models.Q(destination=shelf))
                     .select_related("variant__product").order_by("-created_at")[:10])
        totals = {"items": len(rows), "units": sum((r["quantity"] for r in rows), 0),
                  "available": sum((r["available"] for r in rows), 0),
                  "retail_value": sum((r["retail_value"] for r in rows), 0)}
        if show_cost:
            totals["cost_value"] = sum((r["cost_value"] for r in rows), 0)
        return Response({
            "shelf": ShelfSerializer(shelf).data,
            "location": {"area": shelf.zone.name, "rack": stack.display_name if stack else None,
                         "rack_code": stack.code if stack else None, "level": level.level_number if level else None,
                         "position": shelf.position_in_level,
                         "categories": [a.category.name for a in stack.category_assignments.select_related("category")]
                         if stack else []},
            "totals": totals,
            "show_cost": show_cost,
            "items": rows,
            "recent_movements": [{
                "type": m.movement_type, "product": f"{m.variant.product.name} — {m.variant.name}",
                "quantity": m.quantity, "direction": "in" if m.destination_id == shelf.pk else "out",
                "reference": m.reference, "created_at": m.created_at,
            } for m in movements],
        })
