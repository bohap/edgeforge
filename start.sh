#!/usr/bin/env bash
# Start EdgeForge locally: database, dependencies, migrations, web build, then the server.
#
#   ./start.sh                 # http://127.0.0.1:8000
#   ./start.sh --port 9000     # extra arguments go to `edgeforge serve`
#
# Safe to run every time: each step is skipped or quick when nothing changed.
set -euo pipefail

cd "$(dirname "$0")"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mError:\033[0m %s\n' "$1" >&2; exit 1; }

command -v uv >/dev/null || fail "uv is not installed: https://docs.astral.sh/uv/"
command -v npm >/dev/null || fail "Node.js is not installed (version 24 or newer)."
node_major=$(node -p 'process.versions.node.split(".")[0]')
[ "$node_major" -ge 24 ] || fail "Node.js 24 or newer is needed, found $(node --version)."

# Readable logs in the terminal, unless .env or the environment chose a format.
if [ -z "${EDGEFORGE_LOG_FORMAT:-}" ] && ! grep -qs '^EDGEFORGE_LOG_FORMAT=' .env; then
  export EDGEFORGE_LOG_FORMAT=console
fi

step "Python dependencies"
uv sync --quiet

db_reachable() {
  uv run --quiet python - <<'EOF'
import sys

from sqlalchemy import text

from edgeforge.core.config import get_settings
from edgeforge.core.db import create_db_engine

engine = create_db_engine(get_settings(), connect_args={"connect_timeout": 3})
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as exc:
    print(f"  {type(exc).__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
    sys.exit(1)
EOF
}

step "Database"
if ! db_reachable; then
  command -v docker >/dev/null \
    || fail "Cannot reach the database and Docker is not installed. Start PostgreSQL or set EDGEFORGE_DATABASE_URL in .env."
  echo "  Starting PostgreSQL with docker compose..."
  docker compose up -d --wait db \
    || fail "docker compose could not start the database (is Docker running? is port ${EDGEFORGE_DB_PORT:-5432} free?)"
  db_reachable || fail "PostgreSQL is running but not reachable with EDGEFORGE_DATABASE_URL."
fi
echo "  Database is reachable."

step "Migrations"
uv run --quiet alembic upgrade head

step "Web app"
# npm ci wipes node_modules, so only run it when the lockfile changed since the last install.
if [ ! -f web/node_modules/.package-lock.json ] \
  || [ web/package-lock.json -nt web/node_modules/.package-lock.json ]; then
  (cd web && npm ci --no-audit --no-fund)
fi
(cd web && npm run --silent build -- --progress=false)

step "Starting EdgeForge (Ctrl-C to stop)"
echo "  Open http://127.0.0.1:8000 (or the --host/--port you passed)."
exec uv run edgeforge serve "$@"
