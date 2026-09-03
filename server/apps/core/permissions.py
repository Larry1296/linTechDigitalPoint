from rest_framework.permissions import BasePermission
class IsInternalStaff(BasePermission):
    message="Staff access required."
    def has_permission(self,request,view): return bool(request.user and request.user.is_authenticated and request.user.is_active and request.user.is_staff)
class HasLinTechPermission(IsInternalStaff):
    permission_required=None
    def has_permission(self,request,view):
        if not super().has_permission(request,view): return False
        required=getattr(view,"permission_required",self.permission_required)
        if request.user.is_superuser:return True
        if isinstance(required,dict): required=required.get(request.method)
        return not required or request.user.has_perm(required)

