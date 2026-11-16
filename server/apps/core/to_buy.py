"""The scratch list of things to buy now: add, tick off, change, remove, clear what is bought. Nothing here writes
stock, money or the books. A line leaves the list by itself once the item is recorded in the system: when stock is
received (or entered as opening stock) for the product it was linked to, or, for a line typed without a product, for a
product with the same name (the usual case for something new, added as a product when it arrives)."""
from decimal import Decimal

from django.db.models import Max, Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ToBuyItem
from .permissions import HasLinTechPermission


def variant_label(variant):
    return variant.product.name if variant.name in ("", "Standard") else f"{variant.product.name} {variant.name}"


class ItemInput(serializers.ModelSerializer):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    count = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"), required=False)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True)
    product = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = ToBuyItem
        fields = ["id", "name", "variant", "product", "count", "unit", "unit_price", "total", "note", "bought"]

    def get_product(self, item):
        return variant_label(item.variant) if item.variant_id else None

    def get_total(self, item):
        return item.total


def cleared_by(variant):
    """Lines on the list this variant's stock coming in records: those linked to it, and unlinked ones of its name."""
    names = {variant.product.name.strip().lower(), variant_label(variant).strip().lower()}
    unlinked = Q()
    for name in names:
        unlinked |= Q(name__iexact=name)
    return ToBuyItem.objects.filter(Q(variant=variant) | Q(variant__isnull=True) & unlinked)


@receiver(post_save, sender="inventory.Movement")
def clear_received(sender, instance, created, **kwargs):
    if created and instance.movement_type in ("PURCHASE_RECEIPT", "OPENING_STOCK") and instance.quantity > 0:
        cleared_by(instance.variant).delete()


NEWEST_FIRST = ("bought", "-position", "-pk")


def listing():
    # Newest first: the item just added is at the top. Bought ones follow, also newest first.
    items = list(ToBuyItem.objects.select_related("variant__product").order_by(*NEWEST_FIRST))
    left = [item for item in items if not item.bought]
    bought = [item for item in items if item.bought]
    add = lambda rows: sum((item.total for item in rows if item.total is not None), Decimal("0"))
    return {"items": ItemInput(items, many=True).data, "left": len(left), "left_total": add(left),
            "unpriced": sum(1 for item in left if item.total is None), "bought": len(bought), "bought_total": add(bought),
            "all_total": add(items)}


class ToBuyView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.view_tobuyitem", "POST": "core.add_tobuyitem", "DELETE": "core.delete_tobuyitem"}

    def get(self, request):
        return Response(listing())

    def post(self, request):
        form = ItemInput(data=request.data)
        form.is_valid(raise_exception=True)
        last = ToBuyItem.objects.aggregate(v=Max("position"))["v"] or 0
        form.save(position=last + 1, created_by=request.user)
        return Response(listing(), status=201)

    def delete(self, request):
        """Clear the items already bought."""
        ToBuyItem.objects.filter(bought=True).delete()
        return Response(listing())


class ToBuyItemView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"PATCH": "core.change_tobuyitem", "DELETE": "core.delete_tobuyitem"}

    def patch(self, request, pk):
        form = ItemInput(get_object_or_404(ToBuyItem, pk=pk), data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
        return Response(listing())

    def delete(self, request, pk):
        get_object_or_404(ToBuyItem, pk=pk).delete()
        return Response(listing())


class ToBuyFillView(APIView):
    """What a line for one of the business's products is filled with once it is picked, so only how many is typed:
    the price each from its last purchase (a pack's price when sold in packs), its unit, and who it was bought from."""
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.add_tobuyitem"}

    def get(self, request, variant_id):
        from apps.catalog.models import ProductVariant
        from apps.inventory.api import last_purchase
        variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=variant_id)
        _, supplier, unit_cost = last_purchase(variant)
        # The unit the product is kept in: one by one, or packs of so many pieces. A unit written for it on an earlier
        # line of the list (say cartons) is how this business buys it, so that comes first.
        size = variant.pack_size or 1
        piece = (variant.piece_name or "piece").strip().lower().rstrip("s") + "s"
        unit = f"packs of {size} {piece}" if size > 1 else "pcs"
        earlier = ToBuyItem.objects.filter(variant=variant).exclude(unit="").order_by("-id").values_list("unit", flat=True).first()
        unit = earlier or unit
        return Response({"variant": variant.id, "name": variant_label(variant), "unit": unit,
                         "unit_price": None if unit_cost is None else round(Decimal(unit_cost), 2),
                         "note": f"from {supplier}" if supplier else ""})


def _amount(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value is not None else "—"


def list_pdf(organization):
    """The items still to buy as an A4 PDF, to keep on a phone or print anywhere: the date it was made at the top, each
    item with a box to tick, how many of what, the price each and its total, and the money to carry at the bottom."""
    from io import BytesIO
    from django.utils import timezone
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    class TickBox(Flowable):
        """An empty square to tick by hand once the item is bought."""
        def wrap(self, *_):
            return 3.6 * mm, 3.6 * mm

        def draw(self):
            self.canv.setStrokeColor(colors.HexColor("#5b6b82"))
            self.canv.setLineWidth(0.8)
            self.canv.rect(0, 0, 3.6 * mm, 3.6 * mm)

    items = list(ToBuyItem.objects.select_related("variant__product").filter(bought=False).order_by(*NEWEST_FIRST))
    made = timezone.localtime()
    currency = "KSh" if (organization.currency or "KES") == "KES" else organization.currency
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="To buy", author=organization.name)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=9, leading=12, textColor=colors.HexColor("#5b6b82"))
    cell = styles["BodyText"].clone("cell", fontSize=10, leading=13)

    def page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    story = [Paragraph("To buy", styles["Title"].clone("t", alignment=0, spaceAfter=2)),
             Paragraph(f"{escape(organization.name)} · Made {made:%a %d %b %Y, %I:%M %p}".replace(" 0", " "), small), Spacer(0, 6 * mm)]
    if not items:
        story.append(Paragraph("Nothing left to buy.", cell))
    else:
        rows = [["", "Item", "How many", f"Price each ({currency})", f"Total ({currency})"]]
        for item in items:
            what = escape(item.name) + (f"<br/><font size=8 color='#5b6b82'>{escape(item.note)}</font>" if item.note else "")
            count = f"{item.count:f}".rstrip("0").rstrip(".") + (f" {item.unit}" if item.unit else "")
            rows.append([TickBox(), Paragraph(what, cell), Paragraph(escape(count), cell), _amount(item.unit_price), _amount(item.total)])
        need = sum((item.total for item in items if item.total is not None), Decimal("0"))
        unpriced = sum(1 for item in items if item.total is None)
        rows.append(["", "", "", "Money to carry", _amount(need)])
        table = Table(rows, colWidths=[8 * mm, 78 * mm, 32 * mm, 30 * mm, 30 * mm], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5b6b82")),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#d6e1f0")),
            ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#10213d")),
            ("FONT", (3, -1), (-1, -1), "Helvetica-Bold", 11),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("FONT", (4, 1), (4, -2), "Helvetica-Bold", 10),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(table)
        if unpriced:
            story += [Spacer(0, 2 * mm), Paragraph(f"{unpriced} {'item has' if unpriced == 1 else 'items have'} no price yet and "
                                                   f"{'is' if unpriced == 1 else 'are'} not counted in the money to carry.", small)]
    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return buffer.getvalue()


class ToBuyPdfView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = {"GET": "core.view_tobuyitem"}

    def get(self, request):
        from django.http import HttpResponse
        from django.utils import timezone
        response = HttpResponse(list_pdf(request.organization), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="to-buy-{timezone.localdate():%Y-%m-%d}.pdf"'
        return response
