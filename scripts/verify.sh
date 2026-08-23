#!/usr/bin/env bash
#
# Every gate CI runs, in the same order, locally.
#
# Exists because "commit, then discover CI is red" happened three times in a
# row. `set -e` matters here: chaining checks with && and echoing a tick lets a
# failure scroll past unnoticed, which is exactly how those red commits
# happened.
#
#   ./scripts/verify.sh          # everything, before a commit or a push
#   ./scripts/verify.sh --quick  # the inner loop: skips only the Docker tests
#
# --quick used to skip the backend suite entirely, which made it useless as a
# pre-commit check and meant the full run got used for everything. It now runs
# every backend test except the ones needing a Docker daemon — those are the
# slowest by a wide margin and only matter when the sandbox changes.
set -euo pipefail

cd "$(dirname "$0")/.."
QUICK="${1:-}"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "backend: ruff check"
backend/.venv/bin/ruff check backend/

step "backend: ruff format"
backend/.venv/bin/ruff format --check backend/

step "backend: migrations match models"
(cd backend && .venv/bin/alembic check)

# Split across cores: the suite waits on Postgres and Docker far more than it
# computes, so wall time falls with workers. Each worker gets its own database
# (see tests/conftest.py) — they would otherwise truncate tables under each
# other, which fails only under load and never reproduces alone.
if [ "$QUICK" = "--quick" ]; then
  step "backend: tests (no Docker)"
  (cd backend && .venv/bin/python -m pytest tests/ -q -n auto -m "not docker")
else
  step "backend: tests"
  (cd backend && .venv/bin/python -m pytest tests/ -q -n auto)
fi

step "frontend: eslint"
(cd frontend && npx eslint .)

step "frontend: typecheck"
(cd frontend && npx tsc --noEmit -p tsconfig.app.json)

step "frontend: tests"
(cd frontend && npx vitest run --silent)

step "frontend: build"
(cd frontend && npm run build)

printf '\n\033[32mAll gates passed.\033[0m\n'
