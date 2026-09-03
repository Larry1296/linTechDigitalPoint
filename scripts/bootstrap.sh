#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
test -f .env || cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
command -v pg_isready >/dev/null || { echo "PostgreSQL client tools are required (pg_isready not found)."; exit 1; }
if ! pg_isready -h localhost -p 5432 >/dev/null; then
  echo "PostgreSQL is not ready at localhost:5432. Start it or override DB_HOST/DB_PORT in .env."
  exit 1
fi
cd server
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_initial
../.venv/bin/python manage.py create_owner --noinput
../.venv/bin/python manage.py check
cd ../client
npm install
npm run build
echo "LinTech Digital Point is ready."
