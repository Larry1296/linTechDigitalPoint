from django.urls import include, path

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("tenancy/", include("apps.tenancy.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("commerce/", include("apps.commerce.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("cyber/", include("apps.cyber.urls")),
    path("mpesa/", include("apps.mpesa.urls")),
    path("assistant/", include("apps.assistant.urls")),
    path("business-assistant/", include("apps.assistant.business_urls")),
    path("", include("apps.core.urls")),
]
