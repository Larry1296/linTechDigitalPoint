from django.db.models import DecimalField,ExpressionWrapper,F,Sum
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from apps.catalog.models import ProductVariant
from apps.commerce.models import Order,Sale,SaleItem
from apps.core.permissions import HasLinTechPermission,IsInternalStaff
from .models import Shelf,StockBalance,StockLot,Zone
from .services import receive_stock,transfer_stock
@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def receive(request):
    if not request.user.has_perm("inventory.add_stocklot"):return Response({"detail":"Receiving permission required."},status=403)
    variant=ProductVariant.objects.filter(pk=request.data.get("variant_id")).first()
    placements=[]
    for raw in request.data.get("placements",[]):
        shelf=Shelf.objects.filter(pk=raw.get("shelf_id"),active=True).first()
        if not shelf:return Response({"detail":"Invalid shelf placement."},status=400)
        placements.append({"shelf":shelf,"quantity":raw.get("quantity")})
    lot=receive_stock(variant=variant,placements=placements,unit_cost=request.data.get("unit_cost"),reference=request.data.get("reference"),supplier_name=request.data.get("supplier_name",""),user=request.user)
    if request.data.get("selling_price") is not None and str(variant.selling_price)!=str(request.data["selling_price"]):
        if not request.user.has_perm("catalog.change_productvariant"):return Response({"detail":"Price-change permission required."},status=403)
        variant.selling_price=request.data["selling_price"];variant.save()
    return Response({"lot_id":lot.id,"quantity":lot.received_quantity},status=201)
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
    return Response({"today":{**{k:(v or 0) for k,v in metrics.items()},"sales":sales.count(),"items_sold":items,"pos_revenue":sales.filter(channel="POS").aggregate(v=Sum("total"))["v"] or 0,"online_revenue":sales.filter(channel="ONLINE").aggregate(v=Sum("total"))["v"] or 0},"inventory":{**{k:(v or 0) for k,v in values.items()},"potential_margin":(values["retail"] or 0)-(values["cost"] or 0),"low_stock":low,"total_skus":ProductVariant.objects.filter(active=True).count()},"orders":{"awaiting_payment":Order.objects.filter(payment_status="PENDING").count(),"awaiting_fulfillment":Order.objects.filter(payment_status="PAID").exclude(fulfillment_status="COMPLETED").count()}})
