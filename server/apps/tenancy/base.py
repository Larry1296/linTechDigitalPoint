from django.db import models
from django.core.exceptions import ValidationError
from .context import organization_id, branch_id


class ActiveOrganization(models.Expression):
    """Bind at SQL compilation, including class-level DRF querysets and subqueries."""
    output_field = models.BigIntegerField()
    def as_sql(self, compiler, connection):
        return "%s", [organization_id()]


class TenantQuerySet(models.QuerySet):
    def _check_result_context(self):
        active = (organization_id(), branch_id())
        if getattr(self, "_result_organization", None) != active:
            self._result_cache = None
            self._prefetch_done = False
        self._result_organization = active

    def _fetch_all(self):
        # SQL binding alone does not protect an already evaluated queryset.
        self._check_result_context()
        return super()._fetch_all()

    def __getitem__(self, key):
        self._check_result_context()
        return super().__getitem__(key)

    def contains(self, obj):
        self._check_result_context()
        return super().contains(obj)

    def count(self):
        self._check_result_context()
        return super().count()

    def exists(self):
        self._check_result_context()
        return super().exists()

    def update(self, **kwargs):
        if "organization" in kwargs or "organization_id" in kwargs:
            raise ValidationError("Organization ownership cannot be changed.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            # ON CONFLICT has no tenant WHERE clause: a submitted primary key
            # could otherwise update another business without changing ownership.
            raise ValidationError("Use a tenant-scoped update instead of a bulk upsert.")
        objs = list(objs)
        for obj in objs:
            obj.validate_tenant()
        return super().bulk_create(objs, **kwargs)


class BranchScope(models.Lookup):
    lookup_name = "branch_scope"
    prepare_rhs = False

    def as_sql(self, compiler, connection):
        lhs, params = self.process_lhs(compiler, connection)
        current = branch_id()
        return f"({lhs} = %s OR %s IS NULL)", [*params, current, current]


models.ForeignKey.register_lookup(BranchScope)
models.BigAutoField.register_lookup(BranchScope)

# Business-wide catalog/configuration is shared; operational records follow branch.
BRANCH_PATHS = {
    "inventory.zone": "store", "inventory.shelf": "zone__store",
    "inventory.shelfstack": "zone__store", "inventory.shelflevel": "stack__zone__store",
    "inventory.shelfstackcategory": "stack__zone__store",
    "inventory.shelfhistory": "shelf__zone__store",
    "inventory.stockbalance": "shelf__zone__store",
    "inventory.variantpreferredlocation": "shelf__zone__store",
    "inventory.stockreceiptline": "receipt__branch",
    "inventory.stockreceiptplacement": "line__receipt__branch",
    "inventory.stockreceiptlinecorrection": "line__receipt__branch",
    "inventory.stockadjustment": "shelf__zone__store",
    "commerce.saleitem": "sale__branch", "commerce.saleallocation": "item__sale__branch",
    "commerce.salereturnline": "sale_return__branch",
    "inventory.purchasereturnline": "purchase_return__branch",
    "commerce.orderitem": "order__branch", "commerce.orderstatushistory": "order__branch",
    "cyber.cyberjobline": "job__branch",
    "mpesa.mpesaoutlet": "store", "mpesa.mpesasession": "outlet__store",
    "mpesa.mpesatransaction": "outlet__store", "mpesa.mpesacommissionentry": "outlet__store",
    "mpesa.mpesareconciliation": "session__outlet__store",
    "accounting.expensepayment": "expense__branch", "accounting.supplierpurchase": "receipt__branch",
    "accounting.purchasepayment": "purchase__receipt__branch",
    "accounting.journalline": "entry__branch",
    "accounting.loanrepayment": "loan__branch",
}


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        rows = super().get_queryset().filter(organization_id=ActiveOrganization())
        path = "branch" if any(f.name == "branch" for f in self.model._meta.fields) else BRANCH_PATHS.get(self.model._meta.label_lower)
        if self.model._meta.label_lower == 'inventory.movement':
            rows = rows.filter(models.Q(source__zone__store__branch_scope=True) | models.Q(destination__zone__store__branch_scope=True))
        if self.model._meta.label_lower == 'commerce.payment':
            rows = rows.filter(models.Q(sale__branch__branch_scope=True) | models.Q(order__branch__branch_scope=True))
        if path:
            rows = rows.filter(**{path + "__branch_scope": True})
        return rows


class TenantModel(models.Model):
    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT, editable=False)
    objects = TenantManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def validate_tenant(self):
        active = organization_id()
        if active is None or self.organization_id not in (None, active):
            raise ValidationError("An authorized organization context is required.")
        self.organization_id = active
        # Check IDs as well as model objects; do not trust serializer validation alone.
        for field in self._meta.concrete_fields:
            if not field.is_relation or field.name == "organization":
                continue
            related = field.remote_field.model
            value = getattr(self, field.attname)
            if value is None:
                continue
            if issubclass(related, TenantModel):
                if not related.objects.filter(pk=value).exists():
                    raise ValidationError({field.name: "Choose a record in the active business."})
            elif related._meta.label_lower == "auth.user" and self._meta.label_lower != "accounts.customerprofile":
                from .models import Membership
                from apps.accounts.models import CustomerProfile
                # Historical actors can retain suspended memberships; access is checked separately.
                if not Membership.objects.filter(organization_id=active, user_id=value).exists() and not CustomerProfile.objects.filter(user_id=value).exists():
                    raise ValidationError({field.name: "Choose a user in the active business."})

    def save(self, *args, **kwargs):
        if any(f.name == "branch" for f in self._meta.fields):
            if self._state.adding and self.branch_id is None:
                self.branch_id = branch_id()
                if self.branch_id is None:
                    from apps.core.models import Store
                    stores = list(Store.objects.values_list("pk", flat=True)[:2])
                    if len(stores) == 1:
                        self.branch_id = stores[0]
            if branch_id() is not None and self.branch_id != branch_id():
                raise ValidationError("Choose a record in the active branch.")
        self.validate_tenant()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.validate_tenant()
        return super().delete(*args, **kwargs)
