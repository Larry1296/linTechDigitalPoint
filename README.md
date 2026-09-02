# LinTech Digital Point

A Django/React business platform whose inventory mirrors the real shop: every stocked unit belongs to a cost lot and a physical shelf. POS and ecommerce share the same balances and reservations.

## Architecture

    React + TypeScript -> session/CSRF DRF API -> transactional services -> PostgreSQL
                                                        |-> immutable movement ledger
                                                        |-> lots and shelf balances

The backend is split into core, catalog, inventory, and commerce. Stock writes happen through atomic services; FIFO allocations freeze historical COGS. Public serializers expose price and availability but never costs or shelf locations. The responsive frontend includes System/Light/Dark themes and a geometry-driven Digital Shop.

## Setup

Requirements: Python 3.12+, Node 22+, npm, PostgreSQL 16+.

1. Copy `.env.example` to `.env` and configure PostgreSQL plus a strong secret.
2. Create database `lintech_digital_point` and its dedicated role.
3. Run `./scripts/bootstrap.sh`.
4. Set `OWNER_PASSWORD` temporarily if desired. Otherwise bootstrap prints a generated password once.

Backend: activate `.venv`, enter `backend`, run `python manage.py migrate`, `python manage.py seed_initial`, `python manage.py bootstrap_owner`, then `python manage.py runserver`.

Frontend: enter `frontend`, run `npm ci`, then `npm run dev`.

URLs: storefront/admin http://localhost:5173; API http://localhost:8000/api/v1/; Swagger http://localhost:8000/api/docs/; Django Admin http://localhost:8000/admin/. Vite proxies `/api` to Django.

## Quality

Backend: `cd backend && ../.venv/bin/ruff check . && ../.venv/bin/pytest`

Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`

## Core behavior

Zones and shelves use real configurable dimensions. Shelf codes are permanent while names can change. Products can span shelves/lots. Transfers conserve total quantity. FIFO sales create immutable cost allocations. Online reservations reduce availability without creating separate ecommerce stock. Initial setup creates the store, five zones and roles, but no fictional shelves.

Cash, manual M-Pesa, bank, other, and cash-on-pickup records work locally. Live Daraja credentials are optional secrets; live service cannot be asserted until credentials and public callback hosting exist.

See `docs/` for architecture, invariants, Digital Shop, API and deployment guidance.

