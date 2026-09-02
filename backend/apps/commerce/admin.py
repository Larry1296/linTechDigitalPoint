from django.contrib import admin
from .models import Payment,Sale,SaleAllocation,SaleItem
for model in [Sale,SaleItem,SaleAllocation,Payment]: admin.site.register(model)

