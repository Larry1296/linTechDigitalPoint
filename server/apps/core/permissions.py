from rest_framework.permissions import BasePermission
from apps.tenancy.permissions import membership_for, has_business_permission

class IsInternalStaff(BasePermission):
    message = "Active business membership required."
    def has_permission(self, request, view):
        return membership_for(request.user) is not None

class HasBusinessPermission(IsInternalStaff):
    permission_required = None
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        required = getattr(view, "permission_required", self.permission_required)
        if isinstance(required, dict):
            required = required.get(request.method)
        return not required or has_business_permission(request.user, required)

# Compatibility alias for existing domain APIs.
HasLinTechPermission = HasBusinessPermission
