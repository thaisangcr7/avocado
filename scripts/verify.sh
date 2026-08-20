#!/usr/bin/env bash
#
# Every gate CI runs, in the same order, locally.
#
# Exists because "commit, then discover CI is red" happened three times in a
# row. `set -e` matters here: chaining checks with && and echoing a tick lets a
# failure scroll past unnoticed, which is exactly how those red commits
# happened.
#
#   ./scripts/verify.sh          # everything
#   ./scripts/verify.sh --quick  # skip the slow integration suite
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

if [ "$QUICK" != "--quick" ]; then
  step "backend: tests"
  (cd backend && .venv/bin/python -m pytest tests/ -q)
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
