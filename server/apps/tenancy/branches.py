"""Shared branch selection policy; suspended assignments never widen access."""
from apps.core.models import Store
from .models import BranchMembership


def authorized_stores(user, membership):
    stores = Store.objects.order_by('created_at', 'pk')
    if not membership or membership.status != 'ACTIVE':
        return stores.none()
    stores = stores.filter(organization_id=membership.organization_id)
    if membership.role in {'OWNER', 'ADMIN', 'MANAGER'}:
        return stores
    assignments = BranchMembership.objects.filter(
        user=user, store__organization_id=membership.organization_id,
    )
    # No assignments preserves existing organization-wide legacy access.
    # Once assigned, suspension must not restore organization-wide access.
    if assignments.exists():
        stores = stores.filter(pk__in=assignments.filter(status='ACTIVE').values('store_id'))
    return stores
