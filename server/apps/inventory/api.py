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
    from apps.tenancy.permissions import is_employee
    if is_employee(request.user):
        # The business's dashboard (sales, profit, money) is the owner's; an employee has their own (work_dashboard).
        return Response({"detail": "The business dashboard is the owner's. Yours is on your dashboard.", "code": "owner_only"}, status=403)
    from .dashboard import dashboard_snapshot
    return Response(dashboard_snapshot(request))


# What the people working in the business undid or corrected, as the owner reads it: action -> what it was.
STAFF_UNDOS = {
    "MPESA_TRANSACTION_REVERSED": "Cancelled an M-Pesa transaction",
    "MPESA_TRANSACTION_CORRECTED": "Corrected an M-Pesa transaction",
    "MPESA_RECONCILIATION": "Closed an M-Pesa shift with a different count",
    "SALE_RETURNED": "Took back a whole sale",
    "SALE_ITEMS_RETURNED": "Took back items from a sale",
    "SALE_CREDIT_NOTE": "Lowered a sale's price",
    "SALE_DEBIT_NOTE": "Raised a sale's price",
    "PAYMENT_NOT_RECEIVED": "Marked a payment as not received",
    "CYBER_JOB_CANCELLED": "Cancelled a service job",
    "STAY_CANCELLED": "Cancelled a room booking",
    "STAY_NO_SHOW": "Marked a guest as not coming",
}


def _undo_detail(log, sales):
    after, before = log.after or {}, log.before or {}
    if log.action == "MPESA_TRANSACTION_REVERSED":
        return f"{str(after.get('type', '')).replace('_', ' ').lower()} {after.get('original', '')} of {after.get('amount', '')}".strip()
    if log.action == "MPESA_TRANSACTION_CORRECTED":
        return f"{before.get('reference', '')}: {before.get('amount', '')} changed to {after.get('amount', '')}"
    if log.action == "MPESA_RECONCILIATION":
        return f"cash {after.get('cash_variance')}, float {after.get('float_variance')} against what was expected"
    if log.object_type == "Sale":
        return " · ".join(str(part) for part in [sales.get(log.object_id), after.get("return"), after.get("amount")] if part)
    if log.object_type == "Payment":
        return f"{after.get('method', '')} {after.get('amount', '')}".strip()
    return str(after.get("number") or "")


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def staff_undos(request):
    """For the owner: everything the business's staff undid or corrected in the last 30 days, newest first, each with who
    did it, when and the reason they gave."""
    from datetime import timedelta
    from django.db.models import Q
    from apps.core.models import AuditLog
    from apps.tenancy.models import Membership
    from apps.tenancy.permissions import is_business_owner
    if not is_business_owner(request.user):
        return Response({"detail": "What staff undid is for the business owner.", "code": "owner_only"}, status=403)
    staff = Membership.objects.filter(organization=request.organization).exclude(role="OWNER").values_list("user_id", flat=True)
    logs = list(AuditLog.objects.filter(action__in=STAFF_UNDOS, user_id__in=list(staff), created_at__gte=timezone.now() - timedelta(days=30))
                .exclude(Q(action="MPESA_TRANSACTION_REVERSED") & Q(after__reason__startswith="Corrected:"))  # shown as the correction
                .exclude(action="MPESA_RECONCILIATION", after__cash_variance="0.00", after__float_variance="0.00")
                .select_related("user").order_by("-created_at")[:50])
    sales = dict(Sale.objects.filter(pk__in=[int(log.object_id) for log in logs if log.object_type == "Sale" and log.object_id.isdigit()]).values_list("pk", "number"))
    sales = {str(key): value for key, value in sales.items()}
    if any(log.action == "MPESA_RECONCILIATION" for log in logs):
        from apps.mpesa.models import MpesaReconciliation
        reasons = dict(MpesaReconciliation.objects.filter(pk__in=[log.object_id for log in logs if log.action == "MPESA_RECONCILIATION"]).values_list("pk", "reason"))
    else:
        reasons = {}
    return Response([{"id": log.pk, "at": log.created_at, "who": log.user.get_full_name() or log.user.username if log.user else "",
                      "what": STAFF_UNDOS[log.action], "detail": _undo_detail(log, sales),
                      "reason": (reasons.get(int(log.object_id)) if log.action == "MPESA_RECONCILIATION" else (log.after or {}).get("reason")) or ""}
                     for log in logs])


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def work_dashboard(request):
    """An employee's dashboard: what needs doing on the pages the owner gave them, never the business's money. Counts and
    names only: no sales totals, prices paid, profit, cash, float or commission."""
    from django.db.models.functions import Coalesce
    from apps.tenancy.api import work_pages
    from apps.tenancy.middleware import effective_modules
    from apps.tenancy.permissions import membership_for
    user, today = request.user, timezone.localdate()
    can = lambda permission: has_business_permission(user, permission)
    enabled = effective_modules(request.organization)
    membership = membership_for(user)
    given = set(membership.open_pages or []) if membership and membership.role == "EMPLOYEE" else None
    data = {"name": user.get_full_name() or user.username, "business": request.organization.name,
            "pages": [page for page in work_pages(request.organization) if given is None or page["key"] in given]}
    if "pos" in enabled and can("commerce.add_sale"):
        data["sales"] = {"mine_today": Sale.objects.filter(created_by=user, status="COMPLETED", created_at__date=today).count()}
    if "inventory" in enabled and can("catalog.view_product"):
        zero = Decimal("0")
        variants = (ProductVariant.objects.filter(active=True, product__active=True, product__product_type="STOCK_ITEM", minimum_stock__gt=0)
                    .annotate(available=Coalesce(Sum(F("lots__balances__quantity") - F("lots__balances__reserved"), filter=Q(lots__balances__in=StockBalance.objects.all())), zero, output_field=DecimalField()))
                    .filter(available__lte=F("minimum_stock")).select_related("product").order_by("available", "product__name"))
        data["low_stock"] = {"count": variants.count(), "items": [{"name": str(v.product) if v.name == "Standard" else str(v), "available": v.available,
                                                                   "minimum": v.minimum_stock} for v in variants[:8]]}
    if "services" in enabled and can("cyber.view_cyberjob"):
        jobs = CyberJob.objects.filter(status__in=["QUEUED", "IN_PROGRESS", "WAITING_CUSTOMER", "READY"])
        data["services"] = {"waiting": jobs.exclude(status="READY").count(), "ready": jobs.filter(status="READY").count()}
    if "rooms" in enabled and can("hotel.view_stay"):
        from apps.hotel.models import Stay
        data["rooms"] = {"in_house": Stay.objects.filter(status=Stay.IN).count(), "arriving": Stay.objects.filter(status=Stay.BOOKED, arrival=today).count(),
                         "leaving": Stay.objects.filter(status=Stay.IN, departure=today).count()}
    if "mpesa" in enabled and can("mpesa.view_mpesasession"):
        # The owner opens the shift; the employee records on it and closes it at the end of the day.
        shift = MpesaSession.objects.filter(status="OPEN").first()
        data["mpesa"] = {"shift_open": bool(shift), "transactions": shift.transactions.exclude(transaction_type="REVERSAL").filter(reversal__isnull=True, performed_by=user).count() if shift else 0}
    return Response(data)


@api_view(["GET"])
@permission_classes([IsInternalStaff])
def part_books(request, key):
    """One part of the business on its own (part_books.py), for that part's page."""
    from .dashboard import UNITS
    from .part_books import part_books as books
    unit = next((u for u in UNITS if u[0] == key), None)
    if not unit or not any(has_business_permission(request.user, permission) for _, permission in unit[2]):
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
    # The top of the product's category, where the products list goes back to once it is received.
    root=v.product.category
    while root.parent_id:root=root.parent
    return Response({"item":_search_row(v,on_hand),"root_category_id":root.id,"supplier_name":supplier,"unit_cost":unit_cost,"document_status":document_status,
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
