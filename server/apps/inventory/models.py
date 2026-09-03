from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.core.models import Store,TimeStamped
from apps.catalog.models import ProductVariant
class Zone(TimeStamped):
    store=models.ForeignKey(Store,related_name="zones",on_delete=models.CASCADE); code=models.CharField(max_length=20); name=models.CharField(max_length=120); active=models.BooleanField(default=True); width=models.DecimalField(max_digits=10,decimal_places=2,default=100); height=models.DecimalField(max_digits=10,decimal_places=2,default=100); next_shelf_number=models.PositiveIntegerField(default=1)
    class Meta: constraints=[models.UniqueConstraint(fields=["store","code"],name="unique_zone_code")]
class Shelf(TimeStamped):
    zone=models.ForeignKey(Zone,related_name="shelves",on_delete=models.PROTECT); code=models.CharField(max_length=30); display_name=models.CharField(max_length=160); parent=models.ForeignKey("self",null=True,blank=True,on_delete=models.PROTECT); x=models.DecimalField(max_digits=10,decimal_places=2); y=models.DecimalField(max_digits=10,decimal_places=2); width=models.DecimalField(max_digits=10,decimal_places=2); height=models.DecimalField(max_digits=10,decimal_places=2); depth=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True); rotation=models.DecimalField(max_digits=6,decimal_places=2,default=0); sort_order=models.IntegerField(default=0); capacity=models.DecimalField(max_digits=14,decimal_places=3,null=True,blank=True); active=models.BooleanField(default=True); notes=models.TextField(blank=True); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="shelves_created"); updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="shelves_updated")
    class Meta: constraints=[models.UniqueConstraint(fields=["zone","code"],name="unique_shelf_code_zone"),models.CheckConstraint(condition=Q(width__gt=0)&Q(height__gt=0),name="positive_shelf_dimensions")]
class ShelfHistory(models.Model):
    shelf=models.ForeignKey(Shelf,related_name="history",on_delete=models.PROTECT); event=models.CharField(max_length=40); snapshot=models.JSONField(); changed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); created_at=models.DateTimeField(auto_now_add=True)
class StockLot(TimeStamped):
    variant=models.ForeignKey(ProductVariant,related_name="lots",on_delete=models.PROTECT); reference=models.CharField(max_length=80); received_quantity=models.DecimalField(max_digits=14,decimal_places=3); remaining_quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_cost=models.DecimalField(max_digits=14,decimal_places=2); supplier_name=models.CharField(max_length=180,blank=True); received_at=models.DateTimeField()
    class Meta: constraints=[models.CheckConstraint(condition=Q(received_quantity__gte=0)&Q(remaining_quantity__gte=0),name="nonnegative_lot")]
class StockBalance(TimeStamped):
    lot=models.ForeignKey(StockLot,related_name="balances",on_delete=models.PROTECT); shelf=models.ForeignKey(Shelf,related_name="balances",on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); reserved=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0"))
    class Meta: constraints=[models.UniqueConstraint(fields=["lot","shelf"],name="unique_lot_shelf"),models.CheckConstraint(condition=Q(quantity__gte=0)&Q(reserved__gte=0)&Q(reserved__lte=models.F("quantity")),name="valid_stock_balance")]
class Movement(models.Model):
    TYPES=[(x,x.replace("_"," ").title()) for x in ["OPENING_STOCK","PURCHASE_RECEIPT","SALE","ONLINE_ORDER","TRANSFER","CUSTOMER_RETURN","SUPPLIER_RETURN","DAMAGE","LOSS","STOCKTAKE_ADJUSTMENT","MANUAL_ADJUSTMENT","ORDER_RESERVATION","RESERVATION_RELEASE","OTHER"]]
    variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); lot=models.ForeignKey(StockLot,null=True,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); source=models.ForeignKey(Shelf,null=True,on_delete=models.PROTECT,related_name="movements_out"); destination=models.ForeignKey(Shelf,null=True,on_delete=models.PROTECT,related_name="movements_in"); movement_type=models.CharField(max_length=30,choices=TYPES); reference=models.CharField(max_length=100); performed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); notes=models.TextField(blank=True); created_at=models.DateTimeField(auto_now_add=True)
class Reservation(TimeStamped):
    ACTIVE="ACTIVE"; CONSUMED="CONSUMED"; RELEASED="RELEASED"
    variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); active=models.BooleanField(default=True); status=models.CharField(max_length=12,choices=[(ACTIVE,"Active"),(CONSUMED,"Consumed"),(RELEASED,"Released")],default=ACTIVE); reference=models.CharField(max_length=100); expires_at=models.DateTimeField(); allocations=models.JSONField(default=list)
