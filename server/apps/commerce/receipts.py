"""Customer receipts: one document for print, the private link page and email.

A receipt always carries the selling business's own name and logo, never the platform's.
"""
import secrets
from decimal import Decimal
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape
from apps.tenancy.models import ReceiptLink
from .models import Sale

METHODS = {"CASH": "Cash", "MPESA": "M-Pesa", "BANK": "Bank", "OTHER": "Other", "CASH_ON_PICKUP": "Cash on pickup"}


def app_url(request):
    """Where customers open receipt links: configured, else the web app page that asked.

    Behind the web app's proxy the API's own host is internal, so prefer the browser's Origin
    (sent on POST) or Referer (sent on GET) over the request host.
    """
    from urllib.parse import urlsplit
    configured = getattr(settings, "PUBLIC_APP_URL", "")
    if configured:
        return configured.rstrip("/")
    for header in ("Origin", "Referer"):
        parts = urlsplit(request.headers.get(header, ""))
        if parts.scheme in {"http", "https"} and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return request.build_absolute_uri("/").rstrip("/")


def logo_url(organization, request=None, variant="logo"):
    stored = getattr(organization, variant) or organization.logo
    if stored:
        path = f"/api/v1/tenancy/public/logos/{stored.name.rsplit('/', 1)[-1]}"
        return f"{app_url(request)}{path}" if request else path
    return organization.logo_url or ""


def logo_size(organization):
    """The stored logo's pixel size, so emails can size it without running any script."""
    if not organization.logo:
        return None
    try:
        return organization.logo.width, organization.logo.height
    except (FileNotFoundError, ValueError, OSError):
        return None


def email_logo_width(size, area=15000, min_height=48, max_height=96, max_width=300):
    """Same area rule as the app's logo slots: wide wordmarks get width, square marks get height."""
    width, height = size
    aspect = width / height
    shown_height = min(max_height, max(min_height, (area / aspect) ** 0.5))
    return round(min(max_width, shown_height * aspect))


def receipt_data(sale, organization, request=None):
    branch = sale.branch
    items = []
    for item in sale.items.select_related("variant__product").order_by("pk"):
        variant = item.variant
        items.append({"name": variant.product.name, "variant": variant.name, "sku": variant.sku,
                      "quantity": item.quantity, "unit_price": item.unit_price, "discount": item.discount,
                      "total": item.quantity * item.unit_price - item.discount})
    payments = [{"method": METHODS.get(p.method, p.method.title()), "amount": p.amount, "reference": p.reference,
                 "status": p.status} for p in sale.payments.order_by("pk") if p.status in {"COMPLETED", "PENDING", "MANUAL_REVIEW"}]
    # After returns and price corrections (credit/debit notes) the customer is charged a different amount; the
    # balance due is the same figure Sales history shows, never the original total less payments.
    from .returns import sale_amounts, sale_balance
    charged, paid = sale_amounts(sale) if sale.status not in ("REFUNDED", "CANCELLED") else (Decimal(0), Decimal(0))
    cashier = sale.created_by
    customer = sale.customer
    return {
        "business": {"name": organization.name, "logo": logo_url(organization, request), "logo_size": logo_size(organization),
                     "phone": organization.phone,
                     "email": organization.email, "address": organization.address},
        "branch": {"name": branch.name, "phone": branch.phone, "email": branch.email, "address": branch.address} if branch else None,
        "number": sale.number, "channel": sale.get_channel_display(), "status": sale.status,
        "date": timezone.localtime(sale.created_at).isoformat(), "currency": organization.currency,
        "cashier": (cashier.get_full_name() or cashier.username) if cashier else "",
        "customer": (customer.get_full_name() or customer.username) if customer else "Walk-in customer",
        "items": items, "subtotal": sale.subtotal, "discount": sale.discount, "total": sale.total,
        "charged": charged, "payments": payments, "paid": paid,
        "refunded": sum((p["amount"] for p in payments if p["status"] == "COMPLETED"), Decimal(0)) - paid if sale.status not in ("REFUNDED", "CANCELLED") else Decimal(0),
        "balance": Decimal(0) if sale.status in ("REFUNDED", "CANCELLED") else max(Decimal(0), sale_balance(sale)),
        "footer": branch.receipt_footer if branch else "",
    }


def ensure_link(sale, organization, user):
    link = ReceiptLink.objects.filter(organization=organization, sale_id=sale.pk).first()
    if link and link.revoked_at is None:
        return link
    if link:
        # A turned-off link stays dead; sharing again issues a fresh address.
        link.token, link.revoked_at, link.created_by = secrets.token_urlsafe(24), None, user
        link.save(update_fields=["token", "revoked_at", "created_by"])
        return link
    return ReceiptLink.objects.create(organization=organization, sale_id=sale.pk, token=secrets.token_urlsafe(24), created_by=user)


def link_url(link, request):
    return f"{app_url(request)}/r/{link.token}"


def money(currency, value):
    return f"{'KSh' if currency == 'KES' else currency} {Decimal(value):,.2f}"


def send_receipt_email(receipt, to, url):
    """A branded email in the business's own name, with a link to the full receipt."""
    business = receipt["business"]
    currency = receipt["currency"]
    lines = "".join(
        f"<tr><td style='padding:6px 0'>{escape(i['name'])} — {escape(i['variant'])}<br>"
        f"<span style='color:#60708a;font-size:12px'>{i['quantity'].normalize():f} × {money(currency, i['unit_price'])}</span></td>"
        f"<td style='padding:6px 0;text-align:right'>{money(currency, i['total'])}</td></tr>" for i in receipt["items"])
    logo = ""
    if business["logo"]:
        width = email_logo_width(business["logo_size"]) if business.get("logo_size") else 220
        logo = (f"<img src='{escape(business['logo'])}' alt='{escape(business['name'])}' width='{width}' "
                f"style='width:{width}px;max-width:100%;height:auto'><br>")
    html = f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#10213d">
      <div style="text-align:center;padding:16px 0">{logo}<strong style="font-size:18px">{escape(business['name'])}</strong></div>
      <p>Thank you for your purchase. Here is your receipt <strong>{escape(receipt['number'])}</strong>.</p>
      <table style="width:100%;border-collapse:collapse;border-top:1px solid #d6e1f0;border-bottom:1px solid #d6e1f0">{lines}</table>
      <p style="text-align:right;font-size:16px"><strong>Total {money(currency, receipt['total'])}</strong></p>
      <p style="text-align:center"><a href="{escape(url)}" style="background:#1d4ed8;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">View full receipt</a></p>
      <p style="color:#60708a;font-size:12px;text-align:center">{escape(receipt['footer'] or '')}</p></div>"""
    text = (f"{business['name']}\nReceipt {receipt['number']}\n"
            + "\n".join(f"{i['name']} — {i['variant']}: {money(currency, i['total'])}" for i in receipt["items"])
            + f"\nTotal {money(currency, receipt['total'])}\nFull receipt: {url}\n")
    message = EmailMultiAlternatives(subject=f"Your receipt {receipt['number']} from {business['name']}", body=text,
                                     from_email=settings.DEFAULT_FROM_EMAIL, to=[to],
                                     reply_to=[business["email"]] if business["email"] else None)
    message.attach_alternative(html, "text/html")
    message.send()


def public_receipt(token, request):
    from apps.tenancy.context import organization_context
    link = ReceiptLink.objects.select_related("organization").filter(token=token, revoked_at__isnull=True).first()
    if not link or not link.organization.active:
        return None
    with organization_context(link.organization):
        sale = Sale.objects.select_related("branch", "customer", "created_by").filter(pk=link.sale_id).first()
        return receipt_data(sale, link.organization, request) if sale else None
