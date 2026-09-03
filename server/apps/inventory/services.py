from decimal import Decimal
from django.db import IntegrityError,transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from .models import Movement,Reservation,Shelf,ShelfHistory,StockBalance,StockLot,Zone
def _d(value): return Decimal(str(value))
def _audit(action,obj,user,before=None,after=None):
    AuditLog.objects.create(action=action,object_type=obj.__class__.__name__,object_id=str(obj.pk),user=user,before=before or {},after=after or {})
def _shelf_snapshot(s): return {"code":s.code,"name":s.display_name,"zone":s.zone_id,"x":str(s.x),"y":str(s.y),"width":str(s.width),"height":str(s.height),"active":s.active}
@transaction.atomic
def create_shelf(*,zone,user,display_name,x,y,width,height,**extra):
    zone=Zone.objects.select_for_update().get(pk=zone.pk); number=zone.next_shelf_number; prefix=zone.code[:1].upper()
    while Shelf.objects.filter(zone=zone,code=f"{prefix}-SH-{number:04d}").exists():number+=1
    zone.next_shelf_number=number+1; zone.save(update_fields=["next_shelf_number","updated_at"])
    shelf=Shelf.objects.create(zone=zone,code=f"{prefix}-SH-{number:04d}",display_name=display_name,x=x,y=y,width=width,height=height,created_by=user,updated_by=user,**extra)
    snapshot=_shelf_snapshot(shelf); ShelfHistory.objects.create(shelf=shelf,event="CREATED",snapshot=snapshot,changed_by=user); _audit("SHELF_CREATED",shelf,user,after=snapshot); return shelf
@transaction.atomic
def update_shelf(*,shelf,user,**changes):
    shelf=Shelf.objects.select_for_update().get(pk=shelf.pk); before=_shelf_snapshot(shelf)
    if "code" in changes:changes.pop("code")
    for field,value in changes.items(): setattr(shelf,field,value)
    shelf.updated_by=user; shelf.save(); after=_shelf_snapshot(shelf)
    event="RENAMED" if before["name"]!=after["name"] else "GEOMETRY_CHANGED" if any(before[k]!=after[k] for k in ["x","y","width","height","zone"]) else "UPDATED"
    if before["active"]!=after["active"]:event="REACTIVATED" if after["active"] else "DEACTIVATED"
    ShelfHistory.objects.create(shelf=shelf,event=event,snapshot=after,changed_by=user); _audit(f"SHELF_{event}",shelf,user,before,after); return shelf
@transaction.atomic
def archive_shelf(*,shelf,user):
    if shelf.balances.filter(quantity__gt=0).exists(): raise ValidationError("Transfer or clear stock before archiving this shelf.")
    return update_shelf(shelf=shelf,user=user,active=False)
@transaction.atomic
def receive_stock(*,variant,placements,unit_cost,reference,user=None,supplier_name=""):
    total=sum((_d(p["quantity"]) for p in placements),Decimal("0"))
    if total<=0: raise ValidationError("Received quantity must be positive.")
    lot=StockLot.objects.create(variant=variant,reference=reference,received_quantity=total,remaining_quantity=total,unit_cost=_d(unit_cost),supplier_name=supplier_name,received_at=timezone.now())
    for p in placements:
        shelf=Shelf.objects.select_for_update().get(pk=p["shelf"].pk,active=True); qty=_d(p["quantity"])
        if qty<=0:raise ValidationError("Placement quantities must be positive.")
        StockBalance.objects.create(lot=lot,shelf=shelf,quantity=qty); Movement.objects.create(variant=variant,lot=lot,quantity=qty,destination=shelf,movement_type="PURCHASE_RECEIPT",reference=reference,performed_by=user)
    _audit("STOCK_RECEIVED",lot,user,after={"quantity":str(total),"unit_cost":str(unit_cost),"reference":reference}); return lot
@transaction.atomic
def transfer_stock(*,variant,source,destination,quantity,reference,user=None):
    need=_d(quantity)
    if need<=0 or source.pk==destination.pk: raise ValidationError("Choose distinct shelves and a positive quantity.")
    rows=list(StockBalance.objects.select_for_update().select_related("lot").filter(lot__variant=variant,shelf=source,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id"))
    if sum((r.quantity-r.reserved for r in rows),Decimal("0"))<need: raise ValidationError("Insufficient available stock at source shelf.")
    original=need
    for row in rows:
        take=min(need,row.quantity-row.reserved); row.quantity-=take; row.save(update_fields=["quantity","updated_at"]); target,_=StockBalance.objects.select_for_update().get_or_create(lot=row.lot,shelf=destination,defaults={"quantity":0}); target.quantity+=take; target.save(update_fields=["quantity","updated_at"]); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=source,destination=destination,movement_type="TRANSFER",reference=reference,performed_by=user); need-=take
        if need==0: break
    _audit("STOCK_TRANSFER",source,user,after={"destination":destination.code,"quantity":str(original),"variant":variant.id})
@transaction.atomic
def reserve_stock(*,variant,quantity,reference,expires_at,user=None):
    need=_d(quantity); allocations=[]; rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","shelf_id")); available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
    if need<=0 or available<need: raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
    original=need
    for row in rows:
        take=min(need,row.quantity-row.reserved); row.reserved+=take; row.save(update_fields=["reserved","updated_at"]); allocations.append({"balance_id":row.id,"quantity":str(take),"shelf_id":row.shelf_id,"lot_id":row.lot_id}); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=row.shelf,movement_type="ORDER_RESERVATION",reference=reference,performed_by=user); need-=take
        if need==0: break
    return Reservation.objects.create(variant=variant,quantity=original,reference=reference,expires_at=expires_at,allocations=allocations)
@transaction.atomic
def release_reservation(reservation,user=None):
    reservation=Reservation.objects.select_for_update().get(pk=reservation.pk)
    if not reservation.active:return reservation
    for a in reservation.allocations:
        row=StockBalance.objects.select_for_update().get(pk=a["balance_id"]); qty=_d(a["quantity"]); row.reserved-=qty; row.save(update_fields=["reserved","updated_at"]); Movement.objects.create(variant=reservation.variant,lot=row.lot,quantity=qty,destination=row.shelf,movement_type="RESERVATION_RELEASE",reference=reservation.reference,performed_by=user)
    reservation.active=False; reservation.status=Reservation.RELEASED; reservation.save(update_fields=["active","status","updated_at"]); return reservation
@transaction.atomic
def complete_sale(*,lines,channel,number,user=None,customer=None,discount=0,payment_method="CASH",payment_status="COMPLETED",payment_reference="",idempotency_key=None):
    from apps.commerce.models import Payment,Sale,SaleAllocation,SaleItem
    if idempotency_key and Payment.objects.filter(idempotency_key=idempotency_key).exists(): return Payment.objects.get(idempotency_key=idempotency_key).sale
    sale=Sale.objects.create(number=number,channel=channel,created_by=user,customer=customer,discount=_d(discount)); subtotal=Decimal("0"); cogs=Decimal("0")
    for line in lines:
        variant=line["variant"]; qty=_d(line["quantity"]); price=variant.selling_price; subtotal+=qty*price; item=SaleItem.objects.create(sale=sale,variant=variant,quantity=qty,unit_price=price)
        if variant.product.product_type=="SERVICE":item.cost=qty*variant.service_cost; item.save(update_fields=["cost"]); cogs+=item.cost; continue
        need=qty; rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id","shelf_id")); available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
        if available<need:raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
        for row in rows:
            take=min(need,row.quantity-row.reserved); cost=take*row.lot.unit_cost; row.quantity-=take; row.save(update_fields=["quantity","updated_at"]); StockLot.objects.filter(pk=row.lot_id).update(remaining_quantity=F("remaining_quantity")-take); SaleAllocation.objects.create(item=item,lot=row.lot,shelf=row.shelf,quantity=take,unit_cost=row.lot.unit_cost); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=row.shelf,movement_type="SALE",reference=number,performed_by=user); cogs+=cost; need-=take
            if need==0:break
        item.cost=sum((a.quantity*a.unit_cost for a in item.allocations.all()),Decimal("0")); item.save(update_fields=["cost"])
    sale.subtotal=subtotal; sale.total=subtotal-_d(discount); sale.cogs=cogs; sale.gross_profit=sale.total-cogs; sale.save(); Payment.objects.create(sale=sale,method=payment_method,amount=sale.total,reference=payment_reference,status=payment_status,idempotency_key=idempotency_key or number); _audit("SALE_COMPLETED",sale,user,after={"number":number,"total":str(sale.total),"cogs":str(cogs)}); return sale
