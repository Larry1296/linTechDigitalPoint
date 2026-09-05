# LinTech Digital Point

LinTech Digital Point is a Django REST Framework and React/TypeScript platform for three related business units: Retail/Ecommerce, Cyber Services, and M-Pesa Agency operations. Its Digital Shop is a digital twin of the real hierarchy: Zone → Shelf Stack → Level → Shelf → Stock. Django sessions and CSRF protect the API; anonymous server-side carts are adopted after login or registration.

## Project structure

```text
client/   React + TypeScript application
server/   Django application and top-level API composition
docs/     Architecture and feature documentation
scripts/  Development bootstrap utilities
```

The Python virtual environment and application configuration are different things: `.venv/` is the local Python environment directory, while `.env` is the root configuration text file. Both are ignored by Git. `.env.example` is the committed, secret-free template.

## Runtime requirements

- Python 3.13 (declared in `.python-version`)
- Node.js 22 or newer and npm
- PostgreSQL 16 or newer
- PostgreSQL client tools, including `pg_isready`

LinTech is PostgreSQL-only during normal runtime; there is no SQLite fallback.

## Environment setup

From the project root:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```

Set a strong `SECRET_KEY` and local database password in `.env`. Never commit this file and never place it inside `.venv/`. Browser-visible Vite variables must not contain server secrets or Daraja credentials.

If upgrading an existing environment from the former dependency set:

```bash
source .venv/bin/activate
pip uninstall -y python-dotenv
pip install -r server/requirements.txt
```

## PostgreSQL setup

Create the development role and database using your PostgreSQL administration workflow:

```sql
CREATE ROLE lintech WITH LOGIN PASSWORD 'your-local-password';
CREATE DATABASE lintech_digital_point OWNER lintech;
```

Store the password only in `.env`. The standard connection is:

```env
DB_NAME=lintech_digital_point
DB_USER=lintech
DB_PASSWORD=your-local-password
DB_HOST=localhost
DB_PORT=5432
```

Confirm PostgreSQL is ready before Django setup:

```bash
pg_isready -h localhost -p 5432
```

## Server setup and Owner/Admin creation

With `.venv` activated:

```bash
cd server
python manage.py migrate
python manage.py seed_initial
python manage.py createsuperuser
python manage.py check
```

Django's standard `createsuperuser` command interactively requests the administrator credentials. The Django superuser is the LinTech Owner/Admin: the same account has unrestricted access to Django Admin at `/admin/` and the LinTech administrative application through the shared `/login` page. `seed_initial` creates only the Store, staff/customer groups, and their permissions; it never creates users, zones, or sample shelving. Physical areas are defined freely in Digital Shop using the real shop's names and dimensions.

On an existing installation, any account previously provisioned with `is_superuser=True` remains a valid Owner/Admin. Do not create a second account unless another true system administrator is deliberately required.

## Client setup

In a second terminal:

```bash
cd client
npm install
npm run dev
```

Vite proxies `/api` to Django at `http://127.0.0.1:8000`.

## Running the system

Server:

```bash
source .venv/bin/activate
cd server
python manage.py runserver
```

Client:

```bash
cd client
npm run dev
```

Useful URLs:

- Storefront: http://localhost:5173/
- Shared customer/staff login: http://localhost:5173/login
- Customer registration: http://localhost:5173/register
- Customer account: http://localhost:5173/account
- Staff dashboard: http://localhost:5173/admin-app/dashboard
- POS: http://localhost:5173/admin-app/pos
- Cyber Desk: http://localhost:5173/admin-app/cyber
- M-Pesa Agent Desk: http://localhost:5173/admin-app/mpesa
- Digital Shop: http://localhost:5173/admin-app/digital-shop
- Django Admin: http://localhost:8000/admin/
- Swagger API docs: http://localhost:8000/api/docs/

Customers can browse and maintain an anonymous cart, then log in or register during checkout without losing it. Customers and staff share `/login`; role-aware routing sends each account to an authorized destination.

## Business domains and accounting boundaries

Retail and ecommerce stock items use the existing Product → Sale → Payment workflow and FIFO inventory allocation. Genuine billable services remain `Product.product_type=SERVICE`; `ecommerce_visible` controls whether a product/service is shown publicly, while `online_orderable` separately controls whether it can enter the online cart.

Cyber adds service configuration, job lines, job states, and counter checkout. Configure a `CyberServiceProfile` against an existing SERVICE variant and set its billing unit and visibility. A job moves through queued, in-progress, waiting-customer, ready, and completed states. Quick services use the same job ledger with a short workflow. Financial completion atomically creates exactly one Commerce `Sale` with `channel=CYBER` and one Commerce `Payment`, producing the Cyber receipt number. Customer document contents are not stored; never enter passwords, PINs, OTPs, or other credentials in job metadata.

Optional `ServiceMaterialRequirement` rows consume measurable STOCK_ITEM materials (paper, pouches, binding combs) through FIFO at job completion. When at least one material requirement is configured, actual material cost is Cyber COGS and `service_cost` is not added. When no materials are configured, `ProductVariant.service_cost × billable quantity` is the fallback cost. This prevents double-counting.

M-Pesa Agency is a separate append-only operational ledger. An operator opens an outlet shift with physical cash and electronic float, posts deposits or withdrawals, and closes it with expected-versus-actual reconciliation. Deposits increase cash and decrease float; withdrawals decrease cash and increase float. The backend computes these effects under database locks, prevents negative balances, rejects duplicate provider references, and uses idempotency keys. Errors are corrected by a reversing entry; originals remain in history. Float top-ups, rebalances, adjustments, reversals, and commission entry are restricted operational actions.

`Payment.method=MPESA` means an M-Pesa payment for a LinTech retail, ecommerce, or Cyber sale. It does not create an agency ledger entry. M-Pesa agency deposits and withdrawals are `MpesaTransaction` records, are not Commerce sales, and their principal is never business revenue. Only separately recognized `MpesaCommissionEntry` amounts contribute to total revenue. M-Pesa cash/float and transaction volume are reported separately from retail cash, stock, and revenue.

Run `python manage.py seed_initial` after migrating to provision/update the Manager, Cyber Operator, and M-Pesa Operator permission groups. The command creates structural roles only and never creates sample prices, jobs, outlet balances, or customer transactions. Configure real outlets and service profiles through the protected application/API or Django Admin.

API namespaces:

- `/api/v1/cyber/services/`, `/jobs/`, `/materials/`, and `/dashboard/`
- `/api/v1/mpesa/outlets/`, `/sessions/`, `/transactions/`, `/reconciliation/`, `/commission/`, and `/dashboard/`

M-Pesa APIs require authenticated staff permissions. Only the Cyber advertised-service listing is public; no operational queue, customer metadata, COGS, cash, float, commission, or agency ledger data is exposed on the public website.

## Tests and quality checks

Server:

```bash
cd server
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
ruff check .
```

Client:

```bash
cd client
npm run lint
npm run typecheck
npm test
npm run build
```

End-to-end tests require PostgreSQL plus both development servers:

```bash
cd client
npm run test:e2e
```

CI provisions PostgreSQL and runs the server, client, and Playwright checks using the same `server`/`client` paths.

## Automated bootstrap

After creating the PostgreSQL role/database and configuring `.env`:

```bash
./scripts/bootstrap.sh
```

The script verifies PostgreSQL readiness, installs dependencies, migrates and seeds Django, checks Django, and builds the client. It does not create an administrator. After it completes, deliberately create the Owner/Admin interactively if one does not already exist:

```bash
cd server
python manage.py createsuperuser
```

That one account signs into both administrative interfaces:

- Django system administration: http://localhost:8000/admin/
- Everyday LinTech administration: http://localhost:5173/login → `/admin-app/dashboard`
