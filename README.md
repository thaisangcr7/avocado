# Avocado 🥑

**Team knowledge & analysis copilot.** Upload documents, spreadsheets and images
into a workspace, then ask questions and get answers that are either *cited* —
grounded in the actual text, with the source shown — or *computed*, by writing
and running real code against your data in an isolated sandbox.

The distinction matters. Most "chat with your documents" tools retrieve a
paragraph and paraphrase it. Avocado does that too, but when the question is
analytical ("what's the month-over-month trend by region?") it writes pandas,
runs it, and returns both the number and the program that produced it.

Full design: [`docs/architecture.md`](docs/architecture.md).

---

## Status

| Phase | Scope | State |
|---|---|---|
| 0 — Foundation | Clean-architecture skeleton, Docker, config, CI, auth | ✅ Done |
| 1 — Ingestion + Analysis | Multimodal upload, RAG Q&A, sandboxed analysis engine, UI | ✅ Done |
| 2 — Voice + multi-model | Deepgram STT, second provider, Auto mode | ✅ Done |
| 3 — Multi-tenant | Org/team/workspace, RBAC, invites | Schema + isolation done; invite flow done |
| 4 — Team Mastermind | Projects/tasks, suggestions, task resume, knowledge map | ✅ Done |
| 5 — Connectors + scale | Google Drive, observability, load test | Not started |

**345 backend tests, 96 frontend tests.** Backend coverage 87%.

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

Use the seed script to create a realistic workspace, extra collaborators,
multiple projects and tasks, and a large document set for testing:

```bash
python backend/scripts/generate_demo_data.py --base-url http://localhost:8000
```

It writes the source files and a manifest under `backend/.demo-data/`. One
workspace is intentionally left empty so you can see the honest no-results
response before you upload anything there.

To reset the local demo database before reseeding, run:

```bash
python backend/scripts/generate_demo_data.py --reset --base-url http://localhost:8000
```

That truncates the local Postgres tables in the compose stack, so use it only
against your local demo environment.

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

Not yet chosen — see `docs/architecture.md` §18 for the MIT vs. BUSL tradeoff.
Until a `LICENSE` file exists, this is all-rights-reserved by default.
