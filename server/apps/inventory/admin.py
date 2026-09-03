from django.contrib import admin
from .models import Movement,Reservation,Shelf,ShelfHistory,StockBalance,StockLot,Zone
for model in [Zone,Shelf,ShelfHistory,StockLot,StockBalance,Movement,Reservation]: admin.site.register(model)

