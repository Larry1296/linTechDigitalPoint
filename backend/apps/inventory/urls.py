from django.urls import path
from .api import dashboard,receive,transfer
urlpatterns=[path("receive/",receive),path("transfer/",transfer),path("dashboard/",dashboard)]

