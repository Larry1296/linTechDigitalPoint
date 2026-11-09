"""With Cloudinary's keys set, uploaded logos and product photos live in Cloudinary (they survive a host's disk being
wiped on redeploy) and are still served by the app's own views under the same names: logos publicly, product photos
only to members of the business."""
from io import BytesIO
from unittest import mock
from urllib.error import HTTPError

import cloudinary.exceptions
import pytest
from django.core.files.base import ContentFile
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.models import ProductImage
from apps.core import media_storage
from test_product_display_images import catalog, create, photo  # noqa: F401
from apps.tenancy.tests.test_customer_receipts import png
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db
CLOUD = {"CLOUDINARY_CLOUD_NAME": "duka", "CLOUDINARY_API_KEY": "key", "CLOUDINARY_API_SECRET": "secret"}


class FakeCloudinary:
    """Cloudinary's upload, delete and lookup, kept in memory; files come back only through a signed link."""

    def __init__(self):
        self.files = {}
        self.uploads = []

    def upload(self, content, **options):
        assert options["resource_type"] == "raw" and options["type"] == "authenticated" and options["api_secret"] == "secret"
        self.files[options["public_id"]] = content.read()
        self.uploads.append(options["public_id"])
        return {"public_id": options["public_id"]}

    def destroy(self, name, **options):
        self.files.pop(name, None)
        return {"result": "ok"}

    def resource(self, name, **options):
        if name not in self.files:
            raise cloudinary.exceptions.NotFound(name)
        return {"bytes": len(self.files[name])}

    def urlopen(self, url, timeout):
        assert "/raw/authenticated/" in url and "/s--" in url  # signed, never a public link
        name = url.split("/raw/authenticated/", 1)[1].split("/", 2)[2]  # after the signature and version
        if name not in self.files:
            raise HTTPError(url, 404, "Not Found", {}, None)
        return BytesIO(self.files[name])


@pytest.fixture
def cloud(settings):
    for key, value in CLOUD.items():
        setattr(settings, key, value)
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "apps.core.media_storage.CloudinaryMediaStorage"}}
    fake = FakeCloudinary()
    with mock.patch.object(media_storage.cloudinary.uploader, "upload", fake.upload), \
            mock.patch.object(media_storage.cloudinary.uploader, "destroy", fake.destroy), \
            mock.patch.object(media_storage.cloudinary.api, "resource", fake.resource), \
            mock.patch.object(media_storage, "urlopen", fake.urlopen):
        yield fake


def test_a_logo_is_kept_in_cloudinary_and_served_by_the_app(businesses, cloud):  # noqa: F811
    a, _ = businesses
    response = a["client"].post("/api/v1/tenancy/settings/logo/", {"logo": png()}, format="multipart")
    assert response.status_code == 200, response.content
    logo = response.json()["logo_url"]
    name = "logos/" + logo.rsplit("/", 1)[-1]
    assert logo.startswith("/api/v1/tenancy/public/logos/") and name in cloud.files and len(cloud.uploads) == 2  # light and dark
    served = APIClient().get(logo)  # signed out, as on a customer's receipt
    assert served.status_code == 200 and served["Content-Type"] == "image/png"
    with Image.open(BytesIO(b"".join(served.streaming_content))) as image:
        assert image.size == (600, 200)
    assert a["client"].delete("/api/v1/tenancy/settings/logo/").json()["logo_url"] == ""
    assert cloud.files == {} and APIClient().get(logo).status_code == 404


def test_a_product_photo_is_kept_in_cloudinary_and_shown_only_to_the_business(catalog, cloud):  # noqa: F811
    client, category, _, root = catalog
    assert create(client, category, display_image=photo()).status_code == 201
    image = ProductImage.objects.get()
    assert image.file.name in cloud.files and not any(root.iterdir())  # nothing on the server's own disk
    assert image.file.url == f"/media/{image.file.name}"
    served = client.get(image.file.url)
    assert served.status_code == 200
    with Image.open(BytesIO(b"".join(served.streaming_content))) as saved:
        assert saved.size == (1600, 800)
    assert APIClient().get(image.file.url).status_code == 404


def test_a_missing_file_is_not_found_and_links_are_signed(cloud):
    storage = media_storage.CloudinaryMediaStorage()
    with pytest.raises(FileNotFoundError):
        storage.open("logos/gone.png")
    assert not storage.exists("logos/gone.png")
    assert storage.save("logos/abc.png", ContentFile(b"png")) == "logos/abc.png"
    assert storage.exists("logos/abc.png") and storage.size("logos/abc.png") == 3 and storage.open("logos/abc.png").read() == b"png"
    with pytest.raises(ValueError):
        storage.open("logos/abc.png", "wb")
