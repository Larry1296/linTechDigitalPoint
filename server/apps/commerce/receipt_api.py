"""Staff actions on a sale's customer receipt: view, share a private link, email it."""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.models import ReceiptLink
from .models import Sale
from .receipts import ensure_link, link_url, receipt_data, send_receipt_email


def load_sale(pk):
    return get_object_or_404(Sale.objects.select_related("branch", "customer", "created_by"), pk=pk)


class ReceiptView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "commerce.view_sale"

    def get(self, request, pk):
        sale = load_sale(pk)
        link = ReceiptLink.objects.filter(organization=request.organization, sale_id=sale.pk, revoked_at__isnull=True).first()
        return Response({"sale_id": sale.pk, "receipt": receipt_data(sale, request.organization, request),
                         "link": link_url(link, request) if link else None})


class ReceiptLinkView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "commerce.view_sale"

    def post(self, request, pk):
        sale = load_sale(pk)
        link = ensure_link(sale, request.organization, request.user)
        return Response({"link": link_url(link, request)}, status=201)

    def delete(self, request, pk):
        sale = load_sale(pk)
        updated = ReceiptLink.objects.filter(organization=request.organization, sale_id=sale.pk,
                                             revoked_at__isnull=True).update(revoked_at=timezone.now())
        if updated:
            AuditLog.objects.create(action="RECEIPT_LINK_REVOKED", object_type="Sale", object_id=str(sale.pk), user=request.user)
        return Response(status=204)


class ReceiptEmailThrottle(UserRateThrottle):
    scope = "receipt_email"
    rate = "30/hour"


class ReceiptEmailView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "commerce.view_sale"
    throttle_classes = [ReceiptEmailThrottle]

    def post(self, request, pk):
        email = serializers.EmailField().run_validation(request.data.get("email"))
        sale = load_sale(pk)
        link = ensure_link(sale, request.organization, request.user)
        url = link_url(link, request)
        try:
            send_receipt_email(receipt_data(sale, request.organization, request), email, url)
        except Exception:  # noqa: BLE001 - mail servers fail in many ways; staff need a clear message.
            return Response({"detail": "The email could not be sent. Check the business email settings, or share the receipt on WhatsApp instead."}, status=502)
        AuditLog.objects.create(action="RECEIPT_EMAILED", object_type="Sale", object_id=str(sale.pk), user=request.user,
                                after={"to": email})
        return Response({"sent_to": email, "link": url})
