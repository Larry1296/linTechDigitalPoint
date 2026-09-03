from django.contrib import admin
from .models import Brand,Category,PriceHistory,Product,ProductImage,ProductVariant
for model in [Brand,Category,Product,ProductVariant,ProductImage,PriceHistory]: admin.site.register(model)
