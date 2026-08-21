# Avocado 🥑 — Team Knowledge & Analysis Copilot

**Status:** Planning draft — passion project (with ThriveKid), not just interview prep
**Owner:** Sang Thai

---

## 1. Vision

Avocado ingests anything — documents, spreadsheets, images, and eventually data pulled from wherever a team keeps it — and turns it into something a team can actually talk to: deep analysis of structured data (not just "here's a relevant paragraph," but real computed answers from a spreadsheet), and a living map of a team's policies, processes, procedures, projects, and goals that a new hire — or an auditor, or you six months from now — can query directly instead of hunting through folders and asking around.

Beyond documents, Avocado also tracks what people are actually doing — projects and tasks, per person, not just per team — and uses that to help proactively rather than only when asked: surfacing what's relevant before someone thinks to ask, and picking a person back up where they left off when they jump between tasks and come back later, which is closer to how a real workday actually moves. That's the difference between a document Q&A tool and something closer to a team's shared memory with a personal assistant layer on top.

The enterprise-team framing is the right validation story: a large team drowning in scattered policy docs, process writeups, and project trackers is exactly the pain this solves, and you understand that pain firsthand from your own work. That's genuine, hard-won product insight — worth keeping front and center in how you talk about this.

**Definition of done (v1):**
- Upload anything — PDF, Word, Excel/CSV, images, plain text — into one workspace
- Ask a real analytical question of a spreadsheet and get a computed answer, not just a retrieved snippet
- Ask a question about "the team" (policies/processes/projects) and get a grounded, cited answer
- Deployed and publicly demo-able 24/7, independent of your laptop
- A working onboarding-style demo: point a fictional new hire at a workspace and have them productively query "what does this team do and what's active right now"

---

## 2. Product Positioning — Pick the Wedge First

This is now a genuinely large product surface: multimodal ingestion, arbitrary external data sources, computational analysis, and a structured knowledge graph of an organization are each substantial on their own. Trying to build all of it before anyone uses it is the most common way ambitious solo projects stall.

**Recommended wedge:** nail *deep analysis + multimodal upload in a single workspace* first — no external connectors, no multi-tenant teams yet. That alone, done well, is already differentiated from the reference Atlas repo (which only does retrieval, not computation) and from most "chat with your PDF" clones. Everything else in this doc — connectors, the org knowledge graph, multi-tenant teams — is real, but sequenced *after* that wedge works and is worth showing someone.

Task/project awareness and proactive suggestions (§11) are a genuine part of the vision worth designing now, but they only make sense once real teammates exist to assign tasks to and be proactive about — they're sequenced after the multi-tenant user model (§13) in the roadmap, not in the wedge.

**Reality check on using your current workplace as a user base:** hooking this up to a real employer's actual systems or data would need that employer's own security/vendor review first — that's not something a personal project can shortcut, at a regulated company or otherwise. Near-term, build and demo the "team knowledge" story against your own docs, ThriveKid/USF material, or a synthetic sample company. The category and the story stand on their own without needing real employer data.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (Python 3.12) | async-native, Pydantic-integrated |
| Validation | Pydantic v2 | request/response DTOs, separate from ORM models |
| ORM | SQLAlchemy 2.0 (or SQLModel) | mature, explicit, testable |
| Migrations | Alembic | standard, scriptable |
| Database | PostgreSQL + `pgvector` | relational + vector data in one place |
| Cache / queue | Redis + Arq (or Celery) | async ingestion + analysis jobs, and the suggestion engine's periodic job |
| Object storage | Cloudflare R2 (or AWS S3) | documents/images live in the cloud, not local disk |
| Vision / multimodal | Claude's native image understanding, OCR (Tesseract) as fallback for scanned/handwritten docs | images and scans handled without building a custom vision pipeline |
| Analysis sandbox | E2B (hosted code-execution sandbox built for this exact use case) or a locked-down, no-network Docker container as a self-hosted alternative | lets an LLM write and run real pandas code against uploaded data safely |
| Voice STT | Deepgram (streaming + batch) | live mic query + transcription of recordings |
| LLM | Claude (primary) + pluggable OpenAI / Ollama | provider-agnostic via one interface |
| Auth | Clerk or Auth0 to start | ship fast now, harden later |
| Frontend | React + TypeScript + Vite, Tailwind, shadcn/ui | matches ThriveKid stack |
| Frontend state | React Query + Zustand | server state vs. UI state, cleanly separated |
| Containerization | Docker + docker-compose (local); same images to Render/Fly.io/Railway (cloud) | one Dockerfile, two environments |
| Hosted DB/cache | Neon or Supabase (Postgres + pgvector), Upstash (Redis) | managed, always-on, cheap/free tiers |
| Frontend hosting | Vercel or Cloudflare Pages | deploys from the repo |
| CI/CD | GitHub Actions | lint, test, build image on push |
| Observability | structured logging + OpenTelemetry; hosted dashboard once deployed | real latency/throughput numbers |

---

## 4. Clean Architecture — Layers

```
Request → Router (Controller) → Service → Repository → ORM Model → DB
                ↓                   ↓
            Pydantic DTOs      External clients (LLM providers, Deepgram,
            (validation)       storage, analysis sandbox, connectors)
```

- **Routers** — thin, HTTP concerns only.
- **Schemas (DTOs)** — Pydantic, split `Create`/`Update`/`Read` per resource.
- **Services** — business logic (`DocumentService`, `AnalysisService`, `RAGService`, `VoiceService`, `WorkspaceService`, `ConnectorService`, `TaskService`, `SuggestionService`).
- **Repositories** — data-access abstraction; services never touch SQLAlchemy directly.
- **Domain models** — SQLAlchemy models.
- **Clients** — one small interface per external dependency, so each is swappable and mockable.

### Repo structure

```
avocado/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── workspaces.py
│   │   │   ├── documents.py
│   │   │   ├── analysis.py        # analysis-agent endpoints
│   │   │   ├── conversations.py
│   │   │   ├── voice.py
│   │   │   ├── projects.py        # NEW — projects & tasks
│   │   │   └── suggestions.py     # NEW — proactive suggestions
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── models/
│   │   ├── clients/
│   │   │   ├── llm/                # base.py, claude.py, openai.py, ollama.py
│   │   │   ├── deepgram.py
│   │   │   ├── storage.py
│   │   │   ├── sandbox.py          # analysis code execution
│   │   │   └── connectors/         # later phase — gdrive.py, sharepoint.py, s3.py
│   │   ├── core/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── features/               # workspace/, chat/, voice/, documents/, analysis/, tasks/
│   │   ├── hooks/
│   │   ├── stores/
│   │   └── api/
│   └── Dockerfile
├── docker-compose.yml
├── render.yaml / fly.toml
└── .github/workflows/ci.yml
```

---

## 5. Data Model

| Entity | Key fields | Notes |
|---|---|---|
| `Organization` | id, name, plan_tier | top-level tenant |
| `Team` | id, org_id, name | |
| `User` | id, org_id, email, auth_provider_id | |
| `TeamMembership` | user_id, team_id, role | RBAC: `org_admin`, `team_admin`, `member`, `viewer` |
| `Workspace` | id, team_id, name, preferred_model | shared knowledge base |
| `Document` | id, workspace_id, uploaded_by, filename, type, status | `type`: pdf/docx/xlsx/csv/image/etc.; status: `pending → processing → ready → failed` |
| `DocumentChunk` | id, document_id, content, embedding (vector), metadata (jsonb) | for retrieval |
| `AnalysisRun` | id, workspace_id, document_id, user_id, question, generated_code, result_summary, chart_url, status | one row per analysis-agent invocation — doubles as an audit log |
| `VoiceRecording` | id, workspace_id, uploaded_by, storage_path, duration, transcript_status | Phase 3 |
| `Project` | id, workspace_id, name, goal, status, created_by | a team's tracked initiatives — see §11 |
| `Task` | id, project_id, workspace_id, assignee_id, title, status, due_date, notes | status: `todo → in_progress → blocked → done` — see §11 |
| `Conversation` | id, workspace_id, user_id, title, task_id (nullable) | the optional `task_id` link is what makes "resume where I left off" possible |
| `Message` | id, conversation_id, role, content, citations (jsonb), model_used | |
| `ApiUsageLog` | id, org_id, endpoint, model, tokens_used, cost, latency_ms | scale numbers + provider comparison |

**Org Knowledge Layer (Phase 4, conceptual):** once documents are ingested, a tagging/extraction pass can classify them into `PolicyDocument` and `Process` entities, each linked to a `Team` and versioned over time. Combined with the `Project`/`Task` tables above, this is what turns "a pile of uploaded PDFs" into "a queryable map of what this team does" — genuinely the most differentiated part of the vision, and also the part most worth deferring until the ingestion + analysis core is solid, since it depends on that core working well first.

Proactive suggestions are deliberately *not* a persisted table — they're generated on demand or on a schedule and cached in Redis, not stored as permanent rows. They're a digest, not a record.

Every table with a `workspace_id` gets a **mandatory, non-optional filter** at the repository layer — never rely on the client-supplied ID alone.

---

## 6. REST API Design

Base path: `/api/v1`. Consistent error envelope, cursor pagination, versioned from day one.

| Resource | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| Workspaces | `GET/POST /workspaces`, `GET/PATCH/DELETE /workspaces/{id}` |
| Documents | `GET/POST /workspaces/{id}/documents` (accepts pdf/docx/xlsx/csv/image), `GET/DELETE /documents/{id}`, `POST /documents/{id}/reprocess` |
| Analysis | `POST /documents/{id}/analyze` (natural-language question → generated code → executed in sandbox → result), `GET /analysis-runs/{id}` |
| Conversations | `GET/POST /workspaces/{id}/conversations`, `DELETE /conversations/{id}` |
| Messages | `GET /conversations/{id}/messages`, `POST .../messages` (RAG), `POST .../messages/stream` (SSE) |
| Voice | `WS /voice/stream`, `POST /workspaces/{id}/voice` (Phase 3) |
| Models | `GET /models` |
| Projects | `GET/POST /workspaces/{id}/projects`, `GET/PATCH/DELETE /projects/{id}` |
| Tasks | `GET/POST /projects/{id}/tasks`, `GET/PATCH/DELETE /tasks/{id}`, `GET /tasks/{id}/resume` (synthesized "here's where you left off" summary) |
| Suggestions | `GET /workspaces/{id}/suggestions` (current user's proactive nudges) |
| Connectors *(Phase 5)* | `GET /connectors`, `POST /workspaces/{id}/connectors/{provider}/connect`, `POST .../sync` |

---

## 7. Ingestion Pipeline (multimodal)

**Upload → object storage (R2/S3) → background job → type-specific parse:**
- **Text/doc types** (pdf/docx/pptx/md) — existing pattern: extract text, chunk, embed.
- **Spreadsheets** (xlsx/csv) — parsed into structured tables (schema + rows), *not* just embedded as flat text — this structured form is what the Analysis Engine (below) operates on.
- **Images** — sent to Claude's vision input directly for description/data extraction (charts, screenshots, scanned pages); OCR (Tesseract) as a fallback specifically for dense scanned text where a structured transcript is more useful than a description.

All parsed content lands in `pgvector`, scoped to `workspace_id`, for retrieval — spreadsheets *additionally* keep their structured form for the Analysis Engine.

---

## 8. Analysis Engine (deep spreadsheet/data analysis)

This is the piece that makes Avocado do more than retrieve — it computes.

**Flow:** user asks a question about a spreadsheet ("what's the month-over-month trend by region") → an LLM call generates pandas code against that document's structured schema → the code runs in an isolated sandbox (E2B, or a self-hosted no-network Docker container with strict CPU/memory/time limits) → result (table, number, or chart) is captured, along with the generated code itself → both are returned to the user and logged as an `AnalysisRun`.

This is conceptually similar to Code Interpreter, scoped down: the sandbox only ever runs generated analysis code against one document's data, with no network access and a hard timeout — a materially smaller security surface than executing an arbitrary third-party repository (which is why repo execution was correctly cut earlier), but it's still real code execution and still needs to be sandboxed properly, not skipped.

---

## 9. Voice Pipeline

- **Live query:** browser mic → WebSocket → Deepgram streaming STT → partial transcript → submitted as query text.
- **Recorded audio (Phase 3):** batch transcription → transcript treated as a document, chunked/embedded like any other source.
- **TTS (stretch):** Deepgram Aura or ElevenLabs.

---

## 10. Multi-Model Support

A base `LLMProvider` interface (`generate()`, `stream()`) with adapters per vendor (`claude.py`, `openai.py`, `ollama.py`). A `preferred_model` setting on `Workspace` selects the provider; a small `ModelRouter` can send cheap tasks (classification, reranking) to a fast/cheap model and reserve the primary model for final synthesis and code generation. Real added complexity — each provider streams and errors differently — worth it for the story, budgeted as its own phase.

**Auto is a user-facing option, not just internal plumbing.** The model picker in the UI always has two kinds of choice: "Auto" (default) and each specific model by name. When a user picks a specific model, every request in that conversation uses it, full stop. When "Auto" is selected, the `ModelRouter` picks per request based on task type — e.g. a fast model for simple retrieval, the strongest model for analysis/code generation — and the choice is never hidden: `Message.model_used` (already in the data model, §5) is surfaced in the UI as a small tag on the response, so a user on Auto always sees which model actually answered, not just that "the AI" did.

---

## 11. Task & Project Awareness — the Team Mastermind Layer

This is the part of the vision that turns Avocado from "a copilot you query" into something closer to a shared team brain with a personal assistant layer on top. Two capabilities, both building on the multi-tenant user model in §13 rather than the wedge:

**Proactive suggestions.** Rather than waiting to be asked, a lightweight `SuggestionService` looks at what's changed and what's relevant to the current user — new or updated documents since their last visit, tasks assigned to them with approaching due dates, threads they started but didn't finish — and surfaces a short, dismissible set of nudges (`GET /workspaces/{id}/suggestions`). This runs on a cheap/fast model on a schedule or on session start, not per keystroke, and the result is cached — it's a periodic digest, not a live inference on every render.

**Task & project awareness.** `Project` and `Task` are real entities, not just document tags: a task has an assignee, a status, a due date. Each task can optionally have its own `Conversation` (the `task_id` link on `Conversation`, §5) — its own running thread of context. This is what makes "jump between tasks and come back" actually work: `GET /tasks/{id}/resume` doesn't just reopen the thread, it returns a short synthesized summary of where things stood, so returning to a task after two days on something else starts with "here's where we left off," not a blank chat.

**Visibility isn't the same as document visibility, by default.** Everyone in a workspace can typically see every document, but that's the wrong default for tasks — a task assigned to one person shouldn't be visible workspace-wide just because it lives in a shared workspace. Default: a task is visible to its assignee, the project's other members, and `team_admin`/`org_admin` — not the whole workspace automatically. Broader visibility (e.g. a public project board) is an opt-in setting on the `Project`, not the default.

---

## 12. External Data Connectors (deferred)

Each connector — Google Drive, SharePoint/OneDrive, S3, Confluence — is effectively its own integration project: its own OAuth flow, its own API quirks, its own sync/webhook strategy for keeping content current. Build the connector *interface* early (so `ConnectorService` and the ingestion pipeline don't care where a file came from), but implement only one connector first (Google Drive is the friendliest API to start with) and treat each additional one as separate, scoped work rather than a single "connect to anything" feature.

Current execution decision: connectors are deferred until the first-open UX,
upload-to-insight flow, and report/dashboard experience are polished to a
high standard at low/no additional cost.

---

## 13. Multi-Tenancy & Security

- Every query scoped by `team_id`/`workspace_id`, enforced at the repository layer.
- Postgres Row-Level Security as defense-in-depth once the schema stabilizes.
- RBAC via router-level dependency/decorator.
- Task/project visibility defaults to assignee + project members + admins, not workspace-wide (§11) — a separate check from document access, not an extension of it.
- Redis-based rate limiting per org.
- Upload validation: type/size limits.
- Analysis sandbox: no network access, hard timeout, resource caps — non-negotiable given it executes generated code.

---

## 14. Deployment Strategy — Cloud + Local, Machine-Independent

**12-factor config:** every environment-dependent value from env vars — the same image runs unchanged locally and in the cloud.

- **Local:** `docker-compose up` — Postgres+pgvector, Redis, API, frontend.
- **Cloud:** Neon/Supabase (Postgres), Render/Fly.io/Railway (API + worker), Upstash (Redis), R2/S3 (storage), Vercel/Cloudflare Pages (frontend) — stays live regardless of your machine.

---

## 15. Testing Strategy

- **Unit:** services and repositories, mocked dependencies.
- **Integration:** API endpoints against a real test Postgres.
- **E2E:** Playwright for the critical path (upload → ask → get cited or computed answer).
- **Isolation test:** proves Team A can't retrieve Team B's data, and separately, that a task isn't visible outside its assignee/project/admins.
- **Sandbox test:** confirms the analysis sandbox can't reach the network or exceed its resource limits — this one matters as much as the isolation test.
- **Load (Phase 5):** k6/Locust once deployed.

---

## 16. Frontend

- Shell: org/team switcher, workspace sidebar.
- Document manager: upload (any type, drag-and-drop), status, reprocess.
- Chat view: streaming responses, citations, model indicator.
- Analysis view: shows the generated code, the result/chart, and lets the user re-run or tweak the question.
- Voice recorder: live waveform + partial transcript.
- Suggested panel: a small dismissible row of proactive nudges above the input — new documents, tasks due soon, unfinished threads — from `GET /workspaces/{id}/suggestions`.
- Task view: a lightweight list or board per project; opening a task resumes its thread with a "here's where we left off" summary rather than a blank chat.
- React Query (server state) + Zustand (UI state).

---

## 17. Phased Roadmap

| Phase | Scope | Rough time |
|---|---|---|
| **0 — Foundation** | Repo scaffold, clean-architecture skeleton, Docker Compose, 12-factor config, CI, auth skeleton, single workspace | 1–2 wks |
| **1 — Ingestion + Analysis MVP** | Multimodal upload (docs/images/excel), RAG Q&A, Analysis Engine for spreadsheets (sandboxed), basic chat + analysis UI, single-tenant, **first cloud deploy** — this is the wedge | 3–4 wks |
| **2 — Voice + multi-model** | Deepgram streaming STT, second LLM provider wired in, Auto mode | 2–3 wks |
| **3 — Multi-tenant** | Org/team/workspace, RBAC, invite flow | 2–3 wks |
| **4 — Team Mastermind layer** | Policy/process tagging (org knowledge layer), `Project`/`Task` entities, proactive suggestion engine, task resume flow | 3–4 wks |
| **5 — UX polish + scale (current)** | First-open onboarding flow, upload progress clarity, report templates, performance polish, load test | ongoing |
| **6 — External connectors (later)** | First external connector (Google Drive or equivalent) once UX targets are met | later |

### 17.1 Current no-cost execution plan

The near-term objective is to deliver a high-quality first experience without
new spend on connectors:

1. First-open decision screen: demo workspace or upload own files.
2. Empty-state chat behavior that explains grounded-answer requirements and offers next actions.
3. Upload-to-query progress indicators and "ready" status.
4. Post-ingest suggested prompts plus report/dashboard templates.
5. Bundle/performance optimization for faster perceived response.

Success criteria for this plan:

- A new user can produce one cited answer and one analysis report in under 5 minutes.
- Empty workspace behavior is explicit and helpful, never confusing.
- Demo flow requires zero paid external connector setup.

**Reality check on timing:** Phase 1 is now bigger than before (multimodal + a real analysis engine is more than plain RAG), so it's realistic to treat it as the goal for the pre-leave window rather than something to fully finish — landing image + Excel-analysis + a live cloud deploy by then is a strong, honest milestone on its own.

**On realistic test data (a later but real task):** the current demo content (a couple of files) won't surface real problems in retrieval quality or suggestion relevance — those only show up with real complexity: dozens of documents with overlaps and contradictions, multiple fake users with overlapping and competing tasks, messy/outdated content mixed with current content. Building a synthetic "sample company" dataset with that kind of real-world messiness is worth treating as its own scoped task before Phase 4, not an afterthought — it's what actually tests whether the knowledge layer and suggestion engine work, not just whether they run.

---

## 18. License & Open-Source Strategy

Two separate questions live here — worth untangling, since they get conflated:

**1. What do you publish?** Regardless of license, you don't have to put everything in the public repo. A practical split: architecture, infra, clean-code patterns, most services, and the frontend are exactly what you *want* visible — that's the portfolio signal, and it's also what makes the repo useful to point Cursor/Copilot at. The genuinely differentiating pieces — the specific analysis-agent prompting, any scoring/ranking logic that turns out to be the real "why this works well" — can live in a separate private repo or package, imported at runtime via a private dependency or config, and simply not pushed. This costs you almost nothing in interview/portfolio value, since a clean-architecture RAG + analysis platform is already substantial signal without needing the exact prompts visible.

**2. What license governs what you do publish?** (This is the legal layer — I'm not a lawyer, so treat this as the standard tradeoffs, not binding advice.)
- **MIT / Apache 2.0** — fully permissive. Standard for portfolio projects. Costs you nothing right now since there's no revenue or users to protect yet, but it does mean anyone, including a company, can legally take the published code and build a competing product from it.
- **Business Source License (BUSL-1.1)** — source stays visible on GitHub (so it still works for interviews and for AI coding tools to read), but usage is restricted — typically "you can't run this as a competing hosted service" — for a fixed period (2–4 years is common), after which it auto-converts to a permissive license like Apache 2.0. This is the standard middle ground companies like Sentry and CockroachDB use: open enough to build trust and show real code, protected enough that someone can't just clone your hosted product on day one.
- **No license file / all-rights-reserved** — a public repo with no LICENSE file already defaults to full copyright under the law: visible, but nobody has any legal right to use, copy, or modify it. Maximum protection, but also the least standard-feeling for a repo you want people (or AI tools) to treat as a real reference.

**A reasonable default given where this actually is right now:** publish under MIT/Apache now — there's no product or users yet, so there's nothing meaningful to protect, and permissive licensing is the norm for exactly this kind of build-in-public portfolio project. Revisit BUSL if and when this gets real traction and the "someone forks my hosted product" scenario becomes concrete rather than hypothetical.

---

## 19. Building with AI Coding Tools (Cursor / Copilot / Claude Code)

Using Cursor or Copilot to build this is fine and doesn't have to cost you quality — but it does need structure, or the output drifts toward generic scaffolding instead of the clean-architecture pattern in this doc. Three real files handle this — see the `avocado-agent-files/` bundle:

- **`AGENTS.md`** (repo root) — the tool-agnostic instruction file. It's the closest thing to a universal standard: read natively by Cursor, GitHub Copilot, Codex, Gemini CLI, Windsurf, and most other agents. It encodes the non-negotiables from this doc — thin routers, repository-only DB access, mandatory `workspace_id` scoping, DTOs never exposing ORM models, sandbox constraints — so any tool's suggestions match the architecture instead of reinventing it per file.
- **`CLAUDE.md`** (repo root) — Claude Code reads this natively rather than AGENTS.md, so it's a one-line `@AGENTS.md` import plus a Claude-specific note. This keeps a single source of truth instead of two files drifting apart.
- **`.claude/settings.json`** — disables Claude Code's default commit/PR attribution (by default it adds a `Co-Authored-By: Claude` trailer). Cursor, Copilot, and Codex don't add automatic attribution — they just use your local git identity — so this file is specifically what keeps Claude Code's commits clean too.

Everyday practice on top of those files:
- **Git identity first, before any tool touches the repo:** `git config user.name "Sang Thai"` and `git config user.email "you@example.com"` in the repo (or globally). This is what actually puts your name on commits from Cursor/Copilot — they commit as whoever your local git is configured as.
- **Feed one phase at a time**, not the whole doc — paste the relevant section (e.g. §8, Analysis Engine) as context when working on that piece.
- **Security-critical code gets manually reviewed regardless of what generated it** — tenancy isolation, the sandbox's no-network/timeout limits, and auth all need a human check that the AI-generated version actually enforces what this doc specifies, not just that it compiles.
- **Commit in small, phase-sized increments** so a bad generation is easy to isolate and revert.
- **One caveat worth knowing:** GitHub's autonomous "assign to Copilot" cloud agent (distinct from inline Copilot in your editor) opens PRs and commits under a `Copilot` bot account, since it runs in GitHub's infrastructure rather than through your local git. Not likely the mode you're using day to day, but worth knowing if you ever try it.

---

## 20. Open Decisions

- Second LLM provider: OpenAI vs. a local model via Ollama (Ollama needs a GPU host in the cloud, or stays local-only with a hosted fallback for the deployed version)
- Sandbox choice: E2B (faster to integrate, external dependency) vs. self-hosted Docker sandbox (more control, more DIY signal, more work)
- First connector to build in Phase 5: Google Drive is the recommended default (friendliest API, most universally useful for a demo)
- Demo content strategy: your own docs/ThriveKid material vs. a synthetic "sample company" dataset with real complexity (see the note in §17)
- License: MIT/Apache now vs. BUSL from day one (see §18)
- Task visibility default: assignee + project members + admins (proposed in §11) — worth confirming before real tasks exist in the system, since it's harder to loosen or tighten after the fact
- Suggestion engine cadence: computed on session start vs. a background periodic job — affects both cost and how fresh the nudges feel
