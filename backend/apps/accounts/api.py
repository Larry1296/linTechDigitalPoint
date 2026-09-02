from django.contrib.auth import authenticate,login,logout,password_validation
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group,User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from rest_framework import permissions,serializers,status,viewsets
from rest_framework.decorators import api_view,permission_classes,throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from apps.commerce.services import adopt_cart,get_cart
from apps.core.setup import ensure_initial_setup
from .models import CustomerAddress,CustomerProfile
class LoginThrottle(AnonRateThrottle): scope="auth"
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
def identity(user):
    profile=getattr(user,"customer_profile",None)
    return {"id":user.id,"username":user.username,"first_name":user.first_name,"email":user.email,"authenticated":True,"is_staff":user.is_staff,"is_superuser":user.is_superuser,"roles":list(user.groups.values_list("name",flat=True)),"permissions":sorted(user.get_all_permissions()),"customer_profile":{"phone":profile.phone} if profile else None}
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def me(request): return Response(identity(request.user) if request.user.is_authenticated else {"authenticated":False,"is_staff":False,"is_superuser":False,"roles":[],"permissions":[]})
def do_login(request,staff=False):
    anonymous_cart=get_cart(request)
    user=authenticate(request,username=request.data.get("username"),password=request.data.get("password"))
    if not user or not user.is_active:return Response({"detail":"Invalid credentials."},status=400)
    if staff and not user.is_staff:return Response({"detail":"Staff access required."},status=403)
    if not staff and user.is_staff:return Response({"detail":"Use staff login for an internal account."},status=403)
    login(request,user); adopt_cart(anonymous_cart,user); return Response(identity(user))
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def customer_login(request): return do_login(request)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def staff_login(request): return do_login(request,staff=True)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def register(request):
    anonymous_cart=get_cart(request); serializer=RegistrationSerializer(data=request.data); serializer.is_valid(raise_exception=True); user=serializer.save(); login(request,user); adopt_cart(anonymous_cart,user); return Response(identity(user),status=201)
class RegistrationSerializer(serializers.Serializer):
    username=serializers.CharField(max_length=150); email=serializers.EmailField(); first_name=serializers.CharField(max_length=150); phone=serializers.CharField(max_length=30,required=False,allow_blank=True); password=serializers.CharField(write_only=True)
    def validate_username(self,value):
        if User.objects.filter(username__iexact=value).exists():raise serializers.ValidationError("Username already exists.")
        return value
    def validate_password(self,value):
        try: password_validation.validate_password(value)
        except DjangoValidationError as exc: raise serializers.ValidationError(exc.messages) from exc
        return value
    def create(self,data):
        phone=data.pop("phone",""); ensure_initial_setup(); user=User.objects.create_user(**data,is_staff=False); CustomerProfile.objects.create(user=user,phone=phone); user.groups.add(Group.objects.get(name="Ecommerce Customer")); return user
@api_view(["POST"])
def sign_out(request): logout(request); return Response(status=204)
@api_view(["PATCH"])
def profile(request):
    user=request.user; user.first_name=request.data.get("first_name",user.first_name); user.email=request.data.get("email",user.email); user.save(update_fields=["first_name","email"]); p,_=CustomerProfile.objects.get_or_create(user=user); p.phone=request.data.get("phone",p.phone); p.save(); return Response(identity(user))
@api_view(["POST"])
def change_password(request):
    if not request.user.check_password(request.data.get("current_password","")):return Response({"detail":"Current password is incorrect."},status=400)
    value=request.data.get("new_password","")
    try: password_validation.validate_password(value,request.user)
    except DjangoValidationError as exc:return Response({"new_password":exc.messages},status=400)
    request.user.set_password(value); request.user.save(); login(request,request.user); return Response({"detail":"Password changed."})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def password_reset(request):
    form=PasswordResetForm({"email":request.data.get("email","")})
    if form.is_valid():form.save(request=request,use_https=request.is_secure(),email_template_name="registration/password_reset_email.html")
    return Response({"detail":"If the account exists, reset instructions have been sent."})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_confirm(request):
    try:user=User.objects.get(pk=force_str(urlsafe_base64_decode(request.data["uid"])))
    except Exception:return Response({"detail":"Invalid reset link."},status=400)
    if not default_token_generator.check_token(user,request.data.get("token")):return Response({"detail":"Invalid or expired reset link."},status=400)
    value=request.data.get("password","")
    try:password_validation.validate_password(value,user)
    except DjangoValidationError as exc:return Response({"password":exc.messages},status=400)
    user.set_password(value); user.save(); return Response({"detail":"Password reset complete."})
