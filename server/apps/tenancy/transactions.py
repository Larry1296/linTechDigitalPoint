"""Consistent first lock for business financial operations.

Call inside transaction.atomic before taking stock, payment or cashbook locks.
This intentionally serializes posting within one business; different businesses
remain independent. Narrower locks can replace it after concurrency profiling.
"""
from .context import organization_id
from .models import Organization


def lock_business():
    return Organization.objects.select_for_update().get(pk=organization_id())
