from django.contrib import admin
from .models import Cart,CartItem,Order,OrderItem,OrderStatusHistory,Payment,Sale,SaleAllocation,SaleItem
for model in [Cart,CartItem,Order,OrderItem,OrderStatusHistory,Sale,SaleItem,SaleAllocation,Payment]: admin.site.register(model)
