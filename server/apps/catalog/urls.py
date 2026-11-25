from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import BarcodeLabelsView,BarcodeLinkView,BrandViewSet,CategoryViewSet,ImageViewSet,ProductViewSet,VariantViewSet
router=DefaultRouter();router.register("categories",CategoryViewSet);router.register("brands",BrandViewSet);router.register("products",ProductViewSet);router.register("variants",VariantViewSet);router.register("images",ImageViewSet)
urlpatterns=[path("barcodes/labels/",BarcodeLabelsView.as_view()),path("barcodes/link/<int:pk>/",BarcodeLinkView.as_view()),path("",include(router.urls))]

