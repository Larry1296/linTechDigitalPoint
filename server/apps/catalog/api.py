from django.db.models import Sum
from django.db import transaction
from .display_images import optimise_upload, photo_required, save_display_image, boolean, options, variant_images
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission, IsInternalStaff
from apps.inventory.models import Shelf, StockBalance
from apps.inventory.models import ShelfStackCategory
from apps.inventory.services import create_product_with_opening_stock
from .models import Brand, Category, PriceHistory, Product, ProductImage, ProductOptionType, ProductOptionValue, ProductVariant, ProductVariantOptionValue


class CategorySerializer(serializers.ModelSerializer):
    image_pool = serializers.SerializerMethodField()

    def get_image_pool(self, obj):
        from .image_library import image_choices
        return image_choices(obj)

    class Meta:
        model = Category
        fields = "__all__"
        read_only_fields = ("slug",)

    def validate(self, attrs):
        name = attrs.get("name", self.instance.name if self.instance else "").strip()
        parent = attrs.get("parent", self.instance.parent if self.instance else None)
        if not name:
            raise serializers.ValidationError({"name": "Enter a category name."})
        duplicates = Category.objects.filter(name__iexact=name, parent=parent)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError({"name": "A category with this name already exists under the selected parent."})
        ancestor, seen = parent, set()
        while ancestor:
            if ancestor.pk in seen or (self.instance and ancestor.pk == self.instance.pk):
                raise serializers.ValidationError({"parent": "A category cannot be its own ancestor."})
            seen.add(ancestor.pk)
            ancestor = ancestor.parent
        attrs["name"] = name
        return attrs

    def create(self, validated_data):
        name=validated_data["name"].strip()
        parent=validated_data.get("parent")
        if Category.objects.filter(name__iexact=name,parent=parent).exists():
            raise serializers.ValidationError({"name":"A category with this name already exists under the selected parent."})
        base=slugify(name) or "category"; slug=base; suffix=2
        while Category.objects.filter(slug=slug).exists():slug=f"{base}-{suffix}";suffix+=1
        validated_data["name"]=name;validated_data["slug"]=slug
        return super().create(validated_data)


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class ImageSerializer(serializers.ModelSerializer):
    def validate_file(self, value):
        return optimise_upload(value)

    def validate(self, attrs):
        product = attrs.get("product", self.instance.product if self.instance else None)
        variant = attrs.get("variant", self.instance.variant if self.instance else None)
        if variant and variant.product_id != product.pk:
            raise serializers.ValidationError({"variant": "Choose a variant of this product."})
        return attrs

    class Meta:
        model = ProductImage
        fields = "__all__"


class VariantSerializer(serializers.ModelSerializer):
    display_image = serializers.ImageField(write_only=True, required=False)
    images = serializers.SerializerMethodField()

    def get_images(self, obj):
        return variant_images(obj)

    def validate(self, attrs):
        upload = optimise_upload(attrs.get("display_image"))
        if upload:
            attrs["display_image"] = upload
        if not self.instance:
            product = attrs["product"]
            photo_required(product.ecommerce_visible, upload, product, attrs.get("use_product_image", True))
        return attrs

    @transaction.atomic
    def create(self, data):
        upload = data.pop("display_image", None)
        variant = super().create(data)
        if upload:
            save_display_image(variant.product, upload, variant)
        return variant

    physical = serializers.SerializerMethodField()
    reserved = serializers.SerializerMethodField()
    available = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_type = serializers.CharField(source="product.product_type", read_only=True)
    option_values = serializers.SerializerMethodField()
    latest_bp = serializers.SerializerMethodField()
    average_stock_cost = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = "__all__"

    def get_option_values(self, obj):
        return [{"type": assignment.value.option_type.name, "value": assignment.value.value} for assignment in obj.option_assignments.select_related("value__option_type")]

    def get_latest_bp(self, obj):
        from apps.inventory.models import StockLot
        lot=StockLot.objects.filter(variant=obj).order_by("-received_at","-id").first()
        return lot.unit_cost if lot else None

    def get_physical(self, obj):
        from apps.inventory.models import StockBalance
        return StockBalance.objects.filter(lot__variant=obj).aggregate(value=Sum("quantity"))["value"] or 0

    def get_reserved(self, obj):
        from apps.inventory.models import StockBalance
        return StockBalance.objects.filter(lot__variant=obj).aggregate(value=Sum("reserved"))["value"] or 0

    def get_available(self, obj): return self.get_physical(obj)-self.get_reserved(obj)

    def get_average_stock_cost(self, obj):
        from apps.inventory.models import StockBalance
        rows=StockBalance.objects.filter(lot__variant=obj,quantity__gt=0).values("quantity","lot__unit_cost")
        quantity=sum((row["quantity"] for row in rows),0)
        return (sum((row["quantity"]*row["lot__unit_cost"] for row in rows),0)/quantity) if quantity else None

    @transaction.atomic
    def update(self, obj, data):
        upload = data.pop("display_image", None)
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
        if upload:
            save_display_image(obj.product, upload, obj)
        return obj


class ProductSerializer(serializers.ModelSerializer):
    display_image = serializers.ImageField(write_only=True, required=False)

    def validate(self, attrs):
        upload = optimise_upload(attrs.get("display_image"))
        if upload:
            attrs["display_image"] = upload
        if not self.instance or attrs.get("ecommerce_visible"):
            photo_required(attrs.get("ecommerce_visible", True), upload, self.instance)
        return attrs

    @transaction.atomic
    def create(self, data):
        upload = data.pop("display_image", None)
        product = super().create(data)
        if upload:
            save_display_image(product, upload)
        return product

    @transaction.atomic
    def update(self, product, data):
        upload = data.pop("display_image", None)
        product = super().update(product, data)
        if upload:
            save_display_image(product, upload)
        return product

    variants = VariantSerializer(many=True, read_only=True)
    images = ImageSerializer(many=True, read_only=True)
    locations = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)

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
    @transaction.atomic
    def create_with_stock(self, request):
        if not request.user.has_perm("catalog.add_product"):
            return Response({"detail": "Product creation permission required."}, status=403)
        upload = optimise_upload(request.FILES.get("display_image"))
        visible = boolean(request.data, "ecommerce_visible")
        photo_required(visible, upload)
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
                "ecommerce_visible": visible,
                "online_orderable": boolean(request.data, "online_orderable"),
            },
            variant_data={
                "name": request.data.get("variant_name", "Standard"),
                "sku": request.data.get("sku"),
                "barcode": request.data.get("barcode") or None,
                "selling_price": request.data.get("selling_price", 0),
                "service_cost": request.data.get("service_cost", 0),
                "minimum_stock": request.data.get("minimum_stock", 0),
                "target_stock": request.data.get("target_stock", 0),
            },
            preferred_shelf=shelf,
            opening_quantity=request.data.get("opening_quantity", 0),
            opening_unit_cost=request.data.get("opening_unit_cost", 0),
            opening_reference=request.data.get("opening_reference", "OPENING"),
        )
        if upload:
            save_display_image(product, upload)
        return Response({"product_id": product.id, "variant_id": variant.id}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="create-inline")
    @transaction.atomic
    def create_inline(self, request):
        if not request.user.has_perm("catalog.add_product") or not request.user.has_perm("catalog.add_productvariant"):
            return Response({"detail":"Product creation permission required."},status=403)
        data=request.data
        upload = optimise_upload(request.FILES.get("display_image"))
        visible = boolean(data, "ecommerce_visible")
        photo_required(visible, upload)
        try:
            category=Category.objects.get(pk=data.get("category_id"),active=True)
            if not ShelfStackCategory.objects.filter(category=category,stack__active=True).exists():
                raise serializers.ValidationError({"category_id":"Choose a category assigned to an active rack."})
            name=str(data.get("name","")).strip()
            if not name or not data.get("sku"):raise serializers.ValidationError({"name":"Name and SKU are required."})
            base=slugify(name) or "product"; slug=base; suffix=2
            while Product.objects.filter(slug=slug).exists():slug=f"{base}-{suffix}";suffix+=1
            product=Product.objects.create(name=name,slug=slug,category=category,brand_id=data.get("brand_id") or None,description=data.get("description","") or "",product_type="STOCK_ITEM",ecommerce_visible=visible,online_orderable=boolean(data,"online_orderable"))
            option_values=options(data)
            signature=sorted((str(item.get("type","")).strip().lower(),str(item.get("value","")).strip().lower()) for item in option_values)
            for existing in ProductVariant.objects.filter(product=product):
                if sorted((a.value.option_type.name.lower(),a.value.value.lower()) for a in existing.option_assignments.select_related("value__option_type"))==signature and signature: raise serializers.ValidationError({"option_values":"This variant option combination already exists."})
            display_name=data.get("variant_name") or " — ".join(str(item.get("value")).strip() for item in option_values if item.get("value")) or "Standard"
            variant=ProductVariant.objects.create(product=product,name=display_name,sku=data["sku"],barcode=data.get("barcode") or None,selling_price=data.get("selling_price",0),minimum_stock=data.get("minimum_stock",0),target_stock=data.get("target_stock",0))
            for item in option_values:
                option_type, _ = ProductOptionType.objects.get_or_create(product=product,name=str(item.get("type","")).strip())
                value, _ = ProductOptionValue.objects.get_or_create(option_type=option_type,value=str(item.get("value","")).strip())
                ProductVariantOptionValue.objects.create(variant=variant,value=value)
        except (Category.DoesNotExist, serializers.ValidationError) as exc:
            raise serializers.ValidationError(getattr(exc,"detail",{"category_id":"Choose an active category."}))
        if upload:
            save_display_image(product, upload)
        return Response({"product_id":product.id,"variant_id":variant.id},status=201)

    @action(detail=True, methods=["post"], url_path="variants")
    @transaction.atomic
    def add_variant(self, request, pk=None):
        if not request.user.has_perm("catalog.add_productvariant"): return Response({"detail":"Variant creation permission required."},status=403)
        product=self.get_object(); option_values=options(request.data)
        upload = optimise_upload(request.FILES.get("display_image"))
        reuse = boolean(request.data, "use_product_image")
        photo_required(product.ecommerce_visible, upload, product, reuse)
        signature=sorted((str(item.get("type","")).strip().lower(),str(item.get("value","")).strip().lower()) for item in option_values)
        for existing in product.variants.all():
            old=sorted((a.value.option_type.name.lower(),a.value.value.lower()) for a in existing.option_assignments.select_related("value__option_type"))
            if signature and old==signature: return Response({"detail":"This variant option combination already exists."},status=400)
        variant=ProductVariant.objects.create(product=product,use_product_image=reuse,name=request.data.get("variant_name") or " — ".join(str(item.get("value")) for item in option_values) or "Standard",sku=request.data.get("sku"),barcode=request.data.get("barcode") or None,selling_price=request.data.get("selling_price",0),minimum_stock=request.data.get("minimum_stock",0),target_stock=request.data.get("target_stock",0))
        for item in option_values:
            option_type,_=ProductOptionType.objects.get_or_create(product=product,name=str(item.get("type","")).strip()); value,_=ProductOptionValue.objects.get_or_create(option_type=option_type,value=str(item.get("value","")).strip()); ProductVariantOptionValue.objects.create(variant=variant,value=value)
        if upload:
            save_display_image(product, upload, variant)
        return Response(VariantSerializer(variant,context={"request":request}).data,status=201)

    @action(detail=True, methods=["post"], url_path="display-image")
    @transaction.atomic
    def display_image(self, request, pk=None):
        if not request.user.has_perm("catalog.change_product"):
            return Response({"detail": "Product editing permission required."}, status=403)
        product = self.get_object()
        variant = None
        if request.data.get("variant_id"):
            variant = product.variants.filter(pk=request.data["variant_id"]).first()
            if not variant:
                raise serializers.ValidationError({"variant_id": "Choose a variant of this product."})
        upload = optimise_upload(request.FILES.get("display_image"))
        reuse = boolean(request.data, "use_product_image", False)
        if upload:
            image = save_display_image(product, upload, variant)
        elif variant and reuse:
            photo_required(True, None, product, True)
            variant.display_images.all().delete()
            image = None
        else:
            raise serializers.ValidationError({"display_image": "Choose a product photograph to upload."})
        if variant:
            variant.use_product_image = reuse
            variant.save(update_fields=["use_product_image", "updated_at"])
        return Response(ImageSerializer(image, context={"request": request}).data if image else {"reusing_product_image": True})


class VariantViewSet(SecuredModelViewSet):
    queryset = ProductVariant.objects.select_related("product").all()
    serializer_class = VariantSerializer


class ImageViewSet(SecuredModelViewSet):
    queryset = ProductImage.objects.all()
    serializer_class = ImageSerializer

    def perform_create(self, serializer):
        from .image_library import PREFIX
        image = serializer.save()
        image.product.images.filter(image_url__startswith=PREFIX).exclude(pk=image.pk).delete()
