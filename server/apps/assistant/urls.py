from django.urls import path

from . import admin_views
from .views import chat, public_config

urlpatterns = [
    path("chat/", chat),
    path("config/", public_config),
    path("admin/settings/", admin_views.chat_settings),
    path("admin/articles/<str:audience>/", admin_views.article_list),
    path("admin/articles/<str:audience>/<str:slug>/", admin_views.article_detail),
    path("admin/questions/", admin_views.questions),
]
