from django.contrib import admin

from .models import CyberJob, CyberJobLine, CyberServiceProfile, ServiceMaterialRequirement


class CyberJobLineInline(admin.TabularInline):
    model = CyberJobLine
    extra = 0
    readonly_fields = ["variant", "service_name", "quantity", "billing_unit", "unit_price", "line_total", "service_details"]
    can_delete = False


@admin.register(CyberJob)
class CyberJobAdmin(admin.ModelAdmin):
    list_display = ["number", "status", "walk_in_customer_name", "operator", "total", "created_at"]
    list_filter = ["status", "created_at"]
    readonly_fields = ["number", "subtotal", "discount", "total", "sale", "created_at", "updated_at", "started_at", "completed_at"]
    inlines = [CyberJobLineInline]

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CyberServiceProfile)
admin.site.register(ServiceMaterialRequirement)
