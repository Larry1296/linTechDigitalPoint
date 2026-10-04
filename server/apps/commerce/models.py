from apps.tenancy.base import TenantModel
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from apps.catalog.models import ProductVariant
from apps.core.models import TimeStamped
class Cart(TimeStamped):
    session_key=models.CharField(max_length=40,blank=True,db_index=True); customer=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,related_name="carts",on_delete=models.CASCADE); active=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["organization", "customer"],condition=Q(active=True,customer__isnull=False),name="one_active_customer_cart")]
        base_manager_name = "objects"
        default_manager_name = "objects"
class CartItem(TimeStamped):
    cart=models.ForeignKey(Cart,related_name="items",on_delete=models.CASCADE); variant=models.ForeignKey(ProductVariant,on_delete=models.CASCADE); quantity=models.DecimalField(max_digits=14,decimal_places=3)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["cart","variant"],name="unique_cart_variant"),models.CheckConstraint(condition=Q(quantity__gt=0),name="positive_cart_quantity")]
        base_manager_name = "objects"
        default_manager_name = "objects"
class Order(TimeStamped):
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    STATUSES=[(x,x.replace("_"," ").title()) for x in ["PENDING","AWAITING_PAYMENT","PAID","PROCESSING","READY_FOR_PICKUP","OUT_FOR_DELIVERY","COMPLETED","CANCELLED","REFUNDED"]]; PAYMENT_STATUSES=[(x,x.title()) for x in ["PENDING","MANUAL_REVIEW","PAID","FAILED","REFUNDED"]]; FULFILLMENT=[(x,x.replace("_"," ").title()) for x in ["UNFULFILLED","PROCESSING","READY_FOR_PICKUP","OUT_FOR_DELIVERY","COMPLETED","CANCELLED"]]
    number=models.CharField(max_length=40); customer=models.ForeignKey(settings.AUTH_USER_MODEL,related_name="orders",on_delete=models.PROTECT); status=models.CharField(max_length=30,choices=STATUSES,default="PENDING"); payment_status=models.CharField(max_length=20,choices=PAYMENT_STATUSES,default="PENDING"); fulfillment_status=models.CharField(max_length=30,choices=FULFILLMENT,default="UNFULFILLED"); fulfillment_method=models.CharField(max_length=20,choices=[("PICKUP","Pickup"),("DELIVERY","Delivery")],default="PICKUP"); address=models.ForeignKey("accounts.CustomerAddress",null=True,blank=True,on_delete=models.PROTECT); subtotal=models.DecimalField(max_digits=14,decimal_places=2); discount=models.DecimalField(max_digits=14,decimal_places=2,default=0); total=models.DecimalField(max_digits=14,decimal_places=2); notes=models.TextField(blank=True); completed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="comm_order_number_org")]
class OrderItem(TenantModel):
    image_url = models.CharField(max_length=500, blank=True)
    order=models.ForeignKey(Order,related_name="items",on_delete=models.PROTECT); variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); product_name=models.CharField(max_length=220); variant_name=models.CharField(max_length=120); sku=models.CharField(max_length=64); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_price=models.DecimalField(max_digits=14,decimal_places=2); reservation=models.OneToOneField("inventory.Reservation",null=True,blank=True,related_name="order_item",on_delete=models.PROTECT)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
class OrderStatusHistory(TenantModel):
    order=models.ForeignKey(Order,related_name="history",on_delete=models.CASCADE); status=models.CharField(max_length=30); note=models.CharField(max_length=255,blank=True); changed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
class Sale(TimeStamped):
    idempotency_key = models.CharField(max_length=120, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    POS="POS"; ONLINE="ONLINE"; CYBER="CYBER"
    number=models.CharField(max_length=40); channel=models.CharField(max_length=10,choices=[(POS,"POS"),(ONLINE,"Online"),(CYBER,"Cyber")]); status=models.CharField(max_length=20,default="COMPLETED"); order=models.OneToOneField(Order,null=True,blank=True,related_name="sale",on_delete=models.PROTECT); customer=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL); subtotal=models.DecimalField(max_digits=14,decimal_places=2,default=0); discount=models.DecimalField(max_digits=14,decimal_places=2,default=0); total=models.DecimalField(max_digits=14,decimal_places=2,default=0); cogs=models.DecimalField(max_digits=14,decimal_places=2,default=0); gross_profit=models.DecimalField(max_digits=14,decimal_places=2,default=0); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="sales_created")
    # Accrual amounts: tax collected for the tax authority is kept out of revenue.
    tax_total=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
    net_total=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
    cost_pending=models.BooleanField(default=False)  # some units came from an uncosted cost layer
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="comm_sale_number_org"), models.UniqueConstraint(fields=["organization", "idempotency_key"], name="sale_business_request")]
        permissions = [("sell_below_cost", "Can sell below buying cost")]
class SaleItem(TenantModel):
    sale=models.ForeignKey(Sale,related_name="items",on_delete=models.PROTECT); variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_price=models.DecimalField(max_digits=14,decimal_places=2); discount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); cost=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
    list_price=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)  # catalogue SP when sold
    discount_reason=models.CharField(max_length=160,blank=True)
    tax_amount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
    net_amount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))  # revenue excluding tax
    cost_pending=models.BooleanField(default=False)
    returned_quantity=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0"))
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
class SaleAllocation(TenantModel):
    item=models.ForeignKey(SaleItem,related_name="allocations",on_delete=models.PROTECT); lot=models.ForeignKey("inventory.StockLot",on_delete=models.PROTECT); shelf=models.ForeignKey("inventory.Shelf",on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_cost=models.DecimalField(max_digits=18,decimal_places=4)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
class Payment(TenantModel):
    STATUSES=[(x,x.replace("_"," ").title()) for x in ["PENDING","MANUAL_REVIEW","COMPLETED","FAILED","REFUNDED","REVERSED"]]
    sale=models.ForeignKey(Sale,null=True,blank=True,related_name="payments",on_delete=models.PROTECT); order=models.ForeignKey(Order,null=True,blank=True,related_name="payments",on_delete=models.PROTECT); method=models.CharField(max_length=20,choices=[(x,x.title()) for x in ["CASH","MPESA","BANK","OTHER","CASH_ON_PICKUP"]]); amount=models.DecimalField(max_digits=14,decimal_places=2); reference=models.CharField(max_length=100,blank=True); status=models.CharField(max_length=20,choices=STATUSES,default="PENDING"); idempotency_key=models.CharField(max_length=100); provider_transaction_id=models.CharField(max_length=120,null=True,blank=True); created_at=models.DateTimeField(default=timezone.now,editable=False); updated_at=models.DateTimeField(default=timezone.now)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(sale__isnull=False)|Q(order__isnull=False),name="payment_has_subject")]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [*constraints, models.UniqueConstraint(fields=["organization", "idempotency_key"], name="comm_payment_idempotency_key_org"), models.UniqueConstraint(fields=["organization", "provider_transaction_id"], name="comm_payment_provider_transac_org")]


class SaleReturn(TimeStamped):
    """Goods a customer brought back: reverses the returned share of revenue, tax and COGS."""
    branch=models.ForeignKey("core.Store",null=True,blank=True,on_delete=models.PROTECT,editable=False)
    sale=models.ForeignKey(Sale,related_name="returns",on_delete=models.PROTECT)
    number=models.CharField(max_length=40)
    reason=models.TextField()
    refund_amount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
    refund_method=models.CharField(max_length=20,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="+")
    idempotency_key=models.CharField(max_length=120,null=True,blank=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints=[models.UniqueConstraint(fields=["organization","number"],name="comm_salereturn_number_org"),
                     models.UniqueConstraint(fields=["organization","idempotency_key"],name="comm_salereturn_key_org")]


class SaleReturnLine(TenantModel):
    sale_return=models.ForeignKey(SaleReturn,related_name="lines",on_delete=models.PROTECT)
    item=models.ForeignKey(SaleItem,related_name="return_lines",on_delete=models.PROTECT)
    quantity=models.DecimalField(max_digits=14,decimal_places=3)
    restock=models.BooleanField(default=True)
    net_amount=models.DecimalField(max_digits=14,decimal_places=2)
    tax_amount=models.DecimalField(max_digits=14,decimal_places=2)
    payable_amount=models.DecimalField(max_digits=14,decimal_places=2)
    cost_amount=models.DecimalField(max_digits=14,decimal_places=2)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints=[models.CheckConstraint(condition=Q(quantity__gt=0),name="positive_sale_return_line")]


class SaleAdjustment(TimeStamped):
    """A credit or debit note correcting a posted sale's price; the original sale is never edited."""
    CREDIT="CREDIT"; DEBIT="DEBIT"
    branch=models.ForeignKey("core.Store",null=True,blank=True,on_delete=models.PROTECT,editable=False)
    sale=models.ForeignKey(Sale,related_name="adjustments",on_delete=models.PROTECT)
    item=models.ForeignKey(SaleItem,null=True,blank=True,related_name="adjustments",on_delete=models.PROTECT)
    kind=models.CharField(max_length=6,choices=[(CREDIT,"Credit note: customer owes less"),(DEBIT,"Debit note: customer owes more")])
    amount=models.DecimalField(max_digits=14,decimal_places=2)      # payable change including tax
    net_amount=models.DecimalField(max_digits=14,decimal_places=2)  # revenue change
    tax_amount=models.DecimalField(max_digits=14,decimal_places=2)
    line_amounts=models.JSONField(default=dict, blank=True)
    reason=models.TextField()
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="+")
    idempotency_key=models.CharField(max_length=120,null=True,blank=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name="positive_sale_adjustment"),
                     models.UniqueConstraint(fields=["organization","idempotency_key"],name="comm_saleadjustment_key_org")]
