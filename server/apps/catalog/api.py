from django.db.models import Sum
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission, IsInternalStaff
from apps.inventory.models import Shelf, StockBalance
from apps.inventory.services import create_product_with_opening_stock
from .models import Brand, Category, PriceHistory, Product, ProductImage, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = "__all__"


class VariantSerializer(serializers.ModelSerializer):
    physical = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    reserved = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = ProductVariant
        fields = "__all__"

    def update(self, obj, data):
        old = obj.selling_price
        obj = super().update(obj, data)
        if obj.selling_price != old:
            PriceHistory.objects.create(variant=obj, price=obj.selling_price, changed_by=self.context["request"].user)
            AuditLog.objects.create(
                action="PRICE_CHANGED",
                object_type="ProductVariant",
                object_id=str(obj.pk),
                user=self.context["request"].user,
                before={"price": str(old)},
                after={"price": str(obj.selling_price)},
            )
        return obj


class ProductSerializer(serializers.ModelSerializer):
    variants = VariantSerializer(many=True, read_only=True)
    images = ImageSerializer(many=True, read_only=True)
    locations = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"

    def get_locations(self, obj):
        result = []
        for variant in obj.variants.all():
            preferred = getattr(variant, "preferred_location", None)
            balances = (
                StockBalance.objects.filter(lot__variant=variant, quantity__gt=0)
                .select_related("shelf__level__stack", "shelf__zone")
                .values(
                    "shelf_id",
                    "shelf__code",
                    "shelf__display_name",
                    "shelf__zone__name",
                    "shelf__level__level_number",
                    "shelf__level__stack__display_name",
                )
                .annotate(quantity=Sum("quantity"), reserved=Sum("reserved"))
            )
            result.append(
                {
                    "variant_id": variant.id,
                    "preferred_shelf": {
                        "id": preferred.shelf_id,
                        "code": preferred.shelf.code,
                        "display_name": preferred.shelf.display_name,
                    }
                    if preferred
                    else None,
                    "actual": [{**row, "available": row["quantity"] - row["reserved"]} for row in balances],
                }
            )
        return result


class SecuredModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsInternalStaff]

    def get_permissions(self):
        action = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(
            self.action, "view"
        )
        self.permission_required = (
            f"{self.queryset.model._meta.app_label}.{action}_{self.queryset.model._meta.model_name}"
        )
        return [HasLinTechPermission()]


class CategoryViewSet(SecuredModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class BrandViewSet(SecuredModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer


class ProductViewSet(SecuredModelViewSet):
    queryset = Product.objects.select_related("category", "brand").prefetch_related(
        "variants__preferred_location__shelf", "images"
    )
    serializer_class = ProductSerializer

    @action(detail=False, methods=["post"], url_path="create-with-stock")
    def create_with_stock(self, request):
        if not request.user.has_perm("catalog.add_product"):
            return Response({"detail": "Product creation permission required."}, status=403)
        shelf = (
            Shelf.objects.filter(pk=request.data.get("preferred_shelf_id"), active=True).first()
            if request.data.get("preferred_shelf_id")
            else None
        )
        product, variant = create_product_with_opening_stock(
            user=request.user,
            product_data={
                "name": request.data.get("name"),
                "category_id": request.data.get("category_id"),
                "brand_id": request.data.get("brand_id") or None,
                "description": request.data.get("description", ""),
                "product_type": request.data.get("product_type", "STOCK_ITEM"),
                "ecommerce_visible": request.data.get("ecommerce_visible", True),
            },
            variant_data={
                "name": request.data.get("variant_name", "Standard"),
                "sku": request.data.get("sku"),
                "barcode": request.data.get("barcode") or None,
                "selling_price": request.data.get("selling_price", 0),
                "minimum_stock": request.data.get("minimum_stock", 0),
                "target_stock": request.data.get("target_stock", 0),
            },
            preferred_shelf=shelf,
            opening_quantity=request.data.get("opening_quantity", 0),
            opening_unit_cost=request.data.get("opening_unit_cost", 0),
            opening_reference=request.data.get("opening_reference", "OPENING"),
        )
        if request.data.get("image_url"):
            ProductImage.objects.create(
                product=product,
                image_url=request.data["image_url"],
                alt_text=product.name,
            )
        return Response({"product_id": product.id, "variant_id": variant.id}, status=status.HTTP_201_CREATED)


class VariantViewSet(SecuredModelViewSet):
    queryset = ProductVariant.objects.select_related("product").all()
    serializer_class = VariantSerializer


class ImageViewSet(SecuredModelViewSet):
    queryset = ProductImage.objects.all()
    serializer_class = ImageSerializer
