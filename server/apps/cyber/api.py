from django.db.models import Avg, Count, Sum
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from django.contrib.auth.models import User

from apps.accounts.models import CustomerProfile
from apps.core.permissions import HasLinTechPermission

from .models import CyberJob, CyberJobLine, CyberServiceProfile, ServiceMaterialRequirement
from .services import complete_job, create_job, set_job_status


class CyberServiceSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="variant.product.name", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    selling_price = serializers.DecimalField(source="variant.selling_price", max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = CyberServiceProfile
        fields = ["id", "variant", "name", "variant_name", "selling_price", "billing_unit", "default_turnaround", "requires_job", "active", "publicly_advertised", "online_orderable", "notes"]

    def validate_variant(self, variant):
        if variant.product.product_type != "SERVICE":
            raise serializers.ValidationError("Cyber profiles require a SERVICE product variant.")
        return variant


class MaterialRequirementSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service_variant.product.name", read_only=True)
    material_name = serializers.CharField(source="material_variant.product.name", read_only=True)

    class Meta:
        model = ServiceMaterialRequirement
        fields = "__all__"


class CyberJobLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CyberJobLine
        fields = ["id", "variant", "service_name", "quantity", "billing_unit", "unit_price", "line_total", "service_details"]


class CyberJobSerializer(serializers.ModelSerializer):
    lines = CyberJobLineSerializer(many=True, read_only=True)
    operator_name = serializers.CharField(source="operator.get_full_name", read_only=True)
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = CyberJob
        fields = ["id", "number", "customer", "walk_in_customer_name", "phone", "status", "operator", "operator_name", "notes", "due_at", "subtotal", "discount", "total", "sale", "created_at", "started_at", "completed_at", "lines", "payment_method"]
        read_only_fields = ["number", "operator", "subtotal", "total", "sale", "started_at", "completed_at"]

    def get_payment_method(self, obj):
        payment = obj.sale.payments.first() if obj.sale_id else None
        return payment.method if payment else None


class CyberServiceViewSet(viewsets.ModelViewSet):
    serializer_class = CyberServiceSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "cyber.view_cyberserviceprofile"
    queryset = CyberServiceProfile.objects.select_related("variant__product").order_by("variant__product__name")

    def get_permissions(self):
        action_permission = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(self.action, "view")
        self.permission_required = f"cyber.{action_permission}_cyberserviceprofile"
        return [HasLinTechPermission()]


class MaterialRequirementViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialRequirementSerializer
    permission_classes = [HasLinTechPermission]
    queryset = ServiceMaterialRequirement.objects.select_related("service_variant__product", "material_variant__product")

    def get_permissions(self):
        action_permission = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(self.action, "view")
        self.permission_required = f"cyber.{action_permission}_servicematerialrequirement"
        return [HasLinTechPermission()]


class CyberJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CyberJobSerializer
    permission_classes = [HasLinTechPermission]
    permission_required = "cyber.view_cyberjob"
    queryset = CyberJob.objects.select_related("customer", "operator", "sale").prefetch_related("lines", "sale__payments")

    def create(self, request):
        if not request.user.has_perm("cyber.add_cyberjob"):
            return Response({"detail": "Cyber job creation permission required."}, status=403)
        customer = User.objects.filter(pk=request.data.get("customer")).first() if request.data.get("customer") else None
        job = create_job(user=request.user, lines=request.data.get("lines", []), customer=customer, walk_in_customer_name=request.data.get("walk_in_customer_name", ""), phone=request.data.get("phone", ""), notes=request.data.get("notes", ""), due_at=request.data.get("due_at") or None, discount=request.data.get("discount", 0))
        return Response(self.get_serializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        if not request.user.has_perm("cyber.change_cyberjob"):
            return Response({"detail": "Cyber job update permission required."}, status=403)
        job = set_job_status(job=self.get_object(), status=request.data.get("status"), user=request.user)
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        if not request.user.has_perm("cyber.complete_cyber_job"):
            return Response({"detail": "Cyber checkout permission required."}, status=403)
        sale = complete_job(job=self.get_object(), user=request.user, payment_method=request.data.get("payment_method", "CASH"), payment_reference=request.data.get("payment_reference", ""), idempotency_key=request.data.get("idempotency_key"))
        return Response({"sale_id": sale.id, "receipt_number": sale.number, "total": sale.total, "cogs": sale.cogs, "gross_profit": sale.gross_profit})


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_services(request):
    rows = CyberServiceProfile.objects.filter(active=True, publicly_advertised=True, variant__active=True, variant__product__active=True).select_related("variant__product")
    return Response(CyberServiceSerializer(rows, many=True).data)


@api_view(["GET"])
@permission_classes([HasLinTechPermission])
def dashboard(request):
    if not request.user.has_perm("cyber.view_cyberjob"):
        return Response({"detail": "Cyber access required."}, status=403)
    today = timezone.localdate()
    jobs = CyberJob.objects.filter(created_at__date=today)
    completed = CyberJob.objects.filter(completed_at__date=today, sale__isnull=False)
    totals = completed.aggregate(revenue=Sum("total"), jobs=Count("id"), average=Avg("total"), cogs=Sum("sale__cogs"), profit=Sum("sale__gross_profit"))
    top = CyberJobLine.objects.filter(job__in=completed).values("service_name").annotate(revenue=Sum("line_total"), units=Sum("quantity")).order_by("-revenue").first()
    recent_customers = list(CustomerProfile.objects.select_related("user").filter(user__cyber_jobs__isnull=False).distinct().values("user_id", "user__first_name", "phone")[:5])
    return Response({"today": {key: value or 0 for key, value in totals.items()}, "active_jobs": CyberJob.objects.exclude(status__in=["COMPLETED", "CANCELLED"]).count(), "ready_jobs": CyberJob.objects.filter(status="READY").count(), "queued_today": jobs.count(), "top_service": top, "recent_customers": recent_customers})
