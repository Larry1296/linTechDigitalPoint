from django.contrib import admin
from .models import Brand,Category,PriceHistory,Product,ProductVariant
for model in [Brand,Category,Product,ProductVariant,PriceHistory]: admin.site.register(model)

