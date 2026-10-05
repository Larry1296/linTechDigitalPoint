from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .income import delete_service, record_visit, add_group, add_option, edit_option, income_by_service, service_income, service_settings
from .api import CyberJobViewSet, CyberServiceViewSet, MaterialRequirementViewSet, dashboard, public_services

router = DefaultRouter()
router.register("services", CyberServiceViewSet)
router.register("jobs", CyberJobViewSet)
router.register("materials", MaterialRequirementViewSet)

urlpatterns = [path("dashboard/", dashboard), path("income/", income_by_service), path("income/groups/", add_group), path("income/record/", record_visit), path("income/<int:pk>/settings/", service_settings), path("income/<int:pk>/delete/", delete_service), path("income/<int:pk>/", service_income), path("income/<int:pk>/options/", add_option), path("income/options/<int:pk>/", edit_option), path("public/services/", public_services), path("", include(router.urls))]
