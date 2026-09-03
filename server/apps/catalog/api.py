from rest_framework import serializers,viewsets
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from .models import Brand,Category,PriceHistory,Product,ProductImage,ProductVariant
class CategorySerializer(serializers.ModelSerializer):
    class Meta:model=Category;fields="__all__"
class BrandSerializer(serializers.ModelSerializer):
    class Meta:model=Brand;fields="__all__"
class ImageSerializer(serializers.ModelSerializer):
    class Meta:model=ProductImage;fields="__all__"
class VariantSerializer(serializers.ModelSerializer):
    physical=serializers.DecimalField(max_digits=14,decimal_places=3,read_only=True);reserved=serializers.DecimalField(max_digits=14,decimal_places=3,read_only=True)
    class Meta:model=ProductVariant;fields="__all__"
    def update(self,obj,data):
        old=obj.selling_price;obj=super().update(obj,data)
        if obj.selling_price!=old:PriceHistory.objects.create(variant=obj,price=obj.selling_price,changed_by=self.context["request"].user);AuditLog.objects.create(action="PRICE_CHANGED",object_type="ProductVariant",object_id=str(obj.pk),user=self.context["request"].user,before={"price":str(old)},after={"price":str(obj.selling_price)})
        return obj
class ProductSerializer(serializers.ModelSerializer):
    variants=VariantSerializer(many=True,read_only=True);images=ImageSerializer(many=True,read_only=True)
    class Meta:model=Product;fields="__all__"
class SecuredModelViewSet(viewsets.ModelViewSet):
    permission_classes=[IsInternalStaff]
    def get_permissions(self):
        action={"create":"add","update":"change","partial_update":"change","destroy":"delete"}.get(self.action,"view");self.permission_required=f"{self.queryset.model._meta.app_label}.{action}_{self.queryset.model._meta.model_name}";return [HasLinTechPermission()]
class CategoryViewSet(SecuredModelViewSet):queryset=Category.objects.all();serializer_class=CategorySerializer
class BrandViewSet(SecuredModelViewSet):queryset=Brand.objects.all();serializer_class=BrandSerializer
class ProductViewSet(SecuredModelViewSet):queryset=Product.objects.select_related("category","brand").prefetch_related("variants","images");serializer_class=ProductSerializer
class VariantViewSet(SecuredModelViewSet):queryset=ProductVariant.objects.select_related("product").all();serializer_class=VariantSerializer
class ImageViewSet(SecuredModelViewSet):queryset=ProductImage.objects.all();serializer_class=ImageSerializer

