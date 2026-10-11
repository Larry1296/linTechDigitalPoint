#!/usr/bin/env bash
# Copies this computer's database and uploaded files (logos, product photos) to the live server, once, when going
# live with the records already kept locally. It REPLACES the live database, so it asks first.
#   deploy/copy-local-data.sh deploy@YOUR_DROPLET_IP
# Needs pg_dump locally (the same PostgreSQL major version or newer than the local server) and the site already
# deployed once (the containers exist).
set -euo pipefail

TARGET="${1:?Usage: deploy/copy-local-data.sh deploy@SERVER}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/server/.env"
value() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2-; }

DB_NAME="$(value DB_NAME)"; DB_USER="$(value DB_USER)"; DB_HOST="$(value DB_HOST)"; DB_PORT="$(value DB_PORT)"
export PGPASSWORD="$(value DB_PASSWORD)"
DUMP="$(mktemp -d)/local.dump"

echo "This replaces EVERYTHING in the live database at $TARGET with this computer's database ($DB_NAME)."
read -r -p "Type the server address again to go on: " CONFIRM
[ "$CONFIRM" = "${TARGET#*@}" ] || { echo "Stopped: nothing was changed."; exit 1; }

echo "== Saving the local database"
pg_dump -Fc --no-owner --no-privileges -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" -f "$DUMP"

echo "== Sending it to the server"
scp "$DUMP" "$TARGET:/tmp/local.dump"

echo "== Replacing the live database (the site is down for a moment)"
ssh "$TARGET" 'bash -s' <<'SCRIPT'
set -euo pipefail
cd /opt/lintech
set -a; . ./.env; set +a
docker compose stop app
docker compose cp /tmp/local.dump db:/tmp/local.dump
docker compose exec -T db dropdb -U "$DB_USER" --if-exists --force "$DB_NAME"
docker compose exec -T db createdb -U "$DB_USER" "$DB_NAME"
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges /tmp/local.dump
docker compose exec -T db rm /tmp/local.dump
rm /tmp/local.dump
docker compose up -d app
SCRIPT

if [ -d "$ROOT/server/media" ]; then
  echo "== Copying uploaded files (logos, product photos)"
  sleep 10
  tar -C "$ROOT/server/media" -czf - . | ssh "$TARGET" "cd /opt/lintech && docker compose exec -T app tar -xzf - -C /app/media"
fi

rm -f "$DUMP"
echo "Done. The live site now has this computer's records."
echo "Businesses' saved M-Pesa keys only carry over if FIELD_ENCRYPTION_KEY (or SECRET_KEY, when it is empty) is the same"
echo "on the server as here; otherwise owners enter them again in Settings → M-Pesa payments."
