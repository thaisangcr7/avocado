# Workspace-platform parity — inventory and plan

A reference enterprise GenAI workspace platform was reviewed feature by feature.
This document records **what it does**, **what Avocado already does**, and **the
order in which to close the difference**.

The reference platform is not named here on purpose. It is an internal tool at a
large organisation, and this repository should not read as a clone of one. The
features below are industry patterns — artifacts, prompt libraries, scheduled
runs — not anything proprietary.

---

## 1. Feature inventory

Observed across the landing page, model picker, presets modal, a live
conversation, the artifact viewer, and the history page.

### 1.1 Shell and navigation

| Feature | Detail |
|---|---|
| Left rail | Chat (⇧N), History (⇧H), Presets, Spaces, Schedules |
| Rail footer | Attestation link, Theme switcher |
| Collapsible rail | Toggle button at top-left of content area |
| Top bar | Brand, What's New, Feedback, app-grid launcher, notification bell with unread count, sign out |
| Announcement strip | Dismissible product banner linking to a feature tour |
| Footer | Product info, curated AI content link, escalation policy, support |

### 1.2 Landing page

- Marketing hero with animated gradient headline and inline `AI` / `USER` pills.
- **Quick-ask input** — a single-shot question box that does not require
  creating a conversation first.
- Model selector and a **Tools** control directly beneath the input.
- A secondary call to action ("start a full conversation") for the complete
  surface with uploads and tools.

### 1.3 Model selection

- Flat list of concrete models across **multiple vendors** (six observed).
- Current selection marked with a check.
- Selector appears in three places: landing input, conversation header, and
  persists per conversation.

### 1.4 Presets (prompt library)

The largest feature not present in Avocado.

| Aspect | Detail |
|---|---|
| Entry | Modal, opened from the rail or by typing `/` in the composer |
| Search | Free-text filter across presets |
| Scopes | All · Pinned · My Presets · Native · Community · Shared |
| Card | Title, slash path (`/sage`, `/dockerfile-improvement`), scope badge |
| Enable | Per-preset toggle switch — a preset is activated into the conversation |
| Share | Person-add affordance per preset |
| Authoring | "Create a preset" card → custom preset builder |
| Invocation | Typing `/name` in the composer applies the preset |

Presets are effectively **named, shareable, versionable system prompts** with a
governance model (native = platform-authored, community = user-authored and
published, shared = shared directly with you).

### 1.5 Conversation surface

| Feature | Detail |
|---|---|
| Breadcrumb title | `Space > Conversation`, inline-renameable |
| Per-conversation model | Shown under the title, changeable mid-thread |
| Participant avatars | With presence dot (online) |
| Header actions | Privacy/shield, pin, add-participant, overflow menu |
| Multi-human threads | Messages attributed by real name and timestamp |
| `@mentions` | Rendered as chips, addressable to humans in the thread |
| Message feedback | Thumbs up / thumbs down / copy per assistant message |
| Composer | `/` for presets, `@` for mentions, attach, Tools (with active count), prompt-enhance, formatting, send |

### 1.6 Right rail — three distinct stores

This separation is a genuinely good idea and worth copying exactly:

1. **Artifacts** — generated *by* the assistant in this conversation.
2. **Uploaded documents** — files *you* attached to this conversation.
3. **Files in this Space** — the persistent knowledge base behind the whole
   Space.

Conflating these is the usual mistake; keeping them apart makes it obvious what
the model is grounded in versus what it produced.

### 1.7 Artifacts

| Feature | Detail |
|---|---|
| Panel | Opens beside the conversation, `(1 of N)` pager |
| Versions | Explicit version selector (`V4 (AI)`) — AI edits create versions |
| Rendering | Live HTML render inside the panel, fully interactive (the observed artifact had its own internal tab bar, KPI cards and charts) |
| Actions | Download, view source, open in new tab, edit, duplicate, close |
| Listing | Also listed in the right rail with filename and age |
| Bulk | Download-all from the rail header |

The observed artifact was a self-contained interactive HTML dashboard the model
authored and revised across four versions.

### 1.8 History

| Feature | Detail |
|---|---|
| Dedicated page | Not just a sidebar list |
| Search | Free text |
| Filter | Dropdown (All / by type or status) |
| Row | Title (inline-editable), author, relative age, message count |
| Status | Explicit run state (`Completed`) |
| Row actions | Pin, download, share, delete |
| Pagination | Numbered pages with prev/next, total item count |

### 1.9 Spaces

Persistent containers with their own knowledge files, above the level of a
single conversation. Avocado's workspaces are already close to this.

### 1.10 Schedules

Recurring/scheduled runs. Not observed in detail — a rail entry exists.

### 1.11 Tools and integrations

The largest feature after presets, and a first-class surface rather than a
settings checkbox.

| Aspect | Detail |
|---|---|
| Entry | "Tools" on the composer, carrying a badge with the active count |
| Modal | "Tools and integrations", full-screen, with its own Done action |
| Search | Free text across integrations |
| Categories | All · Analytics · Engineering · General Admin · Financial Data |
| Card | Icon, name, one-line description, enable toggle |
| Scale | ~17 integrations observed, scrolling |
| Cost warning | Footer: enabling too many bloats the context and degrades answer quality, with a link to fuller guidance |

The integrations observed, generalised away from the organisation's own systems:

| Integration | What it does |
|---|---|
| Data explorer | Conversationally explore, analyse and visualise spreadsheets |
| Engineering / product docs | Query technical documentation |
| Regulatory filings | Fetch public company filings |
| Issue tracker (two variants) | Issues, projects, sprints, boards, epics |
| Staff directory | User details and reporting hierarchies |
| Code intelligence | Explore, search and review code across repositories |
| Database inventory | Database details for a given system id |
| Service management | Incidents, change requests, problems, user groups |
| Application inventory | Search registered software applications |
| Directory groups | Distribution lists and group memberships |
| Technology catalogue | Approved software versions |
| Wiki | Knowledge-base access |
| Slide generator | Build presentations conversationally |
| Project tracking | Timesheets, project status, lookups |
| Internal assistant | Sourced answers on HR, policy, standards |
| Market data | Permissioned financial data via natural language |

**The important observation is the footer, not the list.** Every enabled tool
costs context whether or not it is used, and the product says so out loud rather
than letting quality quietly degrade. That is a design position worth copying:
tools are metered, not free.

### 1.12 Conversation instrumentation

Details visible on an open thread that did not appear in the first pass:

| Feature | Detail |
|---|---|
| **Context budget** | A gauge above the composer reading "Context: 96% left" — how much of the window remains, updated as the thread grows |
| Prompt enhance | A wand control that rewrites the drafted message before sending |
| Formatting | A text-format control on the composer |
| Welcome state | A named greeting explaining what the assistant does and how to start, rather than an empty pane |
| Timestamps | Per message, both sides |
| Share | A share control in the conversation header, beside pin |
| Presence | A green dot on the participant avatar |

The context gauge is the standout. It makes the single most confusing property
of a long conversation — that quality falls off as the window fills — visible
before it bites, and it is cheap to build on token counts that are already
recorded per message.

---

## 2. Where Avocado already stands

| Capability | Avocado | Reference |
|---|---|---|
| Streaming chat | ✅ | ✅ |
| **Grounded answers with inline citations** | ✅ | not observed |
| **Sandboxed code execution against your data** | ✅ | not observed |
| Multi-vendor model picker | ✅ (+ Auto routing) | ✅ |
| Workspaces / Spaces | ✅ | ✅ |
| Document upload + ingestion | ✅ | ✅ |
| Voice transcription | ✅ | not observed |
| Multi-tenancy, RBAC, row-level security | ✅ | assumed |
| Cost budgets + spend visibility | ✅ | not observed |
| Distributed tracing | ✅ | not observed |
| Tasks, projects, knowledge map | ✅ | not observed |
| **Artifacts panel** | ❌ (data model exists) | ✅ |
| **Presets / slash commands** | ❌ | ✅ |
| **History page** | ❌ (sidebar list only) | ✅ |
| **Schedules** | ❌ | ✅ |
| **@mentions / multi-human threads** | ❌ | ✅ |
| **Tool / integration registry** | ❌ | ✅ (~17) |
| **Context-budget gauge** | ❌ | ✅ |
| Prompt enhance | ❌ | ✅ |
| Message feedback (thumbs) | ❌ | ✅ |
| Pin / share / download a conversation | ❌ | ✅ |
| Theme switcher | ❌ | ✅ |
| Quick-ask on landing | ❌ | ✅ |

Avocado is **not behind on depth** — it is behind on **surface area**. The two
capabilities in bold at the top of the table are harder than anything in the
gap list.

---

## 3. Plan

Ordered by visible impact per unit of work. Each phase is independently
shippable and leaves the app in a working state.

### Phase A — Artifacts (highest impact, groundwork already exists)

`analysis_runs` already stores `generated_code`, `chart_url`, `result_data` and
`attempt_count`. The data is there; the surface is not.

**A1. Generalise the artifact record.**
New table `artifacts`, because artifacts should outlive the analysis path and
come from ordinary chat too:

```
artifacts
  id, workspace_id, conversation_id (nullable), message_id (nullable)
  kind            enum: html | chart | code | table | markdown
  title           text
  filename        text
  content         text            -- inline for html/code/markdown
  storage_key     text            -- object storage for binary (charts)
  version         int             -- 1-based, incremented on edit
  parent_id       uuid            -- previous version, nullable
  created_by      enum: ai | user
  model_used      text
```

Migration `0010_artifacts`. Repository `repositories/artifacts.py`, scoped by
`workspace_id` like every other repository.

**A2. Let the model emit artifacts.**
A structured-output tool the model can call to write a named document. Route
through `ModelRouter` with a new `TaskType.ARTIFACT`. Backfill: an analysis run
that produces a chart writes an `artifacts` row too.

**A3. Serve them.**
- `GET /workspaces/{id}/artifacts` — list, newest first
- `GET /artifacts/{id}` — single, with version history
- `POST /artifacts/{id}/versions` — new version (AI edit or user edit)
- `GET /artifacts/{id}/download` — raw file

**A4. Render them safely.**
`ArtifactPanel.tsx` beside the conversation. **Model-authored HTML renders in a
sandboxed `<iframe sandbox="allow-scripts">` with a null origin** — never
`dangerouslySetInnerHTML`. This is the security decision of the phase: HTML
written by a model from user documents is untrusted input, and rendering it in
the app origin would hand it the session token.

**A5. Version UI.** Version dropdown, download, view-source, open-in-tab,
duplicate, close. Right-rail list with filename and age.

*Estimate: 8–12 working days.*

### Phase B — Presets and slash commands

**B1. Model.**

```
presets
  id, org_id, created_by_user_id
  name, slug (unique per org), description
  system_prompt   text
  model_hint      text nullable
  scope           enum: private | org | published
  is_native       bool
  version         int
```

Plus `preset_pins (user_id, preset_id)` and `preset_shares (preset_id, user_id)`.
Migration `0011_presets`.

**B2. Service.** `PresetService` with the usual validator split: shape rules on
the Pydantic model, uniqueness/permission rules in `validators/`. Publishing to
org scope requires `team_admin`; only `org_admin` may mark a preset native.

**B3. Endpoints.** Full CRUD, plus `POST /presets/{id}/pin`, `/share`,
`/publish`.

**B4. Composer integration.** Typing `/` opens an inline autocomplete filtered
as you type; selecting one attaches the preset to the next message. The preset's
`system_prompt` is prepended server-side — never trusted from the client.

**B5. Presets modal.** Search, the six scope tabs, cards with slug and scope
badge, enable toggle, and a create/edit form.

*Estimate: 10–14 working days.*

### Phase C — History and conversation management

**C1. Extend `conversations`:** `pinned bool`, `title` already exists, plus a
derived message count and a status.

**C2. Endpoints.** `GET /workspaces/{id}/conversations` gains `search`,
`status`, cursor pagination. Add pin/unpin, rename, `GET /export` (markdown +
JSON), delete.

**C3. History page.** New route. Search, filter dropdown, rows with
inline-rename, author, age, message count, status chip, and pin/download/share/
delete actions. Numbered pagination.

**C4. Message feedback.** `message_feedback (message_id, user_id, rating)`.
Thumbs up/down/copy under each assistant message. This is genuinely useful
beyond parity — it is the only honest signal about answer quality.

*Estimate: 6–9 working days.*

### Phase D — Shell and Spaces polish

- Left rail: Chat / History / Presets / Spaces / Schedules, collapsible.
- Keyboard shortcuts (⇧N new chat, ⇧H history).
- Theme switcher — the token layer in `index.css` is already role-named, so a
  dark theme is one block of overrides, not a sweep.
- Quick-ask on the landing page that creates the conversation on first send.
- Rename "Workspace" → "Space" in the UI only; the code keeps `workspace_id`,
  which is load-bearing across every repository and RLS policy.
- Three-store right rail: Artifacts / Uploaded in this conversation / Files in
  this Space. Requires tagging documents with an optional `conversation_id`.

*Estimate: 6–8 working days.*

### Phase E — Schedules

`schedules (id, workspace_id, preset_id, cron, prompt, next_run_at, enabled)`.
Arq already runs recurring jobs, so the executor is a cron entry that opens a
conversation, runs the prompt, and stores the result. Deliver notifications into
the existing notification surface.

*Estimate: 5–8 working days.*

### Phase E2 — Tools and integrations

The registry is the feature; the individual integrations are content. Building
seventeen bespoke connectors is the wrong shape of work for one person, and the
industry already settled this: **implement MCP as the tool protocol** and every
integration becomes a server rather than a branch in Avocado's codebase. A wiki
connector then costs a config row, not a sprint.

**E2-1. Registry.**

```
tools
  id, org_id (null = built in)
  slug, name, description, category
  kind          enum: builtin | mcp
  endpoint      text        -- MCP server URL, null for builtin
  auth_ref      text        -- name of the secret, never the secret
  enabled_by_default bool
  context_cost_tokens int   -- measured, not guessed
```

Plus `conversation_tools (conversation_id, tool_id)` for per-thread activation.

**E2-2. Two built-ins on day one**, so the registry ships with something real:
the existing analysis sandbox as a *data explorer* tool, and workspace
retrieval as a *documents* tool. Both already exist — this exposes them through
the tool surface rather than as special cases.

**E2-3. MCP client.** One adapter under `clients/tools/`, behind the same
interface as the built-ins, so a service never knows whether a tool is local or
remote. Credentials resolve from the environment by `auth_ref`; a tool
definition never carries a secret.

**E2-4. Metered, not free.** Each tool's schema costs context whether or not it
is called. The registry stores a measured token cost per tool, the composer
shows the running total, and the modal warns before the total crosses a share
of the window. Copy the reference platform's honesty here: say it out loud
rather than letting answer quality quietly degrade.

**E2-5. Modal.** Search, the five category tabs, cards with toggles, active
count on the composer badge.

*Estimate: 12–16 working days for the registry, MCP client and modal. Each
further integration is then hours, not days.*

### Phase E3 — Conversation instrumentation

Small, cheap, and disproportionately reassuring.

**E3-1. Context gauge.** Messages already record `input_tokens`, so the
remaining window is arithmetic against the model's context length, which
`ModelSpec.context_window` already carries. Show percentage left above the
composer; warn as it falls.

**E3-2. Prompt enhance.** A wand that rewrites the draft before sending, via a
cheap-tier model call. One endpoint, one `TaskType`.

**E3-3. Welcome state.** A greeting that says what the assistant does and how
to start, in place of an empty pane. Avocado's landing pane already does the
harder half of this with grounded starter questions.

**E3-4. Timestamps and per-message share/pin.**

*Estimate: 4–6 working days.*

### Phase F — Collaboration

The genuinely hard phase. Multi-human threads need:

- `conversation_participants (conversation_id, user_id, role)`
- `@mention` parsing, storage, and notification fan-out
- Presence (online dots) — needs a WebSocket channel per conversation
- Live message push so two people see one thread update together

Avocado already has a WebSocket path for voice, so the transport exists. The
work is presence, fan-out, and the conflict cases (two people sending at once,
a model reply landing mid-edit).

*Estimate: 15–20 working days. Do this last, or not at all.*

### Phase G — Enterprise trim

Feedback link, What's New feed, notification bell with unread count, attestation
page, support/escalation footer.

*Estimate: 4–6 working days.*

---

## 4. Totals, honestly

| Phase | Days |
|---|---|
| A — Artifacts | 8–12 |
| B — Presets | 10–14 |
| C — History | 6–9 |
| D — Shell polish | 6–8 |
| E — Schedules | 5–8 |
| E2 — Tools and integrations | 12–16 |
| E3 — Conversation instrumentation | 4–6 |
| F — Collaboration | 15–20 |
| G — Enterprise trim | 4–6 |
| **Total** | **70–99 working days** |

That is **14–20 weeks full-time**, or roughly **8–12 months** at ten hours a
week. AI assistance genuinely compresses the CRUD, the migrations and the React
scaffolding — that is most of phases B, C, D and G. It compresses the hard parts
much less: the artifact sandboxing decision, the presence/conflict semantics in
phase F, and every race condition, which are found by running the thing, not by
generating it.

**Phases A + C + D + E3 — about six weeks — close most of the visible
difference.**
Artifacts and a real history page are what make the two products look like peers
in a screenshot. Phase F is what makes them peers in fact, and it costs more
than the other five combined.

---

## 5. What not to copy

- **Do not drop citations.** Grounded answers with a visible source are
  Avocado's differentiator; the reference platform's artifacts do not appear to
  carry them.
- **Do not weaken the sandbox** to make artifacts easier. Model-authored HTML
  renders in a null-origin iframe or it does not render.
- **Do not build seventeen bespoke connectors.** Implement MCP once and each
  integration becomes a server, not a branch in this codebase. The registry is
  the feature; the connectors are content.
- **Do not let tools be free.** Every enabled tool spends context whether or not
  it is called. Meter it and say so, rather than letting answer quality decay
  invisibly as someone switches more on.
- **Do not rename `workspace_id`.** The UI can say "Space"; the schema, the
  repositories and every RLS policy stay as they are.
