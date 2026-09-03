from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import PublicProductViewSet,ShelfLevelViewSet,ShelfStackViewSet,ShelfViewSet,ZoneViewSet,public_home
router=DefaultRouter();router.register("store/products",PublicProductViewSet,basename="public-products");router.register("locations/zones",ZoneViewSet);router.register("locations/stacks",ShelfStackViewSet);router.register("locations/levels",ShelfLevelViewSet);router.register("locations/shelves",ShelfViewSet)
urlpatterns=[path("store/home/",public_home),path("",include(router.urls))]
