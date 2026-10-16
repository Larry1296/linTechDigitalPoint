from django.conf import settings
from django.db import models
from django.utils import timezone

MODULES = ["inventory", "locations", "pos", "services", "customers", "expenses", "mpesa", "reports", "branches", "staff", "chama", "investments"]
def default_modules():
    return list(MODULES)

def logo_path(instance, filename):
    # Random names: logos are public (they print on customer receipts) but not enumerable.
    from uuid import uuid4
    return f"logos/{uuid4().hex}.png"


class Organization(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    # How the business makes money and what kind it is; see business_profiles.py. business_type is the display label.
    business_model = models.CharField(max_length=10, choices=[("GOODS", "Sells goods"), ("SERVICES", "Provides services"), ("MIXED", "Goods and services")], default="MIXED")
    sector = models.CharField(max_length=40, blank=True)
    business_size = models.CharField(max_length=10, choices=[("SOLO", "Just me"), ("SMALL", "2 – 10 people"), ("MEDIUM", "11 – 50 people")], default="SMALL")
    business_type = models.CharField(max_length=100, blank=True)
    logo_url = models.URLField(blank=True)
    logo = models.ImageField(upload_to=logo_path, blank=True)  # for light surfaces: receipts, email
    logo_dark = models.ImageField(upload_to=logo_path, blank=True)  # for the dark navigation bar
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    country = models.CharField(max_length=2, default="KE")
    currency = models.CharField(max_length=3, default="KES")
    timezone = models.CharField(max_length=64, default="Africa/Nairobi")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="owned_organizations")
    active = models.BooleanField(default=True)
    enabled_modules = models.JSONField(default=default_modules)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.name

class BusinessKind(models.Model):
    """A kind of business an owner described under "Other", with the tools and starter list they chose.

    The platform owner reviews it; once listed, later owners find it in the list like any built-in kind (see business_profiles.py).
    Services keep only names and units: each business sets its own prices."""
    STATUSES = [("SUGGESTED", "Waiting for review"), ("LISTED", "Listed for everyone"), ("HIDDEN", "Not listed")]
    business_model = models.CharField(max_length=10, choices=[("GOODS", "Sells goods"), ("SERVICES", "Provides services"), ("MIXED", "Goods and services")])
    key = models.SlugField(max_length=100)  # the label folded, so "Poultry farm" and "poultry  FARM" are one kind
    label = models.CharField(max_length=100)
    hint = models.CharField(max_length=160, blank=True)
    keywords = models.CharField(max_length=255, blank=True)
    modules = models.JSONField(default=list)
    categories = models.JSONField(default=list)
    services = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=STATUSES, default="SUGGESTED")
    uses = models.PositiveIntegerField(default=0)  # businesses that described or chose it
    created_by = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business_model", "key"], name="unique_business_kind")]
        ordering = ["-created_at"]

    @property
    def sector_id(self):
        return f"kind-{self.pk}"

    def __str__(self):
        return self.label


class Membership(models.Model):
    ROLES = [(x, x.replace("_", " ").title()) for x in ["OWNER", "ADMIN", "MANAGER", "CASHIER", "INVENTORY", "ACCOUNTANT", "SERVICE_ATTENDANT", "READ_ONLY", "CUSTOM"]]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=24, choices=ROLES, default="READ_ONLY")
    status = models.CharField(max_length=16, choices=[("ACTIVE", "Active"), ("SUSPENDED", "Suspended"), ("INVITED", "Invited")], default="ACTIVE")
    invitation_state = models.CharField(max_length=16, default="ACCEPTED")
    joined_at = models.DateTimeField(default=timezone.now)
    permissions = models.JSONField(default=list, blank=True)
    def save(self, *args, **kwargs):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=self.organization_id)
            subscription = OrganizationSubscription.objects.select_related("plan").filter(organization_id=self.organization_id).first()
            limit = subscription.plan.user_limit if subscription and subscription.plan_id else None
            if self.status in {"ACTIVE", "INVITED"} and limit is not None:
                used = Membership.objects.filter(organization_id=self.organization_id, status__in=["ACTIVE", "INVITED"]).exclude(pk=self.pk).count()
                if used >= limit:
                    raise ValidationError("The configured plan's user limit has been reached.")
            return super().save(*args, **kwargs)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organization"], name="unique_business_membership")]

class BranchMembership(models.Model):
    """Optional branch-level access for users who should not manage every store."""
    ROLES = [("ADMIN", "Branch Admin"), ("MANAGER", "Branch Manager"), ("STAFF", "Branch Staff")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="branch_memberships")
    store = models.ForeignKey("core.Store", on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=16, choices=ROLES, default="STAFF")
    status = models.CharField(max_length=16, choices=[("ACTIVE", "Active"), ("SUSPENDED", "Suspended")], default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        from apps.tenancy.context import organization_id
        from apps.tenancy.models import Membership
        active = organization_id()
        if active is None or self.store.organization_id != active:
            raise ValidationError("A branch must belong to the active business.")
        if not Membership.objects.filter(user_id=self.user_id, organization_id=active, status="ACTIVE").exists():
            raise ValidationError("The branch user must be an active business member.")
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "store"], name="unique_branch_membership")]

class SubscriptionPlan(models.Model):
    code = models.CharField(max_length=20, blank=True)  # BASIC, PRO: what the platform's own logic refers to
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="KES")
    period_days = models.PositiveIntegerField(default=30)
    description = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    enabled_modules = models.JSONField(default=default_modules)
    user_limit = models.PositiveIntegerField(null=True, blank=True)
    branch_limit = models.PositiveIntegerField(null=True, blank=True)
    reporting_level = models.CharField(max_length=40, blank=True)
    billing_period = models.CharField(max_length=30, blank=True)
    usage_limits = models.JSONField(default=dict, blank=True)

class OrganizationSubscription(models.Model):
    organization = models.OneToOneField(Organization, related_name="subscription", on_delete=models.PROTECT)
    plan = models.ForeignKey(SubscriptionPlan, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="TRIAL", choices=[(x, x.replace("_", " ").title()) for x in ["TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED", "EXPIRED"]])
    ends_at = models.DateTimeField(null=True, blank=True)
    # Never expires and never asks for payment: the platform owner's own businesses, or a free account the platform grants.
    complimentary = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class SubscriptionPayment(models.Model):
    """A payment for one subscription period. Platform billing: kept outside the subscriber's own books."""
    STATUSES = [(x, x.title()) for x in ["PENDING", "PAID", "FAILED", "CANCELLED"]]
    organization = models.ForeignKey(Organization, related_name="subscription_payments", on_delete=models.PROTECT)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    method = models.CharField(max_length=16, choices=[("MPESA", "M-Pesa"), ("MANUAL", "Recorded by the platform")], default="MPESA")
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="PENDING")
    status_detail = models.CharField(max_length=255, blank=True)
    checkout_request_id = models.CharField(max_length=100, blank=True, db_index=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=40, blank=True)
    period_ends_at = models.DateTimeField(null=True, blank=True)  # the subscription end this payment produced
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["checkout_request_id"], condition=~models.Q(checkout_request_id=""), name="unique_mpesa_checkout"),
                       models.UniqueConstraint(fields=["receipt_number"], condition=~models.Q(receipt_number=""), name="unique_payment_receipt")]


class ReceiptLink(models.Model):
    """A private share link for one sale's receipt, sent to the customer by WhatsApp or email.

    A platform-level index: it is looked up by its unguessable token alone (the customer has no
    account), so it is not a TenantModel; the receipt itself is then loaded inside the owning
    business's context.
    """
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, editable=False)
    sale_id = models.BigIntegerField()
    token = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "sale_id"], name="one_receipt_link_per_sale")]


class MpesaExpressSetup(models.Model):
    """A business's own Safaricom till or paybill, so the till can send the customer an M-Pesa prompt (STK push) and the
    money goes straight to the business. Kept with the organization rather than as business data, because Safaricom's
    callback finds the business by ``callback_token`` before any business is known. The secrets are stored encrypted
    (commerce/secrets.py) and never sent back to the browser."""
    NONE, TILL, PAYBILL = "NONE", "TILL", "PAYBILL"
    organization = models.OneToOneField(Organization, related_name="mpesa_express", on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=[(NONE, "No till or paybill: manual payments"), (TILL, "Till number (Buy Goods)"), (PAYBILL, "Paybill")], default=NONE)
    # Paybill: the paybill number. Till: the store number (head office number) Safaricom gave with the till.
    shortcode = models.CharField(max_length=12, blank=True)
    till_number = models.CharField(max_length=12, blank=True)  # Till only: the number customers pay to
    account_reference = models.CharField(max_length=12, blank=True)  # Paybill only: the account the payment is booked to
    environment = models.CharField(max_length=10, choices=[("PRODUCTION", "Live"), ("SANDBOX", "Testing (Safaricom sandbox)")], default="PRODUCTION")
    consumer_key = models.TextField(blank=True)  # encrypted
    consumer_secret = models.TextField(blank=True)  # encrypted
    passkey = models.TextField(blank=True)  # encrypted
    callback_token = models.CharField(max_length=64, unique=True)
    # The secret in the till's payment-notification address. Hex, so the address never spells a word Safaricom refuses in
    # callback addresses; it never changes, because Safaricom registers a live address only once.
    till_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    till_registered_at = models.DateTimeField(null=True, blank=True)  # Safaricom accepted the till's notification address
    till_detail = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)  # Safaricom accepted the consumer key and secret
    tested_at = models.DateTimeField(null=True, blank=True)  # a prompt went through end to end
    status_detail = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

