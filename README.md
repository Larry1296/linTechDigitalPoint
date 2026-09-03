# LinTech Digital Point

LinTech Digital Point is a Django REST Framework and React/TypeScript platform for a public storefront, customer accounts, ecommerce, POS, inventory, and business administration. Its Digital Shop is a digital twin of the real hierarchy: Zone → Shelf Stack → Level → Shelf → Stock. Django sessions and CSRF protect the API; anonymous server-side carts are adopted after login or registration.

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

Django's standard `createsuperuser` command interactively requests the administrator credentials. The Django superuser is the LinTech Owner/Admin: the same account has unrestricted access to Django Admin at `/admin/` and the LinTech administrative application through the shared `/login` page. `seed_initial` creates only the Store, zones, staff/customer groups, and their permissions; it never creates a user.

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
- Digital Shop: http://localhost:5173/admin-app/digital-shop
- Django Admin: http://localhost:8000/admin/
- Swagger API docs: http://localhost:8000/api/docs/

Customers can browse and maintain an anonymous cart, then log in or register during checkout without losing it. Customers and staff share `/login`; role-aware routing sends each account to an authorized destination.

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
