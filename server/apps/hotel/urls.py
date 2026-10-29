from django.urls import path

from . import api

urlpatterns = [
    path("menu/", api.menu_items), path("menu/<int:pk>/", api.menu_item),
    path("kitchen/ingredients/", api.ingredients), path("kitchen/ingredients/<int:pk>/", api.ingredient),
    path("kitchen/use/", api.kitchen_use),
    path("rooms/", api.room_list), path("rooms/<int:pk>/", api.room_detail),
    path("room-types/", api.room_types), path("room-types/<int:pk>/", api.room_type),
    path("stays/", api.stays), path("stays/in-house/", api.in_house), path("stays/<int:pk>/", api.stay_detail),
    path("stays/<int:pk>/<str:action>/", api.stay_action),
    path("settings/", api.hotel_settings),
]
