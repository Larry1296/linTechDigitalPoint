# Customer variant identity

The public `/api/v1/store/products/` API remains variant-based: `id` and
`variant_id` identify a ProductVariant; `product_id` groups sibling variants.
Each response includes product_name, variant_name (also available as the legacy
name field), SKU, display_name, selling_price, images, available quantity,
online_orderable, attributes and variant_count. Costs, lots, barcodes and
physical shelf locations remain private.

`apps.catalog.identity.display_name` is the shared product-plus-variant formatter.
The public catalog and cart use live names. Customer orders and printable order
receipts use the product_name and variant_name snapshots already stored at
checkout, so later catalog renaming does not rewrite purchase history.

Product details include a `variants` array of active, customer-visible siblings.
For multi-variant products, cards link to Choose variant and the detail page
requires an explicit choice before adding to the cart. Single-variant products
can be added directly. Connector type, model, colour, length and amperage display
from the existing option-value assignments when supplied. Category names remain
merchandise classifications, never item identities.

Cards (including home and search), details, cart, account cart, checkout review,
order list, order detail and printable customer receipt use display_name.
Cart/order responses include the actual variant_id. Cart updates validate the
variant's active/online status, a positive confirmed server selling price, and
available stock. Checkout revalidates locked variants and uses the existing
reservation service; submitted prices and totals are not trusted. POS and
inventory reception/placement services are unchanged.

## Confirmed local item

Only existing SKU `AMAYA-AM-M01-MICRO-B-WHT-1M2` was corrected:

- Variant name: `AM-M01 — Type-B (Micro-USB) — White — 1.2m — 3.1A`
- Display name: `Amaya USB Charging Cable — AM-M01 — Type-B (Micro-USB) — White — 1.2m — 3.1A`
- Model: AM-M01; connector: Type-B (Micro-USB); colour: White; length: 1.2m;
  amperage: 3.1A.

The customer endpoint `/api/v1/store/products/1/` was verified against the actual
local database. Inventory table snapshots before and after the identity update
were identical, including receipts, lines, lots, balances, placements and movements.
No Type-C inventory was created; the paired Type-C example exists only in tests.

## Validation

- Backend identity tests cover both connectors in public search/detail, cart,
  checkout, and order history after catalog renaming; authoritative price, stock
  and availability checks; invalid quantities and private field exclusion.
- UI tests cover distinct cards, mandatory selection, selected variant IDs,
  cart, checkout, history and printable receipts.
- Full server suite: 91 passed. Django system checks, Ruff and migration
  consistency checks passed. No schema migration required.
