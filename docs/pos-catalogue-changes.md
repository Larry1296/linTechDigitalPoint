# POS and Products catalogue improvements

Inspected remote `main` before editing: `876a2cd` (Stock Reception); local main matched it.

POS and Products share the homepage search component: two trimmed characters, 250 ms debounce, aborted/ignored stale requests, keyboard navigation, and loading/empty/error states. Admin searches use staff endpoints. POS scanner Enter bypasses the debounce and selects the exact SKU/barcode variant.

POS returns the complete active catalogue when browsing, ordered by category/product/variant/id, with services displayed separately. Stock and locations are loaded in one batch. Empty stock is disabled, cart quantities are bounded, and the existing transactional sale and receiving services remain authoritative.

Products browses 20 products per page and fetches search suggestions from the server. Selecting a suggestion opens its product and highlights the exact variant. Separate permission-controlled editors update catalogue fields through existing serializers, retaining price history; neither editor submits physical inventory. POS shortcuts navigate to Products, Receive Stock, and Adjust Stock. Receive links preselect the variant when starting a new receipt; an existing saved receipt draft takes precedence.

## Validation

- Django: `pytest server/apps/commerce server/apps/catalog server/apps/inventory server/apps/core/tests --reuse-db -q --tb=short` — 131 passed.
- Strengthened exact-priority test subsequently verified with the commerce suite — 8 passed.
- Frontend: `npm --prefix client test -- --reporter=dot` — 72 passed across 15 files.
- Production build: `npm --prefix client run build` — passed.
- ESLint on implementation files and `git diff --check` — passed.
- Existing React `act(...)` warnings and missing Django staticfiles-directory warnings remain non-failing.
- The public variant identity test previously assumed creation order although the endpoint returns newest first; it now verifies each identity by variant ID. Public endpoint behavior was preserved.

## Changed files

Frontend implementation:

- `client/src/modules/admin/AdminPages.jsx`
- `client/src/modules/admin/pos.css` (new)
- `client/src/modules/products/ProductActions.jsx` (new)
- `client/src/modules/products/ProductEditor.jsx` (new)
- `client/src/modules/products/VariantSummary.jsx` (new)
- `client/src/modules/products/ProductsPage.jsx`
- `client/src/modules/products/ProductPhotos.jsx`
- `client/src/modules/receiving/ReceivePage.jsx`
- `client/src/modules/storefront/components/ProductSearch.jsx`

Backend implementation:

- `server/apps/catalog/api.py`
- `server/apps/catalog/search.py` (new)
- `server/apps/commerce/api.py`

Tests:

- `client/src/modules/admin/PosPage.test.jsx` (new)
- `client/src/modules/products/ProductEditor.test.jsx` (new)
- `client/src/modules/products/components/DisplayImageInput.test.jsx`
- `client/src/modules/products/sku.test.jsx`
- `client/src/modules/storefront/ProductSearch.test.jsx`
- `server/apps/commerce/tests.py`
- `server/apps/core/tests/test_customer_variant_identity.py`
- `server/apps/inventory/tests/test_services.py`

Report: `docs/pos-catalogue-changes.md` (new).

Pre-existing user changes preserved: `client/e2e/product-layout.spec.js`, `client/src/assets/styles/modules.css`, and `client/src/assets/styles/public.css`.
