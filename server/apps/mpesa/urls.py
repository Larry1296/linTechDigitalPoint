from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import CommissionViewSet, OutletViewSet, ReconciliationViewSet, SessionViewSet, TransactionViewSet, customer_lookup, dashboard, monthly_report, report_months

router = DefaultRouter()
router.register("outlets", OutletViewSet)
router.register("sessions", SessionViewSet)
router.register("transactions", TransactionViewSet)
router.register("reconciliation", ReconciliationViewSet)
router.register("commission", CommissionViewSet)

urlpatterns = [path("dashboard/", dashboard), path("customers/lookup/", customer_lookup), path("reports/months/", report_months), path("reports/monthly/", monthly_report), path("", include(router.urls))]
