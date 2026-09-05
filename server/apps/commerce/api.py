from decimal import Decimal
from uuid import uuid4
from django.contrib.auth.models import User
from django.db.models import F,Sum
from rest_framework import permissions,serializers,status,viewsets
from rest_framework.decorators import action,api_view,permission_classes
from rest_framework.response import Response
from apps.accounts.models import CustomerAddress
from apps.catalog.models import ProductVariant
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from apps.inventory.models import StockBalance
from apps.inventory.services import complete_sale
from .models import CartItem,Order
from .services import checkout_cart,complete_reserved_order,get_cart
class CartItemSerializer(serializers.ModelSerializer):
    product_name=serializers.CharField(source="variant.product.name",read_only=True); variant_name=serializers.CharField(source="variant.name",read_only=True); sku=serializers.CharField(source="variant.sku",read_only=True); unit_price=serializers.DecimalField(source="variant.selling_price",max_digits=14,decimal_places=2,read_only=True); line_total=serializers.SerializerMethodField(); available=serializers.SerializerMethodField()
    class Meta:model=CartItem;fields=["id","variant","product_name","variant_name","sku","quantity","unit_price","line_total","available"]
    def get_line_total(self,obj):return obj.quantity*obj.variant.selling_price
    def get_available(self,obj):return StockBalance.objects.filter(lot__variant=obj.variant).aggregate(v=Sum(F("quantity")-F("reserved")))["v"] or 0
def cart_payload(cart):
    rows=CartItemSerializer(cart.items.select_related("variant__product"),many=True).data
    return {"id":cart.id,"items":rows,"total":str(sum((Decimal(str(x["line_total"])) for x in rows),Decimal("0")))}
@api_view(["GET","POST"])
@permission_classes([permissions.AllowAny])
def cart(request):
    current=get_cart(request)
    if request.method=="POST":
        variant=ProductVariant.objects.select_related("product").filter(pk=request.data.get("variant_id"),active=True,product__active=True,product__online_orderable=True).first()
        if not variant:return Response({"detail":"Product variant not found."},status=404)
        quantity=Decimal(str(request.data.get("quantity",1)))
        if quantity<=0:return Response({"detail":"Quantity must be positive."},status=400)
        item,created=CartItem.objects.get_or_create(cart=current,variant=variant,defaults={"quantity":quantity})
        if not created:item.quantity=F("quantity")+quantity;item.save(update_fields=["quantity","updated_at"])
    return Response(cart_payload(current))
@api_view(["PATCH","DELETE"])
@permission_classes([permissions.AllowAny])
def cart_item(request,pk):
    current=get_cart(request); item=current.items.filter(pk=pk).first()
    if not item:return Response(status=404)
    if request.method=="DELETE":item.delete()
    else:
        quantity=Decimal(str(request.data.get("quantity",0)))
        if quantity<=0:item.delete()
        else:item.quantity=quantity;item.save(update_fields=["quantity","updated_at"])
    return Response(cart_payload(current))
class OrderItemSerializer(serializers.ModelSerializer):
    pick_locations=serializers.SerializerMethodField()
    class Meta:model=__import__("apps.commerce.models",fromlist=["OrderItem"]).OrderItem;fields=["id","product_name","variant_name","sku","quantity","unit_price","pick_locations"]
    def get_pick_locations(self,obj):
        request=self.context.get("request")
        if not request or not request.user.is_staff:return None
        if not obj.reservation:return []
        shelves={s.id:s for s in __import__("apps.inventory.models",fromlist=["Shelf"]).Shelf.objects.filter(id__in=[a["shelf_id"] for a in obj.reservation.allocations]).select_related("zone","level__stack")}
        return [{"shelf_id":a["shelf_id"],"shelf_code":shelves[a["shelf_id"]].code,"shelf_name":shelves[a["shelf_id"]].display_name,"zone":shelves[a["shelf_id"]].zone.name,"stack":shelves[a["shelf_id"]].level.stack.display_name if shelves[a["shelf_id"]].level_id else None,"level":shelves[a["shelf_id"]].level.level_number if shelves[a["shelf_id"]].level_id else None,"lot_id":a["lot_id"],"quantity":a["quantity"]} for a in obj.reservation.allocations]
class OrderSerializer(serializers.ModelSerializer):
    items=OrderItemSerializer(many=True,read_only=True); payment_method=serializers.SerializerMethodField()
    class Meta:model=Order;fields=["id","number","status","payment_status","fulfillment_status","fulfillment_method","subtotal","discount","total","notes","created_at","items","payment_method"]
    def get_payment_method(self,obj):
        payment=obj.payments.order_by("-created_at").first();return payment.method if payment else None
class CustomerOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class=OrderSerializer
    def get_queryset(self):return Order.objects.filter(customer=self.request.user).prefetch_related("items__reservation","payments")
class StaffOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class=OrderSerializer;permission_classes=[IsInternalStaff];queryset=Order.objects.select_related("customer").prefetch_related("items__reservation","payments").order_by("-created_at")
    @action(detail=True,methods=["post"],permission_classes=[HasLinTechPermission])
    def complete(self,request,pk=None):
        self.permission_required="commerce.change_order";order=self.get_object();key=request.data.get("idempotency_key") or f"staff:{order.number}";provider=request.data.get("provider_transaction_id") or key
        sale=complete_reserved_order(order=order,payment_method=request.data.get("payment_method","CASH"),provider_transaction_id=provider,idempotency_key=key,user=request.user)
        return Response({"sale_id":sale.id,"receipt_number":sale.number,"total":sale.total})
@api_view(["POST"])
def checkout(request):
    address=None
    if request.data.get("address_id"):
        address=CustomerAddress.objects.filter(pk=request.data["address_id"],profile__user=request.user).first()
        if not address:return Response({"detail":"Address not found."},status=400)
    order=checkout_cart(request=request,fulfillment_method=request.data.get("fulfillment_method","PICKUP"),address=address,payment_method=request.data.get("payment_method","CASH_ON_PICKUP"),notes=request.data.get("notes",""))
    return Response(OrderSerializer(order,context={"request":request}).data,status=201)
@api_view(["GET"])
@permission_classes([IsInternalStaff])
def pos_catalog(request):
    search=request.query_params.get("q",""); rows=ProductVariant.objects.select_related("product","product__category").filter(active=True,product__active=True)
    if search:rows=rows.filter(product__name__icontains=search)|rows.filter(sku__iexact=search)|rows.filter(barcode__iexact=search)
    result=[]
    for v in rows[:50]:
        balances=StockBalance.objects.filter(lot__variant=v,quantity__gt=0).select_related("shelf__zone","shelf__level__stack")
        result.append({"id":v.id,"product_name":v.product.name,"variant_name":v.name,"sku":v.sku,"barcode":v.barcode,"product_type":v.product.product_type,"selling_price":v.selling_price,"available":sum((x.quantity-x.reserved for x in balances),Decimal("0")),"locations":[{"zone":x.shelf.zone.name,"stack":x.shelf.level.stack.display_name if x.shelf.level_id else None,"level":x.shelf.level.level_number if x.shelf.level_id else None,"shelf_code":x.shelf.code,"shelf_name":x.shelf.display_name,"available":x.quantity-x.reserved} for x in balances]})
    return Response(result)
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def pos_complete(request):
    if not request.user.has_perm("commerce.add_sale"):return Response({"detail":"You do not have permission to complete sales."},status=403)
    lines=[]
    for raw in request.data.get("items",[]):
        variant=ProductVariant.objects.select_related("product").filter(pk=raw.get("variant_id"),active=True).first()
        if not variant:return Response({"detail":"Invalid product variant."},status=400)
        lines.append({"variant":variant,"quantity":raw.get("quantity")})
    discount=Decimal(str(request.data.get("discount",0)))
    if discount and not request.user.has_perm("commerce.change_sale"):return Response({"detail":"Discount approval required."},status=403)
    customer=User.objects.filter(pk=request.data.get("customer_id")).first() if request.data.get("customer_id") else None;number=f"LT-POS-{uuid4().hex[:10].upper()}";method=request.data.get("payment_method","CASH");payment_status="COMPLETED" if method in ["CASH","BANK","OTHER"] else "MANUAL_REVIEW"
    sale=complete_sale(lines=lines,channel="POS",number=number,user=request.user,customer=customer,discount=discount,payment_method=method,payment_status=payment_status,payment_reference=request.data.get("payment_reference",""),idempotency_key=request.data.get("idempotency_key") or number)
    return Response({"sale_id":sale.id,"receipt_number":sale.number,"subtotal":sale.subtotal,"discount":sale.discount,"total":sale.total,"cogs":sale.cogs,"gross_profit":sale.gross_profit},status=201)
