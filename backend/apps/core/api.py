from django.db.models import F,Sum
from rest_framework import permissions,serializers,viewsets
from apps.catalog.models import ProductVariant
from apps.inventory.models import Shelf,StockBalance,Zone
from apps.inventory.services import archive_shelf,create_shelf,update_shelf
from .permissions import HasLinTechPermission,IsInternalStaff
class PublicVariantSerializer(serializers.ModelSerializer):
    product_name=serializers.CharField(source="product.name");slug=serializers.CharField(source="product.slug");description=serializers.CharField(source="product.description");category=serializers.CharField(source="product.category.name");brand=serializers.CharField(source="product.brand.name",allow_null=True);images=serializers.SerializerMethodField();available=serializers.SerializerMethodField()
    class Meta:model=ProductVariant;fields=["id","product_name","slug","description","category","brand","images","name","sku","barcode","selling_price","available"]
    def get_images(self,obj):return [{"url":x.image_url,"alt":x.alt_text} for x in obj.product.images.all()]
    def get_available(self,obj):
        if obj.product.product_type=="SERVICE":return None
        return StockBalance.objects.filter(lot__variant=obj).aggregate(v=Sum(F("quantity")-F("reserved")))["v"] or 0
class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes=[permissions.AllowAny];serializer_class=PublicVariantSerializer
    queryset=ProductVariant.objects.select_related("product","product__category","product__brand").prefetch_related("product__images").filter(active=True,product__active=True,product__ecommerce_visible=True)
    filterset_fields=["product__category","product__brand"];search_fields=["product__name","product__description","name","sku","barcode"]
class ShelfSerializer(serializers.ModelSerializer):
    total_quantity=serializers.SerializerMethodField();contents=serializers.SerializerMethodField()
    class Meta:model=Shelf;fields=["id","code","display_name","zone","parent","x","y","width","height","depth","rotation","sort_order","capacity","active","notes","total_quantity","contents"];read_only_fields=["code"]
    def get_total_quantity(self,obj):return obj.balances.aggregate(v=Sum("quantity"))["v"] or 0
    def get_contents(self,obj):
        rows=obj.balances.filter(quantity__gt=0).values("lot__variant_id","lot__variant__product__name","lot__variant__name").annotate(quantity=Sum("quantity"))
        return list(rows)
    def create(self,data):return create_shelf(user=self.context["request"].user,**data)
    def update(self,instance,data):return update_shelf(shelf=instance,user=self.context["request"].user,**data)
class ZoneSerializer(serializers.ModelSerializer):
    shelves=ShelfSerializer(many=True,read_only=True)
    class Meta:model=Zone;fields=["id","code","name","width","height","active","shelves"]
class ZoneViewSet(viewsets.ModelViewSet):
    permission_classes=[IsInternalStaff];serializer_class=ZoneSerializer;queryset=Zone.objects.prefetch_related("shelves__balances__lot__variant__product")
    def get_permissions(self):
        if self.action in ["create","update","partial_update","destroy"]:self.permission_required="inventory.change_zone";return [HasLinTechPermission()]
        return [IsInternalStaff()]
class ShelfViewSet(viewsets.ModelViewSet):
    permission_classes=[IsInternalStaff];serializer_class=ShelfSerializer;queryset=Shelf.objects.select_related("zone").prefetch_related("balances__lot__variant__product")
    def get_permissions(self):
        if self.action in ["create"]:self.permission_required="inventory.add_shelf";return [HasLinTechPermission()]
        if self.action in ["update","partial_update","destroy"]:self.permission_required="inventory.change_shelf";return [HasLinTechPermission()]
        return [IsInternalStaff()]
    def perform_destroy(self,instance):archive_shelf(shelf=instance,user=self.request.user)
