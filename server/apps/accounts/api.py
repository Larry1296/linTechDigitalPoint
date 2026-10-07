from .device_auth import state as device_state

def access_state(request):
    device = getattr(request._request if hasattr(request, '_request') else request, 'device_session', None)
    return device_state(device) if device else None

from django.views.decorators.csrf import csrf_protect
from django.contrib.auth import authenticate,login,logout,password_validation
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from rest_framework import permissions,serializers,status,viewsets
from rest_framework.decorators import api_view,permission_classes,throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from .models import CustomerAddress,CustomerProfile
class LoginThrottle(AnonRateThrottle): scope="auth"
class UnlockThrottle(UserRateThrottle): scope="unlock"
class AddressSerializer(serializers.ModelSerializer):
    class Meta: model=CustomerAddress; exclude=["profile"]
class AddressViewSet(viewsets.ModelViewSet):
    serializer_class=AddressSerializer
    def get_queryset(self): return CustomerAddress.objects.filter(profile__user=self.request.user)
    def perform_create(self,serializer):
        profile,_=CustomerProfile.objects.get_or_create(user=self.request.user); serializer.save(profile=profile)
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def csrf(request):
    from django.middleware.csrf import get_token
    return Response({"csrfToken":get_token(request)})
def identity(user, request=None):
    from apps.tenancy.context import organization_context
    from apps.tenancy.middleware import resolve_membership
    from apps.tenancy.models import Membership
    from apps.tenancy.api import organization_data
    from apps.tenancy.permissions import business_permissions
    membership = resolve_membership(request) if request else None
    organization = membership.organization if membership else None
    memberships = Membership.objects.filter(user=user, status="ACTIVE", organization__active=True).select_related("organization__subscription__plan")
    with organization_context(organization):
        profile = CustomerProfile.objects.filter(user=user).first()
        granted = sorted(business_permissions(user))
    branches = []
    current_branch = None
    if organization:
        from apps.tenancy.branches import authorized_stores
        with organization_context(organization):
            stores = list(authorized_stores(user, membership))
        branches = [{"id": s.id, "name": s.name, "currency": s.currency, "timezone": s.timezone} for s in stores]
        current_id = getattr(getattr(request, "store", None), "pk", None) if request else None
        current_branch = next((branch for branch in branches if branch["id"] == current_id), branches[0] if branches else None)
    account = getattr(user, "account_profile", None)  # people who signed up before phones were collected have none
    return {"id": user.id, "username": user.username, "first_name": user.first_name, "last_name": user.last_name, "email": user.email,
        "phone": account.phone if account else "",
        "authenticated": True, "session": access_state(request) if request else None, "is_staff": bool(membership), "is_superuser": False,
        "platform_admin": user.is_superuser, "roles": [membership.role] if membership else [], "permissions": granted,
        "organization": organization_data(organization) if organization else None,
        "branch": current_branch, "branches": branches,
        "memberships": [{"organization": organization_data(m.organization), "role": m.role} for m in memberships],
        # Businesses the platform switched off: the person is told, instead of being asked to set up a new business.
        "switched_off_businesses": list(Membership.objects.filter(user=user, status="ACTIVE", organization__active=False).values_list("organization__name", flat=True)),
        "customer_profile": {"phone": profile.phone} if profile else None}
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def me(request):
    if request.user.is_authenticated:
        state = access_state(request)
        if state['locked']:
            return Response({'authenticated': True, 'id': request.user.pk, 'username': request.user.username, 'session': state})
        return Response(identity(request.user, request))
    return Response({'authenticated': False, 'is_staff': False, 'is_superuser': False, 'roles': [], 'permissions': []})


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def session_status(request):
    if not request.user.is_authenticated:
        return Response({'authenticated': False})
    return Response({'authenticated': True, 'id': request.user.pk, 'username': request.user.username,
                     'session': access_state(request)})


def login_account(request):
    credential=(request.data.get("credential") or request.data.get("username") or "").strip();username=credential
    if "@" in credential:
        matches=list(User.objects.filter(email__iexact=credential,is_active=True).values_list("username",flat=True)[:2])
        if len(matches)!=1:return Response({"detail":"Invalid credentials."},status=400)
        username=matches[0]
    user=authenticate(request,username=username,password=request.data.get("password"))
    if not user or not user.is_active:return Response({"detail":"Invalid credentials."},status=400)
    from .device_auth import create_device, set_cookie
    from .device_api import payload
    device, raw = create_device(user)
    request.session.pop('organization_id', None)
    request.session.pop('branch_id', None)
    return set_cookie(Response(payload(request, device, True)), raw, device)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
@csrf_protect
def account_login(request): return login_account(request)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@csrf_protect
def sign_out(request): logout(request); return Response(status=204)
@api_view(["PATCH"])
def profile(request):
    user=request.user; user.first_name=request.data.get("first_name",user.first_name); user.email=request.data.get("email",user.email); user.save(update_fields=["first_name","email"]); p,_=CustomerProfile.objects.get_or_create(user=user); p.phone=request.data.get("phone",p.phone); p.save(); return Response(identity(user, request))
@api_view(["POST"])
def change_password(request):
    if not request.user.check_password(request.data.get("current_password","")):return Response({"detail":"Current password is incorrect."},status=400)
    value=request.data.get("new_password","")
    try: password_validation.validate_password(value,request.user)
    except DjangoValidationError as exc:return Response({"new_password":exc.messages},status=400)
    from .models import DeviceSession
    from django.utils import timezone
    request.user.set_password(value); request.user.save()
    DeviceSession.objects.filter(user=request.user,revoked_at=None).update(revoked_at=timezone.now())
    return Response({"detail":"Password changed."})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
@csrf_protect
def password_reset(request):
    from django.conf import settings
    form=PasswordResetForm({"email":request.data.get("email","")})
    if form.is_valid():form.save(request=request,use_https=request.is_secure(),email_template_name="registration/password_reset_email.html", extra_email_context={"platform_name":settings.PLATFORM_NAME,"frontend_url":settings.FRONTEND_URL})
    return Response({"detail":"If the account exists, reset instructions have been sent."})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@csrf_protect
def password_reset_confirm(request):
    try:user=User.objects.get(pk=force_str(urlsafe_base64_decode(request.data["uid"])))
    except Exception:return Response({"detail":"Invalid reset link."},status=400)
    if not default_token_generator.check_token(user,request.data.get("token")):return Response({"detail":"Invalid or expired reset link."},status=400)
    value=request.data.get("password","")
    try:password_validation.validate_password(value,user)
    except DjangoValidationError as exc:return Response({"password":exc.messages},status=400)
    from .models import DeviceSession
    from django.utils import timezone
    user.set_password(value); user.save()
    DeviceSession.objects.filter(user=user,revoked_at=None).update(revoked_at=timezone.now())
    return Response({"detail":"Password reset complete."})
