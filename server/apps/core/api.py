from django.db import models
from django.db.models import F,Sum
from rest_framework import permissions,serializers,viewsets
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from apps.catalog.models import Category,ProductVariant
from apps.core.models import Store
from apps.inventory.models import Movement,Shelf,ShelfLevel,ShelfStack,StockBalance,Zone
from apps.inventory.services import archive_shelf,archive_shelf_stack,create_shelf,create_shelf_stack,update_shelf,update_shelf_stack
from .permissions import HasLinTechPermission,IsInternalStaff
class PublicVariantSerializer(serializers.ModelSerializer):
    product_name=serializers.CharField(source="product.name");slug=serializers.CharField(source="product.slug");description=serializers.CharField(source="product.description");category=serializers.CharField(source="product.category.name");brand=serializers.CharField(source="product.brand.name",allow_null=True);images=serializers.SerializerMethodField();available=serializers.SerializerMethodField()
    class Meta:model=ProductVariant;fields=["id","product_name","slug","description","category","brand","images","name","selling_price","available"]
    def get_images(self,obj):return [{"url":x.image_url,"alt":x.alt_text} for x in obj.product.images.all()]
    def get_available(self,obj):
        if obj.product.product_type=="SERVICE":return None
        return StockBalance.objects.filter(lot__variant=obj).aggregate(v=Sum(F("quantity")-F("reserved")))["v"] or 0
class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes=[permissions.AllowAny];serializer_class=PublicVariantSerializer
    queryset=ProductVariant.objects.select_related("product","product__category","product__brand").prefetch_related("product__images").filter(active=True,product__active=True,product__ecommerce_visible=True)
    filterset_fields=["product__category","product__brand"];search_fields=["product__name","product__description","name","sku","barcode"]
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_home(request):
    categories=list(Category.objects.filter(active=True).values("id","name","slug","parent_id").order_by("name"))
    store=Store.objects.first();store_data={"name":store.name,"phone":store.phone,"email":store.email,"address":store.address} if store else {"name":"LinTech Digital Point","phone":"","email":"","address":""}
    products=PublicVariantSerializer(PublicProductViewSet.queryset[:8],many=True).data
    services=PublicVariantSerializer(PublicProductViewSet.queryset.filter(product__product_type="SERVICE")[:6],many=True).data
    return Response({"store":store_data,"categories":categories,"featured_products":products,"services":services})
class ShelfSerializer(serializers.ModelSerializer):
    total_quantity=serializers.SerializerMethodField();contents=serializers.SerializerMethodField()
    stack_id=serializers.IntegerField(source="level.stack_id",read_only=True);stack_name=serializers.CharField(source="level.stack.display_name",read_only=True);level_number=serializers.IntegerField(source="level.level_number",read_only=True)
    class Meta:model=Shelf;fields=["id","code","physical_label","display_name","zone","level","stack_id","stack_name","level_number","position_in_level","parent","x","y","width","height","depth","rotation","sort_order","capacity","active","notes","total_quantity","contents"];read_only_fields=["code","zone","level","position_in_level"]
    def get_total_quantity(self,obj):return obj.balances.aggregate(v=Sum("quantity"))["v"] or 0
    def get_contents(self,obj):
        rows=obj.balances.filter(quantity__gt=0).values("lot__variant_id","lot__variant__product__name","lot__variant__name").annotate(quantity=Sum("quantity"),reserved=Sum("reserved"))
        return list(rows)
    def create(self,data):return create_shelf(user=self.context["request"].user,**data)
    def update(self,instance,data):return update_shelf(shelf=instance,user=self.context["request"].user,**data)
class ZoneSerializer(serializers.ModelSerializer):
    stacks=serializers.SerializerMethodField();unassigned_shelves=serializers.SerializerMethodField();shelves=ShelfSerializer(many=True,read_only=True)
    class Meta:model=Zone;fields=["id","code","name","width","height","active","stacks","unassigned_shelves","shelves"]
    def get_stacks(self,obj):return ShelfStackSerializer(obj.stacks.prefetch_related("levels__shelves__balances__lot__variant__product"),many=True).data
    def get_unassigned_shelves(self,obj):return ShelfSerializer(obj.shelves.filter(level__isnull=True),many=True).data
class ShelfLevelSerializer(serializers.ModelSerializer):
    shelves=ShelfSerializer(many=True,read_only=True)
    class Meta:model=ShelfLevel;fields=["id","stack","level_number","y_position","height","active","shelves"];read_only_fields=["stack","level_number"]
class ShelfStackSerializer(serializers.ModelSerializer):
    levels=ShelfLevelSerializer(many=True,read_only=True);zone_name=serializers.CharField(source="zone.name",read_only=True);measurement_unit=serializers.CharField(source="zone.store.measurement_unit",read_only=True)
    class Meta:model=ShelfStack;fields=["id","zone","zone_name","code","display_name","x","y","width","height","depth","rotation","number_of_levels","active","notes","measurement_unit","levels"];read_only_fields=["code","number_of_levels"]
class ShelfStackViewSet(viewsets.ModelViewSet):
    serializer_class=ShelfStackSerializer;permission_classes=[HasLinTechPermission];permission_required="inventory.change_shelfstack";queryset=ShelfStack.objects.select_related("zone__store").prefetch_related("levels__shelves__balances__lot__variant__product")
    def create(self,request):
        if not request.user.has_perm("inventory.add_shelfstack"):return Response({"detail":"Shelf-stack configuration permission required."},status=403)
        zone=Zone.objects.get(pk=request.data.get("zone"));stack=create_shelf_stack(zone=zone,user=request.user,display_name=request.data.get("display_name"),x=request.data.get("x"),y=request.data.get("y"),width=request.data.get("width"),height=request.data.get("height"),depth=request.data.get("depth"),rotation=request.data.get("rotation",0),notes=request.data.get("notes",""),level_definitions=request.data.get("levels",[]));return Response(self.get_serializer(stack).data,status=201)
    def perform_update(self,serializer):serializer.instance=update_shelf_stack(stack=serializer.instance,user=self.request.user,**serializer.validated_data)
    def perform_destroy(self,instance):archive_shelf_stack(stack=instance,user=self.request.user)
class ShelfLevelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class=ShelfLevelSerializer;permission_classes=[IsInternalStaff];queryset=ShelfLevel.objects.select_related("stack").prefetch_related("shelves")
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
    @__import__("rest_framework.decorators",fromlist=["action"]).action(detail=True,methods=["get"])
    def contents(self,request,pk=None):
        shelf=self.get_object();balances=shelf.balances.filter(quantity__gt=0).select_related("lot__variant__product");movements=Movement.objects.filter(models.Q(source=shelf)|models.Q(destination=shelf)).select_related("variant__product").order_by("-created_at")[:20]
        return Response({"shelf":ShelfSerializer(shelf).data,"items":[{"variant_id":b.lot.variant_id,"product":b.lot.variant.product.name,"variant":b.lot.variant.name,"quantity":b.quantity,"reserved":b.reserved,"available":b.quantity-b.reserved,"cost_value":b.quantity*b.lot.unit_cost,"retail_value":b.quantity*b.lot.variant.selling_price} for b in balances],"recent_movements":[{"type":m.movement_type,"quantity":m.quantity,"reference":m.reference,"created_at":m.created_at} for m in movements]})
