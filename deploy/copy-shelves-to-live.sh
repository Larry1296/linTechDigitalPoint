#!/usr/bin/env bash
# Makes the live site's shelves exactly the same as on this computer: the same walls, racks, levels and compartments
# (codes, labels, sizes, rack categories). Every other shelf place the business has on live is removed. Run from WSL:
#   deploy/copy-shelves-to-live.sh                       # the business LinTechDigitalPoint
#   deploy/copy-shelves-to-live.sh "Business name"       # another business (the same name locally and on live)
# It asks for the live database's External Database URL (Render: the database → Connect → External) and never saves it;
# or set LIVE_DATABASE_URL beforehand. LIVE_BUSINESS / LIVE_BRANCH name the business or branch on live when they differ.
# It shows every change first and asks before saving. A shelf on live that holds stock or appears in sales or receipts
# is never removed: then nothing at all is changed, and it says which ones.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/server"
PYTHON="$ROOT/server/venv/bin/python"
BUSINESS="${1:-LinTechDigitalPoint}"
LIVE_BUSINESS="${LIVE_BUSINESS:-$BUSINESS}"
BRANCH_ARGS=()
[ -n "${LIVE_BRANCH:-}" ] && BRANCH_ARGS=(--branch "$LIVE_BRANCH")
LAYOUT="$(mktemp --suffix=.json)"
trap 'rm -f "$LAYOUT"' EXIT

echo "Reading the shelves of $BUSINESS on this computer…"
"$PYTHON" manage.py export_shelf_layout "$BUSINESS" "$LAYOUT"

URL="${LIVE_DATABASE_URL:-}"
if [ -z "$URL" ]; then
  read -r -s -p "Paste the live database's External Database URL (hidden, not saved): " URL
  echo
fi
# The live database settings replace this computer's for the commands below (environment beats server/.env).
eval "$("$PYTHON" -I - "$URL" <<'PY'
import shlex, sys
from urllib.parse import unquote, urlsplit
url = urlsplit(sys.argv[1].strip())
if url.scheme not in ("postgres", "postgresql") or not url.hostname or not url.path.strip("/"):
    sys.exit("That is not a database URL: it should look like postgresql://user:password@host/name")
for key, value in {"DB_HOST": url.hostname, "DB_PORT": str(url.port or 5432), "DB_NAME": unquote(url.path.lstrip("/")),
                   "DB_USER": unquote(url.username or ""), "DB_PASSWORD": unquote(url.password or "")}.items():
    print(f"export {key}={shlex.quote(value)}")
PY
)"
export PGSSLMODE="${PGSSLMODE:-require}" PGCONNECT_TIMEOUT=20
unset URL LIVE_DATABASE_URL

echo
echo "On the live site ($DB_HOST), $LIVE_BUSINESS's shelves would change like this:"
"$PYTHON" manage.py import_shelf_layout "$LIVE_BUSINESS" "$LAYOUT" --replace --dry-run "${BRANCH_ARGS[@]}"
echo
read -r -p "Type YES to make these changes on the live site: " CONFIRM
[ "$CONFIRM" = "YES" ] || { echo "Stopped: nothing was changed."; exit 1; }
"$PYTHON" manage.py import_shelf_layout "$LIVE_BUSINESS" "$LAYOUT" --replace "${BRANCH_ARGS[@]}"
echo "Done: the live site's shelves now match this computer's."
