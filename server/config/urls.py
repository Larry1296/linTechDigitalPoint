from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser


def health(request):
    """For the deploy and the proxy: the app is up and can reach its database. Says nothing else."""
    from django.db import connection
    from django.http import JsonResponse
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"ok": False}, status=503)
    return JsonResponse({"ok": True})


urlpatterns = [
    path("healthz", health),
    path("platform-admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

from apps.tenancy.media import private_media
urlpatterns += [path("media/<path:path>", private_media)]
