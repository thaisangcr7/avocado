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

### 1.11 Tools

A toggleable tool set with an active-count badge on the composer. Three tools
were active in the observed session.

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
| F — Collaboration | 15–20 |
| G — Enterprise trim | 4–6 |
| **Total** | **54–77 working days** |

That is **11–16 weeks full-time**, or roughly **6–9 months** at ten hours a
week. AI assistance genuinely compresses the CRUD, the migrations and the React
scaffolding — that is most of phases B, C, D and G. It compresses the hard parts
much less: the artifact sandboxing decision, the presence/conflict semantics in
phase F, and every race condition, which are found by running the thing, not by
generating it.

**Phases A + C + D — about five weeks — close most of the visible difference.**
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
- **Do not rename `workspace_id`.** The UI can say "Space"; the schema, the
  repositories and every RLS policy stay as they are.
