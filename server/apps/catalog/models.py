from apps.tenancy.base import TenantModel
from decimal import Decimal
from django.db import models
from apps.core.models import TimeStamped
class Category(TimeStamped):
    name=models.CharField(max_length=120); slug=models.SlugField(); parent=models.ForeignKey("self",null=True,blank=True,on_delete=models.PROTECT); active=models.BooleanField(default=True)
    def __str__(self): return self.name
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "slug"], name="cata_category_slug_org")]
class Brand(TimeStamped):
    name=models.CharField(max_length=120); active=models.BooleanField(default=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="cata_brand_name_org")]
class Product(TimeStamped):
    STOCK_ITEM="STOCK_ITEM"; SERVICE="SERVICE"
    name=models.CharField(max_length=180); slug=models.SlugField(); category=models.ForeignKey(Category,on_delete=models.PROTECT); brand=models.ForeignKey(Brand,null=True,blank=True,on_delete=models.PROTECT); product_type=models.CharField(max_length=20,choices=[(STOCK_ITEM,"Stock item"),(SERVICE,"Service")],default=STOCK_ITEM); description=models.TextField(blank=True); active=models.BooleanField(default=True); ecommerce_visible=models.BooleanField(default=True); online_orderable=models.BooleanField(default=True)
    def __str__(self): return self.name
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "slug"], name="cata_product_slug_org")]
class ProductVariant(TimeStamped):
    use_product_image = models.BooleanField(default=True)
    product=models.ForeignKey(Product,related_name="variants",on_delete=models.CASCADE); name=models.CharField(max_length=120,default="Standard"); sku=models.CharField(max_length=64); barcode=models.CharField(max_length=64,null=True,blank=True); selling_price=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); minimum_price=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0"),help_text="Lowest price a cashier may agree when bargaining; 0 means no bargaining without a manager."); service_cost=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal("0")); minimum_stock=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); target_stock=models.DecimalField(max_digits=14,decimal_places=3,default=Decimal("0")); active=models.BooleanField(default=True)
    # Sold in packs (e.g. 2 sheets of paper for 5, 10 cable clips): one unit in stock, at the till and in its price is one
    # pack of ``pack_size`` pieces. Stock coming in can be counted in pieces and is turned into packs.
    pack_size=models.PositiveIntegerField(default=1)
    piece_name=models.CharField(max_length=40,blank=True)
    def __str__(self): return f"{self.product} — {self.name}"
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.CheckConstraint(condition=models.Q(pack_size__gte=1), name="cata_variant_pack_size_positive"), models.UniqueConstraint(fields=["organization", "sku"], name="cata_productvariant_sku_org"), models.UniqueConstraint(fields=["organization", "barcode"], name="cata_productvariant_barcode_org")]
class ProductOptionType(TimeStamped):
    product=models.ForeignKey(Product,related_name="option_types",on_delete=models.CASCADE)
    name=models.CharField(max_length=80)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["product","name"],name="unique_product_option_type")]
        base_manager_name = "objects"
        default_manager_name = "objects"
class ProductOptionValue(TimeStamped):
    option_type=models.ForeignKey(ProductOptionType,related_name="values",on_delete=models.CASCADE)
    value=models.CharField(max_length=120)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["option_type","value"],name="unique_product_option_value")]
        base_manager_name = "objects"
        default_manager_name = "objects"
class ProductVariantOptionValue(TimeStamped):
    variant=models.ForeignKey(ProductVariant,related_name="option_assignments",on_delete=models.CASCADE)
    value=models.ForeignKey(ProductOptionValue,related_name="variant_assignments",on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["variant","value"],name="unique_variant_option_value")]
        base_manager_name = "objects"
        default_manager_name = "objects"
class PriceHistory(TenantModel):
    variant=models.ForeignKey(ProductVariant,related_name="price_history",on_delete=models.CASCADE); price=models.DecimalField(max_digits=14,decimal_places=2); effective_at=models.DateTimeField(auto_now_add=True); changed_by=models.ForeignKey("auth.User",null=True,on_delete=models.SET_NULL)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"

class ProductImage(TimeStamped):
    file = models.ImageField(upload_to="products/%Y/%m/", blank=True)
    variant = models.ForeignKey(ProductVariant, related_name="display_images", null=True, blank=True, on_delete=models.CASCADE)
    product=models.ForeignKey(Product,related_name="images",on_delete=models.CASCADE); image_url=models.URLField(max_length=500,blank=True); alt_text=models.CharField(max_length=180,blank=True); sort_order=models.PositiveIntegerField(default=0)
    class Meta:
        ordering=["sort_order","id"]
        base_manager_name = "objects"
        default_manager_name = "objects"


def check_code_free(sku, barcode=None, exclude_pk=None):
    """A clear message, naming the product, when a SKU or barcode is already taken (hidden products included)."""
    from rest_framework.exceptions import ValidationError
    for field, value, label in [("sku", sku, "code (SKU)"), ("barcode", barcode, "barcode")]:
        if not value:
            continue
        taken = ProductVariant.objects.filter(**{field: value}).exclude(pk=exclude_pk).select_related("product").first()
        if taken:
            hidden = not (taken.active and taken.product.active)
            advice = ("It is hidden: find it under Products (marked Hidden), open it, tick Active and save to use it again, "
                      "then add stock with Receive stock." if hidden else "Open that product to add stock, or choose a different code.")
            raise ValidationError({field: f"The {label} {value} already belongs to {taken.product.name}. {advice}"})


def check_price_range(selling_price, minimum_price):
    """The bargaining floor must lie between zero and the selling (asking) price."""
    from rest_framework.exceptions import ValidationError
    selling, minimum = Decimal(str(selling_price or 0)), Decimal(str(minimum_price or 0))
    if minimum < 0:
        raise ValidationError({"minimum_price": "Lowest price cannot be negative."})
    if minimum > selling:
        raise ValidationError({"minimum_price": "Lowest price cannot be higher than the selling price."})


def shelves_in_use():
    """Whether the current business maps stock to racks (the Shelves & locations tool). Without it, every category can hold
    stock straight away and stock is kept without a shelf, so a shop with no racks is never blocked from adding products."""
    from apps.tenancy.context import organization_id
    from apps.tenancy.models import Organization
    from apps.tenancy.middleware import effective_modules
    organization = Organization.objects.select_related("subscription__plan").filter(pk=organization_id()).first()
    return bool(organization and "locations" in effective_modules(organization))


def service_category_ids():
    """The Services category and its service groups (two levels), which are managed on the Cyber pages, not with products.
    A category that holds any stock item is never counted, so a stock category that happens to be called Services stays."""
    root=Category.objects.filter(slug="services").values_list("id",flat=True).first()
    if not root:
        return set()
    level=set(Category.objects.filter(parent_id=root).values_list("id",flat=True))
    ids={root}|level|set(Category.objects.filter(parent_id__in=level).values_list("id",flat=True))
    stocked=set(Product.objects.filter(category_id__in=ids,product_type=Product.STOCK_ITEM).values_list("category_id",flat=True))
    return ids-stocked


def category_tree():
    """Every active category in hierarchy order (descendant_ids includes the category itself), labelled child first ("Wall Chargers – Mobile Accessories").
    A sub-category is stored on its nearest parent's rack; categories with no rack can't hold stock yet."""
    from apps.inventory.models import ShelfStackCategory
    categories={c.id:c for c in Category.objects.filter(active=True).exclude(id__in=service_category_ids())}
    racks_required=shelves_in_use()
    racks={}
    for assignment in ShelfStackCategory.objects.filter(stack__active=True,category_id__in=categories).select_related("stack"):
        racks.setdefault(assignment.category_id,{})[assignment.stack_id]=assignment.stack.display_name
    rows={}
    for category in categories.values():
        # Walk up through active parents; the nearest rack assignment applies.
        chain,node,seen,own=[],category,set(),None
        while node and node.id not in seen:
            seen.add(node.id);chain.append(node)
            if own is None:own=racks.get(node.id)
            node=categories.get(node.parent_id)
        own=own or {}
        rows[category.id]={"id":category.id,"name":" – ".join(c.name for c in chain),
            "path":[c.name for c in reversed(chain)],"depth":len(chain)-1,"ancestor_ids":[c.id for c in chain],
            "rack_ids":sorted(own),"rack_names":sorted(set(own.values())),"available":bool(own) or not racks_required}
    for row in rows.values():
        row["descendant_ids"]=[other["id"] for other in rows.values() if row["id"] in other["ancestor_ids"]]
    return sorted(rows.values(),key=lambda row:[part.lower() for part in row["path"]])


def racked_categories():
    """Categories that can hold products now: (category, label, rack names)."""
    categories={c.id:c for c in Category.objects.filter(active=True)}
    return [(categories[row["id"]],row["name"],row["rack_names"]) for row in category_tree() if row["available"]]


def category_lineage(category_id):
    """The category and its parents (a sub-category is stored on its parent's rack)."""
    ids,seen=[],set()
    while category_id and category_id not in seen:
        seen.add(category_id);ids.append(category_id)
        category_id=Category.objects.filter(pk=category_id).values_list("parent_id",flat=True).first()
    return ids



class ProductImport(TenantModel):
    """One committed spreadsheet import. Its rows let the same file be uploaded again without doubling anything."""
    reference=models.CharField(max_length=40); file_name=models.CharField(max_length=255); sha256=models.CharField(max_length=64,db_index=True)
    summary=models.JSONField(default=dict); created_by=models.ForeignKey("auth.User",null=True,on_delete=models.SET_NULL); created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["-created_at"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "reference"], name="cata_productimport_ref_org")]


class ProductImportRow(TenantModel):
    """A spreadsheet row that created a variant, with a fingerprint of the row exactly as it was imported."""
    batch=models.ForeignKey(ProductImport,related_name="rows",on_delete=models.CASCADE); row_number=models.PositiveIntegerField()
    variant=models.ForeignKey(ProductVariant,related_name="import_rows",null=True,on_delete=models.SET_NULL); sku=models.CharField(max_length=64); fingerprint=models.CharField(max_length=64)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
