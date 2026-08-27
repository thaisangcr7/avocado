# Avocado 🥑

**One-line definition:** Avocado is a workspace-grounded AI copilot for team knowledge and data analysis: it answers with citations from your files and can run sandboxed code to produce real computed reports.

**Team knowledge & analysis copilot.** Upload documents, spreadsheets and images
into a workspace, then ask questions and get answers that are either *cited* —
grounded in the actual text, with the source shown — or *computed*, by writing
and running real code against your data in an isolated sandbox.

## 30-second pitch

Most AI chat tools paraphrase text they retrieve. Avocado goes one step further:
it combines grounded retrieval with a safe analysis runtime. For document
questions, it returns cited answers tied to workspace sources. For spreadsheet
questions, it writes and executes analysis code in a locked-down sandbox and
returns the computed result, plus the program that produced it. The result is a
team copilot that is both explainable (citations) and verifiable (computed
outputs).

The distinction matters. Most "chat with your documents" tools retrieve a
paragraph and paraphrase it. Avocado does that too, but when the question is
analytical ("what's the month-over-month trend by region?") it writes pandas,
runs it, and returns both the number and the program that produced it.

Full design: [`docs/architecture.md`](docs/architecture.md). Feature roadmap
toward workspace-platform parity — artifacts, presets, schedules, collaboration —
with effort estimates: [`docs/workspaces-parity.md`](docs/workspaces-parity.md).

---

## How it works — and why not just a Claude or ChatGPT chat

Avocado is **powered by Claude**, not a competitor to it. The model is the
engine; Avocado is the governed workspace built around it. A raw chat window
cannot be all four of these at once:

1. **Grounded, not guessed.** Ask an analytical question and Avocado writes
   pandas, runs it in a locked-down sandbox over the *entire* dataset, and
   returns computed numbers plus the program that produced them. A chat eyeballs
   whatever fits in its context; every figure Avocado reports traces to a real
   computation.
2. **A team's shared memory, not a stateless session.** Ingest documents and
   spreadsheets once; the whole team queries them and answers cite their
   sources. A chat forgets your files between sessions and serves one person.
3. **Your data, isolated and governed.** Every query is scoped to a workspace
   with row-level tenant isolation; generated code runs with no network and hard
   resource caps; that code is inspectable. This is what lets a team point an
   LLM at internal data without hand-wringing.
4. **A product, not a prompt.** Auth, workspaces, streaming answers, persisted
   dashboard artifacts, voice, and connectors — something a team adopts, not a
   transcript you copy-paste and reformat.

**Where the honest line is:** for one person pasting a single CSV, a Claude or
ChatGPT chat is often enough. Avocado is for a *team* that wants a governed,
multi-tenant workspace over *its own* data — grounded answers everyone shares,
auditable analysis, and a memory that outlives the session.

### The three ways to ask

- **Cited retrieval** — "What's our remote-work policy?" → an answer assembled
  from the actual documents, with the sources shown.
- **Single-file analysis** — "What's the month-over-month revenue trend?" →
  generated pandas runs in the sandbox; you get the number *and* the code.
- **Whole-workspace executive report** — "Give me an executive summary" →
  Avocado computes KPIs, trends and breakdowns across *every* spreadsheet in the
  workspace and renders a multi-section dashboard: a KPI strip, per-theme
  narrative with a status (on course / watch / off course), charts, and an
  honest limits note. Every headline number comes from a computation, not the
  model's phrasing.

---

## See it working

Five commands from a clean checkout to a workspace full of documents you can
interrogate. Requires Docker and an `ANTHROPIC_API_KEY`.

```bash
cp .env.example .env
```

Put a generated `SECRET_KEY`, a generated `SANDBOX_AUTH_TOKEN`, and your
`ANTHROPIC_API_KEY` into `.env` (see [Quick start](#quick-start) for the
generator commands), then:

```bash
docker build -t avocado-sandbox:latest ./sandbox && docker compose up -d
```

```bash
python3 backend/scripts/generate_demo_data.py --reset
```

That prints the login it just created. Open **http://localhost:5173**, sign in,
and pick the **Northwind HQ** workspace.

Or skip the sign-in entirely: **http://localhost:5173/demo** starts a public
demo session on load and opens straight into a workspace. That is the link to
use when showing the app to someone — the first thing they see should be the
product working, not a password field. It needs `PUBLIC_DEMO_ENABLED=true`, and
falls back to the sign-in screen when demo mode is off.

A beat-by-beat script for recording or presenting this:
[`docs/demo-runbook.md`](docs/demo-runbook.md).

Three questions worth asking, in this order:

1. **"What policies does this workspace define?"** — a cited answer assembled
   from several documents at once.
2. **"If I don't use all my paid days off this year, how many roll into next
   year?"** — the source says *"unused balance carries over… up to a cap of
   five days"*. The question shares almost none of those words, so a keyword
   index misses it and a semantic one does not.
3. Switch to the **Northwind Sandbox** workspace and ask anything. It is empty
   on purpose, and the answer says so instead of inventing one.

Then hit **Analyse** on `revenue_by_region.csv` and ask for the month-over-month
trend: the model writes pandas, it runs in a locked-down container, and you get
the number *and* the program that produced it.

Finally, in the **Northwind HQ** chat, ask **"Give me an executive summary of the
whole workspace"** (or "KPI report", or "dashboard"). Avocado profiles every
spreadsheet in the sandbox and renders a computed, multi-section briefing — a
KPI strip, per-theme sections with status badges and charts, and a limits note.
Reload the page and it is still there: the report is saved on the message.

---

## Status

| Phase | Scope | State |
|---|---|---|
| 0 — Foundation | Clean-architecture skeleton, Docker, config, CI, auth | ✅ Done |
| 1 — Ingestion + Analysis | Multimodal upload, RAG Q&A, sandboxed analysis engine, UI | ✅ Done |
| 2 — Voice + multi-model | Deepgram STT, second provider, Auto mode | ✅ Done |
| 3 — Multi-tenant | Org/team/workspace, RBAC, invites | ✅ Done |
| 4 — Team Mastermind | Projects/tasks, suggestions, task resume, knowledge map | ✅ Done |
| 5 — UX polish + scale | First-open UX, report templates, bundle/perf, load test | In progress |

**578 backend tests, 176 frontend tests**, all green in CI on every push.

Workspace-platform parity work (presets, history, schedules, tools over MCP,
artifacts) is tracked separately in [`docs/PROGRESS.md`](docs/PROGRESS.md),
which is the file to read first when picking this up cold.

## Current plan (no-cost, UX-first)

The current execution plan is intentionally **not connector-first**. We can hit
the product goal without additional spend by making first-open UX excellent and
using local/demo data flows already in the project.

### What we are building first

1. **First-open guided experience**
  - A clear "Start with demo data" path.
  - A clear "Upload your files" path.
  - Empty-state chat that explains exactly why grounded answers need data.
2. **Upload-to-insight flow**
  - Strong ingest progress and "ready to ask" cues.
  - Suggested starter questions immediately after ingest.
3. **Report and dashboard actions**
  - One-click prompts for executive summary, KPI report, and trend dashboard narrative.
  - **Shipped:** a whole-workspace executive report — KPIs, trends and breakdowns
    computed across every spreadsheet, rendered as a persisted multi-section
    dashboard with grounded (computed, not model-authored) headline numbers.
4. **Performance polish**
  - Reduce initial bundle cost and speed up perceived first interaction.

### How it will look for a new user

1. User opens Avocado and sees two primary choices:
  - "Start with demo workspace"
  - "Upload my files"
2. If they choose demo:
  - Workspace opens with seeded documents, suggested questions, and one analysis-ready CSV.
3. If they upload:
  - They see file processing status and a "ready" badge when querying is meaningful.
4. In chat:
  - If there is no data, the app explains the limitation and offers next actions.
  - If data is ready, the app suggests concrete questions and report templates.

### Cost stance

- Keep local Docker stack for development.
- Keep folder sync + demo data as the default ingestion path.
- Keep paid connectors (for example, Drive) deferred until UX and adoption goals are met.

---

## Quick start

```bash
cp .env.example .env
```

Generate a secret key and put it in `.env`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Build the analysis sandbox image (the runner shells out to it):

```bash
docker build -t avocado-sandbox:latest ./sandbox
```

Generate the shared secret between the API and the sandbox runner, and put it
in `.env` as `SANDBOX_AUTH_TOKEN`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Bring up the stack:

```bash
docker compose up
```

The API is on `http://localhost:8000` (docs at `/docs`), the web app on
`http://localhost:5173`. Postgres is published on **5434** and Redis on **6380**
to avoid colliding with other instances you may already run; inside the compose
network they use their standard ports.

For deployments, the frontend container reads `AVOCADO_API_BASE_URL` at runtime,
so the same image can point at different API hosts without a rebuild.

To enable answer generation and analysis, set `ANTHROPIC_API_KEY` in `.env`.
Without it, upload and retrieval still work and every generation endpoint
returns a clear error rather than a fabricated answer.

For voice, set `DEEPGRAM_API_KEY` and `STT_PROVIDER=deepgram`. Voice stays off
unless *both* are set, and the client asks `GET /voice/capabilities` before
showing a microphone — so an unconfigured server hides the feature rather than
offering a button that fails when pressed.

### Generate demo data

A seeded dataset exists so the app can be evaluated without hunting for
documents to upload. It is created through the public API, exactly as a user
would, rather than written into the database behind the app's back.

`--reset` truncates every table in the local Postgres first, so the seed is
reproducible rather than additive. **It deletes any account you created by
hand**, so leave it off if you have local work you want to keep:

```bash
python3 backend/scripts/generate_demo_data.py          # add to what is there
python3 backend/scripts/generate_demo_data.py --reset  # wipe first
python3 backend/scripts/generate_demo_data.py --skip-if-workspaces-exist
```

**Where it lands.** The generated files and a manifest are written to
`backend/.demo-data/latest/` — gitignored, because it is output, not source:

```
backend/.demo-data/latest/
├── manifest.json              ← workspace ids, and the login it created
├── northwind-hq/documents/    ← policies, meeting notes, 5 spreadsheets
└── northwind-finance/documents/
```

The **credentials are in `manifest.json`** under `owner.email` and
`owner.password`, regenerated on every seed:

```bash
python3 -c "import json;m=json.load(open('backend/.demo-data/latest/manifest.json'));print(m['owner']['email'])"
```

**What it creates.** One organization, one team, two collaborators, projects
and tasks, and three workspaces:

| Workspace | Contents | What it demonstrates |
|---|---|---|
| Northwind HQ | Policies, meeting notes, 5 generated spreadsheets, and one real 110k-row dataset | Cited retrieval and sandboxed analysis over genuine data |
| Northwind Finance | Budget and forecast data | A second tenant with its own documents |
| Northwind Sandbox | Nothing, deliberately | The honest "not in these sources" answer |

Most documents are templated filler — enough to exercise ingestion, not enough
to show retrieval understanding meaning. `time-off-policy.md` and
`expense-policy.md` are real prose with specific figures, and exist so a
paraphrased question has something genuine to match against.

The spreadsheets are generated too, with one exception. `northwind_orders.csv`
in Northwind HQ is **real data**: 110,064 order lines across 2021 and 2022,
derived from Microsoft's Northwind sample database
([MIT](https://github.com/jpwhite3/northwind-SQLite3)) and vendored gzipped at
`backend/scripts/demo_fixtures/`, so seeding needs no network. It exists
because the analysis engine's claim is that it computes over a real file, and
a file invented to be computed over does not test that claim. Provenance, the
exact SQL, and how to regenerate it are in
[`demo_fixtures/SOURCE.md`](backend/scripts/demo_fixtures/SOURCE.md).

### Sync a local folder (connector-style MVP)

To avoid one-by-one uploads, sync a folder into a workspace through the API.
The sync is incremental: unchanged files are skipped, changed files are
re-uploaded, and optional delete mode removes files that were removed locally.

```bash
export AVOCADO_PASSWORD='your-password'

python backend/scripts/sync_workspace_folder.py \
  /absolute/path/to/folder \
  --base-url http://localhost:8000 \
  --email owner@example.com \
  --workspace-name "My Workspace" \
  --wait-ready
```

Useful flags:

- `--delete-missing`: remove previously synced documents when they are no longer in the folder.
- `--dry-run`: preview upload/delete actions without changing remote data.
- `--workspace-id`: target by id instead of name.
- `--password-env`: use a different environment variable for password (default `AVOCADO_PASSWORD`).

The script stores sync state in `<folder>/.avocado-sync-state.json` by default.

### Optional auto-seed on deployment start

For demo environments, the API can seed Northwind data automatically once it
is live. This is opt-in and restart-safe.

- Set `AUTO_SEED_DEMO=true`.
- Startup then runs `scripts/auto_seed_demo.py`, which waits for `/api/v1/live`
  and invokes `generate_demo_data.py --skip-if-workspaces-exist`.
- If one or more workspaces already exist, seeding exits immediately.

Relevant env vars:

- `AUTO_SEED_DEMO` (default `false`)
- `DEMO_SEED_BASE_URL` (default `http://127.0.0.1:8000`)
- `DEMO_SEED_WAIT_SECONDS` (default `180`)
- `DEMO_SEED_POLL_SECONDS` (default `1.5`)
- `DEMO_SEED_ROWS_PER_CSV` (default `800`)
- `DEMO_SEED_OUTPUT_DIR` (optional override for manifest/files output)

Status markers in logs (grep `DEMO_SEED_STATUS=`):

- `launcher_started` (API startup script started the background bootstrap)
- `waiting_for_api`
- `running`
- `seeded`
- `skipped_existing_data`
- `disabled`
- `api_not_ready`
- `failed`

### Optional public demo entry (no manual credentials)

When `PUBLIC_DEMO_ENABLED=true`, the auth page shows **Try demo instantly** and
calls `POST /auth/demo-session` anonymously. The API then issues normal auth
tokens for a configured demo account.

- Development: if `PUBLIC_DEMO_EMAIL`/`PUBLIC_DEMO_PASSWORD` are unset, the API
  can fall back to `PUBLIC_DEMO_MANIFEST_PATH`.
- Production/staging: set explicit `PUBLIC_DEMO_EMAIL` and
  `PUBLIC_DEMO_PASSWORD`. Manifest fallback is refused there.

This gives first-time visitors immediate entry while keeping the rest of the
app behind normal JWT auth.

### What a free deploy can and cannot include

Two components decide the cost, and it is worth being explicit about them
rather than discovering it halfway through a signup.

**The analysis sandbox needs a Docker socket.** Generated code runs in a
container started by the runner service, which means the runner must be able to
talk to a container daemon. Managed platforms do not hand that out — it is
effectively root on their host — and this project's own config refuses to start
with `SANDBOX_BACKEND=docker` outside development for exactly that reason. So:

- **On a VM you control** (including a free-tier one), everything works.
  Step-by-step for Oracle Always Free: [`docs/deploy-oracle.md`](docs/deploy-oracle.md).
- **On a managed platform**, set `SANDBOX_BACKEND=disabled`. Upload, retrieval,
  citations, voice and the knowledge map all work; `/analyze` returns 503
  rather than running code with less isolation than it promises.

**Object storage is required outside development.** `STORAGE_BACKEND=local`
is rejected in staging and production, because a container filesystem is
ephemeral — uploads vanish on the next restart, which on a free tier happens
every time the instance sleeps. Any S3-compatible bucket works via
`S3_ENDPOINT_URL`.

**Redis is optional.** Without `REDIS_URL`, ingestion runs in-process in the
API instead of on a worker, so a single free instance is enough. It is the
right trade for a demo and the wrong one for load.

### Deployment checklist

Before a cloud deploy, set these explicitly:

- `SECRET_KEY` to a generated secret.
- `SANDBOX_AUTH_TOKEN` for the API and sandbox runner.
- `PUBLIC_WEB_URL` to the real frontend origin.
- `CORS_ORIGINS` to the frontend origin list.
- `AVOCADO_API_BASE_URL` for the frontend container, if it is not served from the same origin as the API.

That keeps the same image portable across local, staging, and production.

### Enabling row-level security

RLS is enforced against the **connecting role**. A superuser — or the table
owner without `FORCE` — ignores every policy, so running the application as the
database owner leaves RLS enabled and doing nothing. Create the restricted role
and point the app at it:

```bash
psql "$DATABASE_ADMIN_URL" -v app_password="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" -f scripts/create_app_role.sql
```

Then set `DATABASE_URL` to connect as `avocado_app`, and `DATABASE_ADMIN_URL`
to the owner so Alembic can still alter tables. The app refuses to start in
staging or production when its role can bypass RLS, and logs a warning in
development.

### Running the backend directly

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload
```

Ingestion runs in a worker. Start it, or documents sit in `pending`:

```bash
cd backend && .venv/bin/arq app.worker.main.WorkerSettings
```

---

## Build & test

```bash
pytest backend/tests
```

```bash
cd frontend && npm test -- --run
```

```bash
./scripts/verify.sh
```

That runs every gate CI runs, in the same order, and stops at the first
failure. `--quick` skips the slow integration suite. The individual commands:

```bash
cd backend && ruff check . && ruff format --check .
```

```bash
cd frontend && npm run lint && npm run typecheck && npm run build
```

Backend integration tests need a real PostgreSQL with pgvector — the vector
column, JSONB, enum types and the composite-tuple cursor have no SQLite
equivalent, so testing on SQLite would prove the wrong thing. Point
`TEST_DATABASE_URL` at a throwaway database (`avocado_test` by default).

The sandbox security tests start real containers. They skip if
`avocado-sandbox:latest` is missing — build it first, or those guarantees go
unverified.

---

## Architecture

```
Request → Router → Service → Repository → ORM → Postgres
             ↓         ↓
        Pydantic    Clients (LLM, embeddings, storage, sandbox)
```

- **Routers** are thin: parse, delegate, return. No business logic, no ORM.
- **Services** orchestrate. They never import SQLAlchemy.
- **Repositories** own all data access.
- **Clients** wrap every external dependency behind one interface each, so
  providers are swappable and mockable.

### Two guarantees worth reading the code for

**Tenant isolation is structural, not remembered.**
`WorkspaceScopedRepository` requires `workspace_id` on every read and write and
removes the unscoped `get()` from the subclass entirely — there is no method a
caller could use to act on a client-supplied id alone. Routes that expose a flat
`/documents/{id}` resolve access as a join in the same query as the lookup, so a
row is never loaded before the caller's right to see it is established.
`backend/tests/integration/test_tenant_isolation.py` probes every
workspace-scoped route across two unrelated organizations.

**The analysis sandbox fails closed.**
Generated code runs in a container started with `--network=none`,
`--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, a non-root
uid, a pid limit, a CPU quota, and `--memory` equal to `--memory-swap` so the
memory cap cannot be escaped via swap. Data goes in through a read-only mount
and results come back on stdout, so executed code cannot leave bytes on the
host. There is deliberately **no** weaker fallback: if no compliant sandbox is
available, analysis returns 503 rather than running the code with less
isolation. `backend/tests/integration/test_sandbox_security.py` verifies each of
these against real containers rather than asserting them in a mock.

A static AST screen also rejects obvious escape attempts before execution. That
is defence in depth, explicitly not the boundary — the container is.

---

## Notable decisions

**Local JWT auth rather than Clerk/Auth0.** The architecture doc proposed a
hosted IdP. Local email+password (argon2) was chosen instead so local
development and CI need no external account and the whole auth path is
testable. The token-issuing surface is small; swapping in a hosted IdP later
means replacing `AuthService`, not the routers.

**HNSW rather than IVFFlat** for vector search. IVFFlat needs representative
data at build time to choose useful centroids, so building it on an empty table
quietly costs recall. HNSW is correct from the first row.

**Embeddings have an offline stand-in.** `EMBEDDING_PROVIDER=hash` produces
deterministic lexical vectors so the full retrieval path runs without an API
key. It is not semantic, and config *refuses to start* with it outside
development.

**Spreadsheets are stored twice, on purpose.** Once embedded as text (so "which
file mentions Q3 revenue?" works) and once as a structured table (so pandas has
something to compute against).

**A transcript is just a document.** Recorded audio is transcribed, written to
object storage as text, given a `Document` row, and handed to the ordinary
ingestion pipeline. A meeting recording ends up answerable through exactly the
same retrieval path as an uploaded PDF, with no parallel code path to keep in
sync. The audio stays referenced in metadata so a recording can be
re-transcribed later without asking for it again.

**Authorisation is answered in one place.** `MembershipService` resolves a
user's *effective* role — the strongest of their team membership and their
org-wide standing — and every privileged path goes through it. The
"org admins can administer any team" shortcut is scoped to the admin's own
organization inside that resolution rather than at call sites, because a check
that call sites must remember is one a call site will eventually forget.

**Invitation tokens are credentials.** CSPRNG-generated, stored only as a
SHA-256, returned exactly once, and never logged. Unknown, revoked, used and
expired invitations all report identically, so nobody can probe which tokens
existed. The token must travel in a URL for the link to be openable, so logged
paths and error bodies redact it.

**One account per email address, globally.** Login looks a user up by lowercased
email with no organization, so two accounts sharing an address made it raise
rather than authenticate. The schema now enforces what the code assumed. The
tradeoff is deliberate: one person cannot belong to two organizations with the
same address — that would require choosing an organization at login.

**Task visibility is not document visibility.** Everyone in a workspace can
read every document, but a task assigned to one person is not workspace-public
just because it lives in a shared workspace. A task is visible to its assignee,
to members of its project, to team admins, and to the whole workspace only when
the project has opted in. That rule is a SQL predicate every task query
applies — filtering in Python after loading would mean the rows had already
crossed the boundary, and a query that forgot the filter would leak silently.

**Suggestions are a digest, not a record.** Nothing is persisted. The facts —
what is overdue, what is new, what was left mid-question — are computed
exactly, because a model would only add a chance of being wrong about them. The
model's job is phrasing and ordering, and a rewrite that changes the number of
nudges is rejected wholesale: a lost deadline is worse than an unpolished
sentence. Suggestion ids are content hashes, so a client-side dismissal
survives regeneration without the server storing one.

**The API never holds the Docker socket.** Analysis is delegated to a separate
sandbox runner, which is the only container with the socket and does nothing
else — no database, no model access, no tenant data beyond one run's inputs.
Compromising the API therefore does not mean owning the host. The limits are
the runner's own configuration and are not part of the request, because a
caller that could name its own timeout and memory ceiling could name unlimited
ones. Config refuses to start on the local-daemon backend outside development.

**The dictation socket authenticates from its first message**, not a query
parameter. `WebSocket` cannot set an `Authorization` header, and a token in a
URL lands in access logs, proxy history and browser history. Workspace access
is re-checked on the socket exactly as it is on every HTTP route.

**The model that answered is always recorded and shown.** `Auto` is a real
user-facing choice — it routes cheap tasks to a fast model and analysis/code
generation to the strongest available — and the response carries which model
actually ran, so Auto is never opaque.

---

## Known gaps

- **Text-to-speech** (architecture §9, listed as a stretch) is not built —
  voice is input-only.
- **Document supersession is represented but not derived.** A newer policy can
  point at the one it replaces, and reclassification bumps a version, but
  automatically *detecting* that one document supersedes another needs identity
  resolution across documents and is not attempted.
- **Task assignment has no notification.** Assigning work to someone surfaces
  in their suggestions the next time they look; nothing is pushed.
- **Invitations are not emailed.** The API returns the link and the UI shows it
  once for the inviter to send; there is no mail transport wired up.
- **Live dictation is not persisted.** The socket exists so a question can be
  spoken instead of typed; nothing is stored. Use the recorder for anything
  that should become knowledge.

---

## License

[MIT](LICENSE) — © 2026 Sang Thai. The reasoning behind choosing a permissive
license at this stage, and the conditions under which BUSL-1.1 would be worth
revisiting instead, are in [`docs/architecture.md`](docs/architecture.md) §18.

**Third-party data.** `northwind_orders.csv` in the demo seed is derived from
Microsoft's Northwind sample database via
[northwind-SQLite3](https://github.com/jpwhite3/northwind-SQLite3), which is
MIT-licensed; provenance and the exact derivation are recorded in
[`demo_fixtures/SOURCE.md`](backend/scripts/demo_fixtures/SOURCE.md).
