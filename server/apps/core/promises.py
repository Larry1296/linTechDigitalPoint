"""Customer promises: a customer asked for something the business did not have, and was promised an answer by a time
(say "I'll check for iPhone screen protectors and call you tomorrow"). Each is recorded with their phone, what they
wanted, what they were promised and when they will be answered; the time it was written down is set by itself. It
stays open, and the dashboard reminds in red as its time comes, until it is closed as met or not met, which archives it.
Only notes: nothing here writes stock, money or the books."""
import re
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CustomerPromise
from .permissions import HasLinTechPermission

# A promise is reminded from this long before its time, and stays reminded (as late) until it is closed.
SOON = timedelta(hours=24)
# Archived promises shown on the page: the latest ones, so the page stays quick however many there have been.
DONE_SHOWN = 50


def state(promise, now):
    if promise.status != CustomerPromise.OPEN:
        return "done"
    if promise.due_at <= now:
        return "late"
    return "soon" if promise.due_at <= now + SOON else "later"


class PromiseInput(serializers.ModelSerializer):
    customer_name = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    phone = serializers.CharField(max_length=30, trim_whitespace=True)
    wanted = serializers.CharField(max_length=300, trim_whitespace=True)
    promised = serializers.CharField(max_length=300, trim_whitespace=True)
    outcome = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=True)
    created_by_name = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = CustomerPromise
        fields = ["id", "customer_name", "phone", "wanted", "promised", "due_at", "status", "outcome", "closed_at",
                  "created_at", "created_by_name", "state"]
        read_only_fields = ["closed_at", "created_at"]

    def get_created_by_name(self, promise):
        person = promise.created_by
        return (person.get_full_name() or person.username) if person else ""

    def get_state(self, promise):
        return state(promise, self.context.get("now") or timezone.now())

    def validate_phone(self, value):
        digits = re.sub(r"\D", "", value)
        if not 9 <= len(digits) <= 15 or re.search(r"[^\d\s+()-]", value):
            raise serializers.ValidationError("Type the customer's phone number, such as 0712 345 678.")
        return value

    def validate_due_at(self, value):
        # A new promise is answered later, not earlier: a time already gone is a typing slip. A few minutes are allowed
        # for the time it takes to fill the form in.
        if self.instance is None and value < timezone.now() - timedelta(minutes=10):
            raise serializers.ValidationError("Pick a time still to come for when you will answer them.")
        return value

    def update(self, promise, data):
        status = data.get("status", promise.status)
        if status != promise.status:
            promise.closed_at = None if status == CustomerPromise.OPEN else timezone.now()
        return super().update(promise, data)


def listing():
    now = timezone.now()
    rows = CustomerPromise.objects.select_related("created_by")
    open_ = list(rows.filter(status=CustomerPromise.OPEN).order_by("due_at", "pk"))
    done = list(rows.exclude(status=CustomerPromise.OPEN).order_by("-closed_at", "-pk")[:DONE_SHOWN])
    context = {"now": now}
    return {"open": PromiseInput(open_, many=True, context=context).data,
            "done": PromiseInput(done, many=True, context=context).data,
            "late": sum(1 for p in open_ if state(p, now) == "late"),
            "soon": sum(1 for p in open_ if state(p, now) == "soon"),
            "met": CustomerPromise.objects.filter(status=CustomerPromise.MET).count(),
            "not_met": CustomerPromise.objects.filter(status=CustomerPromise.NOT_MET).count(),
            "soon_hours": int(SOON.total_seconds() // 3600)}


class PromisesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.view_customerpromise", "POST": "core.add_customerpromise"}

    def get(self, request):
        return Response(listing())

    def post(self, request):
        form = PromiseInput(data=request.data)
        form.is_valid(raise_exception=True)
        form.save(created_by=request.user, status=CustomerPromise.OPEN)
        return Response(listing(), status=201)


class PromiseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"PATCH": "core.change_customerpromise", "DELETE": "core.delete_customerpromise"}

    def patch(self, request, pk):
        form = PromiseInput(get_object_or_404(CustomerPromise, pk=pk), data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
        return Response(listing())

    def delete(self, request, pk):
        get_object_or_404(CustomerPromise, pk=pk).delete()
        return Response(listing())


class PromisesDueView(APIView):
    """For the dashboard's reminder: open promises whose time is within a day, or already gone, soonest first."""
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.view_customerpromise"}

    def get(self, request):
        now = timezone.now()
        due = CustomerPromise.objects.select_related("created_by").filter(status=CustomerPromise.OPEN, due_at__lte=now + SOON)
        return Response({"due": PromiseInput(due.order_by("due_at", "pk"), many=True, context={"now": now}).data,
                         "soon_hours": int(SOON.total_seconds() // 3600)})
