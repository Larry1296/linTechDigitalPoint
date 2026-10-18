"""Money market fund rates the app looks up by itself, so a business invested in the fund never has to type them in.

The funds it can follow are in FUNDS (CIC, KCB, Old Mutual, Cytonn, Etica, NCBA, Britam, Madison: the shilling money
market fund of each). Only a fund some business follows is ever looked up.

Every 10 days (``manage.py refresh_fund_rates``, run by the scheduler service) Claude reads the rate the fund publishes
on its own website and reports it through the ``report_rate`` tool. Nothing it reports is trusted as is, because the
rate decides the interest every business sees:

* the page must be on the fund's own website, and the rate must be the shilling fund's current one;
* the rate must be a sensible yearly figure for a money market fund, and when the fund also gives the effective annual
  rate the two must agree (the daily rate compounded monthly gives the effective rate, as CIC credits monthly);
* a date older than the last rate used, or older than 45 days, is ignored;
* a jump of more than 2 points from the last rate is held until a second look, at least 6 hours later, agrees.

A rate that passes becomes the fund's rate from its date: every business's estimate uses it from that day, and this
month's rate on each linked account is updated. A look that fails changes nothing: the last good rate stays, the next
run tries again 6 hours later, and only the platform owner is told why (businesses never hear about the AI).
"""
import json
import logging
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.tenancy.context import organization_context
from apps.tenancy.transactions import lock_business
from apps.market.models import FundRateCheck
from .models import Investment, InvestmentRate

logger = logging.getLogger(__name__)

FUNDS = {
    "CIC_MMF_KES": {
        "name": "CIC Money Market Fund (KES)",
        "short": "CIC",
        "manager": "CIC Asset Management (CIC Insurance Group, Kenya)",
        "domains": ["cicinsurancegroup.com", "cic.co.ke"],
        "start": "https://ke.cicinsurancegroup.com/investment/",
        "others": "the CIC Dollar Fund, Fixed Income Fund, Wealth Fund, Balanced Fund or Equity Fund",
        "keywords": ["cic"],
    },
    "KCB_MMF_KES": {
        "name": "KCB Money Market Fund (KES)",
        "short": "KCB",
        "manager": "KCB Asset Management (KCB Group, Kenya)",
        "domains": ["kcbgroup.com"],
        "start": "https://ke.kcbgroup.com/",
        "others": "the KCB dollar (USD) fund",
        "keywords": ["kcb"],
    },
    "OLD_MUTUAL_MMF_KES": {
        "name": "Old Mutual Money Market Fund (KES)",
        "short": "Old Mutual",
        "manager": "Old Mutual Investment Group (Kenya)",
        "domains": ["oldmutual.co.ke"],
        "start": "https://www.oldmutual.co.ke/fund-prices/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["old", "mutual"],
    },
    "CYTONN_MMF_KES": {
        "name": "Cytonn Money Market Fund (KES)",
        "short": "Cytonn",
        "manager": "Cytonn Asset Managers (Kenya)",
        "domains": ["cytonn.com"],
        "start": "https://cytonn.com/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["cytonn"],
    },
    "ETICA_MMF_KES": {
        "name": "Etica Money Market Fund (KES)",
        "short": "Etica",
        "manager": "Etica Capital (Kenya)",
        "domains": ["eticacap.com"],
        "start": "https://eticacap.com/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["etica"],
    },
    "NCBA_MMF_KES": {
        "name": "NCBA Money Market Fund (KES)",
        "short": "NCBA",
        "manager": "NCBA Investment Bank (NCBA Group, Kenya)",
        "domains": ["ncbagroup.com"],
        "start": "https://investment-bank.ncbagroup.com/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["ncba"],
    },
    "BRITAM_MMF_KES": {
        "name": "Britam Money Market Fund (KES)",
        "short": "Britam",
        "manager": "Britam Asset Managers (Kenya)",
        "domains": ["britam.com"],
        "start": "https://ke.britam.com/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["britam"],
    },
    "MADISON_MMF_KES": {
        "name": "Madison Money Market Fund (KES)",
        "short": "Madison",
        "manager": "Madison Investment Managers (Kenya)",
        "domains": ["madison.co.ke"],
        "start": "https://www.madison.co.ke/investmentmanagers/madison-money-market-fund/",
        "others": "its dollar (USD) fund or any of its other unit trusts (fixed income, balanced, equity)",
        "keywords": ["madison"],
    },
}
# Words that mean an account is one of the manager's other funds, not its shilling money market fund.
NOT_THE_MMF = {"dollar", "usd", "equity", "fixed", "balanced", "wealth", "global", "bond"}
REFRESH_DAYS = 10  # a good rate is looked up again after this many days
RETRY_HOURS = 6  # a failed or unconfirmed look is tried again after this long
FRESH_DAYS = 2 * REFRESH_DAYS  # a rate this recent counts as current: no monthly check is asked for
STALE_DAYS = 45  # a published rate older than this is not used
LOWEST, HIGHEST = Decimal("3"), Decimal("25")  # % a year: anything outside is a misreading, not a money market rate
JUMP = Decimal("2")  # points of change that need a second look
AGREE = Decimal("0.25")  # how close the second look must be
EFFECTIVE_SLACK = Decimal("0.15")  # rounding allowed between the daily and effective rates
LOCK = 7_301_042  # Postgres advisory lock: one look at a time across every app process
MAX_PAUSES = 4
_client = None


class RateNotFound(Exception):
    """The look did not produce a usable rate; the message is for the platform owner."""


def fund_name(code):
    return FUNDS[code]["name"] if code in FUNDS else ""


def guess_fund(name):
    """The fund an account's name points to, e.g. "CIC MMF" -> CIC_MMF_KES, "KCB MMF" -> KCB_MMF_KES; empty when unsure."""
    words = set(str(name or "").lower().replace("-", " ").split())
    if words & NOT_THE_MMF:
        return ""
    return next((code for code, fund in FUNDS.items() if set(fund["keywords"]) <= words), "")


def latest(code, status=FundRateCheck.APPLIED):
    return FundRateCheck.objects.filter(fund=code, status=status).order_by("-checked_at", "-pk").first()


def history(code):
    """[(from_date, yearly rate)] of every rate used for the fund, oldest first."""
    return [(row.as_of, row.annual_rate) for row in
            FundRateCheck.objects.filter(fund=code, status=FundRateCheck.APPLIED).order_by("as_of", "checked_at", "pk")]


def is_fresh(row, now=None):
    return bool(row) and row.checked_at >= (now or timezone.now()) - timedelta(days=FRESH_DAYS)


def summary(code, now=None):
    """What a business is shown about a fund's automatic rate. No word of how it was looked up or why it failed."""
    if code not in FUNDS:
        return None
    row = latest(code)
    now = now or timezone.now()
    return {"code": code, "name": FUNDS[code]["name"], "short": FUNDS[code]["short"],
            "annual_rate": row.annual_rate if row else None, "effective_annual_rate": row.effective_annual_rate if row else None,
            "as_of": row.as_of if row else None, "checked_on": timezone.localdate(row.checked_at) if row else None,
            "source_url": row.source_url if row else "", "fresh": is_fresh(row, now),
            "next_check_on": timezone.localdate(row.checked_at + timedelta(days=REFRESH_DAYS)) if row else None,
            "can_check_now": due(code, now)}


def due(code, now=None):
    """True when the rate is missing or REFRESH_DAYS old, and nobody has looked in the last RETRY_HOURS.

    A person may also ask for a look then ("Check now"); otherwise the rate is current and looking again only costs.
    """
    now = now or timezone.now()
    good = latest(code)
    if good and good.checked_at > now - timedelta(days=REFRESH_DAYS):
        return False
    last = FundRateCheck.objects.filter(fund=code).order_by("-checked_at").first()
    return not last or last.checked_at <= now - timedelta(hours=RETRY_HOURS)


def linked_anywhere(code):
    from apps.tenancy.models import Organization
    return Organization.objects.filter(investment__fund=code).exists()


def _number(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        return None


def effective_from_daily(rate):
    """The yearly rate compounded monthly, as the fund credits interest at each month end."""
    return ((1 + rate / 1200) ** 12 - 1) * 100


def daily_from_effective(effective):
    """The yearly rate that, compounded monthly, gives the effective annual rate."""
    monthly = Decimal(str((1 + float(effective) / 100) ** (1 / 12) - 1))
    return (monthly * 1200).quantize(Decimal("0.001"))


def judge(code, report, today=None, now=None):
    """The status and figures a report earns: (status, fields, reason). Never trusts the report as is."""
    fund = FUNDS[code]
    today = today or timezone.localdate()
    now = now or timezone.now()
    if not report.get("found"):
        return FundRateCheck.FAILED, {}, f"The rate was not found: {report.get('explanation') or 'no reason given'}"
    url = str(report.get("source_url") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain) for domain in fund["domains"]):
        return FundRateCheck.FAILED, {"source_url": url[:500]}, f"The rate did not come from {fund['short']}'s own website ({host or 'no address'})."
    daily, effective = _number(report.get("daily_rate")), _number(report.get("effective_annual_rate"))
    if daily is None and effective is None:
        return FundRateCheck.FAILED, {"source_url": url}, "No rate figure was given."
    rate = daily if daily is not None else daily_from_effective(effective)
    fields = {"annual_rate": rate, "effective_annual_rate": effective, "source_url": url[:500]}
    if not LOWEST <= rate <= HIGHEST:
        return FundRateCheck.FAILED, fields, f"{rate}% a year is not a believable money market rate."
    if daily is not None and effective is not None and abs(effective_from_daily(daily) - effective) > EFFECTIVE_SLACK:
        return FundRateCheck.FAILED, fields, (f"The daily rate {daily}% and effective rate {effective}% do not agree "
                                              f"(the daily rate gives {effective_from_daily(daily):.2f}%), so one was misread.")
    as_of = parse_date(str(report.get("as_of") or "")) if report.get("as_of") else None
    if as_of and as_of > today:
        return FundRateCheck.FAILED, fields, f"The rate is dated {as_of}, which is in the future."
    if as_of and as_of < today - timedelta(days=STALE_DAYS):
        return FundRateCheck.FAILED, {**fields, "as_of": as_of}, f"Only an old rate (from {as_of}) was found."
    as_of = as_of or today
    fields["as_of"] = as_of
    previous = latest(code)
    if previous and as_of < previous.as_of:
        return FundRateCheck.FAILED, fields, f"The rate found ({as_of}) is older than the one in use ({previous.as_of})."
    if previous and abs(rate - previous.annual_rate) > JUMP:
        waiting = latest(code, FundRateCheck.UNCONFIRMED)
        if waiting and waiting.checked_at > now - timedelta(days=3) and waiting.checked_at > previous.checked_at \
                and abs(waiting.annual_rate - rate) <= AGREE:
            return FundRateCheck.APPLIED, fields, f"Confirmed by a second look: {previous.annual_rate}% to {rate}%."
        return FundRateCheck.UNCONFIRMED, fields, (f"{previous.annual_rate}% to {rate}% is a big change: it is used once "
                                                   f"another look agrees, in about {RETRY_HOURS} hours.")
    return FundRateCheck.APPLIED, fields, report.get("quote") or ""


REPORT_TOOL = {
    "name": "report_rate",
    "description": "Report the fund's current published rate, exactly as read on its official web page. Call it once, "
                   "at the end, with found=false if the rate could not be read on an official page.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean", "description": "True only if the rate was read on the fund manager's own page."},
            "daily_rate": {"anyOf": [{"type": "number"}, {"type": "null"}],
                           "description": "The 'Current Daily Rate' / 'daily yield', in % a year, e.g. 8.12. Null if not shown."},
            "effective_annual_rate": {"anyOf": [{"type": "number"}, {"type": "null"}],
                                      "description": "The 'Current Effective Annual Rate' / 'effective annual yield', in % a year, e.g. 8.43. Null if not shown."},
            "as_of": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                      "description": "The date the page gives for this rate (YYYY-MM-DD). Null if the page shows no date for it."},
            "source_url": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "The page the figures were read on."},
            "quote": {"type": "string", "description": "The words on the page around the figures, copied exactly."},
            "explanation": {"type": "string", "description": "One sentence: where the figures came from, or why they were not found."},
        },
        "required": ["found", "daily_rate", "effective_annual_rate", "as_of", "source_url", "quote", "explanation"],
        "additionalProperties": False,
    },
}


def _instructions(code, today):
    fund = FUNDS[code]
    return (
        f"Today is {today:%d %B %Y}. Find the interest rate the {fund['name']}, managed by {fund['manager']}, publishes now.\n\n"
        f"Start from {fund['start']} and use only the fund manager's own website ({', '.join(fund['domains'])}). Search, then "
        "fetch the page itself to read the figures; search snippets can be out of date. The page usually shows a daily "
        "rate or daily yield ('Current Daily Rate', 'Daily Yield') and an effective annual rate or yield for each fund; they "
        "are after the fund's fees and before withholding tax. Read them for the shilling (KES) money market fund only, not "
        f"{fund['others']}. Do not report averages, highest or lowest yields, or figures from news or comparison sites. "
        "If a fact sheet is newer than the page, the page's current rate still wins; use the fact sheet only if the page "
        "has no rate.\n\n"
        "Report what you read with the report_rate tool, copying the numbers exactly. Never estimate, round or work a "
        "figure out. Give the date printed next to the rate as as_of, or null if there is none. If you cannot read the "
        "rate on an official page, call report_rate with found=false and say why."
    )


def _anthropic():
    global _client
    if _client is None:
        import anthropic
        # A look searches and reads pages on Anthropic's side and takes about two minutes; it never runs in a web request.
        options = {"max_retries": 2, "timeout": anthropic.Timeout(300.0, connect=15.0)}
        if settings.ANTHROPIC_API_KEY:
            options["api_key"] = settings.ANTHROPIC_API_KEY
        _client = anthropic.Anthropic(**options)
    return _client


def configured():
    return bool(settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask_claude(code, today=None):
    """Claude's report of the fund's published rate, as the dict report_rate was called with. Raises RateNotFound."""
    import anthropic
    if not configured():
        raise RateNotFound("No ANTHROPIC_API_KEY is set on the server.")
    fund = FUNDS[code]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5, "allowed_domains": fund["domains"]},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6, "allowed_domains": fund["domains"]},
             REPORT_TOOL]
    messages = [{"role": "user", "content": _instructions(code, today or timezone.localdate())}]
    for _ in range(MAX_PAUSES + 1):
        try:
            with _anthropic().beta.messages.stream(
                model=settings.FUND_RATE_MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                tools=tools,
                tool_choice={"type": "auto"},
                messages=messages,
                # If a safety classifier declines, the API retries on its recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                final = stream.get_final_message()
        except anthropic.RateLimitError:
            raise RateNotFound("The Claude API was busy (rate limited).")
        except anthropic.APIConnectionError:
            raise RateNotFound("The Claude API could not be reached.")
        except anthropic.APIStatusError as exc:
            raise RateNotFound(f"Claude API error {exc.status_code}: {exc.message}")
        logger.info("Fund rate lookup (%s): %s in, %s out, stop %s", code, final.usage.input_tokens, final.usage.output_tokens, final.stop_reason)
        if final.stop_reason == "refusal":
            raise RateNotFound("Claude declined the lookup.")
        for block in final.content:
            if block.type == "tool_use" and block.name == "report_rate":
                return block.input if isinstance(block.input, dict) else json.loads(block.input)
        if final.stop_reason != "pause_turn":
            break
        # A long search paused on Anthropic's side: send the turn back as it is and it carries on.
        messages.append({"role": "assistant", "content": final.content})
    raise RateNotFound("The lookup ended without reporting a rate.")


def _locked():
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK])
        return cursor.fetchone()[0]


def _unlock():
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK])


def refresh(code, *, force=False, now=None, ask=None):
    """Look the fund's rate up if it is due (or forced) and use it if it passes. Returns the new check, or None.

    ``ask`` replaces the call to Claude in tests.
    """
    now = now or timezone.now()
    if code not in FUNDS:
        raise ValueError(f"Unknown fund {code}")
    if not force and (not due(code, now) or not linked_anywhere(code)):
        carry_forward(code)
        return None
    if not _locked():
        return None  # another process is looking right now
    try:
        if not force and not due(code, now):
            return None  # looked up by another process while this one waited
        today = timezone.localdate(now)
        try:
            report = (ask or ask_claude)(code, today)
        except RateNotFound as exc:
            report, reason = None, str(exc)
        if report is None:
            check = FundRateCheck.objects.create(fund=code, status=FundRateCheck.FAILED, message=reason, checked_at=now)
        else:
            status, fields, reason = judge(code, report, today, now)
            check = FundRateCheck.objects.create(fund=code, status=status, message=reason[:2000], checked_at=now, **fields)
    finally:
        _unlock()
    log = logger.info if check.status == FundRateCheck.APPLIED else logger.warning
    log("Fund rate %s: %s %s%% as of %s (%s)", code, check.status, check.annual_rate, check.as_of, check.message)
    if check.status == FundRateCheck.APPLIED:
        apply(check, today=timezone.localdate(now))
    return check


def start_refresh(code):
    """Looks the rate up in the background ("Check now"): a look takes a couple of minutes, longer than a web request may."""
    import threading
    from django.db import close_old_connections

    def run():
        try:
            refresh(code)  # due is checked again: a second click while the first look runs does nothing
        except Exception:  # a background thread has nobody to report to but the log
            logger.exception("Fund rate lookup (%s) failed", code)
        finally:
            close_old_connections()
            connection.close()
    threading.Thread(target=run, name=f"fund-rate-{code}", daemon=True).start()


def carry_forward(code):
    """A new month without a new look yet: the rate in use is written into this month on every linked account."""
    good = latest(code)
    if good:
        apply(good)


def apply(check, today=None):
    """Writes the fund's rate into this month's rate on every account that follows the fund, in every business.

    A rate a person typed in this month after the fund's date is left alone. Returns how many accounts changed.
    """
    from apps.tenancy.models import Organization
    from .investment_interest import month_of
    from .services import audit
    today = today or timezone.localdate()
    month = month_of(today)
    note = f"{FUNDS[check.fund]['short']}'s published rate as of {check.as_of:%d %b %Y}, updated automatically"
    changed = 0
    for organization in Organization.objects.filter(investment__fund=check.fund).distinct():
        with organization_context(organization), transaction.atomic():
            lock_business()
            for investment in Investment.objects.filter(fund=check.fund):
                existing = investment.rates.filter(month=month).first()
                if existing and not existing.automatic and existing.recorded_on >= check.as_of:
                    continue
                if existing and existing.automatic and existing.annual_rate == check.annual_rate and existing.note == note:
                    continue
                if existing:
                    InvestmentRate.objects.filter(pk=existing.pk).update(annual_rate=check.annual_rate, recorded_on=today, note=note,
                                                                         automatic=True, created_by=None)
                else:
                    InvestmentRate.objects.create(investment=investment, month=month, annual_rate=check.annual_rate, recorded_on=today,
                                                  note=note, automatic=True)
                audit(investment, None, f"{investment.name} rate for {today:%B %Y}: {check.annual_rate}% a year ({note})")
                changed += 1
    return changed


def link(*, investment, user, fund):
    """An account starts or stops following a fund's published rate."""
    from rest_framework.exceptions import ValidationError
    from .services import audit
    fund = str(fund or "")
    if fund and fund not in FUNDS:
        raise ValidationError("Choose a fund the app can follow, or enter the rate yourself.")
    if fund == investment.fund:
        return investment
    # Every fund followed here is a shilling money market fund.
    Investment.objects.filter(pk=investment.pk).update(fund=fund, **({"kind": "MMF"} if fund else {}))
    investment.fund = fund
    if fund:
        investment.kind = "MMF"
    audit(investment, user, f"{investment.name} now {'follows the published rate of ' + FUNDS[fund]['name'] if fund else 'has its rate entered by hand'}")
    good = latest(fund) if fund else None
    if good:
        transaction.on_commit(lambda: apply(good))
    return investment
