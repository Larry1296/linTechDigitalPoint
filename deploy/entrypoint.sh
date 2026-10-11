#!/bin/sh
# Every start of the app: wait for the database, apply new migrations, then run the server.
# Migrations run here (one app container), so a deploy that adds a migration applies it before serving.
set -e

until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER}" -q; do
  echo "Waiting for the database..."
  sleep 2
done

python manage.py migrate --noinput

exec "$@"
