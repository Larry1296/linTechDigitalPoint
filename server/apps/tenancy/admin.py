from django.contrib import admin
from .models import BusinessKind, Organization, Membership, SubscriptionPlan, OrganizationSubscription

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "active", "owner"]
    search_fields = ["name", "slug"]

@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "role", "status"]
    list_filter = ["organization", "role", "status"]

admin.site.register(SubscriptionPlan)
admin.site.register(OrganizationSubscription)

@admin.register(BusinessKind)
class BusinessKindAdmin(admin.ModelAdmin):
    list_display = ["label", "business_model", "status", "uses", "created_by"]
    list_filter = ["business_model", "status"]
    search_fields = ["label", "keywords"]
