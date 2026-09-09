# Real shop inventory

Run commands from `server` using `../.venv/bin/python manage.py`.

```sh
../.venv/bin/python manage.py cleanup_sample_inventory --dry-run
../.venv/bin/python manage.py cleanup_sample_inventory --execute
# Separately guarded test-layout removal (also works without --execute for preview):
../.venv/bin/python manage.py cleanup_sample_inventory --dry-run --remove-test-layout
../.venv/bin/python manage.py cleanup_sample_inventory --execute --remove-test-layout
../.venv/bin/python manage.py setup_shop_layout
../.venv/bin/python manage.py seed_shop_inventory --dry-run
../.venv/bin/python manage.py seed_shop_inventory
```

## Confirmed receipt and local reset

Supplier receipt 147 is physically reconciled: **14 lines, 18 units and KSh 5,190**.
The manifest and reception tests use the same confirmed totals. A negative test
sets the expected quantity to 19 and verifies atomic rejection.

The owner authorized discarding all records only in this repository's verified
local development database. Before resetting: verify DEBUG, configured and active
database host/name, and the local PostgreSQL service; take a timestamped PostgreSQL
backup. Django `flush --no-input` preserves schema and migration history. Follow
with `migrate`, `seed_initial`, and interactive `createsuperuser` in a local terminal.
Never put administrator credentials in source, command arguments or chat.
Then run layout setup, inventory dry-run, reception and a repeat no-op verification.
Do not run the sample seeder against the development database.

The narrow sample cleanup remains available independently; it has no force
bypass for changed sample balances or unproven ownership.

## Ownership and safety

Cleanup requires both the exact sample receipt key and reference, the seven
known SKUs, two sample product slugs, original receipt quantities/costs,
placements, balances and purchase movements. It rejects any additional related
records, including released reservations, carts, sales, other lots and option
values referenced elsewhere. Placeholder image rows belong to the deleted
products; shared image files are retained. Normal receipt services/APIs are
unchanged. Deletion follows protected-reference order in one transaction.

The old seeder adopted existing categories and rack assignments without recording
ownership. Cleanup therefore preserves those records, even when currently unused,
and reports that limitation. Unused does not prove sample ownership. Audit logs
are retained. This command intentionally cannot remove all demonstration metadata
without further provenance; it must never guess away genuine categories.

## Zone A

Setup creates the root Mobile Accessories category and its primary rack
assignment. Zone A is named `Zone A — Right Wall`; its single rack is
`Mobile Accessories Rack`. Levels run top to bottom and compartments left to
right. The six physical labels are AL1C1S1, AL1C2S1, AL2C1S1, AL2C2S1,
AL3C1S1, AL3C2S1. Internal codes come from the existing rack service.
Dimensions (6 × 6 × 1 ft) are schematic, explicitly marked as awaiting measurement.
Repeated setup validates existing identities, structure, labels and active flags;
conflicts roll back without changing existing objects.

## Incremental rounds and placement

Append future rounds to `server/apps/core/shop_stock.py`; use a new permanent key
for each physical receipt and a distinct receipt reference, as required by the
existing receipt service. Each round declares expected line count, quantity and
buying total. Never edit an already received round. Existing keys are no-ops,
even after stock has moved or prices changed. Stable LINTECH SKUs can be reused
across rounds; existing product names and selling prices are preserved.

All new products are active internally and hidden from ecommerce/online ordering.
The schema's zero selling-price default represents an unset price, not an approved
retail price. No buying costs are added to public serializers. The three unclear
items have explicitly provisional internal names and SKUs. Confirm photos and
selling prices before publishing products.

| Compartment | Provisional contents |
| --- | --- |
| AL1C1S1 | Amaya Fast Micro cable |
| AL1C2S1 | Two provisional charger-head lines |
| AL2C1S1 | P47 headphones and provisional Oraimo item |
| AL2C2S1 | Original Oraimo charger and Oraimo Type-C copy |
| AL3C1S1 | Memory cards |
| AL3C2S1 | Flash disks |

Every round validates category and active exact compartments before catalog writes,
then calls `complete_stock_receipt` in its own transaction. Dry-run exercises the
same path and rolls it back (database sequence numbers may advance). A rejected
round stops the command; previously completed rounds remain committed. Later
rearrangement must use stock transfers, never direct balance or lot edits.

## Files in this change

- `server/apps/core/management/commands/cleanup_sample_inventory.py`
- `server/apps/core/management/commands/setup_shop_layout.py`
- `server/apps/core/management/commands/seed_shop_inventory.py`
- `server/apps/core/shop_stock.py`
- `server/apps/core/tests/test_shop_inventory.py`
- `client/src/components/PhysicalLocationPicker.jsx`
- `client/src/components/PhysicalLocationPicker.test.jsx`
- `client/src/modules/digital-shop/StackPreview.jsx`
- `docs/real-shop-inventory.md`

Existing unrelated catalog/image working-tree changes were preserved.
