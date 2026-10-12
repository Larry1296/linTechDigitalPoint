from .device_api import refresh, logout, unlock, activity, lock
from .protected_pages import protected_lock, protected_set, protected_status, protected_unlock
from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import account_login,change_password,csrf,me,password_reset,password_reset_confirm,profile,session_status
urlpatterns=[path("csrf/",csrf),path("login/",account_login),path("logout/",logout),path("me/",me),path("refresh/",refresh),path("session/",session_status),path("unlock/",unlock),path("activity/",activity),path("lock/",lock),path("profile/",profile),path("password/change/",change_password),path("password/reset/",password_reset),path("password/reset/confirm/",password_reset_confirm),
           path("protected/",protected_status),path("protected/unlock/",protected_unlock),path("protected/password/",protected_set),path("protected/lock/",protected_lock)]
