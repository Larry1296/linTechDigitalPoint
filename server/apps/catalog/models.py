from decimal import Decimal
from django.db import models
from apps.core.models import TimeStamped
class Category(TimeStamped):
    name=models.CharField(max_length=120); slug=models.SlugField(unique=True); parent=models.ForeignKey("self",null=True,blank=True,on_delete=models.PROTECT); active=models.BooleanField(default=True)
    def __str__(self): return self.name
class Brand(TimeStamped):
    name=models.CharField(max_length=120,unique=True); active=models.BooleanField(default=True)
class Product(TimeStamped):
    STOCK_ITEM="STOCK_ITEM"; SERVICE="SERVICE"
    name=models.CharField(max_length=180); slug=models.SlugField(unique=True); category=models.ForeignKey(Category,on_delete=models.PROTECT); brand=models.ForeignKey(Brand,null=True,blank=True,on_delete=models.PROTECT); product_type=models.CharField(max_length=20,choices=[(STOCK_ITEM,"Stock item"),(SERVICE,"Service")],default=STOCK_ITEM); description=models.TextField(blank=True); active=models.BooleanField(default=True); ecommerce_visible=models.BooleanField(default=True); online_orderable=models.BooleanField(default=True)
    def __str__(self): return self.name
class ProductVariant(TimeStamped):
    product=models.ForeignKey(Product,related_name="variants",on_delete=models.CASCADE); name=models.CharField(max_length=120,default="Standard"); sku=models.CharField(max_length=64,unique=True); barcode=models.CharField(max_length=64,null=True,blank=True,unique=True); selling_price=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); service_cost=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); minimum_stock=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); target_stock=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); active=models.BooleanField(default=True)
    def __str__(self): return f"{self.product} — {self.name}"
class PriceHistory(models.Model):
    variant=models.ForeignKey(ProductVariant,related_name="price_history",on_delete=models.CASCADE); price=models.DecimalField(max_digits=14,decimal_places=2); effective_at=models.DateTimeField(auto_now_add=True); changed_by=models.ForeignKey("auth.User",null=True,on_delete=models.SET_NULL)

class ProductImage(TimeStamped):
    product=models.ForeignKey(Product,related_name="images",on_delete=models.CASCADE); image_url=models.URLField(max_length=500,blank=True); alt_text=models.CharField(max_length=180,blank=True); sort_order=models.PositiveIntegerField(default=0)
    class Meta: ordering=["sort_order","id"]
