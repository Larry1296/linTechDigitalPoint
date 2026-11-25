"""Barcodes for every product, so a camera or scanner at the till finds it.

A product either carries the maker's barcode (scanned once and linked to it) or gets the shop's own: an EAN-13 in the
20–29 range that GS1 keeps for codes used only inside a shop, so it never clashes with a maker's code. EAN-13 is the
shortest common barcode and the one a laptop camera reads best. The shop's own code is 21, the product's id in ten
digits, and the check digit; it never changes, so printed labels keep working.
"""
from django.db import transaction
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from apps.tenancy.transactions import lock_business
from .models import ProductVariant, check_code_free


def check_digit(first12):
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def shop_code(variant_id):
    body = f"21{int(variant_id):010d}"
    return body + check_digit(body)


def clean(code):
    """What a scanner or camera read, as stored: no spaces; letters kept for Code 128 labels."""
    return "".join(str(code or "").split())[:64]


def _audit(variant, user, before, reason):
    AuditLog.objects.create(action="UPDATE", object_type="ProductVariant", object_id=str(variant.pk), user=user,
                            before={"barcode": before}, after={"barcode": variant.barcode, "reason": reason})


@transaction.atomic
def give_barcodes(variant_ids, *, user):
    """Products without a barcode get the shop's own; ones that have one keep it. Returned in the order asked."""
    lock_business()
    variants = {v.pk: v for v in ProductVariant.objects.select_for_update().select_related("product").filter(pk__in=variant_ids)}
    for variant in variants.values():
        if variant.barcode:
            continue
        code = shop_code(variant.pk)
        if ProductVariant.objects.filter(barcode=code).exclude(pk=variant.pk).exists():
            continue  # a maker's code that happens to match: leave this one for linking by hand
        variant.barcode = code
        ProductVariant.objects.filter(pk=variant.pk).update(barcode=code)
        _audit(variant, user, None, "Shop's own barcode given for labels")
    return [variants[pk] for pk in variant_ids if pk in variants]


@transaction.atomic
def link_barcode(variant, code, *, user, replace=False):
    """A barcode scanned at the till or on the product page is saved on that product, so the next scan finds it."""
    lock_business()
    variant = ProductVariant.objects.select_for_update().select_related("product").get(pk=variant.pk)
    code = clean(code)
    if len(code) < 4:
        raise ValidationError({"barcode": "That barcode is too short. Scan it again."})
    if variant.barcode == code:
        return variant
    check_code_free(None, code, exclude_pk=variant.pk)
    if variant.barcode and not replace:
        raise ValidationError({"barcode": f"{variant.product.name} already has the barcode {variant.barcode}.",
                               "code": "has_barcode", "current": variant.barcode})
    before = variant.barcode
    ProductVariant.objects.filter(pk=variant.pk).update(barcode=code)
    variant.barcode = code
    _audit(variant, user, before, "Barcode scanned and linked")
    return variant
