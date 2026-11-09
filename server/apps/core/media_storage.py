"""Uploaded files (business logos, product photos) kept in Cloudinary, so they survive a redeploy or restart of a host
whose own disk is wiped (Render).

Files are stored exactly as Django names them ("logos/<random>.png", "products/2026/11/<random>.webp"), as
private raw files that only a signed request can fetch. Nothing links to Cloudinary directly: the app keeps serving
them through its own views (public logos, product photos only to members of the business), which read them here.
"""
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import cloudinary
import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

OPTIONS = {"resource_type": "raw", "type": "authenticated"}


@deconstructible
class CloudinaryMediaStorage(Storage):
    def __init__(self):
        self.config = {"cloud_name": settings.CLOUDINARY_CLOUD_NAME, "api_key": settings.CLOUDINARY_API_KEY,
                       "api_secret": settings.CLOUDINARY_API_SECRET, "secure": True}

    def _options(self, **extra):
        return {**self.config, **OPTIONS, **extra}

    def _save(self, name, content):
        content.seek(0)
        result = cloudinary.uploader.upload(content, **self._options(public_id=name, overwrite=True, invalidate=True,
                                                                     unique_filename=False, use_filename=False))
        return result["public_id"]

    def _open(self, name, mode="rb"):
        if "r" not in mode or "+" in mode:
            raise ValueError("Stored files are replaced with save(), not opened for writing.")
        url, _ = cloudinary.utils.cloudinary_url(name, sign_url=True, **self._options())
        try:
            with urlopen(url, timeout=20) as response:
                data = response.read()
        except HTTPError as error:
            if error.code == 404:
                raise FileNotFoundError(name) from error
            raise OSError(f"Could not fetch {name} from Cloudinary: HTTP {error.code}") from error
        except URLError as error:
            raise OSError(f"Could not fetch {name} from Cloudinary: {error.reason}") from error
        file = File(BytesIO(data), name=name)
        file.mode = mode
        return file

    def delete(self, name):
        if name:
            cloudinary.uploader.destroy(name, **self._options(invalidate=True))

    def exists(self, name):
        try:
            cloudinary.api.resource(name, **self._options())
        except cloudinary.exceptions.NotFound:
            return False
        return True

    def size(self, name):
        try:
            return cloudinary.api.resource(name, **self._options())["bytes"]
        except cloudinary.exceptions.NotFound as error:
            raise FileNotFoundError(name) from error

    def url(self, name):
        # The app's own address for the file (product photos go through the members-only /media/ view).
        return f"{settings.MEDIA_URL}{name}"

    def get_available_name(self, name, max_length=None):
        # Every upload already gets a random name, so asking Cloudinary first would only spend its API quota.
        return name
