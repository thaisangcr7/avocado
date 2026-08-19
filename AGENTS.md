# Avocado — Agent Instructions

Multi-tenant AI copilot: multimodal ingestion (docs, images, spreadsheets), a sandboxed
code-execution analysis engine for real data analysis, RAG-based Q&A, and voice query.
Full architecture, data model, and phased roadmap: `docs/architecture.md`.

## Stack
FastAPI (Python 3.12) + SQLAlchemy 2.0 + PostgreSQL/pgvector. React + TypeScript + Vite +
Tailwind. Docker for local and cloud parity (same image, env-based config).

## Architecture rules — non-negotiable
- Routers stay thin: parse request, call one service method, return response. No business
  logic, no direct ORM access in a router.
- All DB access goes through `repositories/` — services never import SQLAlchemy directly.
- Every query is scoped by `workspace_id`, filtered at the repository layer. Never trust a
  client-supplied ID alone.
- Request/response schemas are Pydantic DTOs, separate from ORM models. Never return an ORM
  model directly from an endpoint.
- New LLM or storage providers are added as an adapter under `clients/`, behind the existing
  interface — never called directly from a service.

## Build & test
- `docker-compose up` — local stack (Postgres+pgvector, Redis, API, web)
- Backend tests: `pytest backend/tests`
- Frontend tests: `npm test` (run from `frontend/`)
- Lint before every commit: `ruff check backend/` and `npm run lint` (from `frontend/`)

## Security — do not weaken without discussion
- The analysis sandbox has no network access, a hard timeout, and resource caps, on every
  code-execution path, no exceptions.
- No secrets in code or commits — environment variables only.
- Any new query path that crosses tenant/workspace boundaries needs an isolation test before
  merge, not after.

## Git / commits
- All commits are authored as Sang Thai. Do not add `Co-Authored-By` or "Generated with
  [tool]" trailers to commit messages or PR descriptions.
- Conventional commit style: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`.
- Small, phase-scoped commits — avoid large multi-concern drops.

## Build order
Follow the phased roadmap in `docs/architecture.md`: foundation → ingestion/analysis MVP →
voice/multi-model → multi-tenant → connectors. Don't build later-phase features (external
connectors, multi-tenant RBAC) ahead of the current phase without asking.
