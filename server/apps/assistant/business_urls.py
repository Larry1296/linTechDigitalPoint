from django.urls import path

from .business_views import assistant_settings, chat

urlpatterns = [path("chat/", chat), path("settings/", assistant_settings)]
