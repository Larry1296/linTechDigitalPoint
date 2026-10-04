from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

urlpatterns = [
    path("platform-admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

from apps.tenancy.media import private_media
urlpatterns += [path("media/<path:path>", private_media)]
