from django.db.models import DecimalField,ExpressionWrapper,F,Sum
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from apps.catalog.models import ProductVariant
from apps.commerce.models import Order,Sale,SaleItem
from apps.cyber.models import CyberJob,CyberJobLine
from apps.mpesa.models import MpesaCommissionEntry,MpesaSession,MpesaTransaction
from apps.mpesa.services import session_balances
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from .models import Shelf,StockBalance,StockLot,Zone
from .services import receive_stock,transfer_stock
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def receive(request):
    if not request.user.has_perm("inventory.add_stocklot"):return Response({"detail":"Receiving permission required."},status=403)
    variant=ProductVariant.objects.select_related("product").filter(pk=request.data.get("variant_id"),active=True,product__active=True,product__product_type="STOCK_ITEM").first()
    if not variant:return Response({"detail":"Choose an active stock-item product variant."},status=400)
    placements=[]
    for raw in request.data.get("placements",[]):
        shelf=Shelf.objects.filter(pk=raw.get("shelf_id"),active=True).first()
        if not shelf:return Response({"detail":"Invalid shelf placement."},status=400)
        placements.append({"shelf":shelf,"quantity":raw.get("quantity")})
    lot=receive_stock(variant=variant,placements=placements,unit_cost=request.data.get("unit_cost"),reference=request.data.get("reference"),supplier_name=request.data.get("supplier_name",""),user=request.user)
    if request.data.get("selling_price") is not None and str(variant.selling_price)!=str(request.data["selling_price"]):
        if not request.user.has_perm("catalog.change_productvariant"):return Response({"detail":"Price-change permission required."},status=403)
        variant.selling_price=request.data["selling_price"];variant.save()
    return Response({"lot_id":lot.id,"quantity":lot.received_quantity,"reference":lot.reference},status=201)
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def transfer(request):
    if not request.user.has_perm("inventory.change_stockbalance"):return Response({"detail":"Transfer permission required."},status=403)
    variant=ProductVariant.objects.get(pk=request.data["variant_id"]);source=Shelf.objects.get(pk=request.data["source_id"]);destination=Shelf.objects.get(pk=request.data["destination_id"]);transfer_stock(variant=variant,source=source,destination=destination,quantity=request.data["quantity"],reference=request.data.get("reference","TRANSFER"),user=request.user);return Response({"detail":"Transfer completed."})
@api_view(["GET"])
@permission_classes([IsInternalStaff])
def dashboard(request):
    today=__import__("django.utils.timezone",fromlist=["localdate"]).localdate();sales=Sale.objects.filter(created_at__date=today)
    metrics=sales.aggregate(revenue=Sum("total"),cogs=Sum("cogs"),profit=Sum("gross_profit"));items=SaleItem.objects.filter(sale__in=sales).aggregate(v=Sum("quantity"))["v"] or 0
    balances=StockBalance.objects.select_related("lot","lot__variant");physical=Sum("quantity");cost=Sum(ExpressionWrapper(F("quantity")*F("lot__unit_cost"),output_field=DecimalField()));retail=Sum(ExpressionWrapper(F("quantity")*F("lot__variant__selling_price"),output_field=DecimalField()))
    values=balances.aggregate(physical=physical,cost=cost,retail=retail);low=sum(1 for v in ProductVariant.objects.filter(active=True) if (StockBalance.objects.filter(lot__variant=v).aggregate(q=Sum(F("quantity")-F("reserved")))["q"] or 0)<=v.minimum_stock)
    retail_sales=sales.exclude(channel=Sale.CYBER);cyber_sales=sales.filter(channel=Sale.CYBER);top=CyberJobLine.objects.filter(job__completed_at__date=today).values("service_name").annotate(value=Sum("line_total")).order_by("-value").first()
    can_view_mpesa=request.user.has_perm("mpesa.view_mpesasession");open_shift=MpesaSession.objects.filter(status="OPEN").prefetch_related("transactions").first() if can_view_mpesa else None;mpesa_cash,mpesa_float=session_balances(open_shift) if open_shift else (0,0);entries=MpesaTransaction.objects.filter(occurred_at__date=today) if can_view_mpesa else MpesaTransaction.objects.none();deposits=entries.filter(transaction_type="CUSTOMER_DEPOSIT").aggregate(v=Sum("amount"))["v"] or 0;withdrawals=entries.filter(transaction_type="CUSTOMER_WITHDRAWAL").aggregate(v=Sum("amount"))["v"] or 0;commission=MpesaCommissionEntry.objects.filter(recognized_at__date=today).aggregate(v=Sum("amount"))["v"] or 0;sales_revenue=metrics["revenue"] or 0
    return Response({"today":{**{k:(v or 0) for k,v in metrics.items()},"revenue":sales_revenue+commission,"sales_revenue":sales_revenue,"sales":sales.count(),"items_sold":items,"pos_revenue":retail_sales.filter(channel="POS").aggregate(v=Sum("total"))["v"] or 0,"online_revenue":retail_sales.filter(channel="ONLINE").aggregate(v=Sum("total"))["v"] or 0},"retail":{"revenue":retail_sales.aggregate(v=Sum("total"))["v"] or 0,"cogs":retail_sales.aggregate(v=Sum("cogs"))["v"] or 0,"profit":retail_sales.aggregate(v=Sum("gross_profit"))["v"] or 0,"sales":retail_sales.count()},"cyber":{"revenue":cyber_sales.aggregate(v=Sum("total"))["v"] or 0,"profit":cyber_sales.aggregate(v=Sum("gross_profit"))["v"] or 0,"jobs_today":CyberJob.objects.filter(created_at__date=today).count(),"active_jobs":CyberJob.objects.exclude(status__in=["COMPLETED","CANCELLED"]).count(),"ready_jobs":CyberJob.objects.filter(status="READY").count(),"top_service":top["service_name"] if top else None},"mpesa":{"cash":mpesa_cash,"float":mpesa_float,"deposits":deposits,"withdrawals":withdrawals,"transaction_count":entries.exclude(transaction_type="REVERSAL").count(),"commission":commission if can_view_mpesa else 0,"principal_revenue":0,"reconciliation_status":"OPEN" if open_shift else "NO OPEN SHIFT","restricted":not can_view_mpesa},"inventory":{**{k:(v or 0) for k,v in values.items()},"potential_margin":(values["retail"] or 0)-(values["cost"] or 0),"low_stock":low,"total_skus":ProductVariant.objects.filter(active=True).count()},"orders":{"awaiting_payment":Order.objects.filter(payment_status="PENDING").count(),"awaiting_fulfillment":Order.objects.filter(payment_status="PAID").exclude(fulfillment_status="COMPLETED").count()}})
