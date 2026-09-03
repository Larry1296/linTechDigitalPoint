from django.contrib import admin
from .models import LocationHistory,Movement,Reservation,Shelf,ShelfHistory,ShelfLevel,ShelfStack,StockBalance,StockLot,VariantPreferredLocation,Zone
for model in [Zone,ShelfStack,ShelfLevel,Shelf,ShelfHistory,LocationHistory,VariantPreferredLocation,StockLot,StockBalance,Movement,Reservation]: admin.site.register(model)
