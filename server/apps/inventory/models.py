from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.core.models import Store,TimeStamped
from apps.catalog.models import Category,ProductVariant
class Zone(TimeStamped):
    store=models.ForeignKey(Store,related_name="zones",on_delete=models.CASCADE); code=models.CharField(max_length=20); name=models.CharField(max_length=120); active=models.BooleanField(default=True); width=models.DecimalField(max_digits=10,decimal_places=2,default=100); height=models.DecimalField(max_digits=10,decimal_places=2,default=100); next_shelf_number=models.PositiveIntegerField(default=1)
    class Meta: constraints=[models.UniqueConstraint(fields=["store","code"],name="unique_zone_code")]
class ShelfStack(TimeStamped):
    zone=models.ForeignKey(Zone,related_name="stacks",on_delete=models.PROTECT);code=models.CharField(max_length=40,unique=True);display_name=models.CharField(max_length=160);x=models.DecimalField(max_digits=10,decimal_places=2);y=models.DecimalField(max_digits=10,decimal_places=2);width=models.DecimalField(max_digits=10,decimal_places=2);height=models.DecimalField(max_digits=10,decimal_places=2);depth=models.DecimalField(max_digits=10,decimal_places=2);rotation=models.DecimalField(max_digits=6,decimal_places=2,default=0);number_of_levels=models.PositiveIntegerField();active=models.BooleanField(default=True);notes=models.TextField(blank=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="stacks_created");updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="stacks_updated")
    class Meta: constraints=[models.CheckConstraint(condition=Q(width__gt=0)&Q(height__gt=0)&Q(depth__gt=0)&Q(number_of_levels__gt=0),name="positive_stack_dimensions")]
    def __str__(self):return f"{self.code} — {self.display_name}"
class ShelfStackCategory(TimeStamped):
    stack=models.ForeignKey(ShelfStack,related_name="category_assignments",on_delete=models.CASCADE)
    category=models.ForeignKey(Category,related_name="rack_assignments",on_delete=models.PROTECT)
    is_primary=models.BooleanField(default=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["stack","category"],name="unique_stack_category"),models.UniqueConstraint(fields=["stack"],condition=Q(is_primary=True),name="one_primary_stack_category")]
class ShelfLevel(TimeStamped):
    stack=models.ForeignKey(ShelfStack,related_name="levels",on_delete=models.PROTECT);level_number=models.PositiveIntegerField();y_position=models.DecimalField(max_digits=10,decimal_places=2);height=models.DecimalField(max_digits=10,decimal_places=2);active=models.BooleanField(default=True)
    class Meta:ordering=["level_number"];constraints=[models.UniqueConstraint(fields=["stack","level_number"],name="unique_stack_level"),models.CheckConstraint(condition=Q(height__gt=0)&Q(level_number__gt=0),name="positive_level_geometry")]
    def __str__(self):return f"{self.stack.code} Level {self.level_number}"
class Shelf(TimeStamped):
    zone=models.ForeignKey(Zone,related_name="shelves",on_delete=models.PROTECT);level=models.ForeignKey(ShelfLevel,related_name="shelves",null=True,blank=True,on_delete=models.PROTECT);code=models.CharField(max_length=60);physical_label=models.CharField(max_length=80,blank=True);display_name=models.CharField(max_length=160);position_in_level=models.PositiveIntegerField(null=True,blank=True);parent=models.ForeignKey("self",null=True,blank=True,on_delete=models.PROTECT);x=models.DecimalField(max_digits=10,decimal_places=2);y=models.DecimalField(max_digits=10,decimal_places=2);width=models.DecimalField(max_digits=10,decimal_places=2);height=models.DecimalField(max_digits=10,decimal_places=2);depth=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True);rotation=models.DecimalField(max_digits=6,decimal_places=2,default=0);sort_order=models.IntegerField(default=0);capacity=models.DecimalField(max_digits=14,decimal_places=3,null=True,blank=True);active=models.BooleanField(default=True);notes=models.TextField(blank=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="shelves_created");updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="shelves_updated")
    class Meta: constraints=[models.UniqueConstraint(fields=["zone","code"],name="unique_shelf_code_zone"),models.CheckConstraint(condition=Q(width__gt=0)&Q(height__gt=0),name="positive_shelf_dimensions")]
class ShelfHistory(models.Model):
    shelf=models.ForeignKey(Shelf,related_name="history",on_delete=models.PROTECT); event=models.CharField(max_length=40); snapshot=models.JSONField(); changed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); created_at=models.DateTimeField(auto_now_add=True)
class LocationHistory(models.Model):
    object_type=models.CharField(max_length=20);object_id=models.PositiveBigIntegerField();event=models.CharField(max_length=40);snapshot=models.JSONField();changed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL);created_at=models.DateTimeField(auto_now_add=True)
class StockLot(TimeStamped):
    variant=models.ForeignKey(ProductVariant,related_name="lots",on_delete=models.PROTECT); reference=models.CharField(max_length=80); received_quantity=models.DecimalField(max_digits=14,decimal_places=3); remaining_quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_cost=models.DecimalField(max_digits=14,decimal_places=2); supplier_name=models.CharField(max_length=180,blank=True); received_at=models.DateTimeField()
    class Meta: constraints=[models.CheckConstraint(condition=Q(received_quantity__gte=0)&Q(remaining_quantity__gte=0),name="nonnegative_lot")]
class StockBalance(TimeStamped):
    lot=models.ForeignKey(StockLot,related_name="balances",on_delete=models.PROTECT); shelf=models.ForeignKey(Shelf,related_name="balances",on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); reserved=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0"))
    class Meta: constraints=[models.UniqueConstraint(fields=["lot","shelf"],name="unique_lot_shelf"),models.CheckConstraint(condition=Q(quantity__gte=0)&Q(reserved__gte=0)&Q(reserved__lte=models.F("quantity")),name="valid_stock_balance")]
class VariantPreferredLocation(TimeStamped):
    variant=models.OneToOneField(ProductVariant,related_name="preferred_location",on_delete=models.CASCADE);shelf=models.ForeignKey(Shelf,related_name="preferred_variants",on_delete=models.PROTECT);updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
class StockReceipt(TimeStamped):
    COMPLETED="COMPLETED"
    status=models.CharField(max_length=20,default=COMPLETED,choices=[(COMPLETED,"Completed")])
    receipt_number=models.CharField(max_length=80,unique=True)
    external_reference=models.CharField(max_length=120,blank=True)
    supplier_name=models.CharField(max_length=180,blank=True)
    received_at=models.DateTimeField()
    notes=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="stock_receipts")
    idempotency_key=models.CharField(max_length=120,unique=True,null=True,blank=True)
class StockReceiptLine(TimeStamped):
    receipt=models.ForeignKey(StockReceipt,related_name="lines",on_delete=models.PROTECT)
    variant=models.ForeignKey(ProductVariant,related_name="receipt_lines",on_delete=models.PROTECT)
    received_quantity=models.DecimalField(max_digits=14,decimal_places=3)
    unit_cost=models.DecimalField(max_digits=14,decimal_places=2)
    lot=models.OneToOneField(StockLot,null=True,blank=True,related_name="receipt_line",on_delete=models.PROTECT)
    previous_selling_price=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    new_selling_price=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(received_quantity__gt=0)&Q(unit_cost__gte=0),name="positive_receipt_line")]
class StockReceiptPlacement(TimeStamped):
    line=models.ForeignKey(StockReceiptLine,related_name="placements",on_delete=models.PROTECT)
    shelf=models.ForeignKey(Shelf,related_name="receipt_placements",on_delete=models.PROTECT)
    quantity=models.DecimalField(max_digits=14,decimal_places=3)
    balance=models.ForeignKey(StockBalance,null=True,blank=True,related_name="receipt_placements",on_delete=models.PROTECT)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(quantity__gt=0),name="positive_receipt_placement"),models.UniqueConstraint(fields=["line","shelf"],name="unique_receipt_line_shelf")]
class StockReceiptLineCorrection(models.Model):
    line = models.ForeignKey(StockReceiptLine, related_name="corrections", on_delete=models.PROTECT)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    before = models.JSONField()
    after = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        default_permissions = ("view",)
        constraints = [models.CheckConstraint(condition=~Q(reason=""), name="receipt_correction_reason_required")]

class StockAdjustment(models.Model):
    REASONS=[(x,x) for x in ["Opening stock correction", "Physical count variance", "Damaged item", "Lost item", "Data-entry correction", "Found stock"]]
    variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT)
    shelf=models.ForeignKey(Shelf,on_delete=models.PROTECT)
    quantity_before=models.DecimalField(max_digits=14,decimal_places=3)
    amount=models.DecimalField(max_digits=14,decimal_places=3)
    quantity_after=models.DecimalField(max_digits=14,decimal_places=3)
    reason=models.CharField(max_length=40,choices=REASONS)
    notes=models.TextField(blank=True)
    reference=models.CharField(max_length=100,blank=True)
    performed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    idempotency_key=models.CharField(max_length=120,unique=True)
    class Meta:
        permissions=[("adjust_stock", "Can post physical stock adjustments")]
        constraints=[models.CheckConstraint(condition=Q(quantity_before__gte=0)&Q(quantity_after__gte=0)&Q(quantity_after=models.F("quantity_before")+models.F("amount"))&~Q(amount=0),name="valid_stock_adjustment")]

class Movement(models.Model):
    receipt_correction = models.ForeignKey(StockReceiptLineCorrection, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    adjustment=models.ForeignKey(StockAdjustment,null=True,blank=True,on_delete=models.PROTECT,related_name="movements")
    quantity_before=models.DecimalField(max_digits=14,decimal_places=3,null=True,blank=True)
    quantity_after=models.DecimalField(max_digits=14,decimal_places=3,null=True,blank=True)
    TYPES=[(x,x.replace("_"," ").title()) for x in ["OPENING_STOCK","PURCHASE_RECEIPT","SALE","ONLINE_ORDER","CYBER_CONSUMPTION","TRANSFER","CUSTOMER_RETURN","SUPPLIER_RETURN","DAMAGE","LOSS","STOCKTAKE_ADJUSTMENT","STOCK_ADJUSTMENT","MANUAL_ADJUSTMENT","ORDER_RESERVATION","RESERVATION_RELEASE","OTHER"]]
    variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); lot=models.ForeignKey(StockLot,null=True,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); source=models.ForeignKey(Shelf,null=True,on_delete=models.PROTECT,related_name="movements_out"); destination=models.ForeignKey(Shelf,null=True,on_delete=models.PROTECT,related_name="movements_in"); movement_type=models.CharField(max_length=30,choices=TYPES); reference=models.CharField(max_length=100); performed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); notes=models.TextField(blank=True); created_at=models.DateTimeField(auto_now_add=True)
class Reservation(TimeStamped):
    ACTIVE="ACTIVE"; CONSUMED="CONSUMED"; RELEASED="RELEASED"
    variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); active=models.BooleanField(default=True); status=models.CharField(max_length=12,choices=[(ACTIVE,"Active"),(CONSUMED,"Consumed"),(RELEASED,"Released")],default=ACTIVE); reference=models.CharField(max_length=100); expires_at=models.DateTimeField(); allocations=models.JSONField(default=list)
