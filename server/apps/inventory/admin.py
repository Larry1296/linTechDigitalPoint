from django.contrib import admin
from .models import LocationHistory,Movement,Reservation,Shelf,ShelfHistory,ShelfLevel,ShelfStack,StockBalance,StockLot,VariantPreferredLocation,Zone
for model in [Zone,ShelfStack,ShelfLevel,Shelf,ShelfHistory,LocationHistory,VariantPreferredLocation,StockLot,StockBalance,Movement,Reservation]: admin.site.register(model)

from .models import StockReceiptLineCorrection


@admin.register(StockReceiptLineCorrection)
class StockReceiptLineCorrectionAdmin(admin.ModelAdmin):
    list_display = ("id", "line", "performed_by", "created_at", "reason")
    readonly_fields = ("line", "performed_by", "created_at", "reason", "before", "after")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
