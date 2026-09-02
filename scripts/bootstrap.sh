#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
test -f .env || cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
command -v psql >/dev/null || { echo "PostgreSQL client required"; exit 1; }
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_initial
../.venv/bin/python manage.py bootstrap_owner
cd ../frontend
npm install
npm run build
echo "LinTech Digital Point is ready."

