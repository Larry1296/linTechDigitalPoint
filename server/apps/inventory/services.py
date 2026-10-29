from apps.tenancy.transactions import lock_business
from apps.tenancy.permissions import has_business_permission, is_business_manager
from decimal import Decimal, InvalidOperation
from django.db import IntegrityError,transaction
from django.db.models import F, Q
from django.utils import timezone
from uuid import uuid4
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from apps.catalog.models import ProductVariant,category_lineage
from .models import LocationHistory,Movement,Reservation,Shelf,ShelfHistory,ShelfLevel,ShelfStack,ShelfStackCategory,StockBalance,StockLot,StockReceipt,StockReceiptLine,StockReceiptPlacement,VariantPreferredLocation,Zone
def _d(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid number.") from exc
    if not result.is_finite():
        raise ValidationError("Enter a finite number.")
    return result
def _audit(action,obj,user,before=None,after=None):
    AuditLog.objects.create(action=action,object_type=obj.__class__.__name__,object_id=str(obj.pk),user=user,before=before or {},after=after or {})
def _shelf_snapshot(s): return {"code":s.code,"name":s.display_name,"zone":s.zone_id,"x":str(s.x),"y":str(s.y),"width":str(s.width),"height":str(s.height),"active":s.active}
def _stack_snapshot(stack):return {"code":stack.code,"name":stack.display_name,"zone":stack.zone_id,"x":str(stack.x),"y":str(stack.y),"width":str(stack.width),"height":str(stack.height),"depth":str(stack.depth),"rotation":str(stack.rotation),"levels":stack.number_of_levels,"active":stack.active}
def _location_history(obj,event,user):LocationHistory.objects.create(object_type=obj.__class__.__name__,object_id=obj.pk,event=event,snapshot=_stack_snapshot(obj) if isinstance(obj,ShelfStack) else {"stack":obj.stack_id,"level":obj.level_number,"height":str(obj.height),"y":str(obj.y_position),"active":obj.active},changed_by=user)
@transaction.atomic
def create_shelf_stack(*,zone,user,display_name,x,y,width,height,depth,level_definitions,rotation=0,notes=""):
    zone=Zone.objects.select_for_update().get(pk=zone.pk)
    number=ShelfStack.objects.filter(zone=zone).count()+1
    while ShelfStack.objects.filter(code=f"{zone.code}-R{number:02d}").exists():number+=1
    code=f"{zone.code}-R{number:02d}";levels_count=len(level_definitions)
    if not levels_count:raise ValidationError("At least one level is required.")
    stack=ShelfStack.objects.create(zone=zone,code=code,display_name=display_name,x=x,y=y,width=width,height=height,depth=depth,rotation=rotation,number_of_levels=levels_count,notes=notes,created_by=user,updated_by=user)
    level_height=_d(height)/levels_count
    for index,definition in enumerate(level_definitions,1):
        count=int(definition.get("compartments",0))
        if count<1:raise ValidationError(f"Level {index} requires at least one compartment.")
        level=ShelfLevel.objects.create(stack=stack,level_number=index,y_position=level_height*(index-1),height=definition.get("height") or level_height)
        _location_history(level,"LEVEL_ADDED",user)
        shelf_width=_d(width)/count
        labels=definition.get("physical_labels",[])
        for position in range(1,count+1):
            shelf=Shelf.objects.create(zone=zone,level=level,code=f"{code}-L{index:02d}-S{position:02d}",physical_label=labels[position-1] if position<=len(labels) else "",display_name=f"Level {index} Compartment {position}",position_in_level=position,x=shelf_width*(position-1),y=level.y_position,width=shelf_width,height=level.height,depth=depth,sort_order=position,created_by=user,updated_by=user)
            snapshot=_shelf_snapshot(shelf);ShelfHistory.objects.create(shelf=shelf,event="CREATED",snapshot=snapshot,changed_by=user);_audit("SHELF_CREATED",shelf,user,after=snapshot)
    snapshot=_stack_snapshot(stack);_location_history(stack,"STACK_CREATED",user);_audit("STACK_CREATED",stack,user,after=snapshot);return stack
@transaction.atomic
def update_shelf_stack(*,stack,user,**changes):
    stack=ShelfStack.objects.select_for_update().get(pk=stack.pk);before=_stack_snapshot(stack);changes.pop("code",None);changes.pop("number_of_levels",None);old_zone_id=stack.zone_id
    for field,value in changes.items():setattr(stack,field,value)
    stack.updated_by=user;stack.save()
    if old_zone_id!=stack.zone_id:Shelf.objects.filter(level__stack=stack).update(zone=stack.zone,updated_by=user)
    after=_stack_snapshot(stack);event="STACK_MOVED" if any(before[k]!=after[k] for k in ["x","y","rotation","zone"]) else "STACK_RESIZED" if any(before[k]!=after[k] for k in ["width","height","depth"]) else "STACK_UPDATED";_location_history(stack,event,user);_audit(event,stack,user,before,after);return stack
@transaction.atomic
def archive_shelf_stack(*,stack,user):
    if StockBalance.objects.filter(shelf__level__stack=stack,quantity__gt=0).exists():raise ValidationError("This shelf stack still contains stock. Transfer or clear stock before removing it.")
    stack.active=False;stack.updated_by=user;stack.save(update_fields=["active","updated_by","updated_at"]);stack.levels.update(active=False);Shelf.objects.filter(level__stack=stack).update(active=False);_location_history(stack,"STACK_DEACTIVATED",user);_audit("STACK_DEACTIVATED",stack,user);return stack
@transaction.atomic
def create_product_with_opening_stock(*,user,product_data,variant_data,preferred_shelf=None,opening_quantity=0,opening_unit_cost=0,opening_reference="OPENING"):
    lock_business()
    from django.utils.text import slugify
    from apps.catalog.models import Product,ProductVariant,check_code_free,check_price_range
    check_price_range(variant_data.get("selling_price",0),variant_data.get("minimum_price",0))
    check_code_free(variant_data.get("sku"),variant_data.get("barcode"))
    # The slug is internal: short enough for its column and unique, so long names and repeated names
    # (the same "Normal Full Charger" from two brands) never fail.
    base=(product_data.pop("slug",None) or slugify(product_data["name"]) or "product")[:44].strip("-") or "product"
    slug,number=base,1
    while Product.objects.filter(slug=slug).exists():
        number+=1;slug=f"{base}-{number}"
    product=Product.objects.create(slug=slug,**product_data);variant=ProductVariant.objects.create(product=product,**variant_data)
    if product.product_type==Product.SERVICE:preferred_shelf=None
    if preferred_shelf:VariantPreferredLocation.objects.create(variant=variant,shelf=preferred_shelf,updated_by=user)
    quantity=_d(opening_quantity)
    if product.product_type==Product.STOCK_ITEM and quantity>0:
        preferred_shelf=add_opening_stock(variant=variant,user=user,quantity=quantity,unit_cost=opening_unit_cost,reference=opening_reference,shelf=preferred_shelf).balances.get().shelf
    _audit("PRODUCT_CREATED",product,user,after={"variant":variant.id,"preferred_shelf":preferred_shelf.id if preferred_shelf else None,"opening_quantity":str(quantity)});return product,variant
def add_opening_stock(*,variant,user,quantity,unit_cost=0,reference="OPENING",shelf=None):
    """Stock the business already owned: valued against opening equity, never a supplier debt."""
    quantity=_d(quantity); unit_cost=_d(unit_cost or 0)
    if quantity<=0:raise ValidationError("Opening quantity must be greater than zero.")
    if unit_cost<0:raise ValidationError("Opening buying price cannot be negative.")
    if not shelf:
        preferred=VariantPreferredLocation.objects.filter(variant=variant,shelf__active=True).select_related("shelf").first()
        if preferred:shelf=preferred.shelf
        else:
            from .unplaced import unplaced_shelf
            shelf=unplaced_shelf()
    # Stock already owned with an unknown buying price is flagged, never valued at an assumed zero.
    lot=StockLot.objects.create(variant=variant,reference=reference,received_quantity=quantity,remaining_quantity=quantity,unit_cost=unit_cost,received_at=timezone.now(),
        cost_status=StockLot.COSTED if unit_cost>0 else StockLot.UNCOSTED);StockBalance.objects.create(lot=lot,shelf=shelf,quantity=quantity);Movement.objects.create(variant=variant,lot=lot,quantity=quantity,destination=shelf,movement_type="OPENING_STOCK",reference=reference,performed_by=user)
    if lot.unit_cost:
        from apps.accounting.ledger import post_journal, paired
        post_journal(key=f'opening-stock:{lot.pk}', description=reference,
            branch=shelf.zone.store_id, user=user,
            lines=paired('1200', '3000', quantity * lot.unit_cost))
    return lot
def product_history(product):
    """Why a product can't be deleted, or "" when its only history is opening stock entered with it."""
    from apps.commerce.models import OrderItem,SaleItem
    from .models import StockAdjustment
    variants=product.variants.all()
    if SaleItem.objects.filter(variant__in=variants).exists():return "it has been sold"
    if OrderItem.objects.filter(variant__in=variants).exists():return "it is on customer orders"
    if StockReceiptLine.objects.filter(variant__in=variants).exists():return "stock deliveries were recorded for it"
    if StockAdjustment.objects.filter(variant__in=variants).exists() or Reservation.objects.filter(variant__in=variants).exists():return "stock adjustments or reservations were recorded for it"
    if Movement.objects.filter(variant__in=variants).exclude(movement_type="OPENING_STOCK").exists():return "its stock has been moved or used"
    if StockLot.objects.filter(variant__in=variants).exclude(remaining_quantity=F("received_quantity")).exists():return "some of its stock has been used"
    from apps.cyber.models import CyberJobLine,CyberServiceProfile,ServiceMaterialRequirement
    if CyberJobLine.objects.filter(variant__in=variants).exists() or CyberServiceProfile.objects.filter(variant__in=variants).exists() or ServiceMaterialRequirement.objects.filter(Q(service_variant__in=variants)|Q(material_variant__in=variants)).exists():return "it is set up as a service or service material"
    return ""


@transaction.atomic
def delete_unused_product(product,user):
    """Deletes a product entered by mistake. Its opening stock value is reversed in the books; anything
    with real history (sales, deliveries, moves) is refused so the accounts stay complete."""
    lock_business()
    reason=product_history(product)
    if reason:
        raise ValidationError(f"{product.name} can't be deleted because {reason}. Open it and untick Active to hide it instead.")
    from apps.accounting.models import JournalEntry
    from apps.accounting.ledger import reverse_journal
    lots=list(StockLot.objects.filter(variant__product=product))
    value=Decimal("0")
    for lot in lots:
        entry=JournalEntry.objects.filter(source_key=f"opening-stock:{lot.pk}").first()
        if entry:
            reverse_journal(entry,user=user,reason=f"Product deleted: {product.name}",key=f"opening-stock-deleted:{lot.pk}")
            value+=lot.received_quantity*lot.unit_cost
    Movement.objects.filter(lot__in=lots).delete();StockBalance.objects.filter(lot__in=lots).delete();StockLot.objects.filter(pk__in=[l.pk for l in lots]).delete()
    _audit("PRODUCT_DELETED",product,user,before={"name":product.name,"skus":list(product.variants.values_list("sku",flat=True)),
        "opening_quantity":str(sum((l.received_quantity for l in lots),Decimal("0"))),"opening_value":str(value)})
    product.delete()


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
    lock_business()
    reference=(reference or "").strip() or f"RCV-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}"
    total=sum((_d(p["quantity"]) for p in placements),Decimal("0"))
    if total<=0: raise ValidationError("Received quantity must be positive.")
    lot=StockLot.objects.create(variant=variant,reference=reference,received_quantity=total,remaining_quantity=total,unit_cost=_d(unit_cost),supplier_name=supplier_name,received_at=timezone.now())
    for p in placements:
        shelf=Shelf.objects.select_for_update().get(pk=p["shelf"].pk,active=True); qty=_d(p["quantity"])
        if qty<=0:raise ValidationError("Placement quantities must be positive.")
        StockBalance.objects.create(lot=lot,shelf=shelf,quantity=qty); Movement.objects.create(variant=variant,lot=lot,quantity=qty,destination=shelf,movement_type="PURCHASE_RECEIPT",reference=reference,performed_by=user)
    from apps.accounting.ledger import post_journal, paired
    branches = {p['shelf'].zone.store_id for p in placements}
    if len(branches) != 1:
        raise ValidationError('Receive stock into one branch, then record a transfer.')
    if lot.unit_cost:
        post_journal(key=f'lot:{lot.pk}', description=reference, branch=branches.pop(), user=user,
            lines=paired('1200', '2000', total * lot.unit_cost))
    _audit("STOCK_RECEIVED",lot,user,after={"quantity":str(total),"unit_cost":str(unit_cost),"reference":reference}); return lot

LANDED_PAID_BY = {"SUPPLIER_INVOICE", "CASH", "MPESA", "BANK", "OTHER"}


def _landed_costs(raw_costs):
    costs = []
    for index, raw in enumerate(raw_costs or []):
        amount = _d(raw.get("amount"))
        description = str(raw.get("description") or "").strip()
        paid_by = str(raw.get("paid_by") or "SUPPLIER_INVOICE").upper()
        if not description or amount <= 0:
            raise ValidationError({f"landed_costs[{index}]": "Describe each delivery cost and enter an amount above zero."})
        if paid_by not in LANDED_PAID_BY:
            raise ValidationError({f"landed_costs[{index}].paid_by": "Choose how this cost was paid."})
        costs.append({"description": description[:160], "amount": str(amount.quantize(Decimal("0.01"))), "paid_by": paid_by})
    return costs


@transaction.atomic
def complete_stock_receipt(*, supplier_name="", external_reference="", received_at=None, notes="", lines=(), user=None, idempotency_key=None,
                           document_status="SUPPLIER_DOCUMENT", landed_costs=(), payment=None, require_documents=False):
    """Create a complete receipt, its cost layers and its accounting, atomically.

    Buying price (BP) is required for every line. A line may be recorded as *uncosted* only on an
    opening-balance receipt, by someone allowed to adjust stock; it is then flagged until its cost is
    supplied (see correct_lot_cost). Delivery and other directly attributable costs are allocated to
    lines by value: lot unit cost = BP + landed cost per unit. The invoice BP is preserved on the line.
    """
    from apps.tenancy.permissions import has_business_permission
    lock_business()
    if idempotency_key:
        existing=StockReceipt.objects.filter(idempotency_key=idempotency_key).first()
        if existing:return existing
    if not lines:raise ValidationError({"lines":"At least one receipt line is required."})
    if document_status not in {StockReceipt.SUPPLIER_DOCUMENT, StockReceipt.NO_DOCUMENT, StockReceipt.OPENING_BALANCE}:
        raise ValidationError({"document_status":"Choose the kind of receipt document."})
    if require_documents and document_status != StockReceipt.OPENING_BALANCE:
        if not (supplier_name or "").strip():raise ValidationError({"supplier_name":"Enter the supplier."})
        if document_status == StockReceipt.SUPPLIER_DOCUMENT and not (external_reference or "").strip():
            raise ValidationError({"external_reference":"Enter the supplier's invoice or delivery note number, or choose 'No supplier document'."})
    landed = _landed_costs(landed_costs)
    if landed and document_status == StockReceipt.OPENING_BALANCE:
        raise ValidationError({"landed_costs":"Opening stock balances do not carry delivery costs."})
    for index, raw in enumerate(lines):
        uncosted = bool(raw.get("uncosted"))
        if uncosted:
            if document_status != StockReceipt.OPENING_BALANCE:
                raise ValidationError({f"lines[{index}].unit_cost":"Only opening stock balances may be recorded without a buying price."})
            if not user or not has_business_permission(user, "inventory.adjust_stock"):
                raise ValidationError({f"lines[{index}].unit_cost":"Recording stock without a buying price needs stock-adjustment permission."})
        elif _d(raw.get("unit_cost")) <= 0:
            raise ValidationError({f"lines[{index}].unit_cost":"Enter the buying price for one unit. If it is genuinely unknown, record the stock as an uncosted opening balance."})
    received_at=received_at or timezone.now()
    reference=(external_reference or "").strip() or f"RCV-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}"
    if StockReceipt.objects.filter(receipt_number=reference).exists():
        raise ValidationError({"external_reference":"This receipt reference already exists."})
    receipt=StockReceipt.objects.create(receipt_number=reference,external_reference=external_reference or "",supplier_name=(supplier_name or "").strip(),received_at=received_at,notes=notes or "",created_by=user,idempotency_key=idempotency_key,
        document_status=document_status,landed_costs=landed,landed_cost_total=sum((_d(c["amount"]) for c in landed),Decimal("0")))
    # Landed cost shares by line value (quantity × BP); the last costed line takes the rounding remainder.
    values=[Decimal("0") if raw.get("uncosted") else _d(raw.get("received_quantity"))*_d(raw.get("unit_cost")) for raw in lines]
    landed_shares=[Decimal("0")]*len(lines)
    if receipt.landed_cost_total:
        # Delivery costs may exceed the goods' value (e.g. transport for a small order); they are never a discount.
        from apps.commerce.pricing import allocate_by_value
        costed=[i for i,v in enumerate(values) if v>0]
        if not costed:raise ValidationError({"landed_costs":"Delivery costs need at least one item with a buying price to be added to."})
        for i,share in zip(costed,allocate_by_value([values[i] for i in costed],receipt.landed_cost_total)):
            landed_shares[i]=share
        receipt.landed_allocation_note=("Delivery and other direct costs of "+str(receipt.landed_cost_total)+" allocated to lines in proportion to quantity × buying price.")
        receipt.save(update_fields=["landed_allocation_note","updated_at"])
    for index, raw in enumerate(lines):
        variant=ProductVariant.objects.select_for_update().select_related("product").filter(pk=raw.get("variant_id"),active=True,product__active=True,product__product_type=ProductVariant._meta.get_field("product").remote_field.model.STOCK_ITEM).first()
        if not variant:raise ValidationError({f"lines[{index}].variant_id":"Choose an active stock-item variant."})
        qty=_d(raw.get("received_quantity")); cost=_d(raw.get("unit_cost") or 0)
        if qty<=0:raise ValidationError({f"lines[{index}].received_quantity":"Quantity must be greater than zero."})
        if cost<0:raise ValidationError({f"lines[{index}].unit_cost":"Buying price cannot be negative."})
        placements=raw.get("placements") or []
        if not placements:
            from .unplaced import unplaced_shelf
            placements = [{'shelf_id': unplaced_shelf().pk, 'quantity': qty}]
        total=sum((_d(p.get("quantity")) for p in placements),Decimal("0"))
        if total!=qty:raise ValidationError({f"lines[{index}].placements":"Placement quantities must equal received quantity."})
        shelves=[]
        for pidx,p in enumerate(placements):
            pqty=_d(p.get("quantity"))
            if pqty<=0:raise ValidationError({f"lines[{index}].placements[{pidx}].quantity":"Placement quantity must be greater than zero."})
            shelf=Shelf.objects.select_for_update(of=("self",)).select_related("zone","level__stack").filter(pk=p.get("shelf_id"),active=True,zone__active=True).filter(Q(is_virtual=True) | Q(level__active=True,level__stack__active=True)).first()
            if not shelf:raise ValidationError({f"lines[{index}].placements[{pidx}].shelf_id":"Choose an active exact compartment."})
            if not shelf.is_virtual and not ShelfStackCategory.objects.filter(stack_id=shelf.level.stack_id,stack__zone__active=True,category_id__in=category_lineage(variant.product.category_id),category__active=True).exists():
                raise ValidationError({f"lines[{index}].placements[{pidx}].shelf_id":"This rack is not assigned to the product category."})
            shelves.append((shelf,pqty))
        update_price=bool(raw.get("update_selling_price")); new_price=raw.get("new_selling_price")
        if update_price:
            if not user or not has_business_permission(user, "catalog.change_productvariant"):raise ValidationError({f"lines[{index}].new_selling_price":"Price-change permission required."})
            if new_price in (None,""):raise ValidationError({f"lines[{index}].new_selling_price":"Enter the new selling price."})
            new_price=_d(new_price); previous=variant.selling_price
            if new_price<variant.minimum_price:raise ValidationError({f"lines[{index}].new_selling_price":f"{variant.product.name}: the new selling price cannot be below its lowest price ({variant.minimum_price})."})
        else:previous=None;new_price=None
        uncosted=bool(raw.get("uncosted")); landed_line=landed_shares[index]
        landed_unit=(landed_line/qty).quantize(Decimal("0.0001")) if landed_line else Decimal("0")
        line=StockReceiptLine.objects.create(receipt=receipt,variant=variant,received_quantity=qty,unit_cost=Decimal("0") if uncosted else cost,previous_selling_price=previous,new_selling_price=new_price,landed_cost=landed_line,uncosted=uncosted)
        lot=StockLot.objects.create(variant=variant,reference=reference,received_quantity=qty,remaining_quantity=qty,unit_cost=Decimal("0") if uncosted else cost+landed_unit,landed_unit_cost=landed_unit,
            cost_status=StockLot.UNCOSTED if uncosted else StockLot.COSTED,supplier_name=(supplier_name or "").strip(),received_at=received_at)
        line.lot=lot;line.save(update_fields=["lot","updated_at"])
        for shelf,pqty in shelves:
            balance=StockBalance.objects.create(lot=lot,shelf=shelf,quantity=pqty)
            StockReceiptPlacement.objects.create(line=line,shelf=shelf,quantity=pqty,balance=balance)
            Movement.objects.create(variant=variant,lot=lot,quantity=pqty,destination=shelf,movement_type="PURCHASE_RECEIPT",reference=reference,performed_by=user)
        if not VariantPreferredLocation.objects.filter(variant=variant).exists():VariantPreferredLocation.objects.create(variant=variant,shelf=shelves[0][0],updated_by=user)
        if update_price:
            variant.selling_price=new_price;variant.save(update_fields=["selling_price","updated_at"])
            from apps.catalog.models import PriceHistory
            PriceHistory.objects.create(variant=variant,price=new_price,changed_by=user)
            _audit("PRICE_CHANGED",variant,user,before={"price":str(previous)},after={"price":str(new_price)})
    _audit("STOCK_RECEIPT_COMPLETED",receipt,user,after={"receipt_number":receipt.receipt_number,"lines":receipt.lines.count()})
    if document_status == StockReceipt.OPENING_BALANCE:
        # Stock the business already owned: valued against opening equity, never a purchase or a supplier debt.
        if payment and _d(payment.get("amount") or 0) > 0:
            raise ValidationError({"payment":"Opening stock is stock you already own; there is no supplier to pay."})
        if receipt.landed_cost_total:
            # Delivery costs would raise the stock layers' cost with nothing in the books to match.
            raise ValidationError({"landed_costs":"Opening stock has no delivery costs; include them in each item's buying price instead."})
        value=sum((line.received_quantity*line.unit_cost for line in receipt.lines.all() if not line.uncosted),Decimal("0"))
        if value:
            from apps.accounting.ledger import post_journal, paired
            post_journal(key=f"opening-receipt:{receipt.pk}",description=f"Opening stock {receipt.receipt_number}",branch=receipt.branch_id,
                date=timezone.localtime(receipt.received_at).date(),user=user,lines=paired("1200","3000",value))
        return receipt
    from apps.accounting.services import link_receipt, pay_purchase
    purchase=link_receipt(receipt)
    if payment and _d(payment.get("amount") or 0) > 0:
        method=str(payment.get("method") or "CASH").upper()
        if method=="INVESTMENT":
            # Paid with money taken out of an MMF or similar, through M-Pesa or the bank.
            from apps.accounting.investments import pay_supplier
            pay_supplier(investment_id=payment.get("investment_id"), purchase=purchase, amount=_d(payment["amount"]), via=payment.get("via"),
                         key=f"receipt:{receipt.receipt_number}", user=user, reference=str(payment.get("reference") or ""))
        elif method=="OWNER":
            # Out of the owner's own pocket: owner money put into the business and paid straight on to the supplier.
            from apps.accounting.supplier_settlement import pay_supplier as settle
            settle(receipt=receipt, amount=_d(payment["amount"]), source="OWNER", user=user, key=f"receipt:{receipt.receipt_number}",
                   paid_on=timezone.localtime(receipt.received_at).date(), reference=str(payment.get("reference") or ""))
        else:
            pay_purchase(purchase=purchase, amount=_d(payment["amount"]), method=method,
                         key=f"receipt:{receipt.receipt_number}", user=user, reference=str(payment.get("reference") or ""))
    return receipt
@transaction.atomic
def _transfer_stock(*,variant,source,destination,quantity,reference,user=None):
    lock_business()
    need=_d(quantity)
    if need<=0 or source.pk==destination.pk: raise ValidationError("Choose distinct shelves and a positive quantity.")
    source_store_id = getattr(getattr(source, "zone", None), "store_id", None)
    destination_store_id = getattr(getattr(destination, "zone", None), "store_id", None)
    if not source_store_id or not destination_store_id or source.zone.store.organization_id != destination.zone.store.organization_id:
        raise ValidationError("Choose shelves belonging to valid branches in the active business.")
    rows=list(StockBalance.objects.select_for_update().select_related("lot").filter(lot__variant=variant,shelf=source,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id"))
    if sum((r.quantity-r.reserved for r in rows),Decimal("0"))<need: raise ValidationError("Insufficient available stock at source shelf.")
    original=need
    transferred_cost = Decimal(0)
    for row in rows:
        take=min(need,row.quantity-row.reserved); transferred_cost += take * row.lot.unit_cost; row.quantity-=take; row.save(update_fields=["quantity","updated_at"]); target,_=StockBalance.objects.select_for_update().get_or_create(lot=row.lot,shelf=destination,defaults={"quantity":0}); target.quantity+=take; target.save(update_fields=["quantity","updated_at"]); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=source,destination=destination,movement_type="TRANSFER",reference=reference,performed_by=user); need-=take
        if need==0: break
    if source_store_id != destination_store_id and transferred_cost:
        from apps.accounting.ledger import post_journal, paired
        transfer_key = uuid4().hex
        post_journal(key=f'transfer:{transfer_key}:out', description=f'Stock transfer {reference}',
            branch=source_store_id, user=user, lines=paired('1250', '1200', transferred_cost))
        post_journal(key=f'transfer:{transfer_key}:in', description=f'Stock transfer {reference}',
            branch=destination_store_id, user=user, lines=paired('1200', '1250', transferred_cost))
    _audit("STOCK_TRANSFER",source,user,after={"destination":destination.code,"source_branch_id":source_store_id,"destination_branch_id":destination_store_id,"quantity":str(original),"variant":variant.id})
@transaction.atomic
def reserve_stock(*,variant,quantity,reference,expires_at,user=None):
    need=_d(quantity); allocations=[]; rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","shelf_id")); available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
    if need<=0 or available<need: raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
    original=need
    transferred_cost = Decimal(0)
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


def consume_stock_fifo(*, variant, quantity, reference, movement_type, user=None):
    """Consume unreserved stock under the caller's transaction and return actual FIFO cost."""
    need = _d(quantity)
    rows = list(
        StockBalance.objects.select_for_update()
        .select_related("lot", "shelf")
        .filter(lot__variant=variant, quantity__gt=F("reserved"))
        .order_by("lot__received_at", "lot_id", "shelf_id")
    )
    available = sum((row.quantity - row.reserved for row in rows), Decimal("0"))
    if need <= 0 or available < need:
        raise ValidationError(f"Only {available} units of {variant} are available. Requested quantity: {need}.")
    cost = Decimal("0")
    for row in rows:
        take = min(need, row.quantity - row.reserved)
        row.quantity -= take
        row.save(update_fields=["quantity", "updated_at"])
        StockLot.objects.filter(pk=row.lot_id).update(remaining_quantity=F("remaining_quantity") - take)
        Movement.objects.create(
            variant=variant,
            lot=row.lot,
            quantity=take,
            source=row.shelf,
            movement_type=movement_type,
            reference=reference,
            performed_by=user,
        )
        cost += take * row.lot.unit_cost
        need -= take
        if need == 0:
            break
    return cost


def service_tool_on(variant, enabled):
    """Whether the tool that sells this service is on: a dish needs the menu, a room night the rooms, any other the services."""
    from apps.hotel.models import MenuItem, RoomType
    if MenuItem.objects.filter(variant_id=variant.pk).exists():
        return "menu" in enabled
    if RoomType.objects.filter(variant_id=variant.pk).exists():
        return "rooms" in enabled
    return "services" in enabled


@transaction.atomic
def complete_sale(*,lines,channel,number,user=None,customer=None,discount=0,discount_reason="",payment_method="CASH",payment_status="COMPLETED",payment_reference="",idempotency_key=None,paid_amount=None,due_date=None,allow_below_cost=False,require_customer_for_balance=False):
    """Completes a sale from actual agreed prices and FIFO cost layers; see apps/commerce/pricing.py.

    Each line may carry ``unit_price`` (the agreed price; defaults to the catalogue price), ``discount``
    and ``discount_reason``. Revenue is recognised now; unpaid amounts stay owed by the customer.
    """
    from apps.commerce.models import Payment,Sale,SaleAllocation,SaleItem
    from apps.commerce.pricing import cents, price_line, spread_discount, tax_config
    from apps.tenancy.models import Organization
    from apps.tenancy.context import organization_id
    from apps.tenancy.middleware import effective_modules
    from apps.tenancy.permissions import has_business_permission
    organization = Organization.objects.select_for_update().get(pk=organization_id())
    if idempotency_key:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            requested = sorted((line['variant'].pk, _d(line['quantity'])) for line in lines)
            recorded = sorted(existing.items.values_list('variant_id','quantity'))
            if requested != recorded or existing.customer_id != getattr(customer,'pk',None):
                raise ValidationError('Sale request key already used for different details.')
            return existing
    if idempotency_key and Payment.objects.filter(idempotency_key=idempotency_key).exists(): return Payment.objects.get(idempotency_key=idempotency_key).sale
    if not lines:
        raise ValidationError("Add at least one sale line.")
    enabled = effective_modules(organization)
    tax = tax_config(organization)
    specs = []
    for line in lines:
        variant = ProductVariant.objects.select_related("product").get(pk=line["variant"].pk)
        qty = _d(line["quantity"])
        if qty <= 0 or not variant.active or not variant.product.active:
            raise ValidationError("Choose an active item and a positive quantity.")
        if variant.product.product_type == "SERVICE" and not service_tool_on(variant, enabled):
            raise ValidationError("Services are not enabled for this business.")
        if variant.product.product_type != "SERVICE" and "inventory" not in enabled:
            raise ValidationError("Products & stock are not enabled for this business.")
        agreed = cents(_d(line["unit_price"])) if line.get("unit_price") not in (None, "") else variant.selling_price
        if agreed < 0:
            raise ValidationError("A selling price cannot be negative.")
        specs.append({"variant": variant, "qty": qty, "list": variant.selling_price, "price": agreed,
                      "discount": cents(_d(line.get("discount") or 0)), "reason": (line.get("discount_reason") or "").strip()})
    # A whole-sale discount is spread across lines by value so every line's profit is exact.
    shares = spread_discount([cents(spec["qty"] * spec["price"]) - spec["discount"] for spec in specs], _d(discount))
    for spec, share in zip(specs, shares):
        spec["discount"] += share
        if share and not spec["reason"]:
            spec["reason"] = discount_reason.strip()
    sale=Sale.objects.create(number=number,channel=channel,created_by=user,customer=customer,idempotency_key=idempotency_key,due_date=due_date)
    totals = {"gross": Decimal("0"), "discount": Decimal("0"), "tax": Decimal("0"), "net": Decimal("0"), "payable": Decimal("0"), "cogs": Decimal("0")}
    below_cost = []
    for spec in specs:
        variant, qty = spec["variant"], spec["qty"]
        money_ = price_line(qty, spec["price"], spec["discount"], tax)
        item=SaleItem.objects.create(sale=sale,variant=variant,quantity=qty,list_price=spec["list"],unit_price=spec["price"],
            discount=money_["discount"],discount_reason=spec["reason"],tax_amount=money_["tax"],net_amount=money_["net"])
        if variant.product.product_type=="SERVICE":
            item.cost=cents(qty*variant.service_cost)
        else:
            need=qty; rows=list(StockBalance.objects.select_for_update().select_related("lot","shelf").filter(lot__variant=variant,quantity__gt=F("reserved")).order_by("lot__received_at","lot_id","shelf_id")); available=sum((r.quantity-r.reserved for r in rows),Decimal("0"))
            if available<need:raise ValidationError(f"Only {available} units are available. Requested quantity: {need}.")
            for row in rows:
                take=min(need,row.quantity-row.reserved); row.quantity-=take; row.save(update_fields=["quantity","updated_at"]); StockLot.objects.filter(pk=row.lot_id).update(remaining_quantity=F("remaining_quantity")-take); SaleAllocation.objects.create(item=item,lot=row.lot,shelf=row.shelf,quantity=take,unit_cost=row.lot.unit_cost); Movement.objects.create(variant=variant,lot=row.lot,quantity=take,source=row.shelf,movement_type="SALE",reference=number,performed_by=user); need-=take
                if row.lot.cost_status==StockLot.UNCOSTED: item.cost_pending=True
                if need==0:break
            item.cost=cents(sum((a.quantity*a.unit_cost for a in item.allocations.all()),Decimal("0")))
        item.save(update_fields=["cost","cost_pending"])
        if not item.cost_pending and item.net_amount < item.cost:
            below_cost.append(f"{variant}: sold for {item.net_amount} but its recorded cost is {item.cost}")
        for key, value in [("gross", money_["gross"]), ("discount", money_["discount"]), ("tax", money_["tax"]), ("net", money_["net"]), ("payable", money_["payable"]), ("cogs", item.cost)]:
            totals[key] += value
    if below_cost:
        if not (allow_below_cost and user and has_business_permission(user, "commerce.sell_below_cost")):
            raise ValidationError({"code": "below_cost", "below_cost": below_cost,
                                   "detail": "This sale is below buying cost (" + "; ".join(below_cost) + "). Only someone allowed to sell at a loss can confirm it."})
        _audit("SALE_BELOW_COST",sale,user,after={"number":number,"lines":below_cost})
    from apps.accounting.ledger import post_sale
    sale.subtotal=totals["gross"]; sale.discount=totals["discount"]; sale.tax_total=totals["tax"]; sale.net_total=totals["net"]
    sale.total=totals["payable"]; sale.cogs=totals["cogs"]; sale.gross_profit=sale.net_total-sale.cogs
    sale.cost_pending=sale.items.filter(cost_pending=True).exists(); sale.save(); post_sale(sale)
    payment_amount=sale.total if paid_amount is None else _d(paid_amount)
    if payment_amount < 0 or payment_amount > sale.total:raise ValidationError("Payment must be between zero and the sale total.")
    if require_customer_for_balance and payment_amount<sale.total and customer is None:
        raise ValidationError(f"{sale.total-payment_amount} will still be owed. Choose the customer who owes it (or add them) instead of Walk-in customer.")
    if payment_amount:
        # M-Pesa with the code from its SMS is confirmed at once; without a code it waits for confirmation.
        from apps.commerce.settlements import mpesa_code
        code=mpesa_code(payment_method,payment_reference)
        Payment.objects.create(sale=sale,method=payment_method,amount=payment_amount,reference=payment_reference,provider_transaction_id=code,
            status="COMPLETED" if code else payment_status,idempotency_key=idempotency_key or number)
    _audit("SALE_COMPLETED",sale,user,after={"number":number,"total":str(sale.total),"net":str(sale.net_total),"cogs":str(sale.cogs)}); return sale


@transaction.atomic
def transfer_stock(*, variant, source, destination, quantity, reference, user=None):
    from apps.tenancy.context import branch_context
    from apps.tenancy.branches import authorized_stores
    from apps.tenancy.permissions import membership_for
    with branch_context(None):
        membership = membership_for(user)
        allowed = authorized_stores(user, membership)
        if not allowed.filter(pk=source.zone.store_id).exists() or not allowed.filter(pk=destination.zone.store_id).exists():
            raise ValidationError('You need access to both branches for this transfer.')
        return _transfer_stock(variant=variant, source=source, destination=destination,
            quantity=quantity, reference=reference, user=user)
