"""Shared internal variant search; public visibility rules remain separate."""
from django.db.models import Case, IntegerField, Q, Value, When


# Words a customer or the counter uses for the same thing. Each group is one meaning; a word in the search finds
# products described with any word of its group.
SAME_MEANING = [
    {"mobile", "phone", "cellphone", "smartphone", "simu"},
    {"earphone", "earphones", "earpods", "earbuds", "headphone", "headphones", "headset", "handsfree"},
    {"flash", "flashdrive", "flashdisk", "usb drive"},
    {"memory card", "memorycard", "sd card", "microsd"},
    {"extension", "power strip", "powerking", "power king"},
    {"bulb", "light", "lamp"},
    {"iphone", "lightning"},
    {"typec", "type c"},
    {"microusb", "micro usb", "v8"},
    {"laptop", "computer"},
    {"cable", "cord"},
    {"charger", "chaja"},
    {"speaker", "woofer"},
    {"tv", "television"},
]
FIELDS = ("product__name", "name", "product__brand__name", "product__description", "sku", "barcode", "product__category_id")


def _plain(text):
    """Lower case, with punctuation as spaces: "MICRO-USB (1M)" -> "micro usb 1m"."""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in str(text or "").lower()).split())


def _forms(word):
    """The word, its singular and every word of the same meaning, each also without spaces."""
    forms = {word}
    for suffix, repl in (("ies", "y"), ("es", ""), ("s", "")):
        if len(word) > 3 and word.endswith(suffix):
            forms.add(word[: -len(suffix)] + repl)
    for group in SAME_MEANING:
        if forms & {form.replace(" ", "") for form in group} | forms & group:
            forms |= group
    return {form.replace(" ", "") for form in forms} | forms


def _words(query):
    """The searched words, with pairs that are one product word joined: "type c" -> "typec", "micro usb" -> "microusb"."""
    words, plain = [], _plain(query).split()
    i = 0
    while i < len(plain):
        pair = " ".join(plain[i:i + 2])
        if any(pair in group for group in SAME_MEANING) and i + 1 < len(plain):
            words.append(pair.replace(" ", ""))
            i += 2
        else:
            words.append(plain[i])
            i += 1
    return words


def search_variants(rows, query):
    """Products matching what was typed, the way a person means it: every word may sit anywhere in the name, variant,
    brand, description, item code or the category (and its parent categories) the product is filed under; plurals,
    words of the same meaning ("mobile" = "phone") and small typos still match. Exact item codes or barcodes come first,
    then products whose own name holds the words. If nothing holds every word, those holding the most are shown."""
    from difflib import get_close_matches

    from .models import Category
    query = query.strip()
    if not query:
        return rows.order_by("product__category__name", "product__name", "name", "id")
    categories = {pk: (name, parent) for pk, name, parent in Category.objects.values_list("id", "name", "parent_id")}

    def path(pk, depth=0):
        name, parent = categories.get(pk, ("", None))
        return name + (" " + path(parent, depth + 1) if parent and depth < 6 else "")

    entries = []
    for pk, product, variant, brand, description, sku, barcode, category in rows.values_list("pk", *FIELDS):
        own = _plain(f"{product} {variant} {brand}")
        text = f"{own} {_plain(description)} {_plain(sku)} {_plain(barcode)} {_plain(path(category))}"
        entries.append((pk, own, own.replace(" ", ""), text, text.replace(" ", ""), {_plain(sku), _plain(barcode)} - {""}))
    vocabulary = sorted({word for entry in entries for word in entry[3].split() if len(word) > 2})
    words = _words(query)
    wanted = []
    for word in words:
        forms = _forms(word)
        if not any(form in entry[4] for entry in entries for form in forms) and len(word) > 3:
            forms |= set(get_close_matches(word, vocabulary, n=3, cutoff=0.75))  # a small typo: "chager" -> "charger"
        wanted.append(forms)
    exact = _plain(query)
    scored = []
    for pk, own, own_squashed, text, squashed, codes in entries:
        hits = [forms for forms in wanted if any(form in text or form in squashed for form in forms)]
        if hits:
            in_name = sum(1 for forms in hits if any(form in own or form in own_squashed for form in forms))
            scored.append((exact not in codes, -len(hits), -in_name, own, pk))
    best = min((score[1] for score in scored), default=0)
    order = [score[4] for score in sorted(s for s in scored if s[1] == best)]
    if not order:
        return rows.none()
    position = Case(*[When(pk=pk, then=Value(i)) for i, pk in enumerate(order)], output_field=IntegerField())
    return rows.filter(pk__in=order).annotate(exact_rank=position).order_by("exact_rank")


def variant_summary(v, balances=None):
    from django.db.models import Sum
    from apps.inventory.models import StockBalance
    if balances is None:
        latest = v.lots.filter(pk__in=StockBalance.objects.values("lot_id")).order_by("-received_at", "-pk").first()
        locations = list(StockBalance.objects.filter(lot__variant=v, quantity__gt=0)
            .values("shelf__zone__name", "shelf__zone__store__name", "shelf__code", "shelf__display_name")
            .annotate(quantity=Sum("quantity")))
    else:
        latest = max((b.lot for b in balances), key=lambda lot:(lot.received_at,lot.pk), default=None)
        locations = [{"shelf__zone__name":b.shelf.zone.name, "shelf__zone__store__name":b.shelf.zone.store.name,
            "shelf__code":b.shelf.code,"shelf__display_name":b.shelf.display_name,"quantity":b.quantity} for b in balances if b.quantity > 0]
    available = sum((row["quantity"] for row in locations), 0)
    return {"id": v.id, "product_id": v.product_id, "product_name": v.product.name, "description": v.product.description,
            "variant_name": v.name, "category_id": v.product.category_id,
            "category_name": v.product.category.name, "sku": v.sku, "barcode": v.barcode,
            "product_type": v.product.product_type, "selling_price": v.selling_price, "minimum_price": v.minimum_price,
            "buying_price": latest.unit_cost if latest else v.service_cost, "available": available,
            "locations": [{"branch":row["shelf__zone__store__name"],"zone": row["shelf__zone__name"], "shelf_code": row["shelf__code"],
                           "shelf_name": row["shelf__display_name"], "quantity": row["quantity"]} for row in locations]}
