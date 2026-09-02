from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import PublicProductViewSet,ShelfViewSet,ZoneViewSet,csrf,me,sign_in,sign_out
router=DefaultRouter(); router.register("store/products",PublicProductViewSet,basename="public-products"); router.register("locations/zones",ZoneViewSet); router.register("locations/shelves",ShelfViewSet)
urlpatterns=[path("auth/csrf/",csrf),path("auth/login/",sign_in),path("auth/logout/",sign_out),path("auth/me/",me),path("",include(router.urls))]

