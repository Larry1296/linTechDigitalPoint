from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import BrandViewSet,CategoryViewSet,ImageViewSet,ProductViewSet,VariantViewSet
router=DefaultRouter();router.register("categories",CategoryViewSet);router.register("brands",BrandViewSet);router.register("products",ProductViewSet);router.register("variants",VariantViewSet);router.register("images",ImageViewSet)
urlpatterns=[path("",include(router.urls))]

