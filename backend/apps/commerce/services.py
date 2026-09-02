from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.catalog.models import ProductVariant
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
@transaction.atomic
def checkout_cart(*,request,fulfillment_method,address=None,payment_method="CASH_ON_PICKUP",notes=""):
    if not request.user.is_authenticated:raise ValidationError("Authentication required.")
    cart=get_cart(request); items=list(cart.items.select_related("variant__product"))
    if not items:raise ValidationError("Cart is empty.")
    number=f"LT-WEB-{timezone.now():%y%m%d}-{uuid4().hex[:6].upper()}"; subtotal=cart_total(cart)
    order=Order.objects.create(number=number,customer=request.user,subtotal=subtotal,total=subtotal,fulfillment_method=fulfillment_method,address=address,notes=notes,status="AWAITING_PAYMENT")
    timeout=Store.objects.first().reservation_timeout_minutes if Store.objects.exists() else 30
    for cart_item in items:
        v=cart_item.variant; reservation=None
        if v.product.product_type=="STOCK_ITEM":reservation=reserve_stock(variant=v,quantity=cart_item.quantity,reference=number,expires_at=timezone.now()+timezone.timedelta(minutes=timeout),user=request.user)
        OrderItem.objects.create(order=order,variant=v,product_name=v.product.name,variant_name=v.name,sku=v.sku,quantity=cart_item.quantity,unit_price=v.selling_price,reservation=reservation)
    status="PENDING" if payment_method in ["CASH_ON_PICKUP"] else "MANUAL_REVIEW"
    Payment.objects.create(order=order,method=payment_method,amount=order.total,status=status,idempotency_key=f"checkout:{order.number}")
    OrderStatusHistory.objects.create(order=order,status=order.status,note="Order placed",changed_by=request.user); cart.active=False; cart.save(update_fields=["active","updated_at"])
    AuditLog.objects.create(action="ORDER_CREATED",object_type="Order",object_id=str(order.pk),user=request.user,after={"number":number,"total":str(order.total)}); return order
@transaction.atomic
def complete_reserved_order(*,order,payment_method,provider_transaction_id,idempotency_key,user=None):
    order=Order.objects.select_for_update().select_related("customer").get(pk=order.pk)
    existing=Payment.objects.filter(idempotency_key=idempotency_key,status="COMPLETED",sale__isnull=False).select_related("sale").first()
    if existing:return existing.sale
    if hasattr(order,"sale"):return order.sale
    sale=Sale.objects.create(number=order.number.replace("WEB","SALE"),channel="ONLINE",order=order,customer=order.customer,created_by=user,subtotal=order.subtotal,discount=order.discount,total=order.total)
    cogs=Decimal("0")
    for order_item in order.items.select_related("variant__product","reservation"):
        item=SaleItem.objects.create(sale=sale,variant=order_item.variant,quantity=order_item.quantity,unit_price=order_item.unit_price)
        if order_item.variant.product.product_type=="SERVICE":item.cost=order_item.quantity*order_item.variant.service_cost; item.save(update_fields=["cost"]); cogs+=item.cost; continue
        reservation=Reservation.objects.select_for_update().get(pk=order_item.reservation_id)
        if not reservation.active or reservation.status!=Reservation.ACTIVE:raise ValidationError("Order reservation is no longer active.")
        allocated=Decimal("0")
        for allocation in reservation.allocations:
            balance=StockBalance.objects.select_for_update().select_related("lot","shelf").get(pk=allocation["balance_id"]); qty=_d(allocation["quantity"])
            if balance.reserved<qty or balance.quantity<qty:raise ValidationError("Reserved stock allocation is inconsistent.")
            balance.reserved-=qty; balance.quantity-=qty; balance.save(update_fields=["reserved","quantity","updated_at"]); StockLot.objects.filter(pk=balance.lot_id).update(remaining_quantity=F("remaining_quantity")-qty); SaleAllocation.objects.create(item=item,lot=balance.lot,shelf=balance.shelf,quantity=qty,unit_cost=balance.lot.unit_cost); Movement.objects.create(variant=order_item.variant,lot=balance.lot,quantity=qty,source=balance.shelf,movement_type="ONLINE_ORDER",reference=order.number,performed_by=user); allocated+=qty; cogs+=qty*balance.lot.unit_cost
        if allocated!=order_item.quantity:raise ValidationError("Reservation quantity does not match order item.")
        item.cost=sum((a.quantity*a.unit_cost for a in item.allocations.all()),Decimal("0")); item.save(update_fields=["cost"]); reservation.active=False; reservation.status=Reservation.CONSUMED; reservation.save(update_fields=["active","status","updated_at"])
    sale.cogs=cogs; sale.gross_profit=sale.total-cogs; sale.save(update_fields=["cogs","gross_profit","updated_at"])
    payment=Payment.objects.filter(order=order).order_by("-created_at").first()
    if payment:
        payment.sale=sale; payment.method=payment_method; payment.status="COMPLETED"; payment.provider_transaction_id=provider_transaction_id; payment.idempotency_key=idempotency_key; payment.save()
    else:Payment.objects.create(order=order,sale=sale,method=payment_method,amount=order.total,status="COMPLETED",provider_transaction_id=provider_transaction_id,idempotency_key=idempotency_key)
    order.status="PAID"; order.payment_status="PAID"; order.fulfillment_status="PROCESSING"; order.completed_at=timezone.now(); order.save(); OrderStatusHistory.objects.create(order=order,status="PAID",note="Payment confirmed and reservation consumed",changed_by=user); AuditLog.objects.create(action="ONLINE_ORDER_COMPLETED",object_type="Order",object_id=str(order.pk),user=user,after={"sale":sale.number}); return sale
