# Local development reset and receipt 147 — 2026-09-09

## Target and backup

Verified `.env`, Django settings and the active connection before deletion:
DEBUG=True; configured host localhost, port 5432; database lintechdigitalpoint;
active server 127.0.0.1:5432; not a replica. The local system PostgreSQL service
runs `/usr/bin/postgres -D /var/lib/pgsql/data`. The only database connection at
verification was local. No hosted/production database was targeted.

Backup (custom PostgreSQL archive, 454,969 bytes, mode 0600):
`.pgdata/backups/lintechdigitalpoint-before-reset-20260909T102444Z.dump`.
The directory is mode 0700 and already excluded from git. `pg_restore --list`
verified that the archive could be read before the flush was allowed.

Django flush preserved all 37 migration-history rows. Migrate had nothing pending.
Seed initial produced one Store, six roles and permissions; immediately after
reset there were no users, products, receipts or zones. Source, migrations,
catalog images and receipt photographs were not deleted.

The interactive `createsuperuser` command was requested in the user's local
terminal; no credentials were collected or scripted. Final database verification
found exactly one user, an active staff superuser.

## Reception result

- One Zone A, one Mobile Accessories Rack, three levels and six compartments.
- Primary root category: Mobile Accessories.
- All six physical labels verified through the internal API and UI component test,
  including every selector level and the rack's top-to-bottom display.
- Dry-run: 14 lines, 18 units, KSh 5,190; all six locations valid.
- All catalog/inventory/core records compared before and after dry-run: unchanged.
- Receipt 147 received through `complete_stock_receipt`, with the confirmed supplier,
  date, notes and permanent idempotency key.
- Second execution: already present; full catalog/inventory/core snapshots unchanged.
- Exactly 14 products, variants, receipt lines, lots, balances, placements and
  PURCHASE_RECEIPT movements. Each source quantity, cost and physical placement matched.
- Every lot initially has received quantity equal to remaining quantity; no reservations.
- All products active internally, under Mobile Accessories, hidden from ecommerce,
  not online-orderable, selling price zero/unset. Three identities remain provisional.
- No sample products or SAMPLE- SKUs. No sales, orders, payments, cyber or M-Pesa
  records remain. The running application subsequently created two empty session carts.
- Public catalog and featured products empty; public serializers contain no costs,
  lots or shelf locations; anonymous catalog, location and receipt APIs return 403.

## Executed operations and results

Paths below are relative to the repository unless a working directory is specified.
`manage.py` commands called inside temporary Django shell scripts use the same
Django management command implementation as their CLI equivalents.

| Command / operation | Result |
| --- | --- |
| `git status --short`; `cat` manifest, reception command, tests, inventory guide, core setup; `rg --files .agents .codex scripts`; settings inspection | Read current implementation and working tree. |
| Python read of `.env` with credential values redacted; `cat server/config/settings.py scripts/bootstrap.sh .gitignore` | Development configuration confirmed; no credentials printed. |
| `cat .pgdata/postmaster.pid` | Absent: repository data directory is not the active PostgreSQL service. |
| Django shell active connection query including `current_setting('data_directory')` | Permission denied for that server setting; no writes. Replaced with unprivileged identity query and local process/service inspection. |
| `ps`, `ss -ltnp '( sport = :5432 )'`, `systemctl status postgresql --no-pager` | Sandbox restricted inspection; rerun with approved local-system access. Local PostgreSQL service and loopback listener confirmed. |
| Django shell `current_database(), inet_server_addr(), inet_server_port(), pg_is_in_recovery()` and `pg_stat_activity` | lintechdigitalpoint, 127.0.0.1, 5432, false; only local connection. |
| Python source edits; `ruff format` on changed Python files; `ruff check server` | Confirmed manifest quantity 18; tests use real manifest; negative test injects 19; dry-run summary expanded. Format/lint pass. |
| `../.venv/bin/pytest apps/core/tests/test_shop_inventory.py -q` from server, before reset | 21 passed. |
| `.venv/bin/python server/manage.py shell -c 'exec(open("/tmp/lintech_reset_local.py").read())'` | Rechecked target, backed up, flushed, migrated, seeded base and verified clean counts. |
| `pg_dump --format=custom --no-password` with connection supplied through subprocess environment | Backup completed. Credentials were not placed in arguments or output. |
| `pg_restore --list <backup>` | Archive list verified before reset. |
| `flush --no-input` via `call_command('flush', interactive=False)` | All old application records cleared; 37 migration rows unchanged. |
| `migrate` via `call_command` | No pending migrations. |
| `seed_initial` via `call_command` | Store, six roles and permissions recreated. No sample seeder run on this database. |
| `cd server && ../.venv/bin/python manage.py createsuperuser` | Delegated to user's interactive terminal; one recreated active superuser subsequently verified. |
| `.venv/bin/python server/manage.py setup_shop_layout` | Exact Zone A created. |
| `.venv/bin/python server/manage.py shell -c 'exec(open("/tmp/lintech_receive_verify.py").read())'` | Dry-run, reception and second-run snapshot checks passed. Final API check initially referenced nonexistent `/inventory/lots/` and stopped at that assertion. Reception had succeeded. |
| `seed_shop_inventory --dry-run` via `call_command` | 14 lines, 18 units, KSh 5,190; six valid locations; no records committed. |
| `seed_shop_inventory` via `call_command`, twice | First received; second already present, no records changed. |
| `.venv/bin/python server/manage.py shell -c 'exec(open("/tmp/lintech_verify_final.py").read())'` | Read-only final verification passed using actual `/inventory/receipts/` endpoint; no reception repeated. |
| `.venv/bin/python server/manage.py check` | No issues. |
| `.venv/bin/python server/manage.py makemigrations --check --dry-run` | No changes detected. |
| `../.venv/bin/pytest apps/core/tests/test_shop_inventory.py -q` from server, after strengthened snapshot assertions | 21 passed. |
| `../.venv/bin/pytest -q` from server | 77 passed; 17 warnings about missing staticfiles directory. Sample fixtures exist only in the isolated test database. |
| `npm test -- src/components/PhysicalLocationPicker.test.jsx` from client | Passed; rerun after extending coverage to all six selector labels also passed. |
| Same npm command once from repository root | Failed because package.json is in client; rerun from client. No application changes from the failed command. |
| Expanded selector test with a fixed-value mock | Failed when changing levels because the mock did not update the controlled value; replaced it with a stateful test harness matching application usage. |
| `npm run lint` from client | Passed after the corrected selector test. |
| Final Django shell user counts, other business-model counts, migration-history count | One active administrator; 37 migration rows; no old business records; two new empty session carts. |
| `git diff --stat`, `git diff --check`, `git status --short`, `git log -1`; final `ruff check server` | No whitespace errors; Ruff passed; inspected concurrent working-tree state without reverting it. |

## Source changes for this task

- `server/apps/core/shop_stock.py`: confirmed expected quantity 18.
- `server/apps/core/management/commands/seed_shop_inventory.py`: totals and validated
  locations in reception/dry-run output; explicit rollback notice.
- `server/apps/core/tests/test_shop_inventory.py`: unmodified production manifest in
  successful fixtures; deliberate 19-unit failure; snapshots prove atomic rejection
  and unchanged dry-run records.
- `client/src/components/PhysicalLocationPicker.test.jsx`: checks all six selector labels.
- `docs/real-shop-inventory.md`: confirmed receipt totals and local reset workflow.
- This execution report.

Some source changes were committed concurrently during this session; this task
made no git commits and did not revert concurrent work.
