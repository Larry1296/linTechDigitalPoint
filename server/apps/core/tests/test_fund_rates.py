"""Money market fund rates the app looks up by itself (CIC): what is trusted, when it looks, and what businesses see."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounting import fund_rates
from apps.accounting.models import Investment, InvestmentRate
from apps.market.models import FundRateCheck
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
def D(value):
    return Decimal(str(value))
CIC = "CIC_MMF_KES"
PAGE = "https://ke.cicinsurancegroup.com/investment/"


def report(daily=8.12, effective=8.43, as_of=None, url=PAGE, found=True):
    return {"found": found, "daily_rate": daily, "effective_annual_rate": effective, "as_of": as_of, "source_url": url,
            "quote": "Current Daily Rate – 8.12% Current Effective Annual Rate – 8.43%", "explanation": "Read on CIC's investment page."}


def business(slug):
    owner = User.objects.create_user(f"{slug}-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name=f"{slug} shop", slug=slug, owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return client, org


def open_cic(client, name="CIC MMF", **extra):
    made = client.post("/api/v1/accounting/investments/", {"name": name, **extra}, format="json")
    assert made.status_code == 201, made.content
    return made.json()


def put_in(client, pk, amount, day):
    moved = client.post(f"/api/v1/accounting/investments/{pk}/move/", {"kind": "DEPOSIT", "amount": amount, "source": "CASH",
                        "occurred_on": str(day), "idempotency_key": f"in-{pk}-{day}"}, format="json")
    assert moved.status_code == 201, moved.content
    return moved.json()


class Asked:
    """Stands in for Claude: hands out the given reports in turn and counts the looks."""
    def __init__(self, *reports):
        self.reports, self.calls = list(reports), 0

    def __call__(self, code, today):
        self.calls += 1
        item = self.reports.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# What is trusted

def test_the_official_page_rate_is_used_and_an_undated_rate_counts_from_the_day_it_was_read():
    today = timezone.localdate()
    status, fields, _ = fund_rates.judge(CIC, report(), today)
    assert status == FundRateCheck.APPLIED
    assert (fields["annual_rate"], fields["effective_annual_rate"], fields["as_of"]) == (D("8.120"), D("8.430"), today)


@pytest.mark.parametrize("bad, why", [
    (report(url="https://www.money254.co.ke/post/cic-money-market-fund"), "own website"),
    (report(url="https://cicinsurancegroup.com.evil.example/rates"), "own website"),
    (report(daily=8.12, effective=9.77), "do not agree"),  # the Fixed Income Fund's effective rate misread as the MMF's
    (report(daily=0.81, effective=None), "not a believable"),
    (report(daily=81.2, effective=None), "not a believable"),
    (report(as_of="2020-01-31"), "old rate"),
    (report(found=False), "not found"),
    (report(daily=None, effective=None), "No rate figure"),
])
def test_a_report_that_does_not_hold_up_is_never_used(bad, why):
    status, _, reason = fund_rates.judge(CIC, bad, timezone.localdate())
    assert status == FundRateCheck.FAILED and why in reason


def test_a_date_in_the_future_is_refused():
    tomorrow = timezone.localdate() + timedelta(days=1)
    assert fund_rates.judge(CIC, report(as_of=str(tomorrow)), timezone.localdate())[0] == FundRateCheck.FAILED


def test_only_the_effective_rate_is_turned_back_into_the_daily_rate_by_monthly_compounding():
    status, fields, _ = fund_rates.judge(CIC, report(daily=None, effective=8.43), timezone.localdate())
    assert status == FundRateCheck.APPLIED and abs(fields["annual_rate"] - D("8.12")) < D("0.01")
    # CIC's own pairs agree with monthly compounding (daily 12.29% -> effective 13.00%; 9.36% -> 9.77%).
    assert abs(fund_rates.effective_from_daily(D("12.29")) - D("13.00")) < D("0.02")
    assert abs(fund_rates.effective_from_daily(D("9.36")) - D("9.77")) < D("0.02")


def test_a_big_jump_waits_for_a_second_look_that_agrees():
    now = timezone.now()
    FundRateCheck.objects.create(fund=CIC, status=FundRateCheck.APPLIED, annual_rate=D("8.12"), as_of=timezone.localdate() - timedelta(days=10),
                                 source_url=PAGE, checked_at=now - timedelta(days=10))
    first = fund_rates.judge(CIC, report(daily=12.29, effective=13.00), timezone.localdate(), now)
    assert first[0] == FundRateCheck.UNCONFIRMED and "big change" in first[2]
    FundRateCheck.objects.create(fund=CIC, status=first[0], checked_at=now, **first[1])
    later = now + timedelta(hours=7)
    assert fund_rates.judge(CIC, report(daily=12.30, effective=13.01), timezone.localdate(), later)[0] == FundRateCheck.APPLIED
    # A second look that disagrees is held again.
    assert fund_rates.judge(CIC, report(daily=14.0, effective=None), timezone.localdate(), later)[0] == FundRateCheck.UNCONFIRMED


def test_names_point_to_the_shilling_fund_only():
    assert fund_rates.guess_fund("CIC MMF") == CIC and fund_rates.guess_fund("cic money market fund") == CIC
    assert fund_rates.guess_fund("CIC-MMF 0042") == CIC
    assert fund_rates.guess_fund("CIC Dollar Fund") == "" and fund_rates.guess_fund("Sanlam MMF") == ""
    assert fund_rates.guess_fund("Cicada savings") == ""


# When it looks, and who gets the rate

def test_the_rate_reaches_every_business_that_follows_the_fund_and_is_looked_up_again_after_ten_days():
    first, first_org = business("cic-one")
    second, second_org = business("cic-two")
    other, other_org = business("sanlam")
    a, b = open_cic(first)["id"], open_cic(second, name="CIC Money Market")["id"]
    sanlam = open_cic(other, name="Sanlam MMF")["id"]
    asked = Asked(report())
    now = timezone.now()
    check = fund_rates.refresh(CIC, now=now, ask=asked)
    assert asked.calls == 1 and check.status == FundRateCheck.APPLIED
    for org, pk in ((first_org, a), (second_org, b)):
        with organization_context(org):
            month = InvestmentRate.objects.get(investment_id=pk)
            assert (month.annual_rate, month.automatic, month.created_by_id) == (D("8.120"), True, None)
            assert "CIC's published rate" in month.note
    with organization_context(other_org):
        assert not InvestmentRate.objects.filter(investment_id=sanlam).exists()
    # Within ten days nobody is asked again, however often the scheduler runs.
    assert fund_rates.refresh(CIC, now=now + timedelta(days=9, hours=23), ask=asked) is None and asked.calls == 1
    asked.reports.append(report(daily=8.05, effective=8.36))
    assert fund_rates.refresh(CIC, now=now + timedelta(days=10, minutes=1), ask=asked).annual_rate == D("8.050")
    assert asked.calls == 2


def test_nobody_is_asked_while_no_business_follows_the_fund():
    asked = Asked(report())
    assert fund_rates.refresh(CIC, ask=asked) is None and asked.calls == 0


def test_a_failed_look_keeps_the_last_rate_and_is_tried_again_six_hours_later():
    client, org = business("cic-retry")
    open_cic(client)
    now = timezone.now()
    asked = Asked(fund_rates.RateNotFound("The Claude API could not be reached."), report(url="https://example.com/rates"), report())
    failed = fund_rates.refresh(CIC, now=now, ask=asked)
    assert failed.status == FundRateCheck.FAILED and "could not be reached" in failed.message
    assert fund_rates.refresh(CIC, now=now + timedelta(hours=5), ask=asked) is None and asked.calls == 1
    assert fund_rates.refresh(CIC, now=now + timedelta(hours=6, minutes=1), ask=asked).status == FundRateCheck.FAILED
    assert fund_rates.refresh(CIC, now=now + timedelta(hours=12, minutes=2), ask=asked).status == FundRateCheck.APPLIED
    # What a business is shown never mentions the failures.
    shown = client.get("/api/v1/accounting/investments/").json()["investments"][0]["fund"]
    assert D(shown["annual_rate"]) == D("8.12") and "message" not in shown


def test_a_rate_a_person_typed_in_after_the_funds_date_is_left_alone():
    client, org = business("cic-typed")
    pk = open_cic(client)["id"]
    FundRateCheck.objects.create(fund=CIC, status=FundRateCheck.APPLIED, annual_rate=D("8.12"), as_of=timezone.localdate() - timedelta(days=3),
                                 source_url=PAGE, checked_at=timezone.now() - timedelta(days=3))
    with organization_context(org):
        InvestmentRate.objects.create(investment_id=pk, month=timezone.localdate().replace(day=1), annual_rate=D("8.5"),
                                      recorded_on=timezone.localdate())
    assert fund_rates.apply(fund_rates.latest(CIC)) == 0
    with organization_context(org):
        assert InvestmentRate.objects.get(investment_id=pk).annual_rate == D("8.5")


def test_the_command_reports_what_it_did(capsys):
    client, _ = business("cic-command")
    open_cic(client)
    original = fund_rates.ask_claude
    fund_rates.ask_claude = Asked(report())
    try:
        call_command("refresh_fund_rates")
        call_command("refresh_fund_rates")
    finally:
        fund_rates.ask_claude = original
    out = capsys.readouterr().out
    assert "CIC_MMF_KES: 8.120% a year" in out and "not due (8.120% as of" in out


# What the interest comes to

def test_interest_is_estimated_at_each_published_rate_from_its_own_date():
    client, org = business("cic-estimate")
    today = timezone.localdate()
    start = today - timedelta(days=4)
    pk = open_cic(client)["id"]
    put_in(client, pk, "365000", start)
    FundRateCheck.objects.create(fund=CIC, status=FundRateCheck.APPLIED, annual_rate=D("10"), as_of=start - timedelta(days=30),
                                 source_url=PAGE, checked_at=timezone.now() - timedelta(days=30))
    FundRateCheck.objects.create(fund=CIC, status=FundRateCheck.APPLIED, annual_rate=D("20"), as_of=today - timedelta(days=1),
                                 source_url=PAGE, checked_at=timezone.now() - timedelta(days=1))
    row = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    # Days start+1 .. today-2 at 10% (100 a day), the last two days at 20% (200 a day), unless a month end credited interest.
    estimate = row["estimate"]
    assert estimate["days"] == 4 and D(estimate["gross"]) >= D("600.00") and D(estimate["gross"]) < D("600.10")
    assert D(estimate["rate"]) == D("20")


def test_each_account_shows_what_it_earns_a_day_a_month_and_a_year_after_tax():
    client, org = business("cic-earn")
    pk = open_cic(client)["id"]
    put_in(client, pk, "365000", timezone.localdate())
    FundRateCheck.objects.create(fund=CIC, status=FundRateCheck.APPLIED, annual_rate=D("10"), effective_annual_rate=D("10.471"),
                                 as_of=timezone.localdate(), source_url=PAGE, checked_at=timezone.now())
    listed = client.get("/api/v1/accounting/investments/").json()
    earning = listed["investments"][0]["earning"]
    assert {k: D(v) for k, v in earning["day"].items()} == {"gross": D("100.00"), "tax": D("15.00"), "net": D("85.00")}
    assert D(earning["month"]["net"]) == D("2585.42")
    # A year: each month's after-tax interest earns interest too, so more than 12 months' worth.
    assert D(earning["year"]["net"]) == D("32262.68") and D(earning["year"]["tax"]) + D(earning["year"]["net"]) == D(earning["year"]["gross"])
    assert {k: D(v) for k, v in listed["earning"].items()} == {"day": D("85.00"), "month": D("2585.42"), "year": D("32262.68")}
    row = listed["investments"][0]
    assert row["fund"]["short"] == "CIC" and row["fund"]["fresh"] and row["check_due"] is False
    assert listed["funds"] == [{"code": CIC, "name": "CIC Money Market Fund (KES)"}]


# Choosing where the rate comes from

def test_a_cic_account_follows_cics_rate_unless_the_owner_types_it_in():
    client, org = business("cic-choose")
    followed = open_cic(client)
    assert followed["fund"]["code"] == CIC and followed["rates"] == []
    typed = open_cic(client, name="CIC Wallet", fund="", annual_rate="9.5")
    assert typed["fund"] is None and D(typed["current_rate"]["annual_rate"]) == D("9.5")
    switched = client.post(f"/api/v1/accounting/investments/{typed['id']}/fund/", {"fund": CIC}, format="json")
    assert switched.status_code == 200 and switched.json()["fund"]["code"] == CIC
    back = client.post(f"/api/v1/accounting/investments/{typed['id']}/fund/", {"fund": ""}, format="json")
    assert back.json()["fund"] is None
    assert client.post(f"/api/v1/accounting/investments/{typed['id']}/fund/", {"fund": "MADE_UP"}, format="json").status_code == 400


def test_check_now_starts_a_look_only_when_the_rate_is_missing_or_due(monkeypatch, django_capture_on_commit_callbacks):
    client, org = business("cic-now")
    open_cic(client)
    asked = Asked(report())
    started = []
    # The look runs in a background thread; here it runs straight away, once the request is saved.
    monkeypatch.setattr(fund_rates, "start_refresh", lambda code: started.append(fund_rates.refresh(code, ask=asked)))
    with django_capture_on_commit_callbacks(execute=True):
        first = client.post(f"/api/v1/accounting/investments/funds/{CIC}/check/")
    assert first.status_code == 200 and first.json()["started"] is True and started[0].status == FundRateCheck.APPLIED
    shown = client.get("/api/v1/accounting/investments/").json()["investments"][0]["fund"]
    assert D(shown["annual_rate"]) == D("8.12") and shown["can_check_now"] is False
    with django_capture_on_commit_callbacks(execute=True):
        again = client.post(f"/api/v1/accounting/investments/funds/{CIC}/check/")
    assert again.json()["started"] is False and asked.calls == 1 and len(started) == 1
    outsider, _ = business("cic-outsider")
    assert outsider.post(f"/api/v1/accounting/investments/funds/{CIC}/check/").status_code == 403


def test_a_second_background_look_does_nothing_once_the_first_has_the_rate():
    client, _ = business("cic-twice")
    open_cic(client)
    asked = Asked(report())
    assert fund_rates.refresh(CIC, ask=asked).status == FundRateCheck.APPLIED
    assert fund_rates.refresh(CIC, ask=asked) is None and asked.calls == 1


# Asking Claude

def _message(stop, *blocks):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage=usage)


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def test_claude_is_resumed_after_a_paused_search_and_its_report_is_returned(monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    sent = []
    replies = [_message("pause_turn", SimpleNamespace(type="server_tool_use", name="web_search")),
               _message("tool_use", SimpleNamespace(type="text", text="Found it."),
                        SimpleNamespace(type="tool_use", name="report_rate", input=report()))]

    def stream(**kwargs):
        sent.append(kwargs)
        return FakeStream(replies.pop(0))
    monkeypatch.setattr(fund_rates, "_anthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream))))
    assert fund_rates.ask_claude(CIC, timezone.localdate()) == report()
    assert len(sent) == 2 and sent[1]["messages"][-1]["role"] == "assistant"
    tools = {tool["name"]: tool for tool in sent[0]["tools"]}
    assert tools["web_search"]["allowed_domains"] == ["cicinsurancegroup.com", "cic.co.ke"]
    assert tools["web_fetch"]["allowed_domains"] == ["cicinsurancegroup.com", "cic.co.ke"]
    assert tools["report_rate"]["strict"] is True and sent[0]["tool_choice"] == {"type": "auto"}


def test_claude_declining_or_not_reporting_is_a_failed_look(monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    for reply in (_message("refusal"), _message("end_turn", SimpleNamespace(type="text", text="I could not find it."))):
        monkeypatch.setattr(fund_rates, "_anthropic", lambda reply=reply: SimpleNamespace(
            beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: FakeStream(reply)))))
        with pytest.raises(fund_rates.RateNotFound):
            fund_rates.ask_claude(CIC, timezone.localdate())


def test_without_a_key_nothing_is_asked(monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = ""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(fund_rates.RateNotFound, match="ANTHROPIC_API_KEY"):
        fund_rates.ask_claude(CIC, timezone.localdate())
