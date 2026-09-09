# Exact product and variant photographs

## Upload and edit

Receive Stock → Create product now includes **Product display image**, with
separate **Upload from storage** and **Take photo** controls. Mobile browsers
that support camera capture open the device camera; storage selection works on
desktop and mobile. A preview appears before saving. Photograph the exact package
alone, not a group of different cable types.

New customer-visible products require a valid photo. An internal-only product
can still be created without one. The standalone Add Product form follows the
same rule. Product creation and image upload are one request; the photograph is
not a receipt attachment or a placement record.

For existing products, open **Products → Edit display images / variants**.
Choose the primary product image or a specific variant. The per-variant
**Edit variant image** button opens the correct variant directly. The same panel
can create another variant with a dedicated photo or explicit reuse of the
product's main photo, only when that photo shows the exact variant.

## Current cable photographs still needed

| Exact item | Required dedicated image |
| --- | --- |
| Amaya AM-M01 Type-B (Micro-USB), White, 1.2m, 3.1A | Type-B package photographed alone |
| Amaya Type-C cable | Type-C package photographed alone |

The existing SKU `AMAYA-AM-M01-MICRO-B-WHT-1M2` is marked to require its own
photo (`use_product_image=False`). Its photo remains pending. No group photograph
was assigned. No Type-C product, stock or placeholder photograph was created.
Physical photographs must be supplied by the shopkeeper; this implementation
does not fabricate product photography.

## Storage and customer display

- ProductImage now supports an uploaded file and an optional variant reference.
- The first image within the product or variant scope is the primary image.
- Dedicated variant photos override primary product photos. General photos are
  used only when the variant allows reuse. Category/AI illustrations are excluded
  from customer image selection; normal creation no longer assigns them.
- Uploads accept JPEG, PNG and WebP, up to 15 MB. Pillow validates the decoded
  image, applies camera orientation, fits it within 1600 × 1600 without upscaling,
  and writes WebP at quality 85. Original proportions and alpha are preserved;
  metadata is not copied into the optimized image.
- UUID filenames are saved through Django's configured file storage. Local
  defaults are `server/media/products/` and `/media/`. Django serves media during
  development; Vite proxies `/media/`. A production web server/storage backend
  must serve the configured media URL.
- Customer cards, detail, cart, checkout and order details use the resolved image.
  Images use `object-fit: contain`. New order lines snapshot the chosen image URL;
  replacing a catalog image does not change a completed order's photo. Previous
  stored files are retained for historical order references.

## APIs

Multipart requests use `display_image` for uploads:

- `POST /api/v1/catalog/products/create-inline/`
- `POST /api/v1/catalog/products/create-with-stock/`
- `POST /api/v1/catalog/products/{product_id}/variants/`
- `POST /api/v1/catalog/products/{product_id}/display-image/`

The edit endpoint optionally takes `variant_id`. For explicit reuse of the main
image, send that variant ID and `use_product_image=true`. Cross-product variant
references are rejected. Product, variant and image model APIs also validate
uploads. Existing customer image responses remain an `images` array with `url`
and `alt`, now resolved consistently for the selected variant.

## Validation and scope

Additive migrations `catalog.0006` and `commerce.0004` were applied locally.
Pillow 12.3.0 was added to requirements. Django system checks, migration
consistency and Ruff pass. Full server suite: 103 passed. Full client suite:
39 passed, with client lint and build passing. Additional image assertions
verify distinct Type-B/Type-C photos on cards, details, cart, checkout and orders.

Tests cover missing/invalid photos, multipart storage and CSRF, camera controls,
preview cleanup, primary/variant selection and reuse, editing existing products,
permissions, no category fallback, and order snapshots. Receipt quantities,
selling prices, lots, balances, movements and exact shelf placement retain their
existing behavior. Inventory snapshots around the current Type-B flag update
were unchanged. No real inventory was created, reset or received by this task.
