"""The M-Pesa agency's monthly report: every shift and every transaction in a calendar month, as a PDF.

Figures come only from recorded shifts and transactions. Reversed transactions are listed with their
reversal and left out of the net totals. Months follow the business's local time (settings.TIME_ZONE).
"""
import calendar
from datetime import datetime, time
from decimal import Decimal
from io import BytesIO

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import MpesaOutlet, MpesaSession, MpesaTransaction

ZERO = Decimal("0")
TYPE_LABELS = {"CUSTOMER_DEPOSIT": "Deposit", "CUSTOMER_WITHDRAWAL": "Withdrawal", "AIRTIME_SALE": "Airtime sale", "FLOAT_TOPUP": "Float top-up",
               "CASH_REBALANCE": "Cash rebalance", "ADJUSTMENT": "Adjustment", "REVERSAL": "Reversal"}

PAID_BY = {"CASH": "Cash", "MPESA_FLOAT": "M-Pesa (agent line)", "MPESA_OTHER": "M-Pesa (other number)"}
TOPUP_SOURCE = {"DRAWER": "Agency drawer", "OUTSIDE": "Outside the agency"}


def month_bounds(value):
    """'YYYY-MM' → (first moment, first moment of the next month), in local time."""
    try:
        year, month = (int(part) for part in str(value).split("-"))
        first = datetime(year, month, 1)
    except (TypeError, ValueError):
        raise ValidationError("Choose a month as YYYY-MM.")
    following = datetime(year + month // 12, month % 12 + 1, 1)
    zone = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(first, time.min), zone), timezone.make_aware(following, zone)


def completed_months():
    """Months that have ended and had agency activity, newest first: the reports that can be generated."""
    this_month = timezone.localdate().replace(day=1)
    months = {}
    for opened in MpesaSession.objects.values_list("opened_at", flat=True):
        day = timezone.localtime(opened).date().replace(day=1)
        if day < this_month:
            months[day] = months.get(day, 0) + 1
    return [{"month": f"{day:%Y-%m}", "label": f"{calendar.month_name[day.month]} {day.year}", "shifts": count}
            for day, count in sorted(months.items(), reverse=True)]


def month_data(value):
    start, end = month_bounds(value)
    if start.date() >= timezone.localdate().replace(day=1):
        raise ValidationError("A month's report is available once the month has ended.")
    transactions = list(MpesaTransaction.objects.filter(occurred_at__gte=start, occurred_at__lt=end)
                        .select_related("outlet", "performed_by", "reversal_of", "corrects").order_by("occurred_at", "pk"))
    reversed_ids = {t.reversal_of_id for t in MpesaTransaction.objects.filter(reversal_of__isnull=False).only("reversal_of_id")}
    sessions = list(MpesaSession.objects.filter(opened_at__gte=start, opened_at__lt=end)
                    .select_related("outlet", "operator", "closed_by").order_by("opened_at", "pk"))
    reconciliations = {s.pk: getattr(s, "reconciliation", None) for s in sessions}
    totals = {}
    for key in TYPE_LABELS:
        if key == "REVERSAL":
            continue
        rows = [t for t in transactions if t.transaction_type == key]
        live = [t for t in rows if t.pk not in reversed_ids]
        totals[key] = {"label": TYPE_LABELS[key], "count": len(rows), "reversed": len(rows) - len(live),
                       "net": sum((t.amount for t in live), ZERO)}
    closed = [s for s in sessions if s.status == MpesaSession.CLOSED]
    return {
        "month": value, "label": f"{calendar.month_name[start.month]} {start.year}", "start": start, "end": end,
        "outlets": list(MpesaOutlet.objects.filter(pk__in={s.outlet_id for s in sessions} | {t.outlet_id for t in transactions})
                        .order_by("display_name")),
        "sessions": sessions, "reconciliations": reconciliations, "transactions": transactions, "reversed_ids": reversed_ids,
        "totals": totals, "reversals": sum(1 for t in transactions if t.transaction_type == "REVERSAL"),
        "open_sessions": [s for s in sessions if s.status == MpesaSession.OPEN],
        "cash_variance": sum((r.cash_variance for r in reconciliations.values() if r), ZERO),
        "float_variance": sum((r.float_variance for r in reconciliations.values() if r), ZERO),
        "first_opening": (sessions[0].opening_cash + sessions[0].opening_float) if sessions else None,
        "last_closing": (closed[-1].closing_cash_actual + closed[-1].closing_float_actual) if closed else None,
    }


def _money(value):
    return "—" if value is None else f"{value:,.2f}"


def _signed(value):
    return "—" if not value else f"{value:+,.2f}"


def _phone(value):
    return f"0{value[3:6]} {value[6:9]} {value[9:]}" if value and value.startswith("254") else (value or "")


def _local(value):
    return timezone.localtime(value).strftime("%d %b %Y %H:%M") if value else "—"


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _time(value):
    return timezone.localtime(value).strftime("%H:%M")


def render_pdf(data, organization):
    """Day by day: money in operation, then that day's deposits, withdrawals and float top-ups, with times."""
    from collections import defaultdict
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    generated = timezone.localtime()
    title = f"M-Pesa agency report — {data['label']}"

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(14 * mm, 9 * mm, f"{organization.name} · {title} · generated {generated:%d %b %Y %H:%M}")
        canvas.drawRightString(A4[0] - 14 * mm, 9 * mm, f"Page {doc.page}")
        canvas.drawString(14 * mm, 5.5 * mm, "Contains customers' phone and ID numbers: store and share it securely.")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=title, author=organization.name)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8.5, leading=11)
    day_heading = styles["Heading2"].clone("day", fontSize=13, spaceBefore=8, spaceAfter=2)
    part_heading = styles["Heading4"].clone("part", fontSize=9.5, spaceBefore=5, spaceAfter=2)

    def table(rows, widths, numeric=()):
        result = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="LEFT")
        style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                 ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f8")),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8d0dc")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        style += [("ALIGN", (column, 0), (column, -1), "RIGHT") for column in numeric]
        result.setStyle(TableStyle(style))
        return result

    def section(heading, body):
        # A heading never sits alone at the bottom of a page, away from its table.
        return KeepTogether([Paragraph(heading, part_heading), body])

    corrected_ids = {t.corrects_id for t in data["transactions"] if t.corrects_id}

    def note(t):
        if t.corrects_id:
            return f"Correction of the {_time(t.corrects.occurred_at)} entry of {_money(t.corrects.amount)}"
        if t.pk in data["reversed_ids"]:
            return "Corrected (see the correction)" if t.pk in corrected_ids else "Reversed"
        return ""

    def total(rows):
        return sum((t.amount for t in rows if t.pk not in data["reversed_ids"]), ZERO)

    by_day = defaultdict(list)
    for t in data["transactions"]:
        by_day[timezone.localtime(t.occurred_at).date()].append(t)
    shifts_by_day = defaultdict(list)
    for s in data["sessions"]:
        shifts_by_day[timezone.localtime(s.opened_at).date()].append(s)

    outlets = ", ".join(f"{o.display_name} (agent {o.agent_reference or '—'}, store {o.store_number or '—'})" for o in data["outlets"])
    story = [Paragraph(title, styles["Title"]),
             Paragraph(f"{organization.name}{' · ' + outlets if outlets else ''} · amounts in {organization.currency}", small),
             Spacer(0, 3 * mm)]
    totals = data["totals"]
    story += [Paragraph("Month in total", part_heading),
              table([["", "Number", "Amount"],
                     ["Deposits", totals["CUSTOMER_DEPOSIT"]["count"] - totals["CUSTOMER_DEPOSIT"]["reversed"], _money(totals["CUSTOMER_DEPOSIT"]["net"])],
                     ["Withdrawals", totals["CUSTOMER_WITHDRAWAL"]["count"] - totals["CUSTOMER_WITHDRAWAL"]["reversed"], _money(totals["CUSTOMER_WITHDRAWAL"]["net"])],
                     ["Airtime sold", totals["AIRTIME_SALE"]["count"] - totals["AIRTIME_SALE"]["reversed"], _money(totals["AIRTIME_SALE"]["net"])],
                     ["Float top-ups", totals["FLOAT_TOPUP"]["count"] - totals["FLOAT_TOPUP"]["reversed"], _money(totals["FLOAT_TOPUP"]["net"])],
                     ["Days with activity", len(set(by_day) | set(shifts_by_day)), ""]], [60, 25, 35], numeric=(1, 2))]
    if data["reversals"]:
        story.append(Paragraph("Reversed transactions are listed on their day, marked \"Reversed\", and left out of the totals.", small))
    if data["open_sessions"]:
        story.append(Paragraph(f"{len(data['open_sessions'])} shift(s) were still open when this report was generated, "
                               "so their closing figures are missing.", small))

    for day in sorted(set(by_day) | set(shifts_by_day)):
        rows = by_day.get(day, [])
        story += [CondPageBreak(60 * mm), Paragraph(f"{day:%A %d %B %Y}", day_heading)]
        shift_rows = [["Shift", "Outlet", "Opening cash", "Opening float", "Opening total", "Closing cash", "Closing float", "Closing total"]]
        for s in shifts_by_day.get(day, []):
            closed = s.closing_cash_actual is not None
            shift_rows.append([f"{_time(s.opened_at)}–{_time(s.closed_at) if s.closed_at else 'open'}", s.outlet.display_name,
                               _money(s.opening_cash), _money(s.opening_float), _money(s.opening_cash + s.opening_float),
                               _money(s.closing_cash_actual), _money(s.closing_float_actual),
                               _money(s.closing_cash_actual + s.closing_float_actual) if closed else "—"])
        if len(shift_rows) > 1:
            story += [section("Money in operation", table(shift_rows, [20, 28, 21, 21, 21, 21, 21, 21], numeric=(2, 3, 4, 5, 6, 7)))]
        deposits = [t for t in rows if t.transaction_type == "CUSTOMER_DEPOSIT"]
        withdrawals = [t for t in rows if t.transaction_type == "CUSTOMER_WITHDRAWAL"]
        airtime = [t for t in rows if t.transaction_type == "AIRTIME_SALE"]
        topups = [t for t in rows if t.transaction_type == "FLOAT_TOPUP"]
        others = [t for t in rows if t.transaction_type not in {"CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE", "FLOAT_TOPUP"}]
        story += [section(f"Deposits ({len(deposits)}) — total {_money(total(deposits))}",
                  table([["Time", "M-Pesa number", "ID number", "Amount", "Transaction ID", "Note"]] +
                        [[_time(t.occurred_at), _phone(t.customer_phone), t.customer_id_number, _money(t.amount),
                          t.provider_reference or "", note(t)] for t in deposits], [16, 32, 28, 26, 36, 24], numeric=(3,))
                  if deposits else Paragraph("None.", small))]
        story += [section(f"Withdrawals ({len(withdrawals)}) — total {_money(total(withdrawals))}",
                  table([["Time", "Amount", "Transaction ID", "Note"]] +
                        [[_time(t.occurred_at), _money(t.amount), t.provider_reference or "", note(t)] for t in withdrawals],
                        [16, 26, 36, 24], numeric=(1,)) if withdrawals else Paragraph("None.", small))]
        if airtime:
            story += [section(f"Airtime sold ({len(airtime)}) — total {_money(total(airtime))}",
                      table([["Time", "Sent to", "Amount", "Paid by", "Transaction ID", "Note"]] +
                            [[_time(t.occurred_at), _phone(t.customer_phone), _money(t.amount), PAID_BY.get(t.paid_by, ""),
                              t.provider_reference or "", note(t)] for t in airtime], [16, 30, 24, 30, 30, 24], numeric=(2,)))]
        story += [section(f"Float top-ups ({len(topups)}) — total {_money(total(topups))}",
                  table([["Time", "Amount", "Money from", "Reference", "Note"]] +
                        [[_time(t.occurred_at), _money(t.amount), TOPUP_SOURCE.get(t.paid_by or "DRAWER", ""), t.provider_reference or "", note(t)]
                         for t in topups], [16, 26, 30, 36, 24], numeric=(1,)) if topups else Paragraph("None.", small))]
        if others:
            story += [section(f"Other entries ({len(others)})",
                      table([["Time", "Type", "Amount", "Cash effect", "Float effect", "Note"]] +
                            [[_time(t.occurred_at), TYPE_LABELS.get(t.transaction_type, t.transaction_type), _money(t.amount),
                              _signed(t.cash_delta), _signed(t.float_delta),
                              (f"Reverses the {_time(t.reversal_of.occurred_at)} {TYPE_LABELS.get(t.reversal_of.transaction_type, '').lower()}"
                               if t.reversal_of else note(t))] for t in others],
                            [16, 26, 24, 24, 24, 48], numeric=(2, 3, 4)))]
    if not by_day and not shifts_by_day:
        story.append(Paragraph("No M-Pesa activity was recorded this month.", small))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
