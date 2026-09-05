from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import ProductVariant
from apps.core.models import TimeStamped


class CyberServiceProfile(TimeStamped):
    BILLING_UNITS = [
        (value, value.replace("_", " ").title())
        for value in ["PER_PAGE", "PER_COPY", "PER_SHEET", "PER_DOCUMENT", "PER_HOUR", "PER_ITEM", "FIXED"]
    ]
    variant = models.OneToOneField(ProductVariant, related_name="cyber_profile", on_delete=models.PROTECT)
    billing_unit = models.CharField(max_length=20, choices=BILLING_UNITS)
    default_turnaround = models.DurationField(null=True, blank=True)
    requires_job = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    publicly_advertised = models.BooleanField(default=True)
    online_orderable = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.variant} ({self.get_billing_unit_display()})"


class ServiceMaterialRequirement(TimeStamped):
    service_variant = models.ForeignKey(
        ProductVariant, related_name="material_requirements", on_delete=models.PROTECT
    )
    material_variant = models.ForeignKey(
        ProductVariant, related_name="service_material_uses", on_delete=models.PROTECT
    )
    quantity_per_service_unit = models.DecimalField(max_digits=14, decimal_places=3)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_variant", "material_variant"], name="unique_cyber_material_requirement"
            ),
            models.CheckConstraint(
                condition=Q(quantity_per_service_unit__gt=0), name="positive_cyber_material_quantity"
            ),
        ]


class CyberJob(TimeStamped):
    STATUSES = [
        (value, value.replace("_", " ").title())
        for value in ["DRAFT", "QUEUED", "IN_PROGRESS", "WAITING_CUSTOMER", "READY", "COMPLETED", "CANCELLED"]
    ]
    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="cyber_jobs", on_delete=models.SET_NULL
    )
    walk_in_customer_name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=24, choices=STATUSES, default="DRAFT")
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, related_name="cyber_jobs_operated", on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    sale = models.OneToOneField(
        "commerce.Sale", null=True, blank=True, related_name="cyber_job", on_delete=models.PROTECT
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [("complete_cyber_job", "Can complete and take payment for Cyber jobs")]


class CyberJobLine(models.Model):
    job = models.ForeignKey(CyberJob, related_name="lines", on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    service_name = models.CharField(max_length=220)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    billing_unit = models.CharField(max_length=20, choices=CyberServiceProfile.BILLING_UNITS)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    service_details = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_cyber_line_quantity")]
