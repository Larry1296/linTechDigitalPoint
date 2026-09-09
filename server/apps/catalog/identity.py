"""Customer identity shared by live variants and immutable order snapshots."""


def display_name(product_name, variant_name):
    return " — ".join(part.strip() for part in (product_name, variant_name) if part and part.strip())
