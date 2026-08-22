# Build progress

**Single source of truth for where the parity work stands.** Update this in the
same commit as the work it describes — a tracker that lags the code is worse
than none.

Plan and estimates: [`workspaces-parity.md`](workspaces-parity.md).

---

## Current phase

**Phase A — Artifacts.** Started 2026-08-21.

| Step | State |
|---|---|
| A1 · `artifacts` table + migration | ✅ done |
| A2 · Repository, scoped by workspace | ⬜ not started |
| A3 · Service + resource schemas | ⬜ not started |
| A4 · Endpoints | ⬜ not started |
| A5 · Model emits artifacts | ⬜ not started |
| A6 · Frontend panel (sandboxed iframe) | ⬜ not started |
| A7 · Version history UI | ⬜ not started |

---

## Phase status

| Phase | State |
|---|---|
| A — Artifacts | 🔨 in progress |
| B — Presets and slash commands | ⬜ not started |
| C — History and conversation management | ⬜ not started |
| D — Shell and Spaces polish | ⬜ not started |
| E — Schedules | ⬜ not started |
| F — Collaboration | ⬜ not started |
| G — Enterprise trim | ⬜ not started |

---

## Decisions already made

Recorded so they are not relitigated in a later session.

- **Model-authored HTML renders in a null-origin sandboxed iframe**, never
  `dangerouslySetInnerHTML`. It is untrusted input written by a model from user
  documents; rendering it in the app origin would expose the session token.
- **`workspace_id` keeps its name** whatever the UI calls it. It is load-bearing
  in every repository and every RLS policy.
- **Citations stay.** They are the differentiator; no parity feature is worth
  trading them for.

---

## Conventions this work follows

- Routers stay thin; services orchestrate; repositories own all data access.
- Every query scoped by `workspace_id` at the repository layer.
- Request/response models are resources under `schemas/`, never ORM models.
- Migrations are numbered (`0010_`, `0011_`, …), not hash-named.
- `./scripts/verify.sh` passes before every commit. It runs every CI gate.
- Small, single-concern commits.

---

## Log

Newest first. One line per shipped increment.

- **A1** · `artifacts` table, enums, migration `0011` with its RLS policy. Versions are rows sharing a `lineage_id`, not a mutable column.
