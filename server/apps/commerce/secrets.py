"""Encryption for the secrets a business gives the platform (its Daraja consumer secret and passkey).

The key is FIELD_ENCRYPTION_KEY when set (a Fernet key), else one derived from SECRET_KEY: changing either makes the
stored secrets unreadable, and the business is asked to enter them again.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or base64.urlsafe_b64encode(hashlib.sha256(f"field-encryption:{settings.SECRET_KEY}".encode()).digest()).decode()
    return Fernet(key.encode())


def seal(value):
    return _fernet().encrypt(value.encode()).decode() if value else ""


def unseal(value):
    """The secret, or "" when it was never given or can no longer be read."""
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""
