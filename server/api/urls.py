from django.urls import include, path


urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("commerce/", include("apps.commerce.urls")),
    path("cyber/", include("apps.cyber.urls")),
    path("mpesa/", include("apps.mpesa.urls")),
    path("", include("apps.core.urls")),
]
