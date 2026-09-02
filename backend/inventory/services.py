from decimal import Decimal
from django.db import transaction
from django.db.models import F,Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Movement,Reservation,Shelf,StockBalance,StockLot
def _d(v): return Decimal(str(v))
@transaction.atomic
def receive_stock(*,variant,placements,unit_cost,reference,user=None,supplier_name=""):
    total=sum((_d(p["quantity"]) for p in placements),Decimal("0"))
    if total<=0: raise ValidationError("Received quantity must be positive.")
    lot=StockLot.objects.create(variant=variant,reference=reference,received_quantity=total,remaining_quantity=total,unit_cost=_d(unit_cost),supplier_name=supplier_name,received_at=timezone.now())
    for p in placements:
        shelf=Shelf.objects.select_for_update().get(pk=p["shelf"].pk,active=True); qty=_d(p["quantity"])
        StockBalance.objects.create(lot=lot,shelf=shelf,quantity=qty)
        Movement.objects.create(variant=variant,lot=lot,quantity=qty,destination=shelf,movement_type="PURCHASE_RECEIPT",reference=reference,performed_by=user)
    return lot
@transaction.atomic
def transfer_stock(*,variant,source,destination,quantity,reference,user=None):
    need=_d(quantity)
    if need<=0 or source.pk==destination.pk: raise ValidationError("Choose distinct shelves and a positive quantity.")
    rows=list(StockBalance.objects.select_for_update().select_related("lot").filter(lot__variant=variant,shelf=source,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id"))
    if sum((r.quantity-r.reserved for r in rows),Decimal("0"))<need: raise ValidationError("Insufficient available stock at source shelf.")
    for row in rows:
        take=min(need,row.quantity-row.reserved); row.quantity-=take; row.save(update_fields=["quantity","updated_at"])
        target,_=StockBalance.objects.select_for_update().get_or_create(lot=row.lot,shelf=destination,defaults={"quantity":0}); target.quantity+=take; target.save(update_fields=["quantity","updated_at"])
        Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=source,destination=destination,movement_type="TRANSFER",reference=reference,performed_by=user)
        need-=take
        if need==0: break
@transaction.atomic
def reserve_stock(*,variant,quantity,reference,expires_at,user=None):
    need=_d(quantity); allocations=[]
    rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","shelf_id"))
    available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
    if need<=0 or available<need: raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
    original=need
    for row in rows:
        take=min(need,row.quantity-row.reserved); row.reserved+=take; row.save(update_fields=["reserved","updated_at"]); allocations.append({"balance_id":row.id,"quantity":str(take),"shelf_id":row.shelf_id,"lot_id":row.lot_id})
        Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=row.shelf,movement_type="ORDER_RESERVATION",reference=reference,performed_by=user)
        need-=take
        if need==0: break
    return Reservation.objects.create(variant=variant,quantity=original,reference=reference,expires_at=expires_at,allocations=allocations)
@transaction.atomic
def release_reservation(reservation,user=None):
    reservation=Reservation.objects.select_for_update().get(pk=reservation.pk)
    if not reservation.active: return reservation
    for a in reservation.allocations:
        row=StockBalance.objects.select_for_update().get(pk=a["balance_id"]); qty=_d(a["quantity"]); row.reserved-=qty; row.save(update_fields=["reserved","updated_at"])
        Movement.objects.create(variant=reservation.variant,lot=row.lot,quantity=qty,destination=row.shelf,movement_type="RESERVATION_RELEASE",reference=reservation.reference,performed_by=user)
    reservation.active=False; reservation.save(update_fields=["active","updated_at"]); return reservation
@transaction.atomic
def complete_sale(*,lines,channel,number,user=None,discount=0,payment_method="CASH",idempotency_key=None):
    from commerce.models import Payment,Sale,SaleAllocation,SaleItem
    sale=Sale.objects.create(number=number,channel=channel,created_by=user,discount=_d(discount))
    subtotal=Decimal("0"); cogs=Decimal("0")
    for line in lines:
        variant=line["variant"]; qty=_d(line["quantity"]); price=_d(line.get("unit_price",variant.selling_price)); subtotal+=qty*price
        item=SaleItem.objects.create(sale=sale,variant=variant,quantity=qty,unit_price=price)
        if variant.product.product_type=="SERVICE": item.cost=qty*variant.service_cost; item.save(update_fields=["cost"]); cogs+=item.cost; continue
        need=qty
        rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id","shelf_id"))
        available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
        if available<need: raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
        for row in rows:
            take=min(need,row.quantity-row.reserved); cost=take*row.lot.unit_cost; row.quantity-=take; row.save(update_fields=["quantity","updated_at"]); row.lot.remaining_quantity=F("remaining_quantity")-take; row.lot.save(update_fields=["remaining_quantity","updated_at"])
            SaleAllocation.objects.create(item=item,lot=row.lot,shelf=row.shelf,quantity=take,unit_cost=row.lot.unit_cost); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=row.shelf,movement_type="SALE" if channel=="POS" else "ONLINE_ORDER",reference=number,performed_by=user); cogs+=cost; need-=take
            if need==0: break
        item.cost=sum((a.quantity*a.unit_cost for a in item.allocations.all()),Decimal("0")); item.save(update_fields=["cost"])
    sale.subtotal=subtotal; sale.total=subtotal-_d(discount); sale.cogs=cogs; sale.gross_profit=sale.total-cogs; sale.save()
    Payment.objects.create(sale=sale,method=payment_method,amount=sale.total,idempotency_key=idempotency_key or number)
    return sale

