from decimal import Decimal
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


class ToBuyItem(TenantModel):
    """A line on the owner's scratch list of things to buy. Only a note: it never touches stock, money or the books. It
    leaves the list by itself once the item is recorded in the system: stock received for its product (``variant``,
    when one was picked), or for a product of the same name."""
    name = models.CharField(max_length=160)
    variant = models.ForeignKey("catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # How many (count) of what (unit: "pcs", "cartons", "kg") at what price each; the line's total is count × unit_price.
    count = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit = models.CharField(max_length=30, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Before the list worked totals out: free words and a price for all of it, turned into the fields above (core 0006).
    quantity = models.CharField(max_length=40, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    bought = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return (self.count * self.unit_price).quantize(Decimal("0.01")) if self.unit_price is not None else None

    class Meta:
        ordering = ["bought", "position", "pk"]
        base_manager_name = "objects"
        default_manager_name = "objects"
