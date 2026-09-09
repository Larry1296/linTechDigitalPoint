"""Reusable AI catalog illustrations; extend POOLS to add product types/variants."""
import random
import re

PREFIX = "/images/catalog/"
POOLS = [
    ("Smartphone Covers", ("cover", "covers", "case", "cases"), ("cover-black", "cover-blue", "cover-clear")),
    ("Padlocks", ("padlock", "padlocks", "lock", "locks"), ("padlock-brass", "padlock-steel", "padlock-black")),
    ("Phone Accessories", ("charger", "chargers", "adapter"), ("charger-white", "charger-black")),
    ("Phone Accessories", ("cable", "cables", "cord"), ("cable-white", "cable-black")),
    ("Phone Accessories", ("earbuds", "earphones", "earbud"), ("earbuds-white", "earbuds-black")),
    ("Computer Accessories", ("mouse", "mice"), ("mouse-black", "mouse-white")),
    ("Computer Accessories", ("keyboard", "keyboards"), ("keyboard-black", "keyboard-white")),
    ("Electrical & Masonry Accessories", ("bulb", "bulbs", "led"), ("bulb-white", "bulb-warm")),
    ("Electrical & Masonry Accessories", ("socket", "sockets"), ("socket-white", "socket-cream")),
    ("Electrical & Masonry Accessories", ("trowel", "trowels"), ("trowel-wood", "trowel-red")),
]


def category_pools(category):
    names, seen = set(), set()
    while category and category.pk not in seen:
        seen.add(category.pk)
        names.add(category.name.casefold())
        category = category.parent
    if "phone accessories" in names:
        names.add("smartphone covers")
    if "electrical & masonry accessories" in names:
        names.add("padlocks")
    return [pool for pool in POOLS if pool[0].casefold() in names]


def image_choices(category, product_name=""):
    pools = category_pools(category)
    words = set(re.findall(r"[a-z0-9]+", product_name.casefold()))
    matched = [pool for pool in pools if words.intersection(pool[1])]
    # A specific product name should never receive an unrelated category item.
    # Category-only requests expose the entire pool for browsing.
    selected = matched if product_name else pools
    if product_name and not matched:
        selected = [pool for pool in pools if pool[0].casefold() == category.name.casefold()
                    and pool[0] in {"Smartphone Covers", "Padlocks"}]
    return [PREFIX + asset + ".png" for _, _, assets in selected for asset in assets]


def assign_product_image(product):
    if product.images.exists():
        return None
    choices = image_choices(product.category, product.name)
    if choices:
        return product.images.create(image_url=random.choice(choices),
                                     alt_text=f"AI illustration of {product.name}"[:180])
    return None
