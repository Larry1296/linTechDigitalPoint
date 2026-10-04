from apps.tenancy.permissions import has_business_permission, is_business_manager
from django.db.models import Sum
from django.db import transaction
from .display_images import optimise_upload, save_display_image, boolean, options, variant_images
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission, IsInternalStaff
from apps.inventory.models import Shelf, StockBalance
from apps.inventory.models import ShelfStackCategory
from apps.inventory.services import create_product_with_opening_stock
from .models import Brand, Category, PriceHistory, Product, ProductImage, ProductOptionType, ProductOptionValue, ProductVariant, ProductVariantOptionValue, check_code_free, check_price_range, category_tree, racked_categories


class CategorySerializer(serializers.ModelSerializer):
    image_pool = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    racks = serializers.SerializerMethodField()

    def get_product_count(self, obj):
        # Annotated on list/detail; freshly created or updated rows are counted directly.
        return obj.product_count if hasattr(obj, "product_count") else obj.product_set.count()

    def get_racks(self, obj):
        return sorted({a.stack.display_name for a in obj.rack_assignments.all() if a.stack.active})

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
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = "__all__"

    def get_product_count(self, obj):
        return obj.product_set.count()

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Enter the brand name.")
        duplicates = Brand.objects.filter(name__iexact=name)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("A brand with this name already exists.")
        return name


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
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not request or not has_business_permission(request.user, "accounting.view_profit"):
            for key in ("latest_bp", "average_stock_cost", "service_cost"):
                data.pop(key, None)
        return data

    display_image = serializers.ImageField(write_only=True, required=False)
    images = serializers.SerializerMethodField()

    def get_images(self, obj):
        return variant_images(obj)

    def validate(self, attrs):
        upload = optimise_upload(attrs.get("display_image"))
        if upload:
            attrs["display_image"] = upload
        check_price_range(attrs.get("selling_price", getattr(self.instance, "selling_price", 0)),
                          attrs.get("minimum_price", getattr(self.instance, "minimum_price", 0)))
        if "sku" in attrs or "barcode" in attrs:
            check_code_free(attrs.get("sku"), attrs.get("barcode"), exclude_pk=getattr(self.instance, "pk", None))
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
        lot=StockLot.objects.filter(variant=obj,pk__in=StockBalance.objects.values("lot_id")).order_by("-received_at","-id").first()
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
        # A service holds no stock, so an item with stock on hand stays a stock item until that stock is sold or adjusted out.
        if (self.instance and attrs.get("product_type") == Product.SERVICE and self.instance.product_type != Product.SERVICE
                and StockBalance.objects.filter(lot__variant__product=self.instance, quantity__gt=0).exists()):
            raise serializers.ValidationError({"product_type": "This product still has stock on hand. Sell or adjust that stock out before making it a service."})
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
    brand_name = serializers.CharField(source="brand.name", read_only=True, default="")

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

    def get_queryset(self):
        from django.db.models import Count, Prefetch
        from .models import service_category_ids
        # Service groups belong to the Cyber pages, not the product categories.
        return super().get_queryset().exclude(id__in=service_category_ids()).annotate(product_count=Count("product", distinct=True)).prefetch_related(
            Prefetch("rack_assignments", queryset=ShelfStackCategory.objects.select_related("stack")))

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """A new category, optionally put straight onto a rack (rack_id) so products can be stocked in it at once,
        e.g. when it is created from the product form. Choosing the rack needs the Shelf management permission."""
        from apps.inventory.models import ShelfStack
        rack_id = request.data.get("rack_id")
        stack = None
        if rack_id not in (None, ""):
            if not has_business_permission(request.user, "inventory.change_shelfstack"):
                return Response({"rack_id": "Putting a category on a rack needs the Shelf management permission. Ask a manager."}, status=403)
            stack = ShelfStack.objects.filter(pk=rack_id if str(rack_id).isdigit() else None, active=True, zone__active=True).first()
            if stack is None:
                return Response({"rack_id": "Choose an active rack."}, status=400)
        response = super().create(request, *args, **kwargs)
        category_id = response.data["id"]
        AuditLog.objects.create(action="CATEGORY_CREATED", object_type="Category", object_id=str(category_id), user=request.user,
                                after={"name": response.data["name"], "parent": response.data.get("parent"), "rack": stack.display_name if stack else None})
        if stack:
            ShelfStackCategory.objects.get_or_create(stack=stack, category_id=category_id, defaults={"is_primary": False})
            AuditLog.objects.create(action="RACK_CATEGORY_ASSIGNED", object_type="ShelfStack", object_id=str(stack.pk), user=request.user,
                                    after={"category": response.data["name"], "rack": stack.display_name})
            response.data["racks"] = [stack.display_name]
        return response

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        products = Product.objects.filter(category=category).count()
        children = Category.objects.filter(parent=category).count()
        blockers = [text for count, text in [(products, f"{products} product{'s' if products != 1 else ''}"),
                    (children, f"{children} subcategor{'ies' if children != 1 else 'y'}")] if count]
        if blockers:
            return Response({"detail": f"{category.name} still has {' and '.join(blockers)}. Move them to another "
                             "category first, or edit this category and untick Active to hide it."}, status=400)
        # Rack assignments only label where the category is shelved; they go with it.
        racks = list(ShelfStackCategory.objects.filter(category=category).values_list("stack__display_name", flat=True))
        ShelfStackCategory.objects.filter(category=category).delete()
        AuditLog.objects.create(action="CATEGORY_DELETED", object_type="Category", object_id=str(category.pk),
                                user=request.user, before={"name": category.name, "racks": racks})
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BrandViewSet(SecuredModelViewSet):
    queryset = Brand.objects.all().order_by("name")
    serializer_class = BrandSerializer

    def destroy(self, request, *args, **kwargs):
        brand = self.get_object()
        count = brand.product_set.count()
        if count:
            return Response({"detail": f"{brand.name} is used by {count} product{'s' if count != 1 else ''}. "
                             "Change those products' brand first, or edit this brand and untick Active to hide it."}, status=400)
        AuditLog.objects.create(action="BRAND_DELETED", object_type="Brand", object_id=str(brand.pk), user=request.user, before={"name": brand.name})
        brand.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductViewSet(SecuredModelViewSet):
    queryset = Product.objects.select_related("category", "brand").prefetch_related(
        "variants__preferred_location__shelf", "images"
    )
    serializer_class = ProductSerializer

    def get_queryset(self):
        # Cyber services (with their price options, groups and price rules) are managed on the Cyber pages, not as products.
        return super().get_queryset().exclude(variants__cyber_profile__isnull=False)

    def destroy(self, request, *args, **kwargs):
        from apps.inventory.services import delete_unused_product
        delete_unused_product(self.get_object(), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _selected(self, request):
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids or len(ids) > 200:
            raise serializers.ValidationError({"ids": "Choose between 1 and 200 products."})
        products = list(self.get_queryset().filter(pk__in=ids))
        if len(products) != len(set(ids)):
            raise serializers.ValidationError({"ids": "Some of these products no longer exist."})
        return products

    @action(detail=False, methods=["post"], url_path="delete-check")
    def delete_check(self, request):
        """For each selected product: can it be permanently removed, and why not; how much stock it still has."""
        from django.db.models import Sum
        from apps.inventory.models import StockBalance
        from apps.inventory.services import product_history
        rows = []
        for product in self._selected(request):
            reason = product_history(product)
            rows.append({"id": product.pk, "name": product.name, "active": product.active, "can_remove": not reason, "reason": reason,
                         "on_shelf": StockBalance.objects.filter(lot__variant__product=product).aggregate(q=Sum("quantity"))["q"] or 0})
        return Response(rows)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    @transaction.atomic
    def bulk_delete(self, request):
        """mode "hide": hidden everywhere, records kept. mode "remove": erased completely, only for products with no
        sales or deliveries; with hide_rest, the others are hidden instead of refusing the whole request."""
        from apps.inventory.services import delete_unused_product, product_history
        mode = request.data.get("mode")
        if mode not in {"hide", "remove"}:
            raise serializers.ValidationError({"mode": "Choose whether to keep the records or remove permanently."})
        needed = "catalog.delete_product" if mode == "remove" else "catalog.change_product"
        if not has_business_permission(request.user, needed):
            return Response({"detail": "You don't have permission to delete products."}, status=403)
        products = self._selected(request)
        blocked = {p.pk: product_history(p) for p in products} if mode == "remove" else {}
        if mode == "remove" and any(blocked.values()) and not request.data.get("hide_rest"):
            names = "; ".join(f"{p.name}: {blocked[p.pk]}" for p in products if blocked[p.pk])
            raise serializers.ValidationError({"ids": f"These can only be hidden, because their records must be kept: {names}."})
        results = []
        for product in products:
            if mode == "remove" and not blocked[product.pk]:
                results.append({"id": product.pk, "name": product.name, "result": "removed"})
                delete_unused_product(product, request.user)
            else:
                Product.objects.filter(pk=product.pk).update(active=False)
                AuditLog.objects.create(action="PRODUCT_HIDDEN", object_type="Product", object_id=str(product.pk), user=request.user,
                                        after={"name": product.name, "reason": "Deleted, records kept"})
                results.append({"id": product.pk, "name": product.name, "result": "hidden"})
        return Response(results)

    @action(detail=True, methods=["get"])
    def overview(self, request, pk=None):
        from .overview import product_overview
        return Response(product_overview(self.get_object(), has_business_permission(request.user, "accounting.view_profit")))

    @action(detail=True, methods=["get"], url_path="can-delete")
    def can_delete(self, request, pk=None):
        from apps.inventory.services import product_history
        reason = product_history(self.get_object())
        return Response({"can_delete": not reason, "reason": reason})

    def list(self, request, *args, **kwargs):
        # Opt-in bounded browsing preserves existing internal clients.
        if "page" not in request.query_params:
            return super().list(request, *args, **kwargs)
        from rest_framework.pagination import PageNumberPagination
        paginator = PageNumberPagination()
        paginator.page_size = 50  # a longer list keeps categories together on one page
        # Products follow the category tree: each parent, then its sub-categories, then by name.
        from django.db.models import Case, IntegerField, Value, When
        order = [row["id"] for row in category_tree()]
        position = Case(*[When(category_id=pk, then=Value(i)) for i, pk in enumerate(order)],
                        default=Value(len(order)), output_field=IntegerField()) if order else Value(0)
        # Browsing one category shows only the products filed directly in it; "other" is products whose category is hidden.
        queryset = self.get_queryset()
        category = request.query_params.get("category", "")
        if category == "other":
            queryset = queryset.exclude(category__active=True)
        elif category:
            if not category.isdigit():
                raise serializers.ValidationError({"category": "Choose a category."})
            queryset = queryset.filter(category_id=category)
        rows = paginator.paginate_queryset(queryset.annotate(tree_position=position)
                                           .order_by("tree_position", "category__name", "name", "id"), request)
        return paginator.get_paginated_response(self.get_serializer(rows, many=True).data)

    @action(detail=False, methods=["get"], url_path="category-counts")
    def category_counts(self, request):
        """How many products are filed directly in each active category (the page adds up sub-categories itself),
        and how many sit in hidden categories."""
        from django.db.models import Count
        active = {row["id"] for row in category_tree()}
        counts = self.get_queryset().order_by().values("category_id").annotate(total=Count("id"))
        return Response({"categories": {str(row["category_id"]): row["total"] for row in counts if row["category_id"] in active},
                         "other": sum(row["total"] for row in counts if row["category_id"] not in active)})

    @action(detail=False, methods=["get"], url_path="search-suggestions")
    def search_suggestions(self, request):
        from .search import search_variants, variant_summary
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response([])
        rows = search_variants(ProductVariant.objects.select_related("product__category").exclude(product__variants__cyber_profile__isnull=False), query)[:30]
        return Response([variant_summary(v) for v in rows])

    @action(detail=False, methods=["post"], url_path="create-with-stock")
    @transaction.atomic
    def create_with_stock(self, request):
        if not has_business_permission(request.user, "catalog.add_product"):
            return Response({"detail": "Product creation permission required."}, status=403)
        upload = optimise_upload(request.FILES.get("display_image"))
        visible = boolean(request.data, "ecommerce_visible")
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
                "minimum_price": request.data.get("minimum_price") or 0,
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

    @action(detail=False, methods=["get"], url_path="import-template")
    def import_template(self, request):
        """The Excel sheet for adding many products, with this business's categories, brands and shelves."""
        from django.http import HttpResponse
        from .import_template import build_template
        if not has_business_permission(request.user, "catalog.add_product"):
            return Response({"detail": "Product creation permission required."}, status=403)
        response = HttpResponse(build_template(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="products-template.xlsx"'
        return response

    @action(detail=False, methods=["post"], url_path="import")
    def import_products(self, request):
        """Checks a product spreadsheet; with commit=true, saves it (all rows or none).
        rack_choices (JSON {category path: rack id}) assigns categories to racks the reviewer chose."""
        import json
        from .product_import import import_products
        if not has_business_permission(request.user, "catalog.add_product"):
            return Response({"detail": "Product creation permission required."}, status=403)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"file": "Choose the completed .xlsx template."}, status=400)
        try:
            choices = json.loads(request.data.get("rack_choices") or "{}")
        except ValueError:
            choices = None
        if not isinstance(choices, dict):
            return Response({"rack_choices": "Send rack choices as {category path: rack id}."}, status=400)
        result = import_products(upload, request.user, commit=boolean(request.data, "commit", default=False), rack_choices=choices)
        return Response(result, status=201 if result.get("reference") else 200)

    @action(detail=False, methods=["post"], url_path="create-inline")
    @transaction.atomic
    def create_inline(self, request):
        if not has_business_permission(request.user, "catalog.add_product") or not has_business_permission(request.user, "catalog.add_productvariant"):
            return Response({"detail":"Product creation permission required."},status=403)
        data=request.data
        upload = optimise_upload(request.FILES.get("display_image"))
        visible = boolean(data, "ecommerce_visible")
        try:
            category=Category.objects.get(pk=data.get("category_id"),active=True)
            if category.id not in {c.id for c,_,_ in racked_categories()}:
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
            check_price_range(data.get("selling_price", 0), data.get("minimum_price") or 0)
            check_code_free(data.get("sku"), data.get("barcode") or None)
            display_name=data.get("variant_name") or " — ".join(str(item.get("value")).strip() for item in option_values if item.get("value")) or "Standard"
            variant=ProductVariant.objects.create(product=product,name=display_name,sku=data["sku"],barcode=data.get("barcode") or None,selling_price=data.get("selling_price",0),minimum_price=data.get("minimum_price") or 0,minimum_stock=data.get("minimum_stock",0),target_stock=data.get("target_stock",0))
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
        if not has_business_permission(request.user, "catalog.add_productvariant"): return Response({"detail":"Variant creation permission required."},status=403)
        product=self.get_object(); option_values=options(request.data)
        upload = optimise_upload(request.FILES.get("display_image"))
        reuse = boolean(request.data, "use_product_image")
        signature=sorted((str(item.get("type","")).strip().lower(),str(item.get("value","")).strip().lower()) for item in option_values)
        for existing in product.variants.all():
            old=sorted((a.value.option_type.name.lower(),a.value.value.lower()) for a in existing.option_assignments.select_related("value__option_type"))
            if signature and old==signature: return Response({"detail":"This variant option combination already exists."},status=400)
        check_price_range(request.data.get("selling_price", 0), request.data.get("minimum_price") or 0)
        variant=ProductVariant.objects.create(product=product,use_product_image=reuse,name=request.data.get("variant_name") or " — ".join(str(item.get("value")) for item in option_values) or "Standard",sku=request.data.get("sku"),barcode=request.data.get("barcode") or None,selling_price=request.data.get("selling_price",0),minimum_price=request.data.get("minimum_price") or 0,minimum_stock=request.data.get("minimum_stock",0),target_stock=request.data.get("target_stock",0))
        for item in option_values:
            option_type,_=ProductOptionType.objects.get_or_create(product=product,name=str(item.get("type","")).strip()); value,_=ProductOptionValue.objects.get_or_create(option_type=option_type,value=str(item.get("value","")).strip()); ProductVariantOptionValue.objects.create(variant=variant,value=value)
        if upload:
            save_display_image(product, upload, variant)
        return Response(VariantSerializer(variant,context={"request":request}).data,status=201)

    @action(detail=True, methods=["post"], url_path="display-image")
    @transaction.atomic
    def display_image(self, request, pk=None):
        if not has_business_permission(request.user, "catalog.change_product"):
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
