from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import CyberJobViewSet, CyberServiceViewSet, MaterialRequirementViewSet, dashboard, public_services

router = DefaultRouter()
router.register("services", CyberServiceViewSet)
router.register("jobs", CyberJobViewSet)
router.register("materials", MaterialRequirementViewSet)

urlpatterns = [path("dashboard/", dashboard), path("public/services/", public_services), path("", include(router.urls))]
