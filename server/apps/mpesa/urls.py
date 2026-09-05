from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import CommissionViewSet, OutletViewSet, ReconciliationViewSet, SessionViewSet, TransactionViewSet, dashboard

router = DefaultRouter()
router.register("outlets", OutletViewSet)
router.register("sessions", SessionViewSet)
router.register("transactions", TransactionViewSet)
router.register("reconciliation", ReconciliationViewSet)
router.register("commission", CommissionViewSet)

urlpatterns = [path("dashboard/", dashboard), path("", include(router.urls))]
