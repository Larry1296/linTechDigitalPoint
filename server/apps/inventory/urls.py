from django.urls import path
from .api import available_categories,dashboard,receive,receipt_detail,receipts,transfer,variant_search
urlpatterns=[path("receive/",receive),path("receipts/",receipts),path("receipts/<int:pk>/",receipt_detail),path("variants/search/",variant_search),path("categories/available/",available_categories),path("transfer/",transfer),path("dashboard/",dashboard)]
