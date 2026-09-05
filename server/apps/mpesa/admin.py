from django.contrib import admin

from .models import MpesaCommissionEntry, MpesaOutlet, MpesaReconciliation, MpesaSession, MpesaTransaction


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ["internal_reference", "transaction_type", "amount", "cash_delta", "float_delta", "occurred_at"]
    list_filter = ["transaction_type", "occurred_at"]
    search_fields = ["internal_reference", "provider_reference"]
    readonly_fields = [field.name for field in MpesaTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MpesaSession)
class MpesaSessionAdmin(admin.ModelAdmin):
    list_display = ["outlet", "operator", "status", "opened_at", "closed_at"]
    readonly_fields = ["opened_at", "closed_at", "closed_by"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MpesaReconciliation)
class MpesaReconciliationAdmin(admin.ModelAdmin):
    readonly_fields = [field.name for field in MpesaReconciliation._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(MpesaOutlet)


@admin.register(MpesaCommissionEntry)
class MpesaCommissionAdmin(admin.ModelAdmin):
    list_display = ["outlet", "period", "amount", "reference", "recognized_at"]
    readonly_fields = ["recorded_by", "created_at", "updated_at"]

    def has_delete_permission(self, request, obj=None):
        return False
