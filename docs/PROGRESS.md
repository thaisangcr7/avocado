# Build progress

**Single source of truth for where the parity work stands.** Update this in the
same commit as the work it describes — a tracker that lags the code is worse
than none.

Plan and estimates: [`workspaces-parity.md`](workspaces-parity.md).

---

## Current phase

**Phase A — Artifacts.** Complete. Next: Phase B (presets and slash commands).

| Step | State |
|---|---|
| A1 · `artifacts` table + migration | ✅ done |
| A2 · Repository, scoped by workspace | ✅ done |
| A3 · Service + resource schemas | ✅ done |
| A4 · Endpoints | ✅ done |
| A5 · Model emits artifacts | ✅ done |
| A6 · Frontend panel (sandboxed iframe) | ✅ done |
| A7 · Version history UI | ✅ done |

---

## Phase status

| Phase | State |
|---|---|
| A — Artifacts | ✅ done |
| B — Presets and slash commands | 🔨 next |
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

- **A5** · A successful analysis keeps its program as a `code` artifact, best-effort so a computation cannot fail over a panel entry. `POST /artifacts/generate` has the model author a document, which does raise on failure since it was asked for explicitly. Verified live: Opus 5 wrote a 3.2KB self-contained dashboard using the supplied figures and inventing none.
- **A6–A7** · `ArtifactFrame` renders model HTML in a null-origin sandboxed iframe with a `default-src 'none'` policy; `ArtifactPanel` adds the version picker, source toggle and download. Six tests assert the sandbox, verified by confirming they fail when `allow-same-origin` is added.
- **A2–A4** · Repository, service, resources and four endpoints. Listing returns the newest version of each artifact, not every version. HTML downloads as an attachment with `nosniff`, never as `text/html`. 19 tests including cross-tenant reads, writes and the database policy.
- **A1** · `artifacts` table, enums, migration `0011` with its RLS policy. Versions are rows sharing a `lineage_id`, not a mutable column.
