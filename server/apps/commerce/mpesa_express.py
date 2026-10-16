"""M-Pesa Express (STK push) for each business's own till or paybill: the till sends the customer a prompt on their
phone, they enter their PIN, and the money goes straight to the business. The sale's waiting M-Pesa payment is then
confirmed with the M-Pesa receipt number, exactly as if someone had typed the code in (settlements.confirm_payment).

What a business provides, once (``REQUIREMENTS``): which of till or paybill it has, its numbers, and the consumer key,
consumer secret and passkey of its own Daraja app. Everything else is done here: the callback address is the
platform's, with a secret per business in it; the credentials are checked with Safaricom as soon as they are saved;
and a prompt whose callback never comes is asked about directly, so a payment never stays pending for good.

A business without a till or paybill (kind NONE) records M-Pesa by hand, with the code from the customer's SMS.
"""
import base64
import json
import logging
import secrets as token_source
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.tenancy.billing import normalize_phone
from apps.tenancy.models import MpesaExpressSetup

from .models import Payment, StkPush
from .secrets import seal, unseal

logger = logging.getLogger(__name__)

# What the setup page lists, so a business knows exactly what to gather before it starts.
REQUIREMENTS = [
    {"id": "number", "label": "Your till or paybill number",
     "help": "Till (Buy Goods): the till number customers pay to, and the store number (head office number) on your till "
             "registration letter. Paybill: the paybill number."},
    {"id": "daraja", "label": "A Safaricom Daraja account, with your till or paybill taken live",
     "help": "Sign up free at developer.safaricom.co.ke, create an app with the M-Pesa Express (Lipa na M-Pesa Online) API, "
             "then use Go Live with your till or paybill. Safaricom confirms it to the till's administrator phone."},
    {"id": "keys", "label": "The app's Consumer Key and Consumer Secret",
     "help": "Shown under My Apps on Daraja once the app is live."},
    {"id": "passkey", "label": "The Lipa na M-Pesa Online passkey",
     "help": "Safaricom emails it to the business's administrator after Go Live (for testing, Daraja shows the sandbox passkey)."},
]
RESULT_MESSAGES = {"1032": "The customer cancelled the prompt on the phone.", "1037": "The customer's phone did not respond in time (off, or no network).",
                   "2001": "The customer entered a wrong M-Pesa PIN.", "1": "The customer does not have enough money in M-Pesa.",
                   "1019": "The prompt expired before the customer answered.", "1025": "M-Pesa could not send the prompt. Try again."}
QUERY_AFTER = 20  # seconds before asking Safaricom about a prompt whose callback has not come
GIVE_UP_AFTER = 180


class PromptUnavailable(Exception):
    pass


def simulated():
    """Development only: prompts are answered by the app itself after a few seconds, never sent to Safaricom."""
    return getattr(settings, "MPESA_MODE", "off") == "simulate" and settings.DEBUG


def setup_for(organization):
    setup = MpesaExpressSetup.objects.filter(organization=organization).first()
    return setup or MpesaExpressSetup.objects.create(organization=organization, callback_token=token_source.token_urlsafe(32))


def callback_url(setup):
    base = getattr(settings, "MPESA_CALLBACK_BASE_URL", "").rstrip("/")
    return f"{base}/api/v1/tenancy/mpesa/express/callback/{setup.callback_token}/" if base else ""


def till_url(setup, which):
    """The till's payment-notification address (which: "confirm" or "accept"). Safaricom refuses callback addresses with
    words such as M-Pesa, Safaricom, exe, sql or query in them: this one is neutral and its secret is hex."""
    base = getattr(settings, "MPESA_CALLBACK_BASE_URL", "").rstrip("/")
    if not base:
        return ""
    if not setup.till_token:
        setup.till_token = token_source.token_hex(24)
        setup.save(update_fields=["till_token", "updated_at"])
    return f"{base}/api/v1/tenancy/payments/till/{setup.till_token}/{which}/"


def register_till(setup):
    """Asks Safaricom to tell the business each time a customer pays its till or paybill (C2B URL registration). For a
    till it is registered with the store number, the same short code prompts use. Live, Safaricom registers an address
    only once, which is why the address never changes."""
    if setup.kind == MpesaExpressSetup.NONE or not setup.verified_at:
        return setup
    if simulated():
        setup.till_registered_at, setup.till_detail = timezone.now(), "Simulated till payments (development only)."
    elif not till_url(setup, "confirm"):
        setup.till_detail = "The platform's public address is not set (MPESA_CALLBACK_BASE_URL), so Safaricom cannot tell it about till payments."
    else:
        try:
            data = _request(setup, "/mpesa/c2b/v2/registerurl", {"ShortCode": setup.shortcode, "ResponseType": "Completed",
                                                                  "ConfirmationURL": till_url(setup, "confirm"),
                                                                  "ValidationURL": till_url(setup, "accept")}, token=_token(setup))
        except PromptUnavailable as problem:
            setup.till_detail = str(problem)[:255]
        else:
            answer = str(data.get("ResponseDescription") or data.get("errorMessage") or "")
            if str(data.get("ResponseCode")) == "0" or "already registered" in answer.lower():
                setup.till_registered_at, setup.till_detail = timezone.now(), ""
            else:
                logger.warning("C2B URL registration refused for org %s: %s", setup.organization_id, answer)
                setup.till_detail = f"Safaricom did not register the till's payment notices: {answer or 'no reason given'}"[:255]
    setup.save(update_fields=["till_registered_at", "till_detail", "updated_at"])
    return setup


def simulate_till_payment(setup, *, amount, name="Test", phone="254700000000", account=""):
    """Development only: a customer paying the till, as Safaricom would report it."""
    from .checkout import mask, till_notice
    if not simulated():
        raise ValidationError("Till payments can only be simulated in development.")
    return till_notice(setup, {"TransID": f"SIM{token_source.token_hex(4).upper()}", "TransAmount": str(amount),
                               "TransTime": timezone.localtime().strftime("%Y%m%d%H%M%S"), "BusinessShortCode": setup.shortcode,
                               "BillRefNumber": account, "MSISDN": mask(phone), "FirstName": name})


def ready(setup):
    """Prompts can be sent: a till or paybill whose credentials Safaricom accepted (or the development simulator)."""
    if setup.kind == MpesaExpressSetup.NONE:
        return False
    complete = bool(setup.shortcode and (setup.kind == MpesaExpressSetup.PAYBILL or setup.till_number)
                    and unseal(setup.consumer_key) and unseal(setup.consumer_secret) and unseal(setup.passkey))
    return complete and (simulated() or (bool(setup.verified_at) and bool(callback_url(setup))))


def view(setup, full=True):
    """What the browser sees. Secrets never leave the server: only whether each one is saved."""
    data = {"kind": setup.kind, "ready": ready(setup), "simulated": simulated(), "till_number": setup.till_number,
            "paybill": setup.shortcode if setup.kind == MpesaExpressSetup.PAYBILL else "", "till_notices": bool(setup.till_registered_at)}
    if not full:
        return data
    key = unseal(setup.consumer_key)
    return {**data, "shortcode": setup.shortcode, "till_number": setup.till_number, "account_reference": setup.account_reference,
            "environment": setup.environment, "consumer_key_hint": f"…{key[-4:]}" if key else "",
            "has_consumer_secret": bool(unseal(setup.consumer_secret)), "has_passkey": bool(unseal(setup.passkey)),
            "verified_at": setup.verified_at, "tested_at": setup.tested_at, "status_detail": setup.status_detail,
            "callback_ready": simulated() or bool(callback_url(setup)), "requirements": REQUIREMENTS,
            "till_notices": bool(setup.till_registered_at), "till_detail": setup.till_detail}


def _digits(value, label, required=True):
    text = "".join(str(value or "").split())
    if not text and not required:
        return ""
    if not text.isdigit() or not 5 <= len(text) <= 10:
        raise ValidationError(f"Enter the {label} as digits only (5 to 10 of them).")
    return text


@transaction.atomic
def save(setup, data, user):
    """Saves what the business entered and checks it with Safaricom straight away. A secret left blank keeps the saved one."""
    from apps.core.models import AuditLog
    setup = MpesaExpressSetup.objects.select_for_update().get(pk=setup.pk)
    kind = data.get("kind", setup.kind)
    if kind not in {MpesaExpressSetup.NONE, MpesaExpressSetup.TILL, MpesaExpressSetup.PAYBILL}:
        raise ValidationError("Choose till, paybill, or manual payments only.")
    before = {"kind": setup.kind, "shortcode": setup.shortcode, "till_number": setup.till_number, "environment": setup.environment}
    setup.kind = kind
    if kind != MpesaExpressSetup.NONE:
        setup.shortcode = _digits(data.get("shortcode"), "store number" if kind == MpesaExpressSetup.TILL else "paybill number")
        setup.till_number = _digits(data.get("till_number"), "till number") if kind == MpesaExpressSetup.TILL else ""
        setup.account_reference = " ".join(str(data.get("account_reference") or "").split())[:12] if kind == MpesaExpressSetup.PAYBILL else ""
        environment = data.get("environment", setup.environment)
        if environment not in {"PRODUCTION", "SANDBOX"}:
            raise ValidationError("Choose live or testing.")
        setup.environment = environment
        changed = any(before[k] != getattr(setup, k) for k in ("shortcode", "till_number", "environment"))
        for field in ("consumer_key", "consumer_secret", "passkey"):
            value = "".join(str(data.get(field) or "").split())
            if value:
                setattr(setup, field, seal(value))
                changed = True
        missing = [label for field, label in (("consumer_key", "Consumer Key"), ("consumer_secret", "Consumer Secret"), ("passkey", "passkey"))
                   if not unseal(getattr(setup, field))]
        if missing:
            raise ValidationError(f"Enter the {', '.join(missing)} from your Daraja app.")
        if changed:
            setup.verified_at = setup.tested_at = setup.till_registered_at = None
    setup.updated_by = user
    setup.save()
    AuditLog.objects.create(action="MPESA_EXPRESS_SETUP_SAVED", object_type="MpesaExpressSetup", object_id=str(setup.pk), user=user,
                            before=before, after={"kind": setup.kind, "shortcode": setup.shortcode, "till_number": setup.till_number,
                                                  "environment": setup.environment})
    if setup.kind != MpesaExpressSetup.NONE and not setup.verified_at:
        verify(setup)
    return setup


def _base(setup):
    return "https://api.safaricom.co.ke" if setup.environment == "PRODUCTION" else "https://sandbox.safaricom.co.ke"


def _request(setup, path, payload=None, token=None, basic=None):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}" if token else f"Basic {basic}"}
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(_base(setup) + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read() or b"{}")
        except ValueError:
            raise PromptUnavailable(f"Safaricom answered with an error ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise PromptUnavailable("Could not reach Safaricom. Check the internet connection and try again.") from error


def _token(setup):
    basic = base64.b64encode(f"{unseal(setup.consumer_key)}:{unseal(setup.consumer_secret)}".encode()).decode()
    data = _request(setup, "/oauth/v1/generate?grant_type=client_credentials", basic=basic)
    if not data.get("access_token"):
        where = "live" if setup.environment == "PRODUCTION" else "sandbox (testing)"
        raise PromptUnavailable(f"Safaricom did not accept the Consumer Key and Secret for {where}. Copy them again from your Daraja app, "
                                "and check the app is live if you chose Live.")
    return data["access_token"]


def verify(setup):
    """Asks Safaricom for a token with the business's keys: proof the keys are right. The passkey is proven by the first
    prompt (send_test)."""
    try:
        if not simulated():
            _token(setup)
    except PromptUnavailable as problem:
        setup.verified_at, setup.status_detail = None, str(problem)[:255]
    else:
        setup.verified_at = timezone.now()
        setup.status_detail = "Safaricom accepted your keys. Send a test prompt to your own phone to finish." if not setup.tested_at else ""
    setup.save(update_fields=["verified_at", "status_detail", "updated_at"])
    if setup.verified_at and not setup.till_registered_at:
        register_till(setup)
    return setup


def _password(setup, timestamp):
    return base64.b64encode(f"{setup.shortcode}{unseal(setup.passkey)}{timestamp}".encode()).decode()


def whole_shillings(amount):
    amount = Decimal(str(amount))
    if amount != amount.to_integral_value() or amount < 1:
        raise ValidationError("M-Pesa prompts are for whole shillings (at least 1). Round the amount, or record M-Pesa by hand with the code.")
    return int(amount)


def send(setup, *, phone, amount, user, payment=None, reference="Payment"):
    """Sends the prompt to the customer's phone. Returns the StkPush, PENDING until the customer answers."""
    if not ready(setup):
        raise ValidationError("M-Pesa prompts are not set up for this business yet. The owner can set them up in Settings → M-Pesa payments.")
    try:
        phone = normalize_phone(phone)
    except ValueError as problem:
        raise ValidationError(str(problem))
    value = whole_shillings(amount)
    push = StkPush.objects.create(payment=payment, phone=phone, amount=value, requested_by=user)
    if simulated():
        push.checkout_request_id, push.detail = f"SIM-{push.pk}", "Simulated prompt (development only)."
        push.save(update_fields=["checkout_request_id", "detail", "updated_at"])
        return push
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    till = setup.kind == MpesaExpressSetup.TILL
    body = {"BusinessShortCode": setup.shortcode, "Password": _password(setup, timestamp), "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline" if till else "CustomerPayBillOnline", "Amount": value,
            "PartyA": phone, "PartyB": setup.till_number if till else setup.shortcode, "PhoneNumber": phone,
            "CallBackURL": callback_url(setup), "AccountReference": (setup.account_reference or reference)[:12],
            "TransactionDesc": reference[:13]}
    try:
        data = _request(setup, "/mpesa/stkpush/v1/processrequest", body, token=_token(setup))
    except PromptUnavailable as problem:
        _finish(push, StkPush.FAILED, str(problem))
        raise ValidationError(str(problem))
    if str(data.get("ResponseCode")) != "0":
        message = data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa could not send the prompt."
        logger.warning("STK push refused for org %s: %s", setup.organization_id, message)
        _finish(push, StkPush.FAILED, f"Safaricom refused the prompt: {message}")
        raise ValidationError(push.detail)
    push.checkout_request_id, push.merchant_request_id = data["CheckoutRequestID"], data.get("MerchantRequestID", "")
    push.detail = data.get("CustomerMessage") or "Prompt sent. Waiting for the customer to enter their PIN."
    push.save(update_fields=["checkout_request_id", "merchant_request_id", "detail", "updated_at"])
    return push


def _finish(push, status, detail, receipt=""):
    """Moves a pending prompt to its result once: the callback and a status check may both arrive."""
    done = StkPush.objects.filter(pk=push.pk, status=StkPush.PENDING).update(status=status, detail=detail[:255], receipt_number=receipt,
                                                                              updated_at=timezone.now())
    push.refresh_from_db()
    return bool(done)


def apply_result(push, code, description="", metadata=None):
    """Applies Safaricom's answer. Paid: the sale's waiting M-Pesa payment is confirmed with the M-Pesa receipt number, or
    the checkout the prompt was for is paid (checkout.prompt_answered)."""
    from .checkout import prompt_answered
    from .settlements import confirm_payment
    code = str(code)
    if code != "0":
        if _finish(push, StkPush.CANCELLED if code == "1032" else StkPush.FAILED, RESULT_MESSAGES.get(code, description or "The payment did not go through.")):
            prompt_answered(push)
        return push
    items = {item.get("Name"): item.get("Value") for item in (metadata or {}).get("Item", [])}
    receipt = str(items.get("MpesaReceiptNumber") or "").upper()
    if not _finish(push, StkPush.COMPLETED, f"Paid. M-Pesa code {receipt}.", receipt):
        return push
    _keep_receipt(push, receipt)
    prompt_answered(push)
    setup = MpesaExpressSetup.objects.get(organization_id=push.organization_id)
    if not setup.tested_at:
        setup.tested_at, setup.status_detail = timezone.now(), ""
        setup.save(update_fields=["tested_at", "status_detail", "updated_at"])
    if push.payment_id and receipt:
        try:
            confirm_payment(payment=Payment.objects.get(pk=push.payment_id), reference=receipt)
        except ValidationError as problem:
            message = problem.detail[0] if isinstance(problem.detail, list) else problem.detail
            StkPush.objects.filter(pk=push.pk).update(detail=f"Paid ({receipt}), but the payment could not be confirmed: {message}"[:255])
            push.refresh_from_db()
    return push


def _keep_receipt(push, receipt):
    """Every prompt's payment joins the ledger of M-Pesa payments the business received. One for a sale's payment or the
    owner's test is marked as already used, so the till's own notice of the same payment is never offered for a sale."""
    from .checkout import mask, record_incoming
    from .models import IncomingMpesaPayment as Incoming
    if not receipt or hasattr(push, "checkout_payment"):
        return  # a checkout's prompt is kept by prompt_answered, with the checkout
    incoming, _ = record_incoming(transaction_id=receipt, source=Incoming.PROMPT, amount=push.amount, paid_at=timezone.now(), payer_phone=mask(push.phone))
    if incoming.status == Incoming.UNMATCHED:
        note = f"Sale {push.payment.sale.number}" if push.payment_id else "The owner's test prompt"
        Incoming.objects.filter(pk=incoming.pk).update(status=Incoming.USED if push.payment_id else Incoming.SETTLED, used_amount=incoming.amount, note=note)


def check(push):
    """A prompt still pending: the simulator answers after a few seconds; otherwise Safaricom is asked once the callback is late."""
    if push.status != StkPush.PENDING or not push.checkout_request_id:
        return push
    age = (timezone.now() - push.created_at).total_seconds()
    if push.checkout_request_id.startswith("SIM-"):
        if age >= 4:
            return apply_result(push, "0", metadata={"Item": [{"Name": "MpesaReceiptNumber", "Value": f"SIM{push.pk:07d}"}, {"Name": "Amount", "Value": int(push.amount)}]})
        return push
    if age < QUERY_AFTER:
        return push
    setup = MpesaExpressSetup.objects.get(organization_id=push.organization_id)
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    try:
        data = _request(setup, "/mpesa/stkpushquery/v1/query", {"BusinessShortCode": setup.shortcode, "Password": _password(setup, timestamp),
                                                                "Timestamp": timestamp, "CheckoutRequestID": push.checkout_request_id}, token=_token(setup))
    except PromptUnavailable:
        return push
    if "ResultCode" in data:  # still waiting answers with an errorCode instead
        if str(data["ResultCode"]) == "0":
            # Paid. The M-Pesa code comes only with the callback; when that is late (the platform cannot be reached from
            # outside), the payment is confirmed with Safaricom's checkout id instead, so the sale does not wait.
            if age < 2 * QUERY_AFTER:
                return push
            return apply_result(push, "0", metadata={"Item": [{"Name": "MpesaReceiptNumber", "Value": push.checkout_request_id}]})
        return apply_result(push, data["ResultCode"], data.get("ResultDesc", ""))
    if age > GIVE_UP_AFTER and _finish(push, StkPush.FAILED, "No answer from M-Pesa. Check the till's M-Pesa messages, and confirm the payment by hand with its code if it came."):
        from .checkout import prompt_answered
        prompt_answered(push)
    return push


def push_data(push):
    return {"id": push.pk, "status": push.status, "phone": push.phone, "amount": push.amount, "receipt_number": push.receipt_number,
            "detail": push.detail, "payment": push.payment_id, "created_at": push.created_at}
