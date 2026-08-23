# Build progress

**Single source of truth for where the parity work stands.** Update this in the
same commit as the work it describes — a tracker that lags the code is worse
than none.

Plan and estimates: [`workspaces-parity.md`](workspaces-parity.md).

---

## Current phase

**Phase E is done. What is left of the parity plan is E3's last two items,
then Phase F (collaboration) and G (enterprise trim).**

| Step | State |
|---|---|
| A1 · `artifacts` table + migration | ✅ done |
| A2 · Repository, scoped by workspace | ✅ done |
| A3 · Service + resource schemas | ✅ done |
| A4 · Endpoints | ✅ done |
| A5 · Model emits artifacts | ✅ done |
| A6 · Frontend panel (sandboxed iframe) | ✅ done, and reachable |
| A7 · Version history UI | ✅ done |

---

## Phase status

| Phase | State |
|---|---|
| A — Artifacts | ✅ done |
| B — Presets and slash commands | ✅ done |
| C — History and conversation management | ✅ done |
| D — Shell and Spaces polish | ✅ done |
| E — Schedules | ✅ done |
| E2 — Tools and integrations (MCP) | ✅ done |
| E3 — Conversation instrumentation | 🔨 gauge done; enhance + welcome left |
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
- **Tools arrive as MCP, not bespoke connectors.** One protocol adapter, then
  each integration is a server and a config row. Seventeen hand-written
  connectors is the wrong shape of work for one person.
- **A preset never outranks the honesty rules.** It is prepended, so the
  built-in prompt — cite every claim, never fill a gap from general knowledge —
  is always the last word a model reads.
- **`PUBLISHED` is not public.** Every preset scope stops at the organisation.
  A system prompt encodes how a team works, and no scope crosses a tenant.
- **A connected system is not a document.** MCP tools take the same path web
  search does — the no-hits path only — so a grounded answer's citations keep
  meaning "from your documents". The prompt tells the model to name the system
  and say it did not come from their uploads.
- **A tool's output is data, never instruction.** It is written by whoever runs
  that server. Nothing in the client parses it for anything that decides what
  the code does, and the prompt says so for the model.
- **Tools are metered.** Each enabled tool spends context whether or not it is
  called, so the cost is measured, shown, and warned about — never silent.

---

## Known gaps

- Nothing outstanding in E2. The two gaps recorded when it was first connected
  — unreachable servers being invisible, and unmeasured context cost — are both
  closed.

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

- **Phase E** · Schedules: a prompt, a recurrence, optionally a preset. Each run opens a conversation and sends it, so a scheduled answer lands in history with its citations rather than being a special kind of object. `croniter` rather than a hand-rolled parser, and the expression is validated at the boundary — an invalid cron does not fail loudly, it simply never fires. One arq cron entry sweeping every minute, because arq's cron jobs are static and a user's schedule is not. Two executor properties have tests: one failing schedule cannot stop another tenant's, and a failure still moves the clock forward rather than retrying for ever. The UI leads with the next run time and the last error, since a schedule failing quietly for a week is what this has to be designed against. 11 backend tests, 7 frontend.
- **Phase D** · Presets reachable from the rail, not only the composer. Keyboard shortcuts (⇧N, ⇧H, ⇧P) that refuse to fire while someone is typing — these are bare letters, so without that guard a capital N in the composer would start a new conversation and lose the question. "Workspace" reads as "Space" in the UI; `workspace_id` is untouched. The theme switcher and the three-store library rail were already done, so this phase was smaller than the plan's estimate. 5 tests.
- **Phase C** · History as a page rather than a longer sidebar scroll: search, filter, numbered pagination, inline rename, pin, archive, download, delete — and a message count that comes back in the same query as a correlated scalar, since a list page is exactly where an N+1 bites. No status chip: every chat is complete the moment it stops, so "Completed" on every row would be decoration. Export is markdown with its citations, fetched through the authenticated client rather than a bare link, which would have 401'd silently. Plus message feedback — two values rather than a scale, one row per reader, showing your own rating and never someone else's. 21 backend tests, 9 frontend.
- **Phase B** · Presets: named, shareable system prompts. Org-scoped, because how a team writes does not change between workspaces. A message names one by slug and never by prompt text — the instruction is read from the row, so a client cannot post its own system prompt and drop the honesty rules with it. The preset goes *before* the built-in prompt, never after, so "always answer confidently" cannot cancel the citation rules; there is a test on the ordering, not just the presence. The turn records which preset and version it ran under, since editing one would otherwise rewrite what a past answer was told. Wired into the streamed path as well as the plain POST — the stream is what the UI actually uses, and a preset that worked only on the POST would have looked built and done nothing. 31 tests.
- **E2-3 health** · One probe per connected server answers both open questions at once: whether it is answering, and what its schemas really cost. Cached for a minute and shared with the answer path, so showing health does not make the next question slower, and bounded by a short timeout so a hanging server cannot hold the picker. The card now distinguishes connected from reachable — an unreachable server says so instead of looking fine with a switch that quietly does nothing — and `context_cost_tokens` is measured from the real `tools/list` rather than taken from whatever configuration guessed.
- **E2-3 connected** · `MCP_SERVERS` is now the whole delivery mechanism: a JSON row declares a server, and a slug matching a placeholder upgrades that card rather than adding a second one. `auth_ref` names the environment variable holding the credential, never the credential — and a named variable that is unset, a duplicate slug, or plaintext in production are all boot-time refusals rather than call-time surprises. Tools are qualified by server (`wiki__search`) so two servers offering `search` stay apart. A server that is down costs its own tools and not the turn. 25 tests. Verified against a real MCP server over a real socket, not only `MockTransport`: handshake, the session the server then required on every later call, a `tools/list` answered as SSE, a `tools/call` answered as JSON, the credential resolved from `auth_ref`, and a wrong token refused.
- **E2-3 loop** · The model can now call a tool this side runs. `generate` takes tool schemas and an executor; the Anthropic adapter loops on `tool_use` and hands results back, capped at eight rounds so a model that keeps calling cannot bill indefinitely. Every call is answered including the ones that fail — the API rejects a turn that leaves one open, and a model told nothing about a failure assumes it worked. A vendor without the loop declares `supports_client_tools = False` rather than accepting tools and ignoring them. Still not reachable by a user: no server is configured yet.
- **E2-3 client** · An MCP client over Streamable HTTP, hand-written rather than pulled from the SDK: a client needs `initialize`, `tools/list` and `tools/call`, and the SDK brings a server framework and a stdio transport this application has no use for. Handshakes once, carries the session, and keeps a hostile server from exhausting either the process or the context window — response bytes, listing pages and result text are all capped. Twelve tests against a fake server; nothing is wired to it yet.
- **A-fix** · The Phase A viewer was built but wired to nothing — no user could open an artifact. Surfaced in the right rail and renamed `ArtifactViewer`, because an unrelated `ArtifactPanel` already held that name. Verified in a browser, not just by tests.
- **First real tool** · Web search, via Anthropic's server-hosted `web_search_20260209`. No new account: it runs on the key already configured. Applies to the no-hits path only, so a grounded answer's citations keep meaning "from your documents". 10 placeholders left.
- **E2 modal** · Search, five category tabs, cards with toggles, Tools button with the active count on the composer, and the cost line stating that enabled tools are spent whether or not they are used. A placeholder's toggle is disabled rather than failing on submit.
- **E2 backend** · Tool registry with 2 real tools and 9 placeholders, per-conversation choices, and a reported context cost. A placeholder is shown but refuses to be switched on — a tool that silently does nothing would have the model report success it never had.
- **E3-1** · Context gauge above the composer. No endpoint and no request: messages already record what was sent, and `ModelSpec` already carries the window.
- **A5** · A successful analysis keeps its program as a `code` artifact, best-effort so a computation cannot fail over a panel entry. `POST /artifacts/generate` has the model author a document, which does raise on failure since it was asked for explicitly. Verified live: Opus 5 wrote a 3.2KB self-contained dashboard using the supplied figures and inventing none.
- **A6–A7** · `ArtifactFrame` renders model HTML in a null-origin sandboxed iframe with a `default-src 'none'` policy; `ArtifactPanel` adds the version picker, source toggle and download. Six tests assert the sandbox, verified by confirming they fail when `allow-same-origin` is added.
- **A2–A4** · Repository, service, resources and four endpoints. Listing returns the newest version of each artifact, not every version. HTML downloads as an attachment with `nosniff`, never as `text/html`. 19 tests including cross-tenant reads, writes and the database policy.
- **A1** · `artifacts` table, enums, migration `0011` with its RLS policy. Versions are rows sharing a `lineage_id`, not a mutable column.
