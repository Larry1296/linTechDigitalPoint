from decimal import Decimal
from apps.tenancy.permissions import has_business_permission, is_business_manager
from django.db.models import DecimalField,ExpressionWrapper,F,Sum,Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from apps.catalog.models import Category,ProductVariant
from apps.commerce.models import Order,Sale,SaleItem
from apps.cyber.models import CyberJob,CyberJobLine
from apps.mpesa.models import MpesaCommissionEntry,MpesaSession,MpesaTransaction
from apps.mpesa.services import session_balances
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from .models import Shelf, ShelfStackCategory,StockBalance,StockLot,StockReceipt,StockReceiptLine,Zone
from .services import complete_stock_receipt,receive_stock,transfer_stock
from apps.accounting.supplier_settlement import receipt_balance
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def receive(request):
    if not has_business_permission(request.user, "inventory.add_stocklot"):return Response({"detail":"Receiving permission required."},status=403)
    variant=ProductVariant.objects.select_related("product").filter(pk=request.data.get("variant_id"),active=True,product__active=True,product__product_type="STOCK_ITEM").first()
    if not variant:return Response({"detail":"Choose an active stock-item product variant."},status=400)
    placements=[{"shelf_id":raw.get("shelf_id"),"quantity":raw.get("quantity")} for raw in request.data.get("placements",[])]
    requested_price=request.data.get("selling_price")
    if requested_price is not None and str(variant.selling_price)!=str(requested_price) and not has_business_permission(request.user, "catalog.change_productvariant"):
        return Response({"detail":"Price-change permission required."},status=403)
    # A single-item receipt goes through the full receipt rules (supplier, document, buying price) so its
    # supplier debt has a purchase record that can be paid and reconciled.
    try:
        receipt=complete_stock_receipt(supplier_name=request.data.get("supplier_name",""),external_reference=request.data.get("reference") or "",
            document_status=request.data.get("document_status") or "SUPPLIER_DOCUMENT",user=request.user,require_documents=True,
            idempotency_key=request.data.get("idempotency_key"),
            lines=[{"variant_id":variant.pk,"received_quantity":sum((Decimal(str(p["quantity"] or 0)) for p in placements),Decimal("0")),
                    "unit_cost":request.data.get("unit_cost"),"placements":placements}])
    except ValidationError as exc:return Response(exc.detail,status=400)
    lot=receipt.lines.get().lot
    if requested_price is not None and str(variant.selling_price)!=str(requested_price):
        from apps.catalog.models import PriceHistory
        old=variant.selling_price;variant.selling_price=requested_price;variant.save(update_fields=["selling_price","updated_at"])
        PriceHistory.objects.create(variant=variant,price=variant.selling_price,changed_by=request.user)
        from apps.core.models import AuditLog
        AuditLog.objects.create(action="PRICE_CHANGED",object_type="ProductVariant",object_id=str(variant.pk),user=request.user,before={"price":str(old)},after={"price":str(variant.selling_price)})
    return Response({"lot_id":lot.id,"quantity":lot.received_quantity,"reference":lot.reference},status=201)

def _receipt_data(receipt):
    lines = receipt.lines.select_related("variant__product").prefetch_related(
        "placements__shelf__zone", "placements__shelf__level__stack", "corrections__performed_by",
    )
    return {
        "id": receipt.id, "receipt_number": receipt.receipt_number,
        "external_reference": receipt.external_reference, "supplier_name": receipt.supplier_name,
        "received_at": receipt.received_at, "notes": receipt.notes, "created_at": receipt.created_at,
        "document_status": receipt.document_status, "supplier": receipt_balance(receipt),
        "lines": [{
            "id": line.id, "updated_at": line.updated_at, "variant_id": line.variant_id,
            "product_name": line.variant.product.name, "variant_name": line.variant.name,
            "sku": line.variant.sku, "quantity": line.received_quantity, "unit_cost": line.unit_cost,
            "selling_price": line.variant.selling_price, "line_cost": line.received_quantity * line.unit_cost,
            "placements": [{
                "shelf_id": p.shelf_id, "code": p.shelf.code, "name": p.shelf.display_name,
                "zone": p.shelf.zone.name,
                "stack": p.shelf.level.stack.display_name if p.shelf.level_id else None,
                "level": p.shelf.level.level_number if p.shelf.level_id else None, "quantity": p.quantity,
            } for p in line.placements.all()],
            "corrections": [{
                "id": c.id, "reason": c.reason, "before": c.before, "after": c.after,
                "created_at": c.created_at, "administrator": c.performed_by.get_username(),
            } for c in line.corrections.all()],
        } for line in lines],
    }

@api_view(["GET","POST"])
@permission_classes([HasLinTechPermission])
def receipts(request):
    if request.method=="GET":
        if not has_business_permission(request.user, "inventory.view_stockreceipt"):return Response({"detail":"Receipt history permission required."},status=403)
        from apps.accounting.services import purchase_outstanding
        rows=StockReceipt.objects.prefetch_related("lines").select_related("purchase").order_by("-received_at", "-pk")[:100]
        # What each receipt still owes its supplier, so an unpaid one is easy to find and clear.
        owed=lambda r:purchase_outstanding(r.purchase) if hasattr(r,"purchase") else Decimal("0")
        return Response([{"id":r.id,"receipt_number":r.receipt_number,"supplier_name":r.supplier_name,"received_at":r.received_at,"total_units":sum((l.received_quantity for l in r.lines.all()),0),"line_count":r.lines.count(),"owed":owed(r)} for r in rows])
    if not has_business_permission(request.user, "inventory.add_stockreceipt"):return Response({"detail":"Receiving permission required."},status=403)
    try:
        receipt=complete_stock_receipt(supplier_name=request.data.get("supplier_name",""),external_reference=request.data.get("external_reference",request.data.get("reference","")),received_at=request.data.get("received_at") or timezone.now(),notes=request.data.get("notes",""),lines=request.data.get("lines",[]),user=request.user,idempotency_key=request.data.get("idempotency_key"),
            document_status=request.data.get("document_status") or "SUPPLIER_DOCUMENT",landed_costs=request.data.get("landed_costs") or [],payment=request.data.get("payment") or None,require_documents=True)
    except ValidationError as exc:return Response(exc.detail,status=400)
    return Response(_receipt_data(receipt),status=200 if request.data.get("idempotency_key") and receipt.created_by_id==request.user.id else 201)

@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def receipt_detail(request,pk):
    if not has_business_permission(request.user, "inventory.view_stockreceipt"):return Response({"detail":"Receipt detail permission required."},status=403)
    receipt=StockReceipt.objects.filter(pk=pk).first()
    if not receipt:return Response({"detail":"Receipt not found."},status=404)
    return Response(_receipt_data(receipt))

@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def variant_search(request):
    q=(request.query_params.get("q") or "").strip()
    qs=ProductVariant.objects.select_related("product","product__category","product__brand").filter(active=True,product__active=True,product__product_type="STOCK_ITEM")
    if q:qs=qs.filter(Q(name__icontains=q)|Q(product__name__icontains=q)|Q(sku__icontains=q)|Q(barcode__icontains=q)|Q(product__brand__name__icontains=q)|Q(product__category__name__icontains=q))
    # Live stock, limited to the balances this user's branch can see.
    qs=qs.annotate(on_hand=Sum(F("lots__balances__quantity")-F("lots__balances__reserved"),filter=Q(lots__balances__in=StockBalance.objects.all()))).order_by("product__name","name","id")
    return Response([{"id":v.id,"product_name":v.product.name,"variant_name":v.name,"sku":v.sku,"barcode":v.barcode,"brand":v.product.brand.name if v.product.brand else "","category":v.product.category.name,"category_id":v.product.category_id,"selling_price":v.selling_price,"pack_size":v.pack_size,"piece_name":v.piece_name,"available":v.on_hand or Decimal("0")} for v in qs[:50]])

@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def available_categories(request):
    if not has_business_permission(request.user, "catalog.view_category"):return Response({"detail":"Category permission required."},status=403)
    from apps.catalog.models import category_tree
    return Response(category_tree())
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def transfer(request):
    if not has_business_permission(request.user, "inventory.change_stockbalance"):return Response({"detail":"Transfer permission required."},status=403)
    from apps.tenancy.context import branch_context
    from apps.tenancy.branches import authorized_stores
    variant=ProductVariant.objects.filter(pk=request.data.get("variant_id")).first()
    source=Shelf.objects.filter(pk=request.data.get("source_id")).select_related("zone__store").first()
    with branch_context(None):
        destination=Shelf.objects.filter(pk=request.data.get("destination_id"), zone__store__in=authorized_stores(request.user,request.membership)).select_related("zone__store").first()
    if not variant or not source or not destination:return Response({"detail":"Choose valid stock and branch shelves."},status=400)
    try: transfer_stock(variant=variant,source=source,destination=destination,quantity=request.data.get("quantity"),reference=request.data.get("reference","TRANSFER"),user=request.user)
    except ValidationError as exc:return Response({"detail":str(exc.detail)},status=400)
    return Response({"detail":"Transfer completed.","source_branch_id":source.zone.store_id,"destination_branch_id":destination.zone.store_id})
@api_view(["GET"])
@permission_classes([IsInternalStaff])
def dashboard(request):
    from .dashboard import dashboard_snapshot
    return Response(dashboard_snapshot(request))


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def part_books(request, key):
    """One part of the business on its own (part_books.py), for that part's page."""
    from .dashboard import UNITS
    from .part_books import part_books as books
    unit = next((u for u in UNITS if u[0] == key), None)
    if not unit or not has_business_permission(request.user, unit[3]):
        return Response({"detail": "You don't have access to this part of the business."}, status=403)
    return Response(books(key, profit_visible=has_business_permission(request.user, "accounting.view_profit"),
                          money_visible=has_business_permission(request.user, "accounting.view_moneycheck")))


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def receipt_return(request, pk):
    """Send goods from a receipt back to the supplier."""
    from .purchase_returns import return_to_supplier
    if not has_business_permission(request.user, "inventory.add_stockreceipt"):return Response({"detail":"Receiving permission required."},status=403)
    receipt=StockReceipt.objects.filter(pk=pk).first()
    if not receipt:return Response({"detail":"Receipt not found."},status=404)
    try:
        result=return_to_supplier(receipt=receipt,lines=request.data.get("lines") or [],reason=str(request.data.get("reason") or ""),user=request.user,idempotency_key=request.data.get("idempotency_key"))
    except ValidationError as exc:return Response(exc.detail,status=400)
    return Response({"id":result.pk,"number":result.number,"value":result.total_cost},status=201)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def lot_cost(request, pk):
    """Supply a missing buying price, or correct one entered by mistake, for one delivery (cost layer)."""
    from .purchase_returns import correct_lot_cost
    lot=StockLot.objects.select_related("receipt_line__receipt").filter(pk=pk).first()
    if not lot:return Response({"detail":"Delivery not found."},status=404)
    if not has_business_permission(request.user, _cost_permission(lot)):
        return Response({"detail":"Receipt correction permission required." if _cost_permission(lot)=="inventory.change_stockreceipt" else "Stock-adjustment permission required."},status=403)
    try:
        correct_lot_cost(lot=lot,unit_cost=request.data.get("unit_cost"),reason=str(request.data.get("reason") or ""),user=request.user)
    except ValidationError as exc:return Response(exc.detail,status=400)
    lot.refresh_from_db()
    return Response(_lot_cost_row(lot, request.user),status=201)


def _cost_permission(lot):
    """Supplier deliveries are corrected like their receipt; opening stock like a stock adjustment."""
    line=getattr(lot,"receipt_line",None)
    supplier=lot.cost_status==StockLot.COSTED and line and line.receipt.document_status!=StockReceipt.OPENING_BALANCE
    return "inventory.change_stockreceipt" if supplier else "inventory.adjust_stock"


def _lot_cost_row(lot, user):
    line=getattr(lot,"receipt_line",None)
    opening=not line or line.receipt.document_status==StockReceipt.OPENING_BALANCE
    return {"id":lot.pk,"reference":lot.reference,"received_at":lot.received_at,"supplier_name":lot.supplier_name,
            "source":"opening" if opening else "supplier","receipt_id":line.receipt_id if line else None,
            "received_quantity":lot.received_quantity,"remaining_quantity":lot.remaining_quantity,
            "uncosted":lot.cost_status==StockLot.UNCOSTED,
            "buying_price":None if lot.cost_status==StockLot.UNCOSTED else lot.unit_cost-lot.landed_unit_cost,
            "landed_cost_per_unit":lot.landed_unit_cost,
            "can_correct":has_business_permission(user,_cost_permission(lot))}


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def variant_buying_prices(request, pk):
    """Every delivery of a variant with its buying price, newest first, for checking and correcting BP."""
    if not has_business_permission(request.user, "accounting.view_profit"):
        return Response({"detail":"Permission to see buying prices is required."},status=403)
    lots=StockLot.objects.filter(variant_id=pk).select_related("receipt_line__receipt").order_by("-received_at","-id")[:50]
    return Response([_lot_cost_row(lot, request.user) for lot in lots])


def _search_row(v, on_hand):
    return {"id":v.id,"product_id":v.product_id,"product_name":v.product.name,"variant_name":v.name,"sku":v.sku,"barcode":v.barcode,"brand":v.product.brand.name if v.product.brand else "","category":v.product.category.name,"category_id":v.product.category_id,"selling_price":v.selling_price,"pack_size":v.pack_size,"piece_name":v.piece_name,"available":on_hand or Decimal("0")}


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def receive_defaults(request, pk):
    """Everything a new delivery of one item is expected to repeat from the last one, so receiving it from its
    product page asks only how many arrived: the supplier, the buying price, whether it had a supplier document, how
    the supplier was paid, and the compartment it is kept in."""
    if not has_business_permission(request.user, "inventory.add_stockreceipt"):return Response({"detail":"Receiving permission required."},status=403)
    v=ProductVariant.objects.select_related("product","product__category","product__brand").filter(pk=pk,active=True,product__active=True,product__product_type="STOCK_ITEM").first()
    if not v:return Response({"detail":"Item not found."},status=404)
    on_hand=StockBalance.objects.filter(lot__variant=v).aggregate(q=Sum(F("quantity")-F("reserved")))["q"]
    line=(StockReceiptLine.objects.filter(variant=v,uncosted=False).exclude(receipt__document_status=StockReceipt.OPENING_BALANCE)
          .select_related("receipt").order_by("-receipt__received_at","-id").first())
    lot=StockLot.objects.filter(variant=v).order_by("-received_at","-id").first()
    supplier=line.receipt.supplier_name if line else (lot.supplier_name if lot else "")
    unit_cost=line.unit_cost if line else (lot.unit_cost-(lot.landed_unit_cost or 0) if lot else None)
    # Never bought before: the document and payment follow the shop's last purchase of anything (its habit), the
    # supplier and price are asked once.
    last=line.receipt if line else StockReceipt.objects.exclude(document_status=StockReceipt.OPENING_BALANCE).order_by("-received_at","-id").first()
    document_status=last.document_status if last else StockReceipt.NO_DOCUMENT
    payment_method=""
    purchase=getattr(last,"purchase",None) if last else None
    if purchase:
        paid=purchase.payments.select_related("entry__account").first()
        from apps.accounting.supplier_settlement import _source
        method=_source(paid.entry) if paid else ""
        payment_method=method if method in ("CASH","MPESA","BANK","OWNER") else ""
    preferred=getattr(v,"preferred_location",None)
    shelf=preferred.shelf if preferred and preferred.shelf.active else None
    if not shelf:
        held=(StockBalance.objects.filter(lot__variant=v,quantity__gt=0,shelf__active=True,shelf__is_virtual=False)
              .values("shelf_id").annotate(q=Sum("quantity")).order_by("-q").first())
        shelf=Shelf.objects.filter(pk=held["shelf_id"]).first() if held else None
    return Response({"item":_search_row(v,on_hand),"supplier_name":supplier,"unit_cost":unit_cost,"document_status":document_status,
                     "payment_method":payment_method,"shelf":{"id":shelf.id,"code":shelf.code,"display_name":shelf.display_name} if shelf else None})

@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def suppliers(request):
    """The suppliers already in the system, for the supplier list when receiving stock: those in the books and any
    name used on an earlier delivery, each once whatever its capitals, A to Z."""
    if not (has_business_permission(request.user, "inventory.add_stockreceipt") or has_business_permission(request.user, "inventory.add_stocklot")):
        return Response({"detail":"Receiving permission required."},status=403)
    from apps.accounting.models import Supplier
    names={}
    for name in [*Supplier.objects.values_list("name",flat=True),*StockReceipt.objects.exclude(supplier_name="").values_list("supplier_name",flat=True).distinct()]:
        name=(name or "").strip()
        if name:names.setdefault(name.casefold(),name)
    return Response(sorted(names.values(),key=str.casefold))
