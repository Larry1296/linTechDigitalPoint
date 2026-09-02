from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import AddressViewSet,change_password,csrf,customer_login,me,password_reset,password_reset_confirm,profile,register,sign_out,staff_login
router=DefaultRouter(); router.register("addresses",AddressViewSet,basename="address")
urlpatterns=[path("csrf/",csrf),path("login/",customer_login),path("staff/login/",staff_login),path("register/",register),path("logout/",sign_out),path("me/",me),path("profile/",profile),path("password/change/",change_password),path("password/reset/",password_reset),path("password/reset/confirm/",password_reset_confirm),path("",include(router.urls))]

