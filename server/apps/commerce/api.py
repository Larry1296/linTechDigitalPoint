from apps.tenancy.permissions import has_business_permission, is_business_manager
from decimal import Decimal, InvalidOperation
from apps.core.models import AuditLog
from uuid import uuid4
from django.contrib.auth.models import User
from django.db.models import F,Sum
from django.db import transaction
from apps.catalog.identity import display_name
from apps.catalog.display_images import variant_images
from rest_framework import permissions,serializers,status,viewsets
from rest_framework.decorators import action,api_view,permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from apps.accounts.models import CustomerAddress
from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from apps.inventory.models import StockBalance
from apps.inventory.services import complete_sale
from .models import Cart,CartItem,Order
from .services import checkout_cart,complete_reserved_order,get_cart,validate_online_variant
class CartItemSerializer(serializers.ModelSerializer):
    images = serializers.SerializerMethodField()
    def get_images(self, obj):
        return variant_images(obj.variant)
    display_name = serializers.SerializerMethodField()
    variant_id = serializers.IntegerField(read_only=True)
    def get_display_name(self, obj):
        return display_name(obj.variant.product.name, obj.variant.name)
    product_name=serializers.CharField(source="variant.product.name",read_only=True); variant_name=serializers.CharField(source="variant.name",read_only=True); sku=serializers.CharField(source="variant.sku",read_only=True); unit_price=serializers.DecimalField(source="variant.selling_price",max_digits=14,decimal_places=2,read_only=True); line_total=serializers.SerializerMethodField(); available=serializers.SerializerMethodField()
    class Meta:model=CartItem;fields=["images","id","variant","variant_id","display_name","product_name","variant_name","sku","quantity","unit_price","line_total","available"]
    def get_line_total(self,obj):return obj.quantity*obj.variant.selling_price
    def get_available(self,obj):return StockBalance.objects.filter(lot__variant=obj.variant).aggregate(v=Sum(F("quantity")-F("reserved")))["v"] or 0
def cart_payload(cart):
    rows=CartItemSerializer(cart.items.select_related("variant__product"),many=True).data
    return {"id":cart.id,"items":rows,"total":str(sum((Decimal(str(x["line_total"])) for x in rows),Decimal("0")))}
class CartInputSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"), default=1)


@api_view(["GET", "POST"])
@permission_classes([permissions.AllowAny])
def cart(request):
    current = get_cart(request)
    with transaction.atomic():
        current = Cart.objects.select_for_update().get(pk=current.pk)
        if request.method == "POST":
            payload = CartInputSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            variant = ProductVariant.objects.select_for_update().select_related("product").filter(pk=payload.validated_data["variant_id"]).first()
            if not variant:
                return Response({"detail": "Product variant not found."}, status=404)
            item = current.items.select_for_update().filter(variant=variant).first()
            quantity = payload.validated_data["quantity"] + (item.quantity if item else 0)
            validate_online_variant(variant, quantity)
            if item:
                item.quantity = quantity
                item.save(update_fields=["quantity", "updated_at"])
            else:
                CartItem.objects.create(cart=current, variant=variant, quantity=quantity)
    return Response(cart_payload(current))


@api_view(["PATCH", "DELETE"])
@permission_classes([permissions.AllowAny])
def cart_item(request, pk):
    current = get_cart(request)
    with transaction.atomic():
        current = Cart.objects.select_for_update().get(pk=current.pk)
        item = current.items.select_for_update().filter(pk=pk).first()
        if not item:
            return Response(status=404)
        if request.method == "DELETE":
            item.delete()
        else:
            field = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)
            quantity = field.run_validation(request.data.get("quantity"))
            if quantity == 0:
                item.delete()
            else:
                variant = ProductVariant.objects.select_for_update().select_related("product").get(pk=item.variant_id)
                validate_online_variant(variant, quantity)
                item.quantity = quantity
                item.save(update_fields=["quantity", "updated_at"])
    return Response(cart_payload(current))


class OrderItemSerializer(serializers.ModelSerializer):
    images = serializers.SerializerMethodField()
    def get_images(self, obj):
        return [{"url": obj.image_url, "alt": obj.product_name + " — " + obj.variant_name}] if obj.image_url else variant_images(obj.variant)
    display_name = serializers.SerializerMethodField()
    variant_id = serializers.IntegerField(read_only=True)
    def get_display_name(self, obj):
        return display_name(obj.product_name, obj.variant_name)
    pick_locations=serializers.SerializerMethodField()
    class Meta:model=__import__("apps.commerce.models",fromlist=["OrderItem"]).OrderItem;fields=["images","id","variant_id","display_name","product_name","variant_name","sku","quantity","unit_price","pick_locations"]
    def get_pick_locations(self,obj):
        request=self.context.get("request")
        if not request or not has_business_permission(request.user, "inventory.view_shelf"):return None
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
    def get_permissions(self):
        self.permission_required = "commerce.change_order" if self.action == "complete" else "commerce.view_order"
        return [HasLinTechPermission()]

    @action(detail=True,methods=["post"],permission_classes=[HasLinTechPermission])
    def complete(self,request,pk=None):
        order=self.get_object();key=request.data.get("idempotency_key") or f"staff:{order.number}";provider=request.data.get("provider_transaction_id") or key
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
    from collections import defaultdict
    from apps.catalog.search import search_variants, variant_summary
    search = request.query_params.get("q", "").strip()
    from apps.tenancy.middleware import effective_modules
    enabled = effective_modules(request.organization)
    # Only what this business sells: a barbershop sees services, a mama mboga sees produce.
    kinds = [kind for kind, module in ((Product.STOCK_ITEM, "inventory"), (Product.SERVICE, "services")) if module in enabled]
    rows = search_variants(ProductVariant.objects.select_related("product__category").filter(active=True, product__active=True, product__product_type__in=kinds), search)
    rows = list(rows[:50] if search else rows)
    stock = defaultdict(list)
    for balance in StockBalance.objects.filter(lot__variant_id__in=[v.id for v in rows]).select_related("lot", "shelf__zone__store", "shelf__level__stack").order_by("shelf__code", "id"):
        stock[balance.lot.variant_id].append(balance)
    result = []
    for v in rows:
        balances = stock[v.id]
        summary = variant_summary(v, balances=balances)
        if not has_business_permission(request.user, 'accounting.view_profit'):
            summary.pop('buying_price', None)
        result.append({**summary, "available": sum((x.quantity-x.reserved for x in balances), Decimal("0")), "locations": [{"zone": x.shelf.zone.name, "stack": x.shelf.level.stack.display_name if x.shelf.level_id else None, "level": x.shelf.level.level_number if x.shelf.level_id else None, "shelf_code": x.shelf.code, "shelf_name": x.shelf.display_name, "available": x.quantity-x.reserved} for x in balances if x.quantity > 0]})
    return Response(result)
def _quantity(value):
    try: number=Decimal(str(value or 0))
    except InvalidOperation: return Decimal("0")
    return number if number.is_finite() else Decimal("0")
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def pos_complete(request):
    if not has_business_permission(request.user, "commerce.add_sale"):return Response({"detail":"You do not have permission to complete sales."},status=403)
    lines=[]
    for raw in request.data.get("items",[]):
        variant=ProductVariant.objects.select_related("product").filter(pk=raw.get("variant_id"),active=True,product__active=True).first()
        if not variant:return Response({"detail":"Invalid product variant."},status=400)
        line={"variant":variant,"quantity":raw.get("quantity")}
        if raw.get("unit_price") not in (None,""):
            line["unit_price"]=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0).run_validation(raw.get("unit_price"))
        if raw.get("discount") not in (None,"",0,"0"):
            line["discount"]=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0).run_validation(raw.get("discount"))
        line["discount_reason"]=str(raw.get("discount_reason") or "")[:160]
        lines.append(line)
    discount=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0).run_validation(request.data.get("discount") or 0)
    # Bargaining: anyone may agree any price up to the asking price. The only floor is what the item cost to
    # buy (checked by complete_sale from the actual stock layers sold), never the product's "lowest price".
    # Going below that lowest price is allowed but logged for the owner to review. A price above the asking
    # price, a line discount or a whole-sale discount still needs a manager.
    manager=has_business_permission(request.user, "commerce.change_sale")
    below_floor=[]
    for line in lines:
        v=line["variant"]; price=line.get("unit_price", v.selling_price); quantity=_quantity(line["quantity"])
        effective=price-(line.get("discount") or 0)/quantity if quantity>0 else price
        if v.minimum_price and effective<v.minimum_price:
            below_floor.append(line)
        if line.get("discount") or price>v.selling_price:
            line["needs_manager"]=True
    if not manager and (discount or any(line.get("needs_manager") for line in lines)):
        return Response({"detail":"A price above the asking price, or a discount, needs a manager's approval."},status=403)
    customer=User.objects.filter(customer_profiles__organization_id=request.organization.pk, pk=request.data.get("customer_id")).first() if request.data.get("customer_id") else None
    if request.data.get("customer_id") and not customer:
        return Response({"detail": "Choose a customer in this business."}, status=400)
    number=f"POS-{uuid4().hex[:10].upper()}";method=request.data.get("payment_method","CASH");payment_status="COMPLETED" if method in ["CASH","BANK","OTHER"] else "MANUAL_REVIEW"
    try:
        sale=complete_sale(lines=lines,channel="POS",number=number,user=request.user,customer=customer,discount=discount,discount_reason=str(request.data.get("discount_reason") or "")[:160],allow_below_cost=bool(request.data.get("allow_below_cost")),payment_method=method,payment_status=payment_status,payment_reference=request.data.get("payment_reference",""),idempotency_key=request.data.get("idempotency_key") or number,paid_amount=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0,allow_null=True).run_validation(None if request.data.get("paid_amount") in (None, "") else request.data.get("paid_amount")),due_date=serializers.DateField(allow_null=True).run_validation(request.data.get("due_date") or None),require_customer_for_balance=True)
    except ValidationError as exc:
        detail=exc.detail if isinstance(exc.detail, dict) else {}
        if "below_cost" in detail and not has_business_permission(request.user, "accounting.view_profit"):
            names=", ".join(sorted({str(row).split(": sold for")[0] for row in detail["below_cost"]}))
            return Response({"code":"below_cost_hidden","detail":f"{names}: this price is below what the item cost to buy. Agree a higher price."},status=400)
        raise
    for line in below_floor:
        v=line["variant"]
        AuditLog.objects.create(action="SALE_BELOW_MINIMUM_PRICE",object_type="Sale",object_id=str(sale.pk),user=request.user,
            after={"variant":v.pk,"minimum_price":str(v.minimum_price),"unit_price":str(line.get("unit_price",v.selling_price)),"discount":str(line.get("discount") or 0),"reason":line["discount_reason"] or "Bargained"})
    data = {"sale_id":sale.id,"receipt_number":sale.number,"subtotal":sale.subtotal,"discount":sale.discount,"tax":sale.tax_total,"total":sale.total}
    # Mobile money is not counted as received until someone confirms it; the till offers that straight away.
    waiting=sale.payments.filter(status__in=["PENDING","MANUAL_REVIEW"]).order_by("pk").first()
    if waiting:
        data["waiting_payment"]={"id":waiting.pk,"method":waiting.method,"amount":waiting.amount,"reference":waiting.reference}
    if has_business_permission(request.user, "accounting.view_profit"):
        data.update(net_revenue=sale.net_total, cogs=sale.cogs, gross_profit=sale.gross_profit, loss=sale.gross_profit<0, cost_pending=sale.cost_pending)
    return Response(data,status=201)
