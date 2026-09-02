from django.contrib.auth import authenticate,login,logout
from django.db.models import F,Sum
from rest_framework import permissions,serializers,status,viewsets
from rest_framework.decorators import action,api_view,permission_classes,throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from catalog.models import Category,Product,ProductVariant
from inventory.models import Shelf,StockBalance,Zone
class LoginThrottle(AnonRateThrottle): scope="auth"
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def csrf(request):
    from django.middleware.csrf import get_token
    return Response({"csrfToken":get_token(request)})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def sign_in(request):
    user=authenticate(request,username=request.data.get("username"),password=request.data.get("password"))
    if not user or not user.is_active:return Response({"detail":"Invalid credentials."},status=400)
    login(request,user); return Response({"username":user.username,"permissions":list(user.get_all_permissions())})
@api_view(["POST"])
def sign_out(request): logout(request); return Response(status=204)
@api_view(["GET"])
def me(request): return Response({"username":request.user.username,"permissions":list(request.user.get_all_permissions()),"is_staff":request.user.is_staff})
class PublicVariantSerializer(serializers.ModelSerializer):
    product_name=serializers.CharField(source="product.name"); available=serializers.SerializerMethodField()
    class Meta: model=ProductVariant; fields=["id","product_name","name","sku","barcode","selling_price","available"]
    def get_available(self,obj):
        return StockBalance.objects.filter(lot__variant=obj).aggregate(v=Sum(F("quantity")-F("reserved")))["v"] or 0
class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes=[permissions.AllowAny]; serializer_class=PublicVariantSerializer
    queryset=ProductVariant.objects.select_related("product").filter(active=True,product__active=True,product__ecommerce_visible=True)
    filterset_fields=["product__category","product__brand"]; search_fields=["product__name","name","sku","barcode"]
class ShelfSerializer(serializers.ModelSerializer):
    total_quantity=serializers.SerializerMethodField()
    class Meta: model=Shelf; fields=["id","code","display_name","zone","parent","x","y","width","height","depth","rotation","sort_order","capacity","active","notes","total_quantity"]; read_only_fields=["code"]
    def get_total_quantity(self,obj): return obj.balances.aggregate(v=Sum("quantity"))["v"] or 0
    def create(self,data):
        zone=data["zone"]; prefix=zone.code[0]; count=Shelf.objects.filter(zone=zone).count()+1; data["code"]=f"{prefix}-SH-{count:04d}"; return super().create(data)
class ZoneSerializer(serializers.ModelSerializer):
    shelves=ShelfSerializer(many=True,read_only=True)
    class Meta: model=Zone; fields=["id","code","name","width","height","active","shelves"]
class ZoneViewSet(viewsets.ModelViewSet):
    serializer_class=ZoneSerializer; queryset=Zone.objects.prefetch_related("shelves__balances")
    def get_permissions(self):
        return [permissions.IsAuthenticated()] if self.action in ["list","retrieve"] else [permissions.DjangoModelPermissions()]
class ShelfViewSet(viewsets.ModelViewSet):
    serializer_class=ShelfSerializer; queryset=Shelf.objects.select_related("zone").prefetch_related("balances")
    def get_permissions(self): return [permissions.DjangoModelPermissions()]
