"""Investments page: accounts such as an MMF, money put in and taken out, interest from statements, and corrections."""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from . import fund_rates
from .investment_interest import current_rate, day_by_day, due, earnings, estimate, first_rate, month_label, month_of, rate_now, record_month
from .investments import SOURCES, move, open_investment, record_statement, totals, undo, value
from .models import Investment, InvestmentMovement


def _require(request, permission):
    if not has_business_permission(request.user, permission):
        raise PermissionDenied()


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _rate(rate):
    return {"month": rate.month, "label": month_label(rate.month), "annual_rate": rate.annual_rate, "statement_balance": rate.statement_balance,
            "recorded_on": rate.recorded_on, "recorded_by": _name(rate.created_by) or ("Automatic" if rate.automatic else ""),
            "note": rate.note, "automatic": rate.automatic}


def _earning(investment, guess):
    """What the money earns at today's rate: on the estimated value today when there is one, else the recorded value."""
    rate = rate_now(investment)
    balance = guess["value"] if guess else value(investment)
    if rate is None or balance <= 0:
        return None
    return {**earnings(balance, rate, investment.tax_rate), "estimated_balance": bool(guess)}


def investment_row(investment):
    sums = totals(investment)
    latest = current_rate(investment)
    guess = estimate(investment)
    return {"id": investment.pk, "name": investment.name, "account_number": investment.account_number, "notes": investment.notes,
            "value": value(investment), "put_in": sums["DEPOSIT"], "taken_out": sums["WITHDRAWAL"], "interest": sums["INTEREST"],
            "fees": sums["FEE"], "tax_rate": investment.tax_rate,
            "current_rate": _rate(latest) if latest else None, "check_due": due(investment), "estimate": guess,
            "fund": fund_rates.summary(investment.fund), "earning": _earning(investment, guess), "daily": day_by_day(investment),
            "rates": [_rate(r) for r in investment.rates.select_related("created_by").order_by("-month")[:12]],
            "movements": [{"id": m.pk, "kind": m.kind, "amount": m.amount, "occurred_on": m.occurred_on, "source": m.source,
                           "reference": m.reference, "note": m.note, "statement_balance": m.statement_balance,
                           "recorded_by": _name(m.created_by), "reversed_at": m.reversed_at, "reverse_reason": m.reverse_reason,
                           "purchase": _purchase(m.purchase) if m.purchase_id else None}
                          for m in investment.movements.select_related("created_by", "purchase__receipt", "purchase__supplier")
                          .order_by("-occurred_on", "-pk")]}


def _purchase(purchase):
    return {"id": purchase.pk, "receipt_number": purchase.receipt.receipt_number, "supplier": purchase.supplier.name if purchase.supplier_id else ""}


def _spare_money():
    """What the app expects in the shop's own till, drawer and bank: the money that could be invested."""
    from .money_check import places
    return [{"method": p["method"], "label": p["label"], "expected": p["expected"]} for p in places() if p["method"] != "OTHER"]


def _agency_sessions():
    from apps.mpesa.models import MpesaSession
    from apps.mpesa.services import session_balances
    rows = []
    for session in MpesaSession.objects.filter(status=MpesaSession.OPEN).select_related("outlet"):
        cash, electronic = session_balances(session)
        rows.append({"id": session.pk, "outlet": session.outlet.display_name, "cash": cash, "float": electronic})
    return rows


class InvestmentInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    account_number = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"), required=False, default=Decimal("15"))
    annual_rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=Decimal("0"), max_value=Decimal("100"), required=False, allow_null=True)
    # A fund whose published rate the app follows; left out, it is guessed from the name ("CIC MMF"); "" means typed in.
    fund = serializers.ChoiceField(choices=["", *fund_rates.FUNDS], required=False, allow_null=True, allow_blank=True)


def _sum(rows, period):
    return sum((r["earning"][period]["net"] for r in rows if r["earning"]), Decimal("0"))


class InvestmentsView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_investment"

    def get(self, request):
        rows = [investment_row(i) for i in Investment.objects.prefetch_related("movements")]
        return Response({"investments": rows, "total_value": sum((r["value"] for r in rows), Decimal("0")),
                         # What it is all worth today: the recorded value plus the interest estimated since each statement.
                         "worth_today": sum((r["estimate"]["value"] if r["estimate"] else r["value"] for r in rows), Decimal("0")),
                         "interest_earned": sum((r["interest"] - r["fees"] for r in rows), Decimal("0")),
                         "estimated_interest": sum((r["estimate"]["net"] for r in rows if r["estimate"]), Decimal("0")),
                         "earning": {period: _sum(rows, period) for period in ("day", "month", "year")},
                         "funds": [{"code": code, "name": fund["name"]} for code, fund in fund_rates.FUNDS.items()],
                         "this_month": month_label(timezone.localdate()),
                         "spare_money": _spare_money(), "agency_sessions": _agency_sessions()})

    def post(self, request):
        _require(request, "accounting.add_investment")
        form = InvestmentInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        rate = d.pop("annual_rate", None)
        fund = d.pop("fund", None)
        with transaction.atomic():
            investment = open_investment(user=request.user, **d)
            fund = fund_rates.guess_fund(investment.name) if fund is None else fund
            if fund:
                fund_rates.link(investment=investment, user=request.user, fund=fund)
            if rate is not None and not (fund and fund_rates.latest(fund)):
                first_rate(investment=investment, user=request.user, annual_rate=rate)
        return Response(investment_row(investment), status=201)


class MoveInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["DEPOSIT", "WITHDRAWAL"])
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    source = serializers.ChoiceField(choices=sorted(SOURCES))
    occurred_on = serializers.DateField(required=False, allow_null=True)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    session_id = serializers.IntegerField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=100)


class InvestmentMoveView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_investmentmovement"

    def post(self, request, pk):
        form = MoveInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        investment = get_object_or_404(Investment, pk=pk)
        move(investment=investment, user=request.user, kind=d["kind"], amount=d["amount"], source=d["source"], key=d["idempotency_key"],
             occurred_on=d.get("occurred_on"), reference=d["reference"], note=d["note"], session_id=d.get("session_id"))
        return Response(investment_row(Investment.objects.get(pk=pk)), status=201)


class StatementInput(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    occurred_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class InvestmentStatementView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_investmentmovement"

    def post(self, request, pk):
        form = StatementInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        investment = get_object_or_404(Investment, pk=pk)
        record_statement(investment=investment, user=request.user, balance=d["balance"], key=d["idempotency_key"],
                         occurred_on=d.get("occurred_on"), note=d["note"])
        return Response(investment_row(Investment.objects.get(pk=pk)), status=201)


class InvestmentUndoView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.reverse_cashentry"

    def post(self, request, pk):
        movement = undo(movement=get_object_or_404(InvestmentMovement, pk=pk), user=request.user, reason=str(request.data.get("reason") or ""))
        return Response(investment_row(movement.investment))


class MonthlyInput(serializers.Serializer):
    annual_rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=Decimal("0"), max_value=Decimal("100"))
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class InvestmentMonthlyView(APIView):
    """This month's check: the rate the fund quotes now and, if known, its balance."""
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_investmentmovement"

    def post(self, request, pk):
        form = MonthlyInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        investment = get_object_or_404(Investment, pk=pk)
        record_month(investment=investment, user=request.user, annual_rate=d["annual_rate"], balance=d.get("balance"),
                     key=d["idempotency_key"], note=d["note"])
        return Response(investment_row(Investment.objects.get(pk=pk)), status=201)


class InvestmentReminderView(APIView):
    """Investments whose monthly check is due, for the reminder on the dashboard."""
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_investment"

    def get(self, request):
        today = timezone.localdate()
        return Response({"month": month_label(today), "month_start": month_of(today),
                         "due": [{"id": i.pk, "name": i.name} for i in Investment.objects.all() if due(i, today)]})


class InvestmentFundView(APIView):
    """An account starts or stops following its fund's published rate (e.g. CIC's), which the app keeps up to date."""
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_investmentmovement"

    def post(self, request, pk):
        form = serializers.ChoiceField(choices=["", *fund_rates.FUNDS], allow_blank=True)
        fund = form.run_validation(request.data.get("fund", ""))
        investment = get_object_or_404(Investment, pk=pk)
        fund_rates.link(investment=investment, user=request.user, fund=fund)
        return Response(investment_row(Investment.objects.get(pk=pk)))


class FundRateCheckView(APIView):
    """Starts a look at the fund's rate when it is missing or due and nobody has looked lately. The look runs in the
    background (it takes a couple of minutes) and the page shows the rate when it arrives. Whatever happens, the
    business sees only whether a rate is there; why a look failed is for the platform owner.
    """
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.add_investmentmovement"

    def post(self, request, code):
        if code not in fund_rates.FUNDS:
            return Response({"detail": "Unknown fund."}, status=404)
        if not Investment.objects.filter(fund=code).exists():
            return Response({"detail": "None of your investments follow this fund."}, status=403)
        started = fund_rates.due(code)
        if started:
            transaction.on_commit(lambda: fund_rates.start_refresh(code))
        return Response({"started": started, "fund": fund_rates.summary(code)})
