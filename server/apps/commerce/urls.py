from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import CustomerOrderViewSet,StaffOrderViewSet,cart,cart_item,checkout,pos_catalog,pos_complete
router=DefaultRouter();router.register("orders",CustomerOrderViewSet,basename="customer-orders");router.register("staff/orders",StaffOrderViewSet,basename="staff-orders")
urlpatterns=[path("cart/",cart),path("cart/items/<int:pk>/",cart_item),path("checkout/",checkout),path("pos/catalog/",pos_catalog),path("pos/complete/",pos_complete),path("",include(router.urls))]

