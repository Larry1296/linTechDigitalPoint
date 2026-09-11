# Receipt line corrections

Open **Admin → Inventory → Receipt History**, open the receipt, and choose
**Correct receipt line** on the exact product variant/SKU. Receipt details also
have direct URLs such as `/admin-app/receipts/145`.

Viewing requires `inventory.view_stockreceipt`; posting additionally requires an
active staff account with `inventory.change_stockreceipt`. The review displays
the old/new variant, buying price, received quantity and line total. A reason and
confirmation are mandatory. Stale edits are rejected; reload and review again.

For receipt 145's Amaya charging cable, retain the exact cable variant and quantity
**3**, enter buying price **KSh 80**, verify total **KSh 240**, and enter:

> Amaya 10W wall-charger buying price was mistakenly entered against the cable.

The local database inspected during implementation did not contain receipt 145
by ID, receipt number, or external reference. No real receipt correction was
posted. The 3 × 80 example is covered by backend, frontend and browser fixtures.

## Inventory and audit rules

- Buying-price-only corrections update the receipt line and linked stock lot in
  one transaction. Quantities, balances, placements and movements remain unchanged.
- Future FIFO sales use the corrected lot cost. Existing sale allocations and
  historical cost of goods sold remain unchanged.
- Variant/quantity corrections are limited to unused lots still in their original
  compartments. Sold, reserved, transferred or otherwise used stock requires a
  separate reversal workflow; this feature rejects direct changes to those lots.
- For split receipts, enter each original compartment's new positive quantity;
  their sum must match the corrected received quantity.
- Quantity corrections update placements, balances and lot quantities atomically.
  Variant corrections update the line and lot identity. Original movements remain;
  compensating movements are appended and linked to the correction.
- Each correction preserves old/new values, reason, actor and timestamp. PostgreSQL
  triggers reject updates/deletions of correction records and their movements,
  including direct SQL changes. Django admin exposes the audit as read-only.

Apply migrations `inventory.0009` and `inventory.0010` before running the new code.
The correction endpoint is POST
`/api/v1/inventory/receipts/<receipt_id>/lines/<line_id>/correct/`;
its payload requires `variant_id`, `unit_cost`, `received_quantity`, `reason`,
`confirmed: true` and `expected_updated_at` from the receipt detail. Split quantity
changes also require `placements` with `shelf_id` and `quantity` for every original
compartment. No audit edit/delete endpoint is exposed.
