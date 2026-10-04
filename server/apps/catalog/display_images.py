"""Actual product photographs, never category/AI illustration fallbacks."""
from io import BytesIO
from uuid import uuid4
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.files.base import ContentFile
from rest_framework import serializers
from .models import ProductImage


def optimise_upload(upload):
    if not upload:
        return None
    if upload.size > 15 * 1024 * 1024:
        raise serializers.ValidationError({"display_image": "Choose an image smaller than 15 MB."})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError("format")
                image.load()
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = BytesIO()
                image.save(output, format="WEBP", quality=85, method=6)
        return ContentFile(output.getvalue(), name=f"{uuid4().hex}.webp")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError({"display_image": "Upload a valid JPEG, PNG or WebP photograph."})


def image_url(image):
    return image.file.url if image.file else image.image_url


def actual_images(product, variant=None):
    rows = product.images.all()
    return [image for image in rows if image.variant_id == (variant.pk if variant else None)
            and image_url(image) and not image.image_url.startswith("/images/catalog/")
            and not image.alt_text.startswith("AI illustration")]


def variant_images(variant):
    dedicated = actual_images(variant.product, variant)
    selected = dedicated or (actual_images(variant.product) if variant.use_product_image else [])
    return [{"url": image_url(image), "alt": image.alt_text} for image in selected]


def save_display_image(product, upload, variant=None):
    if variant and variant.product_id != product.pk:
        raise serializers.ValidationError({"variant_id": "Choose a variant of this product."})
    image = product.images.filter(variant=variant).order_by("sort_order", "id").first()
    if image is None:
        image = ProductImage(product=product, variant=variant)
    image.file.save(upload.name, upload, save=False)
    image.image_url = ""
    image.alt_text = f"{product.name} — {variant.name}"[:180] if variant else product.name
    try:
        image.save()
    except Exception:
        image.file.storage.delete(image.file.name)
        raise
    return image


def boolean(data, key, default=True):
    return serializers.BooleanField().run_validation(data.get(key, default))


def options(data):
    import json
    value = data.get("option_values") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise serializers.ValidationError({"option_values": "Enter valid variant options."})
    if not isinstance(value, list):
        raise serializers.ValidationError({"option_values": "Enter a list of variant options."})
    return value
