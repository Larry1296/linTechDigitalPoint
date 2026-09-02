# LinTech Digital Point

LinTech Digital Point is a Django REST Framework and React/TypeScript platform joining the real shop, POS and ecommerce to one PostgreSQL lot/location inventory ledger.

## Architecture

    Storefront / Customer / Staff React routes
                    |
            session + CSRF API v1
                    |
    accounts | catalog | inventory | commerce
                    |
       transactional service layer
                    |
              PostgreSQL

Stock remains in cost-bearing lots and physical shelf balances. Transfers conserve total stock. POS consumes FIFO unreserved stock. Ecommerce checkout reserves exact lot/shelf allocations; payment completion consumes those same allocations exactly once. Public serializers never include buying price, lots, COGS, profit, suppliers or shelf locations.

## Requirements and PostgreSQL

Use Python 3.12+, Node 22+, npm and PostgreSQL 16+. No SQLite fallback exists.

Create an application database/role, then copy .env.example to .env and set the PostgreSQL variables plus a strong DJANGO_SECRET_KEY. The local development database name is lintech_digital_point.

## Initial setup

From the project root:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r backend/requirements.txt
    cd backend
    python manage.py migrate
    python manage.py seed_initial
    python manage.py create_owner

create_owner interactively requests username, email, display name and validated password. It safely creates or repairs the Store, zones, roles and permissions. Existing intended owners keep their password unless explicitly confirmed. Normal createsuperuser remains available. bootstrap_owner is a compatibility alias.

## Run and URLs

Backend: activate .venv, enter backend, then run python manage.py runserver.

Frontend: enter frontend, run npm ci, then npm run dev.

- Storefront: http://localhost:5173/
- Customer login/register: http://localhost:5173/login and /register
- Staff login: http://localhost:5173/staff/login
- Staff application: http://localhost:5173/admin-app/dashboard
- POS: http://localhost:5173/admin-app/pos
- Digital Shop: http://localhost:5173/admin-app/digital-shop
- Django Admin: http://localhost:8000/admin/
- Swagger: http://localhost:8000/api/docs/

Vite proxies /api to Django.

## Workflows

Customers browse and maintain an anonymous server-side cart. Login or registration preserves it across session rotation. Checkout requires authentication, freezes server prices, creates an order and reserves exact inventory. Account routes expose only the signed-in customer's profile, addresses and orders.

Staff use the separate staff login. Backend permissions protect every internal API. POS supports barcode/SKU/text search, shelf pick locations, products/services, permitted discounts, payments and printable receipts. Online fulfillment displays reserved picks and consumes them idempotently.

Digital Shop starts with real zones but no fake shelves. Configure existing walls and unequal shelves with persisted geometry. Permanent codes use a locked allocator. Shelf changes write ShelfHistory and AuditLog. Receiving requires physical placement.

Cash, bank, manual M-Pesa, other and cash-on-pickup states work locally. Live Daraja requires external credentials and a public HTTPS callback.

## Quality

Backend: ruff check, manage.py check, makemigrations --check, and pytest from backend using ../.venv.

Frontend: npm run lint, npm run typecheck, npm test, npm run build, and npm run test:e2e.

Playwright needs Chromium and both dev servers for local E2E. CI provisions PostgreSQL and runs backend/frontend checks.

