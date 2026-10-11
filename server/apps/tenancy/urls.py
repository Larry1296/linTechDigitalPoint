from apps.commerce.mpesa_express_api import callback as express_callback
from django.urls import path
from . import api, billing_api
urlpatterns = [
    path("platform/", api.platform_info),
    path("organizations/", api.organizations),
    path("select/", api.select_organization),
    path("branches/", api.branches),
    path("branches/<int:pk>/", api.branch),
    path("select-branch/", api.select_branch),
    path("business-profiles/", api.business_profiles),
    path("create/", api.create_business),
    path("register/", api.register),
    path("staff/", api.staff),
    path("staff/<int:pk>/", api.staff_member),
    path("settings/", api.business_settings),
    path("settings/logo/", api.business_logo),
    path("plans/", billing_api.public_plans),
    path("billing/", billing_api.subscription),
    path("billing/pay/", billing_api.pay),
    path("billing/payments/<int:pk>/", billing_api.payment_status),
    path("billing/mpesa/callback/<str:token>/", billing_api.mpesa_callback),
    # Safaricom posts each business's own M-Pesa prompt results here (commerce/mpesa_express.py); public, like billing's.
    path("mpesa/express/callback/<str:token>/", express_callback),
    path("platform-admin/overview/", billing_api.platform_overview),
    path("platform-admin/businesses/<int:pk>/", billing_api.platform_business),
    path("platform-admin/plans/<int:pk>/", billing_api.platform_plan),
    path("platform-admin/business-kinds/", billing_api.platform_kinds),
    path("platform-admin/business-kinds/<int:pk>/", billing_api.platform_kind),
    path("public/receipts/<str:token>/", api.public_receipt),
    path("public/logos/<str:name>", api.public_logo),
]
