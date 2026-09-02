from django.contrib import admin
from .models import AuditLog,Store
admin.site.register(Store)
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display=("created_at","action","object_type","object_id","user");readonly_fields=("action","object_type","object_id","user","before","after","ip_address","user_agent","created_at")
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
