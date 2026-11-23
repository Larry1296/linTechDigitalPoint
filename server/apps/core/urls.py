from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .api import PublicProductViewSet,ShelfLevelViewSet,ShelfStackViewSet,ShelfViewSet,ZoneViewSet,public_home,public_search_suggestions
router=DefaultRouter();router.register("store/products",PublicProductViewSet,basename="public-products");router.register("locations/zones",ZoneViewSet);router.register("locations/stacks",ShelfStackViewSet);router.register("locations/levels",ShelfLevelViewSet);router.register("locations/shelves",ShelfViewSet)
from .promises import PromiseView, PromisesDueView, PromisesView
from .to_buy import ToBuyFillView, ToBuyItemView, ToBuyPdfView, ToBuyView
urlpatterns=[path("promises/",PromisesView.as_view()),path("promises/due/",PromisesDueView.as_view()),path("promises/<int:pk>/",PromiseView.as_view()),path("to-buy/",ToBuyView.as_view()),path("to-buy/<int:pk>/",ToBuyItemView.as_view()),path("to-buy/fill/<int:variant_id>/",ToBuyFillView.as_view()),path("to-buy/pdf/",ToBuyPdfView.as_view()),path("store/search-suggestions/",public_search_suggestions),path("store/home/",public_home),path("",include(router.urls))]
