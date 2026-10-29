"""Subscriptions: plans, free first month, paid periods, and what a business may use at each stage.

A new business gets its first period free on the plan chosen at registration. After that, each paid period
extends the subscription. When a subscription ends without renewal the business keeps its data and can still
sign in, view records and record counter sales, but everything else (accounting, stock receiving, expenses,
shelves, staff, branches, M-Pesa agency) is paused until it renews. The platform owner's own businesses and
any the platform grants for free are *complimentary*: always on the Pro plan and never expire.
"""
import base64
import json
import re
import urllib.error
import urllib.request
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

TRIAL_DAYS = 30
RUNNING, ENDED = {"TRIAL", "ACTIVE"}, "EXPIRED"
# What still works after a subscription ends: record counter sales and look at products, services, the menu and customers.
ENDED_MODULES = {"pos", "inventory", "services", "menu", "customers"}
ENDED_WRITES = (re.compile(r"^commerce/pos/complete$"), re.compile(r"^commerce/customers$"), re.compile(r"^commerce/sales/\d+/payments$"))
WARN_DAYS = 5


def plan(code):
    from .models import SubscriptionPlan
    return SubscriptionPlan.objects.filter(code=code, active=True).first()


def billing_sector(organization):
    """The kind of business the plans are priced for: the one recorded on the subscription, else the business's kind."""
    subscription = getattr(organization, "subscription", None)
    return (subscription.billing_sector if subscription else "") or organization.sector


def price_for(plan_, organization=None, sector=None):
    """What ``plan_`` costs, most specific first, as (price, source): the business's own price ("business"), the price
    for its kind of business or for ``sector`` ("kind"), or the plan's standard price ("standard")."""
    from .models import PlanPrice
    if organization is not None:
        own = PlanPrice.objects.filter(plan=plan_, organization=organization).first()
        if own:
            return own.price, "business"
        sector = billing_sector(organization)
    if sector:
        kind = PlanPrice.objects.filter(plan=plan_, sector=sector, organization__isnull=True).first()
        if kind:
            return kind.price, "kind"
    return plan_.price, "standard"


def state(organization):
    """The subscription as the business experiences it right now (status, plan, days left, whether it has ended)."""
    subscription = getattr(organization, "subscription", None) if organization else None
    if subscription is None:
        return {"status": "UNCONFIGURED", "ended": True, "plan": None, "plan_name": "", "ends_at": None, "days_left": None,
                "complimentary": False, "stored_status": None}
    now = timezone.now()
    ended = subscription.status not in RUNNING or bool(subscription.ends_at and subscription.ends_at <= now)
    if subscription.complimentary:
        ended = False
    status = subscription.status if not ended or subscription.status not in RUNNING else ENDED
    days_left = None
    if subscription.ends_at and not subscription.complimentary:
        days_left = max(0, (subscription.ends_at - now + timedelta(seconds=86399)).days) if not ended else 0
    plan_ = subscription.plan
    return {"status": "ACTIVE" if subscription.complimentary else status, "stored_status": subscription.status, "ended": ended,
            "plan": plan_.code if plan_ else None, "plan_name": plan_.name if plan_ else "", "ends_at": subscription.ends_at,
            "days_left": days_left, "complimentary": subscription.complimentary,
            "expiring_soon": bool(days_left is not None and not ended and days_left <= WARN_DAYS)}


def plan_modules(organization):
    """The tools the business's plan includes, or None when the plan does not limit them (free platform plan, legacy)."""
    subscription = getattr(organization, "subscription", None)
    if not subscription or subscription.complimentary or not subscription.plan_id:
        return None
    return set(subscription.plan.enabled_modules)


def modules_for(organization):
    """The tools a business may use now: its own choice, within its plan, and only the essentials once ended."""
    modules = set(organization.enabled_modules)
    subscription = getattr(organization, "subscription", None)
    if subscription and subscription.complimentary:
        return modules
    if subscription and subscription.plan_id:
        modules &= set(subscription.plan.enabled_modules)
    if subscription and state(organization)["ended"]:
        modules &= ENDED_MODULES
    return modules


def write_allowed(organization, relative_path):
    """Changes are allowed while running; after the end only counter sales and collecting what customers owe."""
    if not state(organization)["ended"]:
        return True
    path = relative_path.strip("/")
    return getattr(organization, "subscription", None) is not None and any(rule.match(path) for rule in ENDED_WRITES)


def start_trial(organization, plan_code, platform_owner=False):
    from .models import OrganizationSubscription
    now = timezone.now()
    if platform_owner:
        return OrganizationSubscription.objects.create(organization=organization, plan=plan("PRO"), status="ACTIVE",
                                                       complimentary=True, started_at=now)
    return OrganizationSubscription.objects.create(organization=organization, plan=plan(plan_code), status="TRIAL",
                                                   billing_sector=organization.sector, started_at=now, ends_at=now + timedelta(days=TRIAL_DAYS))


def new_period_end(subscription, new_plan, now=None):
    """When a payment for `new_plan` makes the subscription end.

    - During the free month, the paid period starts when the free month ends.
    - Renewing the same plan adds a period to the current end.
    - Changing plan applies straight away; unused paid days are converted at the two plans' prices for this business.
    - After it has ended, the period starts now.
    """
    now = now or timezone.now()
    period = timedelta(days=new_plan.period_days)
    ends_at = subscription.ends_at
    if not ends_at or ends_at <= now or subscription.status not in RUNNING:
        return now + period
    if subscription.status == "TRIAL" or subscription.plan_id == new_plan.pk:
        return ends_at + period
    old = subscription.plan
    remaining = ends_at - now
    business = subscription.organization if subscription.organization_id else None
    old_price = price_for(old, business)[0] if old else 0
    new_price = price_for(new_plan, business)[0]
    if old_price and new_price:
        credit = remaining * float(Decimal(old_price) / Decimal(new_price))
    else:
        credit = remaining
    return now + period + credit


@transaction.atomic
def mark_paid(payment, receipt_number="", amount=None):
    """Record a successful payment once and extend the subscription it paid for."""
    from .models import OrganizationSubscription, SubscriptionPayment
    payment = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == "PAID":
        return payment
    if amount is not None and Decimal(str(amount)) < payment.amount:
        payment.status, payment.status_detail = "FAILED", f"Paid {amount}, expected {payment.amount}."
        payment.save(update_fields=["status", "status_detail"])
        return payment
    subscription = OrganizationSubscription.objects.select_for_update().get(organization_id=payment.organization_id)
    now = timezone.now()
    subscription.ends_at = new_period_end(subscription, payment.plan, now)
    subscription.plan = payment.plan
    subscription.status = "ACTIVE"
    subscription.save(update_fields=["ends_at", "plan", "status", "updated_at"])
    payment.status, payment.status_detail, payment.paid_at = "PAID", "Paid", now
    payment.receipt_number = receipt_number or payment.receipt_number
    payment.period_ends_at = subscription.ends_at
    payment.save(update_fields=["status", "status_detail", "paid_at", "receipt_number", "period_ends_at"])
    return payment


def mark_failed(payment, detail, status="FAILED"):
    from .models import SubscriptionPayment
    SubscriptionPayment.objects.filter(pk=payment.pk, status="PENDING").update(status=status, status_detail=detail[:255])
    payment.refresh_from_db()
    return payment


# --- M-Pesa (Safaricom Daraja STK push) -------------------------------------------------------------------------

class PaymentUnavailable(Exception):
    pass


def normalize_phone(value):
    """0712 345 678, +254712345678 or 254712345678 → 254712345678 (Safaricom's format)."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("Enter a Safaricom number such as 0712 345 678.")
    return digits


def mpesa_mode():
    return getattr(settings, "MPESA_MODE", "off")


def mpesa_configured():
    mode = mpesa_mode()
    if mode == "simulate":
        return settings.DEBUG
    required = ["MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY", "MPESA_CALLBACK_BASE_URL", "MPESA_CALLBACK_TOKEN"]
    return mode in {"sandbox", "production"} and all(getattr(settings, name, "") for name in required)


def _base_url():
    return "https://api.safaricom.co.ke" if mpesa_mode() == "production" else "https://sandbox.safaricom.co.ke"


def _request(path, payload=None, token=None, basic=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        headers["Authorization"] = f"Basic {basic}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(_base_url() + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read() or b"{}")
        except ValueError:
            raise PaymentUnavailable(f"M-Pesa returned an error ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise PaymentUnavailable("Could not reach M-Pesa. Check the internet connection and try again.") from error


def _token():
    credentials = base64.b64encode(f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode()).decode()
    data = _request("/oauth/v1/generate?grant_type=client_credentials", basic=credentials)
    if not data.get("access_token"):
        raise PaymentUnavailable("M-Pesa did not accept the platform's credentials.")
    return data["access_token"]


def _password(timestamp):
    return base64.b64encode(f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode()).decode()


def request_payment(payment):
    """Send the M-Pesa prompt to the payer's phone. Returns the payment, still PENDING until the callback."""
    if not mpesa_configured():
        raise PaymentUnavailable("M-Pesa payments are not set up on this platform yet. Contact the platform team to activate your subscription.")
    if mpesa_mode() == "simulate":
        payment.checkout_request_id = f"SIM-{payment.pk}"
        payment.status_detail = "Simulated prompt sent (development only)."
        payment.save(update_fields=["checkout_request_id", "status_detail"])
        return payment
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": settings.MPESA_SHORTCODE, "Password": _password(timestamp), "Timestamp": timestamp,
        "TransactionType": getattr(settings, "MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
        "Amount": int(payment.amount), "PartyA": payment.phone, "PartyB": getattr(settings, "MPESA_PARTY_B", "") or settings.MPESA_SHORTCODE,
        "PhoneNumber": payment.phone,
        "CallBackURL": f"{settings.MPESA_CALLBACK_BASE_URL.rstrip('/')}/api/v1/tenancy/billing/mpesa/callback/{settings.MPESA_CALLBACK_TOKEN}/",
        "AccountReference": f"SUB{payment.organization_id}"[:12], "TransactionDesc": f"{payment.plan.name} plan"[:13],
    }
    data = _request("/mpesa/stkpush/v1/processrequest", body, token=_token())
    if str(data.get("ResponseCode")) != "0":
        mark_failed(payment, data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa could not send the prompt.")
        raise PaymentUnavailable(payment.status_detail)
    payment.checkout_request_id = data["CheckoutRequestID"]
    payment.merchant_request_id = data.get("MerchantRequestID", "")
    payment.status_detail = data.get("CustomerMessage", "Prompt sent")
    payment.save(update_fields=["checkout_request_id", "merchant_request_id", "status_detail"])
    return payment


RESULT_MESSAGES = {"1032": "The payment was cancelled on the phone.", "1037": "The phone did not respond in time.",
                   "2001": "The M-Pesa PIN was wrong.", "1": "There is not enough money in the M-Pesa account."}


def apply_result(payment, code, description="", metadata=None):
    """Apply an STK result (from the callback or a status query) to a pending payment."""
    code = str(code)
    if code == "0":
        items = {item.get("Name"): item.get("Value") for item in (metadata or {}).get("Item", [])}
        return mark_paid(payment, receipt_number=str(items.get("MpesaReceiptNumber") or ""), amount=items.get("Amount"))
    return mark_failed(payment, RESULT_MESSAGES.get(code, description or "The payment did not go through."),
                       status="CANCELLED" if code == "1032" else "FAILED")


def check_pending(payment):
    """Resolve a payment still pending after the prompt: the simulator completes it; Daraja is asked for the result."""
    if payment.status != "PENDING" or not payment.checkout_request_id:
        return payment
    age = (timezone.now() - payment.created_at).total_seconds()
    if mpesa_mode() == "simulate" and settings.DEBUG:
        return apply_result(payment, "0", metadata={"Item": [{"Name": "MpesaReceiptNumber", "Value": f"SIM{payment.pk:07d}"},
                                                            {"Name": "Amount", "Value": str(payment.amount)}]}) if age >= 4 else payment
    if age < 20 or not mpesa_configured():
        return payment
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    try:
        data = _request("/mpesa/stkpushquery/v1/query", {"BusinessShortCode": settings.MPESA_SHORTCODE, "Password": _password(timestamp),
                                                         "Timestamp": timestamp, "CheckoutRequestID": payment.checkout_request_id}, token=_token())
    except PaymentUnavailable:
        return payment
    if "ResultCode" in data:  # still processing responds with an errorCode instead
        return apply_result(payment, data["ResultCode"], data.get("ResultDesc", ""))
    if age > 180:
        return mark_failed(payment, "No answer from M-Pesa. If money was deducted, contact the platform team with the M-Pesa message.")
    return payment
