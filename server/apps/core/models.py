from apps.tenancy.base import TenantModel
from django.conf import settings
from django.db import models
class TimeStamped(TenantModel):
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        abstract=True
        base_manager_name = "objects"
        default_manager_name = "objects"
class Store(TimeStamped):
    name=models.CharField(max_length=160); currency=models.CharField(max_length=3,default="KES"); timezone=models.CharField(max_length=50,default="Africa/Nairobi"); measurement_unit=models.CharField(max_length=10,default="ft"); phone=models.CharField(max_length=30,blank=True); email=models.EmailField(blank=True); address=models.TextField(blank=True); receipt_footer=models.CharField(max_length=255,blank=True); reservation_timeout_minutes=models.PositiveIntegerField(default=30)
    def save(self, *args, **kwargs):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from apps.tenancy.models import Organization, OrganizationSubscription
        self.validate_tenant()
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=self.organization_id)
            subscription = OrganizationSubscription.objects.select_related("plan").filter(organization_id=self.organization_id).first()
            limit = subscription.plan.branch_limit if subscription and subscription.plan_id else None
            if limit is not None and Store.objects.exclude(pk=self.pk).count() >= limit:
                raise ValidationError("The configured plan's branch limit has been reached.")
            return super().save(*args, **kwargs)
    def __str__(self): return self.name
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
class AuditLog(TenantModel):
    action=models.CharField(max_length=80); object_type=models.CharField(max_length=80); object_id=models.CharField(max_length=64); user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL); before=models.JSONField(default=dict); after=models.JSONField(default=dict); ip_address=models.GenericIPAddressField(null=True); user_agent=models.CharField(max_length=300,blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["-created_at"]
        base_manager_name = "objects"
        default_manager_name = "objects"
