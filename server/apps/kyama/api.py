"""Kyama API: set up a kyama, see who has paid, record money in and out, excuses, fines and turns.

The kyama's figures are its own; none of these views read or write the shop's books.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasLinTechPermission, IsInternalStaff
from apps.tenancy.permissions import has_business_permission
from . import services
from .models import FREQUENCIES, METHODS, PAYOUT_MODES, ROLES, TURN_CHOICES, Kyama, KyamaAllocation, KyamaDue, KyamaMember, KyamaPayment, KyamaPayout
from .services import ZERO, agreed_next, cycle, fine_owed, held, period_date, period_index, round_of, schedule, sync, with_totals

ROLE_LABELS = dict(ROLES)


def _require(request, permission):
    if not has_business_permission(request.user, permission):
        raise PermissionDenied()


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _late(today):
    return Q(excused_until__isnull=True, deadline__lt=today) | Q(excused_until__lt=today)


def _member_totals(kyama, today):
    """Per member: contributions still unpaid so far, the part of it that is late, and fines still owed."""
    totals = defaultdict(lambda: {"unpaid": ZERO, "late": ZERO, "fines": ZERO, "paid": ZERO})
    for due in with_totals(KyamaDue.objects.filter(kyama=kyama).filter(Q(period_date__lte=today) | Q(fine_amount__gt=0))):
        row = totals[due.member_id]
        short = due.amount - due.paid
        if due.period_date <= today:
            row["unpaid"] += short
            if due.pay_by < today:
                row["late"] += short
        row["fines"] += fine_owed(due)
    for member_id, amount in KyamaPayment.objects.filter(kyama=kyama, reversed_at__isnull=True).values_list("member_id", "amount"):
        totals[member_id]["paid"] += amount
    return totals


def _due_status(due, today):
    if due.paid >= due.amount:
        return "PAID"
    if due.period_date > today:
        return "UPCOMING"
    if due.excused_until and today <= due.excused_until:
        return "EXCUSED"
    if today <= due.deadline:
        return "WAITING"
    return "LATE"


def _due_row(due, today):
    return {"id": due.pk, "member_id": due.member_id, "period_date": due.period_date, "amount": due.amount, "paid": due.paid,
            "deadline": due.deadline, "pay_by": due.pay_by, "status": _due_status(due, today),
            "excused_until": due.excused_until, "excuse_reason": due.excuse_reason,
            "fine_amount": due.fine_amount, "fine_paid": due.fine_paid, "fine_owed": fine_owed(due), "fined_on": due.fined_on,
            "fine_waived": bool(due.fine_waived_at), "fine_waive_reason": due.fine_waive_reason}


def _periods(kyama, today):
    index = period_index(kyama, today)
    current = period_date(kyama, index) if index >= 0 else None
    return current, period_date(kyama, index + 1)


def kyama_summary(kyama, today):
    current, upcoming = _periods(kyama, today)
    active = [m for m in kyama.members.all() if m.left_on is None]
    board = list(with_totals(KyamaDue.objects.filter(kyama=kyama, period_date=current))) if current else []
    next_turn = None
    if kyama.payout_mode == "ROTATION":
        rows = [row for row in schedule(kyama, today, ahead=1) if row["status"] != "GIVEN"]
        next_turn = {"member": rows[0]["member"], "date": rows[0]["date"], "round": rows[0]["round"], "agreed": rows[0]["agreed"]} if rows else None
    return {"id": kyama.pk, "name": kyama.name, "contribution_amount": kyama.contribution_amount, "frequency": kyama.frequency,
            "payout_mode": kyama.payout_mode, "turn_choice": kyama.turn_choice, "members": len(active), "held": held(kyama), "current_period": current, "next_period": upcoming,
            "paid_count": sum(1 for due in board if due.paid >= due.amount), "due_count": len(board),
            "late_count": sum(1 for due in board if _due_status(due, today) == "LATE"),
            "collected": sum((due.paid for due in board), ZERO), "expected": sum((due.amount for due in board), ZERO), "next_turn": next_turn}


def _payment_row(payment):
    return {"id": payment.pk, "member_id": payment.member_id, "member": payment.member.full_name, "amount": payment.amount,
            "paid_on": payment.paid_on, "method": payment.method, "reference": payment.reference, "recorded_by": _name(payment.created_by),
            "reversed_at": payment.reversed_at, "reverse_reason": payment.reverse_reason,
            "allocations": [{"period_date": a.due.period_date, "part": a.part, "amount": a.amount} for a in payment.allocations.all()]}


def _payout_row(payout):
    return {"id": payout.pk, "member_id": payout.member_id, "member": payout.member.full_name, "round": payout.round_number,
            "amount": payout.amount, "paid_on": payout.paid_on, "method": payout.method, "reference": payout.reference, "notes": payout.notes,
            "recorded_by": _name(payout.created_by), "reversed_at": payout.reversed_at, "reverse_reason": payout.reverse_reason}


def kyama_detail(kyama, today):
    kyama.refresh_from_db()  # actions update the kyama row directly; show what was saved
    current, upcoming = _periods(kyama, today)
    members = list(kyama.members.all())
    totals = _member_totals(kyama, today)
    turns = schedule(kyama, today) if kyama.payout_mode == "ROTATION" else []
    next_turns = {}
    for row in turns:
        if row["status"] != "GIVEN":
            next_turns.setdefault(row["member_id"], {"round": row["round"], "date": row["date"]})
    received = defaultdict(lambda: ZERO)
    for member_id, amount in KyamaPayout.objects.filter(kyama=kyama, reversed_at__isnull=True).values_list("member_id", "amount"):
        received[member_id] += amount
    board = {due.member_id: due for due in with_totals(KyamaDue.objects.filter(kyama=kyama, period_date=current))} if current else {}
    payments = KyamaPayment.objects.filter(kyama=kyama).select_related("member", "created_by").prefetch_related("allocations__due")[:300]
    payouts = KyamaPayout.objects.filter(kyama=kyama).select_related("member", "created_by")
    fines = with_totals(KyamaDue.objects.filter(kyama=kyama, fine_amount__gt=0)).order_by("-period_date", "member__turn_position")[:300]
    excuses = with_totals(KyamaDue.objects.filter(kyama=kyama, excused_until__isnull=False)).order_by("-period_date")[:200]
    names = {m.pk: m.full_name for m in members}
    in_money = KyamaPayment.objects.filter(kyama=kyama, reversed_at__isnull=True)
    fines_in = KyamaAllocation.objects.filter(due__kyama=kyama, part="FINE", payment__reversed_at__isnull=True)
    fines_total = sum((a.amount for a in fines_in), ZERO)
    waiting = cycle(kyama)[2] if kyama.payout_mode == "ROTATION" else []
    agreed = agreed_next(kyama, waiting)
    return {
        "id": kyama.pk, "name": kyama.name, "contribution_amount": kyama.contribution_amount, "frequency": kyama.frequency,
        "start_date": kyama.start_date, "grace_days": kyama.grace_days, "fine_amount": kyama.fine_amount, "payout_mode": kyama.payout_mode,
        "periods_per_round": kyama.periods_per_round, "notes": kyama.notes, "today": today, "turn_choice": kyama.turn_choice,
        "next_receiver": {"id": agreed.pk, "full_name": agreed.full_name, "note": kyama.next_receiver_note, "agreed_at": kyama.next_receiver_set_at}
        if agreed else None,
        "still_to_receive": [{"id": m.pk, "full_name": m.full_name} for m in waiting],
        "schedule_locked": kyama.dues.exists(), "turns_locked": kyama.payouts.filter(reversed_at__isnull=True).exists(),
        "current_period": current, "next_period": upcoming,
        "current_round": round_of(kyama, current) if current else None,
        "money": {"held": held(kyama), "paid_in": sum((p.amount for p in in_money), ZERO), "fines_paid": fines_total,
                  "given_out": sum((p.amount for p in payouts if not p.reversed_at), ZERO),
                  "unpaid": sum((t["unpaid"] for t in totals.values()), ZERO), "late": sum((t["late"] for t in totals.values()), ZERO),
                  "fines_owed": sum((t["fines"] for t in totals.values()), ZERO)},
        "members": [{"id": m.pk, "full_name": m.full_name, "id_number": m.id_number, "phone": m.phone, "role": m.role,
                     "role_label": ROLE_LABELS[m.role], "turn_position": m.turn_position, "joined_on": m.joined_on, "left_on": m.left_on,
                     "leave_reason": m.leave_reason, "active": m.left_on is None,
                     "unpaid": totals[m.pk]["unpaid"], "late": totals[m.pk]["late"], "fines_owed": totals[m.pk]["fines"],
                     "paid_in": totals[m.pk]["paid"], "received": received[m.pk], "next_turn": next_turns.get(m.pk),
                     "this_period": _due_row(board[m.pk], today) if m.pk in board else None} for m in members],
        "turns": turns,
        "fines": [{**_due_row(due, today), "member": names.get(due.member_id, "")} for due in fines],
        "excuses": [{**_due_row(due, today), "member": names.get(due.member_id, "")} for due in excuses],
        "payments": [_payment_row(p) for p in payments],
        "payouts": [_payout_row(p) for p in payouts],
    }


# --- Views ------------------------------------------------------------------------------------------------------

class MemberInput(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    id_number = serializers.CharField(max_length=40)
    phone = serializers.CharField(max_length=40)
    role = serializers.ChoiceField(choices=[r for r, _ in ROLES], default="MEMBER")


class KyamaInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    contribution_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    frequency = serializers.ChoiceField(choices=[f for f, _ in FREQUENCIES])
    start_date = serializers.DateField()
    grace_days = serializers.IntegerField(default=0)
    fine_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    payout_mode = serializers.ChoiceField(choices=[m for m, _ in PAYOUT_MODES], default="ROTATION")
    periods_per_round = serializers.IntegerField(default=1)
    turn_choice = serializers.ChoiceField(choices=[c for c, _ in TURN_CHOICES], default="ORDER")
    first_receiver = serializers.IntegerField(required=False, allow_null=True, default=None)  # position in `members`, counting from 0
    notes = serializers.CharField(allow_blank=True, default="")
    members = MemberInput(many=True)


def setup_state(request):
    """Whether this business can add a kyama, and why not."""
    from apps.tenancy.billing import plan_modules
    organization = request.organization
    included = plan_modules(organization)
    return {"enabled": "kyama" in organization.enabled_modules and (included is None or "kyama" in included),
            "plan_allows": included is None or "kyama" in included,
            "can_manage": has_business_permission(request.user, "kyama.add_kyama"),
            "can_turn_on": request.membership.role in {"OWNER", "ADMIN"},
            "kyamas": Kyama.objects.count(),
            "you": {"full_name": request.user.get_full_name(), "phone": getattr(getattr(request.user, "account_profile", None), "phone", "")}}


def create_from_setup(user, data):
    form = KyamaInput(data=data)
    form.is_valid(raise_exception=True)
    return services.create_kyama(user=user, data=form.validated_data)


class KyamaSetupView(APIView):
    """Set up a kyama, also from a business that has not turned kyama management on yet (it is turned on here)."""
    permission_classes = [IsInternalStaff]

    def get(self, request):
        return Response(setup_state(request))

    @transaction.atomic
    def post(self, request):
        from apps.core.models import AuditLog
        from apps.tenancy.billing import state
        from apps.tenancy.models import Organization
        state_now = setup_state(request)
        if not state_now["plan_allows"]:
            return Response({"detail": "Kyama management is part of the Pro plan. Upgrade on the Subscription page to use it."}, status=403)
        if state(request.organization)["ended"]:
            return Response({"detail": "Your subscription has ended, so this is paused. Renew it on the Subscription page to continue."}, status=403)
        if not state_now["enabled"]:
            if not state_now["can_turn_on"]:
                return Response({"detail": "Only the business owner or an administrator can turn on kyama management."}, status=403)
            organization = Organization.objects.select_for_update().get(pk=request.organization.pk)
            organization.enabled_modules = sorted(set(organization.enabled_modules) | {"kyama"})
            organization.save(update_fields=["enabled_modules", "updated_at"])
            AuditLog.objects.create(action="BUSINESS_SETTINGS_CHANGED", object_type="Organization", object_id=str(organization.pk),
                                    user=request.user, after={"enabled_modules": organization.enabled_modules})
        elif not state_now["can_manage"]:
            raise PermissionDenied()
        kyama = create_from_setup(request.user, request.data)
        return Response(kyama_detail(kyama, timezone.localdate()), status=201)


class KyamaListView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.view_kyama"

    def get(self, request):
        today = timezone.localdate()
        return Response({"kyamas": [kyama_summary(sync(kyama, today), today) for kyama in Kyama.objects.all()],
                         "frequencies": FREQUENCIES, "roles": ROLES, "turn_choices": TURN_CHOICES, "methods": METHODS, "payout_modes": PAYOUT_MODES})


class RulesInput(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False)
    contribution_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    frequency = serializers.ChoiceField(choices=[f for f, _ in FREQUENCIES], required=False)
    start_date = serializers.DateField(required=False)
    grace_days = serializers.IntegerField(required=False)
    fine_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    payout_mode = serializers.ChoiceField(choices=[m for m, _ in PAYOUT_MODES], required=False)
    periods_per_round = serializers.IntegerField(required=False)
    turn_choice = serializers.ChoiceField(choices=[c for c, _ in TURN_CHOICES], required=False)
    notes = serializers.CharField(allow_blank=True, required=False)


class KyamaDetailView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "kyama.view_kyama", "PATCH": "kyama.change_kyama"}

    def get(self, request, pk):
        today = timezone.localdate()
        return Response(kyama_detail(sync(get_object_or_404(Kyama, pk=pk), today), today))

    def patch(self, request, pk):
        form = RulesInput(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        kyama = services.update_rules(kyama=get_object_or_404(Kyama, pk=pk), user=request.user, data=form.validated_data)
        return Response(kyama_detail(kyama, timezone.localdate()))


class NewMemberInput(MemberInput):
    joined_on = serializers.DateField(required=False, allow_null=True)


class MembersView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        form = NewMemberInput(data=request.data)
        form.is_valid(raise_exception=True)
        kyama = get_object_or_404(Kyama, pk=pk)
        services.add_member(kyama=kyama, user=request.user, data=form.validated_data)
        return Response(kyama_detail(kyama, timezone.localdate()), status=201)


class MemberView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "kyama.view_kyama", "PATCH": "kyama.change_kyama"}

    def get(self, request, pk, member_pk):
        """One member's statement: every contribution, fine and excuse, the money they paid and what they received."""
        kyama = sync(get_object_or_404(Kyama, pk=pk))
        member = get_object_or_404(KyamaMember, kyama=kyama, pk=member_pk)
        today = timezone.localdate()
        dues = with_totals(KyamaDue.objects.filter(member=member)).order_by("-period_date")
        return Response({"id": member.pk, "full_name": member.full_name, "id_number": member.id_number, "phone": member.phone,
                         "role": member.role, "role_label": ROLE_LABELS[member.role], "joined_on": member.joined_on, "left_on": member.left_on,
                         "dues": [_due_row(due, today) for due in dues],
                         "payments": [_payment_row(p) for p in member.payments.select_related("member", "created_by").prefetch_related("allocations__due")],
                         "payouts": [_payout_row(p) for p in member.payouts.select_related("member", "created_by")]})

    def patch(self, request, pk, member_pk):
        form = MemberInput(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        kyama = get_object_or_404(Kyama, pk=pk)
        services.update_member(member=get_object_or_404(KyamaMember, kyama=kyama, pk=member_pk), user=request.user, data=form.validated_data)
        return Response(kyama_detail(kyama, timezone.localdate()))


class MemberLeaveView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk, member_pk):
        kyama = get_object_or_404(Kyama, pk=pk)
        services.member_leaves(member=get_object_or_404(KyamaMember, kyama=kyama, pk=member_pk), user=request.user,
                               reason=str(request.data.get("reason") or ""))
        return Response(kyama_detail(kyama, timezone.localdate()))


class TurnsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        kyama = get_object_or_404(Kyama, pk=pk)
        services.set_turn_order(kyama=kyama, user=request.user, member_ids=request.data.get("order") or [])
        return Response(kyama_detail(kyama, timezone.localdate()))


class PaymentInput(serializers.Serializer):
    member = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_on = serializers.DateField(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=[m for m, _ in METHODS])
    reference = serializers.CharField(max_length=120, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class PaymentsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.add_kyamapayment"

    def post(self, request, pk):
        form = PaymentInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        kyama = get_object_or_404(Kyama, pk=pk)
        payment = services.record_payment(kyama=kyama, member_id=d["member"], amount=d["amount"], paid_on=d.get("paid_on"), method=d["method"],
                                          reference=d["reference"], key=d["idempotency_key"], user=request.user)
        return Response({"payment": _payment_row(payment), "kyama": kyama_detail(kyama, timezone.localdate())}, status=201)


class PaymentReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        payment = services.reverse_payment(payment=get_object_or_404(KyamaPayment, pk=pk), user=request.user,
                                           reason=str(request.data.get("reason") or ""))
        return Response(kyama_detail(payment.kyama, timezone.localdate()))


class ExcuseInput(serializers.Serializer):
    member = serializers.IntegerField()
    period_date = serializers.DateField()
    pay_by = serializers.DateField()
    reason = serializers.CharField(max_length=1000)


class ExcusesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        form = ExcuseInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        kyama = get_object_or_404(Kyama, pk=pk)
        services.excuse(kyama=kyama, member_id=d["member"], period=d["period_date"], pay_by=d["pay_by"], reason=d["reason"], user=request.user)
        return Response(kyama_detail(kyama, timezone.localdate()), status=201)


class WaiveFineView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        due = services.waive_fine(due=get_object_or_404(KyamaDue, pk=pk), user=request.user, reason=str(request.data.get("reason") or ""))
        return Response(kyama_detail(due.kyama, timezone.localdate()))


class PayoutInput(serializers.Serializer):
    member = serializers.IntegerField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_on = serializers.DateField(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=[m for m, _ in METHODS])
    reference = serializers.CharField(max_length=120, allow_blank=True, default="")
    notes = serializers.CharField(allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class PayoutsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.add_kyamapayout"

    def post(self, request, pk):
        form = PayoutInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        kyama = get_object_or_404(Kyama, pk=pk)
        services.record_payout(kyama=kyama, member_id=d.get("member"), amount=d["amount"], paid_on=d.get("paid_on"), method=d["method"],
                               reference=d["reference"], notes=d["notes"], key=d["idempotency_key"], user=request.user)
        return Response(kyama_detail(kyama, timezone.localdate()), status=201)


class PayoutReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        payout = services.reverse_payout(payout=get_object_or_404(KyamaPayout, pk=pk), user=request.user,
                                         reason=str(request.data.get("reason") or ""))
        return Response(kyama_detail(payout.kyama, timezone.localdate()))


class NextReceiverView(APIView):
    """Who the members agreed receives the next turn. Send no member to clear the agreement."""
    permission_classes = [HasLinTechPermission]
    permission_required = "kyama.change_kyama"

    def post(self, request, pk):
        kyama = get_object_or_404(Kyama, pk=pk)
        member = request.data.get("member")
        try:
            member = int(member) if member not in (None, "") else None
        except (TypeError, ValueError):
            member = -1  # not a member of this kyama
        services.set_next_receiver(kyama=kyama, member_id=member, note=request.data.get("note"), user=request.user)
        return Response(kyama_detail(kyama, timezone.localdate()))
