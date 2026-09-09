# Stock adjustments

Use **Inventory → Adjust Stock**, or **Adjust Stock / Stock history** on an exact variant in Products. Only active staff with `inventory.adjust_stock` (and superusers) can open the adjustment data or post a count. Grant that permission deliberately; receiving or selling permission alone is insufficient.

1. Select the exact variant and physical shelf compartment.
2. Compare the displayed system quantity with a physical count, including reserved units.
3. Enter the count and select a reason. Add optional notes and a reference.
4. For an increase, select the original lot. When genuinely found stock has no suitable lot, choose a new adjustment lot and explicitly enter its unit cost. This lot records zero purchased/received units; its stock originates from the adjustment. No purchase receipt is fabricated. Existing lot costs and received quantities never change.
5. Review the signed difference and confirm before posting.

Decreases consume unreserved quantities FIFO within the selected compartment. Counts cannot go below zero or below reserved stock. Shelf, rack and zone must be active. A changed system quantity rejects the request so the owner can refresh and recount. A stable request key prevents a retry from posting twice.

Posting runs in one database transaction with locked balances. It creates a `StockAdjustment` and one signed `STOCK_ADJUSTMENT` movement per affected lot, recording before/amount/after, shelf, reason, notes, reference, administrator and time. It changes only the affected balances and lot remaining quantities. Original receipts, receipt placements, completed sales and their movements remain unchanged. A corrected lot can consequently have more remaining units than its original received quantity; the adjustment explains the difference.

PostgreSQL triggers reject updates and deletes to posted adjustments and their movements, including bulk ORM operations. To reverse a mistake, post a new physical-count adjustment. No API exposes adjustment editing or deletion.

The adjustment screen shows product stock history; **Analytics → Stock adjustment report** shows the latest 200 adjustments. These are internal endpoints; the public shop continues to expose available quantity without lot costs, shelf locations or adjustment notes.

Internal API:

- `GET /api/v1/inventory/adjustments/`: latest 200 adjustments and their lot movements.
- `GET /api/v1/inventory/adjustments/variants/<variant_id>/`: current balances, selectable lots and latest 200 stock movements.
- `POST /api/v1/inventory/adjustments/`: `variant_id`, `shelf_id`, `expected_quantity`, `counted_quantity`, `reason`, `confirmed: true`, unique `idempotency_key`, optional `notes`/`reference`, and (for increases) `lot_id` or explicit `new_lot_unit_cost`.

Apply schema changes with `python manage.py migrate`. This does not seed inventory or alter receipt/sale services.

Verification commands (from `server`, unless noted):

- `../.venv/bin/python manage.py check`
- `../.venv/bin/python manage.py makemigrations --check --dry-run`
- `../.venv/bin/pytest -q apps/inventory/tests/test_adjustments.py`
- `../.venv/bin/pytest -q`
- `.venv/bin/ruff check server` (repository root)
- `npm test -- --reporter=dot`, `npm run lint`, `npm run build` (client)

## Verified local correction — 2026-09-09

Posted adjustment **#1**, movement **#3**, as the existing administrator, through `adjust_stock`:

- SKU `AMAYA-AM-M01-MICRO-B-WHT-1M2`, compartment `AL1C1S1`.
- System 2, counted 4, adjustment +2, reserved 0, available 4.
- Reason: `Opening stock correction`.
- Note: `Physical recount found four Type-B cables after one earlier sale.`
- Reference: `TYPE-B-RECOUNT-20260909`.
- Request key: `lintech-type-b-al1c1s1-recount-20260909-v1`.

Before posting, the script verified `DEBUG=True`, host `localhost`, database `lintechdigitalpoint`, and the exact balance of 2. The surrounding transaction compared all original receipt, placement, sale, payment, catalog and movement rows before/after and verified other balances were untouched. The lot still records 3 originally received, with 4 now remaining. The public product endpoint returned the complete Type-B identity and 4 available without costs or physical locations. Anonymous adjustment access returned 403.

Executed verification results:

- Focused server adjustment tests: **21 passed**. Initial fixture failures (receipt quantity field and reservation expiry) were corrected before the successful run.
- Full server suite: **124 passed**; 47 existing missing-`staticfiles` warnings.
- Focused client adjustment tests: **6 passed**.
- Full client suite: **45 passed**; existing React `act` warnings.
- Django checks: no issues. Migration consistency: no changes detected.
- Ruff, client lint and client build: passed.
- `../.venv/bin/python manage.py migrate --noinput`: inventory migrations 0007 and 0008 applied successfully.
- `../.venv/bin/python manage.py shell < /tmp/lintech_type_b_adjustment.py`: posted and verified the single authorized correction; exited successfully. This was a local one-time script, not a seeder or a committed command.
