"""Customer receipts carry the selling business's own name and logo, and travel by private link or email."""
from io import BytesIO
import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient
from apps.inventory.services import complete_sale
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization
from apps.tenancy.tests.test_business_admin import add_staff, signed_in
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db


def png(width=900, height=300):
    output = BytesIO()
    Image.new("RGBA", (width, height), (29, 78, 216, 255)).save(output, format="PNG")
    return SimpleUploadedFile("logo.png", output.getvalue(), content_type="image/png")


def sell(business, number="POS-1"):
    with organization_context(business["org"]):
        return complete_sale(lines=[{"variant": business["variant"], "quantity": 2}], channel="POS", number=number,
                             user=business["user"], payment_method="MPESA")


def test_owner_uploads_a_logo_that_is_resized_and_shown_on_the_business(businesses):
    a, _ = businesses
    response = a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": png()}, format="multipart")
    assert response.status_code == 200, response.content
    logo = response.json()["logo_url"]
    assert logo.startswith("/api/v1/tenancy/public/logos/") and logo.endswith(".png")
    served = APIClient().get(logo)
    assert served.status_code == 200 and served["Content-Type"] == "image/png"
    with Image.open(BytesIO(b"".join(served.streaming_content))) as image:
        assert image.size == (600, 200)
    assert a["client"].get("/api/v1/tenancy/settings/").json()["logo_url"] == logo
    bad = a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": SimpleUploadedFile("x.png", b"not an image")}, format="multipart")
    assert bad.status_code == 400
    add_staff(a["client"], "alpha-cashier", "CASHIER")
    assert signed_in("alpha-cashier").post("/api/v1/tenancy/settings/logo/", {"logo": png()}, format="multipart").status_code == 403
    assert a["client"].delete("/api/v1/tenancy/settings/logo/").json()["logo_url"] == ""
    assert APIClient().get(logo).status_code == 404


def test_receipt_uses_the_selling_business_identity_and_a_private_link(businesses):
    a, b = businesses
    a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": png()}, format="multipart")
    Organization.objects.filter(pk=a["org"].pk).update(phone="0700 000 000")
    sale = sell(a)
    data = a["client"].get(f"/api/v1/commerce/sales/{sale.pk}/receipt/").json()
    receipt = data["receipt"]
    assert receipt["business"]["name"] == "Alpha" and receipt["business"]["phone"] == "0700 000 000"
    assert "/api/v1/tenancy/public/logos/" in receipt["business"]["logo"]
    assert [(i["name"], float(i["quantity"])) for i in receipt["items"]] == [("Alpha private product", 2.0)]
    assert receipt["payments"][0]["method"] == "M-Pesa" and data["link"] is None

    link = a["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/link/", HTTP_ORIGIN="https://shop.example").json()["link"]
    assert link.startswith("https://shop.example/r/")
    token = link.rsplit("/", 1)[-1]
    public = APIClient().get(f"/api/v1/tenancy/public/receipts/{token}/")
    assert public.status_code == 200 and public.json()["number"] == "POS-1" and public.json()["business"]["name"] == "Alpha"
    assert "cogs" not in public.content.decode() and "gross_profit" not in public.content.decode()

    # Another business can neither read the sale nor share it.
    assert b["client"].get(f"/api/v1/commerce/sales/{sale.pk}/receipt/").status_code == 404
    assert b["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/link/").status_code == 404

    assert a["client"].delete(f"/api/v1/commerce/sales/{sale.pk}/receipt/link/").status_code == 204
    assert APIClient().get(f"/api/v1/tenancy/public/receipts/{token}/").status_code == 404
    fresh = a["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/link/").json()["link"].rsplit("/", 1)[-1]
    assert fresh != token and APIClient().get(f"/api/v1/tenancy/public/receipts/{fresh}/").status_code == 200
    assert APIClient().get("/api/v1/tenancy/public/receipts/guessing-is-not-going-to-work/").status_code == 404


def test_receipt_email_is_sent_in_the_business_name_with_its_logo_and_link(businesses):
    a, _ = businesses
    a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": png()}, format="multipart")
    sale = sell(a, "POS-9")
    response = a["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/email/", {"email": "customer@example.com"},
                                format="json", HTTP_ORIGIN="https://shop.example")
    assert response.status_code == 200, response.content
    message = mail.outbox[-1]
    assert message.to == ["customer@example.com"] and message.subject == "Your receipt POS-9 from Alpha"
    html = message.alternatives[0][0]
    assert "https://shop.example/api/v1/tenancy/public/logos/" in html and response.json()["link"] in html
    assert "LinTech" not in html
    assert a["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/email/", {"email": "nope"}, format="json").status_code == 400


def test_receipt_links_use_the_web_app_address_not_the_internal_api_host(businesses, settings):
    a, _ = businesses
    sale = sell(a, "POS-5")
    a["client"].post(f"/api/v1/commerce/sales/{sale.pk}/receipt/link/", HTTP_ORIGIN="https://shop.example")
    viewed = a["client"].get(f"/api/v1/commerce/sales/{sale.pk}/receipt/", HTTP_REFERER="https://shop.example/admin/sales-history")
    assert viewed.json()["link"].startswith("https://shop.example/r/")
    settings.PUBLIC_APP_URL = "https://app.business.example/"
    assert a["client"].get(f"/api/v1/commerce/sales/{sale.pk}/receipt/").json()["link"].startswith("https://app.business.example/r/")


@pytest.mark.parametrize("canvas,mark,background,expected", [
    ((400, 400), (180, 190, 220, 210), (0, 0, 0, 0), (469, 240)),          # tiny 41×21 mark lost in a transparent margin
    ((4000, 1000), (500, 300, 3500, 700), (255, 255, 255, 255), (600, 80)),  # huge logo on a white background
    ((48, 48), (0, 0, 47, 47), (0, 0, 0, 0), (240, 240)),                  # small square icon
])
def test_uploaded_logos_are_trimmed_and_scaled_to_fill_the_standard_box(businesses, canvas, mark, background, expected):
    from PIL import ImageDraw
    a, _ = businesses
    image = Image.new("RGBA", canvas, background)
    ImageDraw.Draw(image).rectangle(mark, fill=(22, 163, 74, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    response = a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": SimpleUploadedFile("logo.png", output.getvalue())}, format="multipart")
    assert response.status_code == 200, response.content
    served = APIClient().get(response.json()["logo_url"])
    with Image.open(BytesIO(b"".join(served.streaming_content))) as stored:
        # Soft anti-aliased edges may add a pixel; the logo still fills the box.
        assert max(abs(got - want) for got, want in zip(stored.size, expected)) <= 2, stored.size


def test_logo_background_is_removed_and_a_readable_version_is_made_for_the_dark_bar(businesses):
    from PIL import ImageDraw
    a, _ = businesses
    # Navy lettering with a hole (like an "o") on a plain white JPEG-style background.
    image = Image.new("RGB", (900, 300), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 60, 800, 240), fill=(16, 33, 61))
    draw.rectangle((380, 120, 520, 180), fill=(255, 255, 255))  # enclosed hole, same colour as the background
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    data = a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": SimpleUploadedFile("logo.jpg", output.getvalue())}, format="multipart").json()
    assert data["logo_dark_url"] and data["logo_dark_url"] != data["logo_url"]

    def load(url):
        return Image.open(BytesIO(b"".join(APIClient().get(url).streaming_content))).convert("RGBA")
    light, dark = load(data["logo_url"]), load(data["logo_dark_url"])
    width, height = light.size
    assert light.getpixel((width // 2, height // 2))[3] == 0          # the hole is see-through, not white
    ink = light.getpixel((10, height // 2))
    assert ink[3] == 255 and ink[:3] == (16, 33, 61) or sum(ink[:3]) < 200  # navy stays navy on receipts
    assert dark.getpixel((10, height // 2))[:3] == (255, 255, 255)      # and turns white for the dark bar
    assert a["client"].delete("/api/v1/tenancy/settings/logo/").json()["logo_dark_url"] == ""


def test_logo_trim_ignores_a_border_line_but_keeps_a_solid_badge():
    from PIL import ImageDraw
    from apps.tenancy.logos import trim
    framed = Image.new("RGBA", (360, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(framed)
    draw.line([(0, 0), (359, 0)], fill=(198, 198, 198, 207))  # a screenshot's top border
    draw.rectangle([150, 60, 209, 179], fill=(120, 200, 60, 255))  # the design itself
    assert trim(framed).size == (60, 120)
    assert trim(Image.new("RGBA", (900, 300), (29, 78, 216, 255))).size == (900, 300)
