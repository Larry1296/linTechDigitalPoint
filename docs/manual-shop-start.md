# Current workflow: manual entry from an empty shop

The latest owner instruction supersedes the earlier opening-stock setup workflow.
The local development database was backed up and reset again on 2026-09-09.
Only required Django system records and the existing administrator were retained.
The administrator's existing credentials still work; sessions were cleared.
No Store, categories, products, stock, zones, racks, shelves or receipts were seeded.
No inventory, layout or initial-data seeder was invoked during this reset.

Backup: `.pgdata/backups/lintechdigitalpoint-before-manual-reset-20260909T110939Z.dump`
(451,150 bytes, private PostgreSQL custom archive). All 37 migration-history rows
were preserved. Files, catalog images and receipt photographs were not removed.

## First owner action

1. Sign in with the existing administrator account.
2. Open **Digital Shop**.
3. Under **Merchandise categories**, type **Mobile Accessories** in Category name.
4. Leave Parent category set to **Root category**.
5. Click **Create category**.

The form starts blank. Opening the page never creates categories. Rack creation
is not offered on the empty Digital Shop page until an active category exists.
This work deliberately leaves Mobile Accessories uncreated in the development
database, so its creation is the owner's first business action.

Categories can be added under a parent, renamed or made inactive through Edit.
Slugs are generated internally and remain stable when names change. Duplicate
sibling names and cyclic parent relationships are rejected by the API. Existing
category references are retained when a category is made inactive.

Do not run `seed_initial`, `setup_shop_layout`, `seed_shop_inventory`, or
`seed_sample_inventory` as part of this manual workflow. Receipt 147 remains
unreceived. Products and receipts will be entered individually from physical
photographs through the normal application workflow.

## Verification

- Local target: DEBUG=True, localhost:5432, lintechdigitalpoint; active server
  127.0.0.1 and local PostgreSQL service verified before deletion.
- PostgreSQL backup created and checked with `pg_restore --list` before flush.
- Django flush and administrator recreation completed atomically; password hash
  retained only in memory and never included in source or command arguments.
- Migrations: no pending migrations; migration consistency check passed.
- Django system checks and Ruff passed.
- Category API tests: 3 passed; full server suite: 80 passed.
- Manual category UI tests: 3 passed; client lint and production build passed.
- Final read-only category/location requests returned empty lists for the admin.
- All application business tables were verified empty after reset.

Test fixtures use the separate test database; no manual category test created
records in the development database.
