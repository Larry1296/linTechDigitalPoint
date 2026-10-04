"""Money lent: list and record loans, confirm repayments, and correct mistakes."""
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from .loans import cancel_loan, lend, outstanding, repaid, repay, reverse_repayment, status
from .models import Loan, LoanRepayment

METHODS = ["CASH", "MPESA", "BANK", "OTHER"]


def _require(request, permission):
    if not has_business_permission(request.user, permission):
        raise PermissionDenied()


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def loan_row(loan, today=None):
    today = today or timezone.localdate()
    left = outstanding(loan)
    return {"id": loan.pk, "borrower_name": loan.borrower_name, "borrower_phone": loan.borrower_phone, "amount": loan.amount,
            "method": loan.method, "lent_on": loan.lent_on, "due_date": loan.due_date, "notes": loan.notes,
            "repaid": repaid(loan), "outstanding": left, "status": status(loan, today),
            "days_overdue": (today - loan.due_date).days if left > 0 and not loan.cancelled_at and loan.due_date < today else 0,
            "recorded_by": _name(loan.created_by), "cancelled_at": loan.cancelled_at, "cancel_reason": loan.cancel_reason,
            "repayments": [{"id": r.pk, "amount": r.amount, "method": r.method, "reference": r.reference, "received_on": r.received_on,
                            "recorded_by": _name(r.created_by), "reversed_at": r.reversed_at, "reverse_reason": r.reverse_reason}
                           for r in loan.repayments.select_related("created_by").all()]}


class LoanInput(serializers.Serializer):
    borrower_name = serializers.CharField(max_length=120)
    borrower_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=METHODS)
    lent_on = serializers.DateField(required=False, allow_null=True)
    due_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class LoansView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_loan"

    def get(self, request):
        today = timezone.localdate()
        rows = [loan_row(loan, today) for loan in Loan.objects.select_related("created_by").prefetch_related("repayments")[:500]]
        owed = [r for r in rows if r["status"] not in {"REPAID", "CANCELLED"}]
        return Response({"loans": rows, "total_outstanding": sum((r["outstanding"] for r in owed), Decimal("0")),
                         "overdue": sum(1 for r in owed if r["status"] == "OVERDUE")})

    def post(self, request):
        _require(request, "accounting.add_loan")
        form = LoanInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        loan = lend(user=request.user, borrower_name=d["borrower_name"], borrower_phone=d["borrower_phone"], amount=d["amount"],
                    method=d["method"], lent_on=d.get("lent_on"), due_date=d["due_date"], notes=d["notes"], key=d["idempotency_key"])
        return Response(loan_row(loan), status=201)


class RepayInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=METHODS)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class LoanRepayView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_loanrepayment"

    def post(self, request, pk):
        form = RepayInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        loan = get_object_or_404(Loan, pk=pk)
        repay(loan=loan, user=request.user, amount=d["amount"], method=d["method"], reference=d["reference"], key=d["idempotency_key"])
        return Response(loan_row(Loan.objects.get(pk=pk)), status=201)


class LoanCancelView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.reverse_cashentry"

    def post(self, request, pk):
        loan = cancel_loan(loan=get_object_or_404(Loan, pk=pk), user=request.user, reason=str(request.data.get("reason") or ""))
        return Response(loan_row(loan))


class RepaymentReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.reverse_cashentry"

    def post(self, request, pk):
        repayment = reverse_repayment(repayment=get_object_or_404(LoanRepayment, pk=pk), user=request.user,
                                      reason=str(request.data.get("reason") or ""))
        return Response(loan_row(repayment.loan))
