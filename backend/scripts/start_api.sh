#!/bin/sh
set -eu

# Optionally run migrations here for non-compose deployments.
if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
  alembic upgrade head
fi

# Optional demo bootstrap for first-start environments. Runs in the background
# and exits quickly on restarts once workspaces already exist.
if [ "${AUTO_SEED_DEMO:-false}" = "true" ]; then
  echo "DEMO_SEED_STATUS=launcher_started"
  python scripts/auto_seed_demo.py &
fi

RELOAD_ARGS=""
if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
  RELOAD_ARGS="--reload"
fi

exec sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} ${RELOAD_ARGS}"
