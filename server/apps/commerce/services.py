from apps.tenancy.transactions import lock_business
from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.catalog.models import ProductVariant
from apps.catalog.display_images import variant_images
from apps.core.models import AuditLog,Store
from apps.inventory.models import Movement,Reservation,StockBalance,StockLot
from apps.inventory.services import _d,reserve_stock
from .models import Cart,CartItem,Order,OrderItem,OrderStatusHistory,Payment,Sale,SaleAllocation,SaleItem
def ensure_session(request):
    if not request.session.session_key:request.session.create()
    return request.session.session_key
@transaction.atomic
def get_cart(request):
    session_key=ensure_session(request)
    if request.user.is_authenticated:
        cart,_=Cart.objects.get_or_create(customer=request.user,active=True,defaults={"session_key":session_key})
        anonymous=Cart.objects.filter(session_key=session_key,customer__isnull=True,active=True).exclude(pk=cart.pk).first()
        if anonymous:
            for item in anonymous.items.select_related("variant"):
                target,created=CartItem.objects.get_or_create(cart=cart,variant=item.variant,defaults={"quantity":item.quantity})
                if not created:target.quantity=F("quantity")+item.quantity; target.save(update_fields=["quantity","updated_at"])
            anonymous.active=False; anonymous.save(update_fields=["active","updated_at"])
        return cart
    cart,_=Cart.objects.get_or_create(session_key=session_key,customer__isnull=True,active=True); return cart
@transaction.atomic
def adopt_cart(cart,user):
    cart=Cart.objects.select_for_update().get(pk=cart.pk);target=Cart.objects.select_for_update().filter(customer=user,active=True).first()
    if target and target.pk!=cart.pk:
        for item in cart.items.select_for_update().all():
            existing,created=CartItem.objects.get_or_create(cart=target,variant=item.variant,defaults={"quantity":item.quantity})
            if not created:existing.quantity=F("quantity")+item.quantity;existing.save(update_fields=["quantity","updated_at"])
        cart.active=False;cart.save(update_fields=["active","updated_at"]);return target
    cart.customer=user;cart.session_key="";cart.save(update_fields=["customer","session_key","updated_at"]);return cart
def cart_total(cart): return sum((item.quantity*item.variant.selling_price for item in cart.items.select_related("variant")),Decimal("0"))
def validate_online_variant(variant, quantity):
    if not variant.active or not variant.product.active or not variant.product.ecommerce_visible or not variant.product.online_orderable:
        raise ValidationError("This variant is not available for online ordering.")
    if variant.selling_price <= 0:
        raise ValidationError("This variant's selling price has not been confirmed.")
    if quantity <= 0 or not quantity.is_finite():
        raise ValidationError("Quantity must be positive and finite.")
    if variant.product.product_type == "STOCK_ITEM":
        available = StockBalance.objects.filter(lot__variant=variant).aggregate(value=Sum(F("quantity") - F("reserved")))["value"] or Decimal("0")
        if quantity > available:
            raise ValidationError(f"Only {available} units of {variant.product.name} — {variant.name} are available.")


@transaction.atomic
def checkout_cart(*,request,fulfillment_method,address=None,payment_method="CASH_ON_PICKUP",notes=""):
    if not request.user.is_authenticated:raise ValidationError("Authentication required.")
    cart=get_cart(request)
    cart=Cart.objects.select_for_update().get(pk=cart.pk)
    items=list(cart.items.select_for_update().select_related("variant__product"))
    variants = {v.pk: v for v in ProductVariant.objects.select_for_update().select_related("product").filter(pk__in=[i.variant_id for i in items]).order_by("pk")}
    for item in items:
        item.variant = variants[item.variant_id]
        validate_online_variant(item.variant, item.quantity)
    if not items:raise ValidationError("Cart is empty.")
    if any(not item.variant.product.online_orderable for item in items):raise ValidationError("This cart contains a service that is not available for online ordering.")
    number=f"LT-WEB-{timezone.now():%y%m%d}-{uuid4().hex[:6].upper()}"; subtotal=sum((item.quantity * item.variant.selling_price for item in items), Decimal("0"))
    order=Order.objects.create(number=number,customer=request.user,subtotal=subtotal,total=subtotal,fulfillment_method=fulfillment_method,address=address,notes=notes,status="AWAITING_PAYMENT")
    timeout=Store.objects.first().reservation_timeout_minutes if Store.objects.exists() else 30
    for cart_item in items:
        v=cart_item.variant; reservation=None
        if v.product.product_type=="STOCK_ITEM":reservation=reserve_stock(variant=v,quantity=cart_item.quantity,reference=number,expires_at=timezone.now()+timezone.timedelta(minutes=timeout),user=request.user)
        photos = variant_images(v)
        OrderItem.objects.create(order=order,variant=v,image_url=photos[0]["url"] if photos else "",product_name=v.product.name,variant_name=v.name,sku=v.sku,quantity=cart_item.quantity,unit_price=v.selling_price,reservation=reservation)
    status="PENDING" if payment_method in ["CASH_ON_PICKUP"] else "MANUAL_REVIEW"
    Payment.objects.create(order=order,method=payment_method,amount=order.total,status=status,idempotency_key=f"checkout:{order.number}")
    OrderStatusHistory.objects.create(order=order,status=order.status,note="Order placed",changed_by=request.user); cart.active=False; cart.save(update_fields=["active","updated_at"])
    AuditLog.objects.create(action="ORDER_CREATED",object_type="Order",object_id=str(order.pk),user=request.user,after={"number":number,"total":str(order.total)}); return order
@transaction.atomic
def complete_reserved_order(*,order,payment_method,provider_transaction_id,idempotency_key,user=None):
    lock_business()
    order=Order.objects.select_for_update().select_related("customer").get(pk=order.pk)
    existing=Payment.objects.filter(idempotency_key=idempotency_key,status="COMPLETED",sale__isnull=False).select_related("sale").first()
    if existing:return existing.sale
    if hasattr(order,"sale"):return order.sale
    sale=Sale.objects.create(number=order.number.replace("WEB","SALE"),channel="ONLINE",order=order,customer=order.customer,created_by=user,subtotal=order.subtotal,discount=order.discount,total=order.total)
    cogs=Decimal("0")
    from apps.commerce.pricing import cents, price_line, spread_discount, tax_config
    from apps.tenancy.models import Organization
    from apps.tenancy.context import organization_id
    tax=tax_config(Organization.objects.get(pk=organization_id()))
    order_items=list(order.items.select_related("variant__product","reservation"))
    shares=spread_discount([cents(i.quantity*i.unit_price) for i in order_items],order.discount)
    totals={"gross":Decimal("0"),"discount":Decimal("0"),"tax":Decimal("0"),"net":Decimal("0"),"payable":Decimal("0")}
    for order_item,share in zip(order_items,shares):
        amounts=price_line(order_item.quantity,order_item.unit_price,share,tax)
        for key in totals: totals[key]+=amounts[key]
        item=SaleItem.objects.create(sale=sale,variant=order_item.variant,quantity=order_item.quantity,list_price=order_item.unit_price,unit_price=order_item.unit_price,
            discount=amounts["discount"],discount_reason="Order discount" if share else "",tax_amount=amounts["tax"],net_amount=amounts["net"])
        if order_item.variant.product.product_type=="SERVICE":item.cost=cents(order_item.quantity*order_item.variant.service_cost); item.save(update_fields=["cost"]); cogs+=item.cost; continue
        reservation=Reservation.objects.select_for_update().get(pk=order_item.reservation_id)
        if not reservation.active or reservation.status!=Reservation.ACTIVE:raise ValidationError("Order reservation is no longer active.")
        allocated=Decimal("0")
        for allocation in reservation.allocations:
            balance=StockBalance.objects.select_for_update().select_related("lot","shelf").get(pk=allocation["balance_id"]); qty=_d(allocation["quantity"])
            if balance.reserved<qty or balance.quantity<qty:raise ValidationError("Reserved stock allocation is inconsistent.")
            balance.reserved-=qty; balance.quantity-=qty; balance.save(update_fields=["reserved","quantity","updated_at"]); StockLot.objects.filter(pk=balance.lot_id).update(remaining_quantity=F("remaining_quantity")-qty); SaleAllocation.objects.create(item=item,lot=balance.lot,shelf=balance.shelf,quantity=qty,unit_cost=balance.lot.unit_cost); Movement.objects.create(variant=order_item.variant,lot=balance.lot,quantity=qty,source=balance.shelf,movement_type="ONLINE_ORDER",reference=order.number,performed_by=user); allocated+=qty; cogs+=qty*balance.lot.unit_cost
        if allocated!=order_item.quantity:raise ValidationError("Reservation quantity does not match order item.")
        item.cost=cents(sum((a.quantity*a.unit_cost for a in item.allocations.all()),Decimal("0"))); item.cost_pending=item.allocations.filter(lot__cost_status="UNCOSTED").exists(); item.save(update_fields=["cost","cost_pending"]); reservation.active=False; reservation.status=Reservation.CONSUMED; reservation.save(update_fields=["active","status","updated_at"])
    sale.subtotal,sale.discount,sale.tax_total,sale.net_total,sale.total=totals["gross"],totals["discount"],totals["tax"],totals["net"],totals["payable"]
    sale.cogs=cents(cogs); sale.gross_profit=sale.net_total-sale.cogs; sale.cost_pending=sale.items.filter(cost_pending=True).exists()
    sale.save(update_fields=["subtotal","discount","tax_total","net_total","total","cogs","gross_profit","cost_pending","updated_at"])
    from apps.accounting.ledger import post_sale
    post_sale(sale)
    payment=Payment.objects.filter(order=order).order_by("-created_at").first()
    if payment:
        payment.sale=sale; payment.method=payment_method; payment.status="COMPLETED"; payment.provider_transaction_id=provider_transaction_id; payment.idempotency_key=idempotency_key; payment.save()
    else:Payment.objects.create(order=order,sale=sale,method=payment_method,amount=order.total,status="COMPLETED",provider_transaction_id=provider_transaction_id,idempotency_key=idempotency_key)
    order.status="PAID"; order.payment_status="PAID"; order.fulfillment_status="PROCESSING"; order.completed_at=timezone.now(); order.save(); OrderStatusHistory.objects.create(order=order,status="PAID",note="Payment confirmed and reservation consumed",changed_by=user); AuditLog.objects.create(action="ONLINE_ORDER_COMPLETED",object_type="Order",object_id=str(order.pk),user=user,after={"sale":sale.number}); return sale
