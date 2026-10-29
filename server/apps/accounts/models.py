from apps.tenancy.base import TenantModel
from django.conf import settings
from django.db import models
from apps.core.models import TimeStamped
class CustomerProfile(TimeStamped):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,related_name="customer_profiles",on_delete=models.CASCADE); phone=models.CharField(max_length=30,blank=True)
    def __str__(self): return self.user.get_full_name() or self.user.username
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="acco_customerprofile_user_org")]
class CustomerAddress(TimeStamped):
    profile=models.ForeignKey(CustomerProfile,related_name="addresses",on_delete=models.CASCADE); label=models.CharField(max_length=60,default="Home"); recipient_name=models.CharField(max_length=160); phone=models.CharField(max_length=30); county=models.CharField(max_length=100); town=models.CharField(max_length=100); address_line=models.CharField(max_length=255); directions=models.TextField(blank=True); is_default=models.BooleanField(default=False)
    class Meta:
        ordering=["-is_default","-updated_at"]
        base_manager_name = "objects"
        default_manager_name = "objects"



class DeviceSession(models.Model):
    import uuid
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_sessions')
    version = models.PositiveIntegerField(default=1)
    password_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_user_activity_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    failed_unlocks = models.PositiveIntegerField(default=0)
    unlock_blocked_until = models.DateTimeField(null=True, blank=True)
    # The protected pages are open on this device while this matches ``version``: locking or unlocking the
    # workspace changes the version, so they close again with it.
    protected_version = models.PositiveIntegerField(null=True, blank=True)
    # The private pages open on this device (keys of protected_pages.PAGES), while protected_version matches.
    protected_open = models.JSONField(default=list, blank=True)
    protected_failures = models.PositiveIntegerField(default=0)
    protected_blocked_until = models.DateTimeField(null=True, blank=True)


class LockPin(models.Model):
    """A short PIN that opens a lock in a moment. ``page`` blank is the person's lock PIN: it opens the workspace after
    they locked it, and every private page without a PIN of its own. A private page's key (see protected_pages.PAGES)
    is that page's own PIN."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="lock_pins", on_delete=models.CASCADE)
    page = models.CharField(max_length=20, blank=True, default="")
    digest = models.CharField(max_length=128)
    length = models.PositiveSmallIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "page"], name="accounts_lockpin_user_page")]


class RefreshCredential(models.Model):
    session = models.ForeignKey(DeviceSession, related_name='credentials', on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)


class SessionAudit(models.Model):
    session = models.ForeignKey(DeviceSession, null=True, on_delete=models.SET_NULL)
    event = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class AccountProfile(models.Model):
    """Personal details of a person's sign-in, shared by every business they belong to (not business data)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="account_profile", on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)


class ProtectedPagesPassword(models.Model):
    """No longer used: the private pages open with PINs now (see LockPin). Kept so earlier records stay.

    A person's password for the protected pages (M-Pesa, investments), apart from their sign-in password.

    Every password they ever set stays, so none can be used twice; the newest is the one in use, for seven days.
    The digest uses one salt per person, so a new password is checked against all the old ones in a single lookup.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="protected_passwords", on_delete=models.CASCADE)
    salt = models.CharField(max_length=32)
    digest = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["user", "digest"], name="acco_protected_password_once")]
