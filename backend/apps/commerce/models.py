from decimal import Decimal
from django.conf import settings
from django.db import models
from apps.core.models import TimeStamped
from apps.catalog.models import ProductVariant
class Sale(TimeStamped):
    POS="POS"; ONLINE="ONLINE"
    number=models.CharField(max_length=40,unique=True); channel=models.CharField(max_length=10,choices=[(POS,"POS"),(ONLINE,"Online")]); status=models.CharField(max_length=20,default="COMPLETED"); customer=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL); subtotal=models.DecimalField(max_digits=14,decimal_places=2,default=0); discount=models.DecimalField(max_digits=14,decimal_places=2,default=0); total=models.DecimalField(max_digits=14,decimal_places=2,default=0); cogs=models.DecimalField(max_digits=14,decimal_places=2,default=0); gross_profit=models.DecimalField(max_digits=14,decimal_places=2,default=0); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL,related_name="sales_created")
class SaleItem(models.Model):
    sale=models.ForeignKey(Sale,related_name="items",on_delete=models.PROTECT); variant=models.ForeignKey(ProductVariant,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_price=models.DecimalField(max_digits=14,decimal_places=2); discount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); cost=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"))
class SaleAllocation(models.Model):
    item=models.ForeignKey(SaleItem,related_name="allocations",on_delete=models.PROTECT); lot=models.ForeignKey("inventory.StockLot",on_delete=models.PROTECT); shelf=models.ForeignKey("inventory.Shelf",on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_cost=models.DecimalField(max_digits=14,decimal_places=2)
class Payment(models.Model):
    sale=models.ForeignKey(Sale,related_name="payments",on_delete=models.PROTECT); method=models.CharField(max_length=20,choices=[(x,x.title()) for x in ["CASH","MPESA","BANK","OTHER","CASH_ON_PICKUP"]]); amount=models.DecimalField(max_digits=14,decimal_places=2); reference=models.CharField(max_length=100,blank=True); status=models.CharField(max_length=20,default="COMPLETED"); idempotency_key=models.CharField(max_length=100,unique=True)
