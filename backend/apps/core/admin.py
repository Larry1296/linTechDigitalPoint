from django.contrib import admin
from .models import AuditLog,Store
admin.site.register(Store); admin.site.register(AuditLog)

