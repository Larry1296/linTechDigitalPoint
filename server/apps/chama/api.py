"""Chama API: set up a chama, see who has paid, record money in and out, excuses, fines and turns.

The chama's figures are its own; none of these views read or write the shop's books.
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
from .models import FREQUENCIES, METHODS, PAYOUT_MODES, ROLES, TURN_CHOICES, Chama, ChamaAllocation, ChamaDue, ChamaMember, ChamaPayment, ChamaPayout
from .services import ZERO, agreed_next, cycle, fine_owed, held, period_date, period_index, round_of, schedule, sync, with_totals

ROLE_LABELS = dict(ROLES)


def _require(request, permission):
    if not has_business_permission(request.user, permission):
        raise PermissionDenied()


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _late(today):
    return Q(excused_until__isnull=True, deadline__lt=today) | Q(excused_until__lt=today)


def _member_totals(chama, today):
    """Per member: contributions still unpaid so far, the part of it that is late, and fines still owed."""
    totals = defaultdict(lambda: {"unpaid": ZERO, "late": ZERO, "fines": ZERO, "paid": ZERO})
    for due in with_totals(ChamaDue.objects.filter(chama=chama).filter(Q(period_date__lte=today) | Q(fine_amount__gt=0))):
        row = totals[due.member_id]
        short = due.amount - due.paid
        if due.period_date <= today:
            row["unpaid"] += short
            if due.pay_by < today:
                row["late"] += short
        row["fines"] += fine_owed(due)
    for member_id, amount in ChamaPayment.objects.filter(chama=chama, reversed_at__isnull=True).values_list("member_id", "amount"):
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


def _periods(chama, today):
    index = period_index(chama, today)
    current = period_date(chama, index) if index >= 0 else None
    return current, period_date(chama, index + 1)


def chama_summary(chama, today):
    current, upcoming = _periods(chama, today)
    active = [m for m in chama.members.all() if m.left_on is None]
    board = list(with_totals(ChamaDue.objects.filter(chama=chama, period_date=current))) if current else []
    next_turn = None
    if chama.payout_mode == "ROTATION":
        rows = [row for row in schedule(chama, today, ahead=1) if row["status"] != "GIVEN"]
        next_turn = {"member": rows[0]["member"], "date": rows[0]["date"], "round": rows[0]["round"], "agreed": rows[0]["agreed"]} if rows else None
    return {"id": chama.pk, "name": chama.name, "contribution_amount": chama.contribution_amount, "frequency": chama.frequency,
            "payout_mode": chama.payout_mode, "turn_choice": chama.turn_choice, "members": len(active), "held": held(chama), "current_period": current, "next_period": upcoming,
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


def chama_detail(chama, today):
    chama.refresh_from_db()  # actions update the chama row directly; show what was saved
    current, upcoming = _periods(chama, today)
    members = list(chama.members.all())
    totals = _member_totals(chama, today)
    turns = schedule(chama, today) if chama.payout_mode == "ROTATION" else []
    next_turns = {}
    for row in turns:
        if row["status"] != "GIVEN":
            next_turns.setdefault(row["member_id"], {"round": row["round"], "date": row["date"]})
    received = defaultdict(lambda: ZERO)
    for member_id, amount in ChamaPayout.objects.filter(chama=chama, reversed_at__isnull=True).values_list("member_id", "amount"):
        received[member_id] += amount
    board = {due.member_id: due for due in with_totals(ChamaDue.objects.filter(chama=chama, period_date=current))} if current else {}
    payments = ChamaPayment.objects.filter(chama=chama).select_related("member", "created_by").prefetch_related("allocations__due")[:300]
    payouts = ChamaPayout.objects.filter(chama=chama).select_related("member", "created_by")
    fines = with_totals(ChamaDue.objects.filter(chama=chama, fine_amount__gt=0)).order_by("-period_date", "member__turn_position")[:300]
    excuses = with_totals(ChamaDue.objects.filter(chama=chama, excused_until__isnull=False)).order_by("-period_date")[:200]
    names = {m.pk: m.full_name for m in members}
    in_money = ChamaPayment.objects.filter(chama=chama, reversed_at__isnull=True)
    fines_in = ChamaAllocation.objects.filter(due__chama=chama, part="FINE", payment__reversed_at__isnull=True)
    fines_total = sum((a.amount for a in fines_in), ZERO)
    waiting = cycle(chama)[2] if chama.payout_mode == "ROTATION" else []
    agreed = agreed_next(chama, waiting)
    return {
        "id": chama.pk, "name": chama.name, "contribution_amount": chama.contribution_amount, "frequency": chama.frequency,
        "start_date": chama.start_date, "grace_days": chama.grace_days, "fine_amount": chama.fine_amount, "payout_mode": chama.payout_mode,
        "periods_per_round": chama.periods_per_round, "notes": chama.notes, "today": today, "turn_choice": chama.turn_choice,
        "next_receiver": {"id": agreed.pk, "full_name": agreed.full_name, "note": chama.next_receiver_note, "agreed_at": chama.next_receiver_set_at}
        if agreed else None,
        "still_to_receive": [{"id": m.pk, "full_name": m.full_name} for m in waiting],
        "schedule_locked": chama.dues.exists(), "turns_locked": chama.payouts.filter(reversed_at__isnull=True).exists(),
        "current_period": current, "next_period": upcoming,
        "current_round": round_of(chama, current) if current else None,
        "money": {"held": held(chama), "paid_in": sum((p.amount for p in in_money), ZERO), "fines_paid": fines_total,
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


class ChamaInput(serializers.Serializer):
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
    """Whether this business can add a chama, and why not."""
    from apps.tenancy.billing import plan_modules
    organization = request.organization
    included = plan_modules(organization)
    return {"enabled": "chama" in organization.enabled_modules and (included is None or "chama" in included),
            "plan_allows": included is None or "chama" in included,
            "can_manage": has_business_permission(request.user, "chama.add_chama"),
            "can_turn_on": request.membership.role in {"OWNER", "ADMIN"},
            "chamas": Chama.objects.count(),
            "you": {"full_name": request.user.get_full_name(), "phone": getattr(getattr(request.user, "account_profile", None), "phone", "")}}


def create_from_setup(user, data):
    form = ChamaInput(data=data)
    form.is_valid(raise_exception=True)
    return services.create_chama(user=user, data=form.validated_data)


class ChamaSetupView(APIView):
    """Set up a chama, also from a business that has not turned chama management on yet (it is turned on here)."""
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
            return Response({"detail": "Chama management is part of the Pro plan. Upgrade on the Subscription page to use it."}, status=403)
        if state(request.organization)["ended"]:
            return Response({"detail": "Your subscription has ended, so this is paused. Renew it on the Subscription page to continue."}, status=403)
        if not state_now["enabled"]:
            if not state_now["can_turn_on"]:
                return Response({"detail": "Only the business owner or an administrator can turn on chama management."}, status=403)
            organization = Organization.objects.select_for_update().get(pk=request.organization.pk)
            organization.enabled_modules = sorted(set(organization.enabled_modules) | {"chama"})
            organization.save(update_fields=["enabled_modules", "updated_at"])
            AuditLog.objects.create(action="BUSINESS_SETTINGS_CHANGED", object_type="Organization", object_id=str(organization.pk),
                                    user=request.user, after={"enabled_modules": organization.enabled_modules})
        elif not state_now["can_manage"]:
            raise PermissionDenied()
        chama = create_from_setup(request.user, request.data)
        return Response(chama_detail(chama, timezone.localdate()), status=201)


class ChamaListView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.view_chama"

    def get(self, request):
        today = timezone.localdate()
        return Response({"chamas": [chama_summary(sync(chama, today), today) for chama in Chama.objects.all()],
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


class ChamaDetailView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "chama.view_chama", "PATCH": "chama.change_chama"}

    def get(self, request, pk):
        today = timezone.localdate()
        return Response(chama_detail(sync(get_object_or_404(Chama, pk=pk), today), today))

    def patch(self, request, pk):
        form = RulesInput(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        chama = services.update_rules(chama=get_object_or_404(Chama, pk=pk), user=request.user, data=form.validated_data)
        return Response(chama_detail(chama, timezone.localdate()))


class NewMemberInput(MemberInput):
    joined_on = serializers.DateField(required=False, allow_null=True)


class MembersView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        form = NewMemberInput(data=request.data)
        form.is_valid(raise_exception=True)
        chama = get_object_or_404(Chama, pk=pk)
        services.add_member(chama=chama, user=request.user, data=form.validated_data)
        return Response(chama_detail(chama, timezone.localdate()), status=201)


class MemberView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "chama.view_chama", "PATCH": "chama.change_chama"}

    def get(self, request, pk, member_pk):
        """One member's statement: every contribution, fine and excuse, the money they paid and what they received."""
        chama = sync(get_object_or_404(Chama, pk=pk))
        member = get_object_or_404(ChamaMember, chama=chama, pk=member_pk)
        today = timezone.localdate()
        dues = with_totals(ChamaDue.objects.filter(member=member)).order_by("-period_date")
        return Response({"id": member.pk, "full_name": member.full_name, "id_number": member.id_number, "phone": member.phone,
                         "role": member.role, "role_label": ROLE_LABELS[member.role], "joined_on": member.joined_on, "left_on": member.left_on,
                         "dues": [_due_row(due, today) for due in dues],
                         "payments": [_payment_row(p) for p in member.payments.select_related("member", "created_by").prefetch_related("allocations__due")],
                         "payouts": [_payout_row(p) for p in member.payouts.select_related("member", "created_by")]})

    def patch(self, request, pk, member_pk):
        form = MemberInput(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        chama = get_object_or_404(Chama, pk=pk)
        services.update_member(member=get_object_or_404(ChamaMember, chama=chama, pk=member_pk), user=request.user, data=form.validated_data)
        return Response(chama_detail(chama, timezone.localdate()))


class MemberLeaveView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk, member_pk):
        chama = get_object_or_404(Chama, pk=pk)
        services.member_leaves(member=get_object_or_404(ChamaMember, chama=chama, pk=member_pk), user=request.user,
                               reason=str(request.data.get("reason") or ""))
        return Response(chama_detail(chama, timezone.localdate()))


class TurnsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        chama = get_object_or_404(Chama, pk=pk)
        services.set_turn_order(chama=chama, user=request.user, member_ids=request.data.get("order") or [])
        return Response(chama_detail(chama, timezone.localdate()))


class PaymentInput(serializers.Serializer):
    member = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_on = serializers.DateField(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=[m for m, _ in METHODS])
    reference = serializers.CharField(max_length=120, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class PaymentsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.add_chamapayment"

    def post(self, request, pk):
        form = PaymentInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        chama = get_object_or_404(Chama, pk=pk)
        payment = services.record_payment(chama=chama, member_id=d["member"], amount=d["amount"], paid_on=d.get("paid_on"), method=d["method"],
                                          reference=d["reference"], key=d["idempotency_key"], user=request.user)
        return Response({"payment": _payment_row(payment), "chama": chama_detail(chama, timezone.localdate())}, status=201)


class PaymentReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        payment = services.reverse_payment(payment=get_object_or_404(ChamaPayment, pk=pk), user=request.user,
                                           reason=str(request.data.get("reason") or ""))
        return Response(chama_detail(payment.chama, timezone.localdate()))


class ExcuseInput(serializers.Serializer):
    member = serializers.IntegerField()
    period_date = serializers.DateField()
    pay_by = serializers.DateField()
    reason = serializers.CharField(max_length=1000)


class ExcusesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        form = ExcuseInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        chama = get_object_or_404(Chama, pk=pk)
        services.excuse(chama=chama, member_id=d["member"], period=d["period_date"], pay_by=d["pay_by"], reason=d["reason"], user=request.user)
        return Response(chama_detail(chama, timezone.localdate()), status=201)


class WaiveFineView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        due = services.waive_fine(due=get_object_or_404(ChamaDue, pk=pk), user=request.user, reason=str(request.data.get("reason") or ""))
        return Response(chama_detail(due.chama, timezone.localdate()))


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
    permission_required = "chama.add_chamapayout"

    def post(self, request, pk):
        form = PayoutInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        chama = get_object_or_404(Chama, pk=pk)
        services.record_payout(chama=chama, member_id=d.get("member"), amount=d["amount"], paid_on=d.get("paid_on"), method=d["method"],
                               reference=d["reference"], notes=d["notes"], key=d["idempotency_key"], user=request.user)
        return Response(chama_detail(chama, timezone.localdate()), status=201)


class PayoutReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        payout = services.reverse_payout(payout=get_object_or_404(ChamaPayout, pk=pk), user=request.user,
                                         reason=str(request.data.get("reason") or ""))
        return Response(chama_detail(payout.chama, timezone.localdate()))


class NextReceiverView(APIView):
    """Who the members agreed receives the next turn. Send no member to clear the agreement."""
    permission_classes = [HasLinTechPermission]
    permission_required = "chama.change_chama"

    def post(self, request, pk):
        chama = get_object_or_404(Chama, pk=pk)
        member = request.data.get("member")
        try:
            member = int(member) if member not in (None, "") else None
        except (TypeError, ValueError):
            member = -1  # not a member of this chama
        services.set_next_receiver(chama=chama, member_id=member, note=request.data.get("note"), user=request.user)
        return Response(chama_detail(chama, timezone.localdate()))
