"""Adds the LinTech cyber price list (Cyber Services and Online Applications) to one business.

Services are grouped as on the sheets (Printing & Copying, Document Services, Finishing & Files, and Online
Applications with its three sub-groups). Kinds of the same service are one service with price options: Printing (B&W A4, Colour A4), Photocopy, Lamination
(ID card, A5, A4) and Typing (Simple page, With formatting). Running it again adds only what is missing, and turns
services added separately by an earlier run (e.g. "B&W Printing - A4") into options of their service, as long as
nothing has been recorded against them yet. The printed list has no prices, so new options start without one
(price 0, "not set") unless --prices gives them; set the rest under each service's price options. Photography is
not offered, so the passport photo line is not included.

    python manage.py add_cyber_price_list --business lintech
    python manage.py add_cyber_price_list --business lintech --prices prices.csv   # "Printing - B&W A4,10" per line
"""
import csv
from decimal import Decimal, InvalidOperation
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization

PORTAL = "Service fee only - government/portal charges are separate."
# Groups as on the printed sheets: (group, sub-group, [(service, unit, note, [(option, name an earlier run gave it as a
# separate service)])]). The printer's work is "Printing & Copying"; the online sheet is one group with three sub-groups.
SECTIONS = [
    ("Printing & Copying", None, [
        ("Printing", "PER_PAGE", "", [("B&W A4", "B&W Printing - A4"), ("Colour A4", "Colour Printing - A4")]),
        ("Photocopy", "PER_PAGE", "", [("B&W A4", "B&W Photocopy - A4"), ("Colour A4", "Colour Photocopy - A4")]),
        ("Scanning to PDF/JPG", "PER_PAGE", "", []), ("ID Scan & Print - Front + Back", "PER_DOCUMENT", "", [])]),
    ("Document Services", None, [
        ("Typing", "PER_PAGE", "", [("Simple page", "Typing - Simple page"), ("With formatting", "Typing + Formatting")]),
        ("CV Typing / Editing", "PER_DOCUMENT", "", []), ("Cover Letter", "PER_DOCUMENT", "", []),
        ("PDF Convert / Merge / Split", "PER_DOCUMENT", "", []), ("Email / WhatsApp docs send", "FIXED", "", [])]),
    ("Finishing & Files", None, [
        ("Lamination", "PER_ITEM", "", [("ID card", "ID Lamination"), ("A5", "A5 Lamination"), ("A4", "A4 Lamination")]),
        ("Flash Disk / File Transfer", "FIXED", "", []), ("Downloads / Uploads", "FIXED", "", [])]),
    ("Online Applications", "Government & KRA", [
        ("eCitizen account/service assistance", "FIXED", PORTAL, []), ("Police Clearance / Good Conduct", "FIXED", PORTAL, []),
        ("KRA PIN registration / retrieval", "FIXED", PORTAL, []), ("KRA PIN certificate printing", "FIXED", PORTAL, []),
        ("iTax NIL return assistance", "FIXED", PORTAL, []), ("Tax document download / printing", "FIXED", PORTAL, [])]),
    ("Online Applications", "NTSA & Education", [
        ("NTSA / Driving Licence renewal", "FIXED", PORTAL, []), ("NTSA document download / print", "FIXED", PORTAL, []),
        ("KUCCPS application assistance", "FIXED", PORTAL, []), ("HELB application assistance", "FIXED", PORTAL, []),
        ("University / College application", "FIXED", PORTAL, []), ("Bursary / Scholarship application", "FIXED", PORTAL, [])]),
    ("Online Applications", "Jobs & Online Services", [
        ("Online Job Application", "FIXED", PORTAL, []), ("PSC / County portal assistance", "FIXED", PORTAL, []),
        ("CV upload + application support", "FIXED", PORTAL, []), ("Email setup / recovery assistance", "FIXED", PORTAL, []),
        ("General online form filling", "FIXED", PORTAL, []), ("Other online service", "FIXED", PORTAL, [])]),
]
PRICE_LIST = [entry for _, _, entries in SECTIONS for entry in entries]


def group_category(name, parent):
    """The service group (or sub-group) called ``name`` inside ``parent``, made if missing."""
    from django.utils.text import slugify
    from apps.catalog.models import Category
    found = Category.objects.filter(parent=parent, name__iexact=name).first()
    if found:
        return found
    base = f"services-{slugify(name)[:36]}"
    slug, number = base, 1
    while Category.objects.filter(slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    return Category.objects.create(name=name, slug=slug, parent=parent)


def read_prices(path):
    """{name: price} from "Service,price" or "Service - Option,price" lines (an earlier run's names work too)."""
    prices = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if len(row) < 2 or not row[0].strip():
                continue
            try:
                prices[row[0].strip().lower()] = Decimal(row[1].strip().replace(",", ""))
            except InvalidOperation:
                continue  # a heading row such as "name,price"
    return prices


def _has_history(product):
    from apps.commerce.models import CartItem, OrderItem, SaleItem
    from apps.cyber.models import CyberJobLine
    return any(model.objects.filter(variant__product=product).exists() for model in (CyberJobLine, SaleItem, OrderItem, CartItem))


class Command(BaseCommand):
    help = "Add the LinTech cyber and online-application services to a business (existing services are kept)."

    def add_arguments(self, parser):
        parser.add_argument("--business", required=True, help="The business's short name (slug).")
        parser.add_argument("--prices", help='Optional CSV of name,price, e.g. "Printing - B&W A4,10" or "Cover Letter,100".')

    def handle(self, *args, business, prices=None, **options):
        organization = Organization.objects.filter(slug=business).first()
        if not organization:
            raise CommandError(f"No business with the short name {business!r}.")
        owner = User.objects.filter(pk=organization.owner_id).first()
        priced = read_prices(prices) if prices else {}
        report = {"services": 0, "options": 0, "grouped": 0, "unpriced": 0}
        with organization_context(organization), transaction.atomic():
            from apps.cyber.services import services_category
            root = services_category()
            for group, subgroup, entries in SECTIONS:
                category = group_category(group, root)
                if subgroup:
                    category = group_category(subgroup, category)
                for name, unit, note, choices in entries:
                    product = self._service(owner, name, unit, note, choices, priced, report, category)
                    # Put it in its group unless the owner already chose one (it is then no longer straight under Services).
                    if product and product.category_id in (None, root.pk):
                        product.category = category
                        product.save(update_fields=["category", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Added {report['services']} services and {report['options']} price options; "
                                             f"{report['grouped']} separate services became price options."))
        if report["unpriced"]:
            self.stdout.write(f"{report['unpriced']} have no price yet: set them on Cyber Services > Income by service > the service > Price options.")

    def _price(self, priced, report, *names):
        for key in names:
            if key and key.lower() in priced:
                return priced[key.lower()]
        report["unpriced"] += 1
        return Decimal("0")

    def _service(self, owner, name, unit, note, choices, priced, report, category):
        from apps.catalog.models import Product, ProductVariant
        from apps.cyber.services import add_price_option, create_service
        services = Product.objects.filter(product_type=Product.SERVICE, variants__cyber_profile__isnull=False).distinct()
        product = services.filter(name__iexact=name).first()
        if not choices:
            if not product:
                product = create_service(owner, name, self._price(priced, report, name), billing_unit=unit, notes=note, category=category).variant.product
                report["services"] += 1
            return product
        for option, legacy in choices:
            separate = services.filter(name__iexact=legacy).first()
            if product and product.variants.filter(name__iexact=option).exists():
                continue
            if separate and not _has_history(separate) and separate.variants.count() == 1:
                variant = separate.variants.get()
                if not product:
                    # The first separate service becomes the grouped service itself.
                    separate.name = name
                    separate.save(update_fields=["name", "updated_at"])
                    product = separate
                else:
                    variant.product = product
                    variant.save(update_fields=["product", "updated_at"])
                    separate.delete()
                ProductVariant.objects.filter(pk=variant.pk).update(name=option)
                report["grouped"] += 1
                continue
            price = self._price(priced, report, f"{name} - {option}", legacy)
            if not product:
                profile = create_service(owner, name, price, billing_unit=unit, notes=note, category=category)
                ProductVariant.objects.filter(pk=profile.variant_id).update(name=option)
                product = profile.variant.product
                report["services"] += 1
            else:
                add_price_option(product, name=option, price=price, billing_unit=unit, notes=note)
                report["options"] += 1
        return product
