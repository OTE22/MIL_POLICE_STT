#!/bin/sh
set -eu

# Wait for PostgreSQL, then apply Alembic migrations before serving.
python - <<'PY'
import os, sys, time
import psycopg
url = os.environ.get("CENTRAL_DATABASE_URL", "postgresql+psycopg://stt:stt@postgres:5432/military_stt")
dsn = url.replace("postgresql+psycopg://", "postgresql://")
for attempt in range(60):
    try:
        psycopg.connect(dsn, connect_timeout=3).close()
        print("database reachable", flush=True)
        sys.exit(0)
    except Exception as exc:
        print(f"waiting for database ({attempt+1}/60): {exc}", flush=True)
        time.sleep(2)
sys.exit(1)
PY

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
  alembic upgrade head
fi

exec "$@"
