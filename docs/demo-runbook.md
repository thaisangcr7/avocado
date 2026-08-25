# Demo runbook

A beat-by-beat script for recording a short product video, or for showing
Avocado live. Roughly three minutes of footage.

The shape it is built around: the app is *already open and working* in the
first second, the viewer understands what it is within ten, and every claim
after that is something they watch happen rather than something they are told.

---

## Before you record

**1. Reseed.** The local database drifts as soon as anyone tests against it —
uploads land in the wrong workspace, throwaway threads collect in the sidebar,
and the Sandbox workspace stops being empty, which kills the last beat.

```bash
python3 backend/scripts/generate_demo_data.py --reset
```

This wipes the local database, including any account you made by hand. The new
login is written to `backend/.demo-data/latest/manifest.json`. Do this *before*
you set up the shot, not between takes.

**2. Check the stack is warm.** Ask one throwaway question and delete the
thread. A cold first request pays for a connection pool and a model handshake,
and that latency is the one thing you cannot edit out gracefully.

**3. Set the window up.**

- Browser at a wide window — the three-column shell (threads · chat · Library)
  is the layout worth showing, and it collapses to overlays below 1024px.
- Pick a theme deliberately. The toggle is at the foot of the left rail; dark
  reads better on video, light reads better in a slide deck.
- Hide the bookmarks bar and any extension icons.
- Browser zoom at 100%. Anything else makes the citation chips look wrong.

**4. Do not sign in.** That is the point of the first beat.

---

## The shot list

### 0:00 — Open the app · *no login screen*

Navigate to:

```
http://localhost:5173/demo
```

It opens **signed in**, on the Northwind HQ workspace, with the landing pane
showing: *"12 documents ready · 5 spreadsheets for analysis."*

> **Say:** "This is a team's own documents and spreadsheets. Ask it anything —
> every answer either cites the source it came from, or shows the code it ran."

That is the whole product in two sentences. Nothing else is claimed until it
has been shown.

### 0:15 — Beat 1 · A cited answer to a question nobody wrote down

Type, or click the **Semantic check** suggestion, which already offers it:

```
If I don't use all my paid days off this year, how many roll into next year?
```

The answer comes back: **up to five days carry over, anything beyond that is
forfeited at year end**, with a citation chip under it.

> **Point at:** the citation chip. Click it. The passage it quotes says
> *"unused balance carries over… up to a cap of five days."*

> **Say:** "The question and the document share almost no words — no 'carry
> over', no 'cap', no 'vacation'. A keyword index misses this. It matched on
> meaning, and it showed me where it got it."

### 0:45 — Beat 2 · The moment it refuses to guess

```
Do I need a receipt for a $60 taxi ride?
```

It answers **no — the threshold is $75** — cites the receipts section, and then
adds, unprompted, that the sources do not mention taxis specifically, so that
part is inference rather than a written rule.

> **Say:** "That last paragraph is the difference. It answered, and it told me
> exactly how far the document actually goes."

This is the beat to protect if the video has to be cut shorter. It is the one
thing a general chat assistant does not do.

### 1:15 — Beat 3 · A number that came from running code

Open the **Library** (top right), find `revenue_by_region.csv`, hit **Analyse**.
Ask:

```
What is the month-over-month revenue trend by region?
```

It writes pandas, runs it in a locked-down container, and returns the computed
result with a chart — and the program that produced it. The panel shows the
table profile first (`800 rows x 10 columns`, every column typed), which is
worth a beat on its own.

**Timing, measured:** about seventeen seconds from pressing *Run analysis* to
the result rendering. That is a cut in the edit, or somewhere to talk over.
**The result renders below the question box**, so scroll the Library panel down
to it — do not leave the shot sitting on the button.

> **Point at:** the Method tab, which holds the generated code.

> **Say:** "It ran over the whole file, not the part that fits in a prompt. The
> number is a computation, and the code is right there to check."

### 1:50 — Beat 4 · A whole-workspace report, and it persists

Back in the chat:

```
Give me an executive summary of the whole workspace
```

A multi-section dashboard renders: a headline verdict with a status badge, a
KPI strip, per-theme sections with charts, and a **Limits** note. **Reload the
page.** It is still there.

The limits note is the part to point at. In a measured run it said, unprompted,
that forecast and actual revenue are separate datasets at different scales and
should not be summed, and that the support data shows volumes but not
resolution outcomes, so the backlog gap is a volume signal and not a quality
one. That is a report arguing with itself in public.

> **Say:** "Every headline figure there is computed across every spreadsheet in
> the workspace. And it is saved on the message, not regenerated — that is a
> document the team keeps."

### 2:30 — Beat 5 · What happens when the documents do not cover it

The header carries a grounding control — **Grounded only** / **General
fallback** — and the strongest version of this beat is to show both, because
the point is that it is a *setting* rather than a hope.

On **General fallback**, ask something the documents plainly do not cover:

```
What is the capital of France?
```

It answers — *Paris* — but stamps the reply **GENERAL ANSWER · Not from
documents** and opens with "this isn't grounded in your uploaded documents".

Then switch the control to **Grounded only**, switch the Space picker to
**Northwind Sandbox** (empty after a reseed), and ask the policy question from
Beat 1 again. Now it declines rather than answering.

> **Say:** "Same model, same question. One setting decides whether it may
> answer from outside your documents — and when it does, it says so on the
> message."

Check which mode the header is in before you record. It is per-workspace and
it persists, so it will be wherever it was left.

### 2:45 — Close

Leave the shell on screen with the Library open. Nothing to say over it.

---

## If you have another thirty seconds

In rough order of how well they show on camera:

- **Voice** — the microphone in the composer. Needs `DEEPGRAM_API_KEY` and
  `STT_PROVIDER=deepgram`; the button hides itself when they are unset.
- **Presets** — `/` in the composer. A named system prompt the team shares.
- **Schedules** — a prompt that runs on a recurrence, with the answer landing
  in history and a notification in the bell.
- **Artifacts** — the Library's top shelf, holding what previous answers
  produced. Model-authored HTML renders in a sandboxed null-origin iframe.

## What not to do on camera

- **Do not upload a file live.** Ingestion is quick but not instant, and dead
  air is worse than a cut.
- **Do not open Spaces you have not reseeded.** Northwind Finance is there to
  prove tenant separation exists, not to be toured.
- **Do not ask a broad corpus question** such as *"what policies exist here?"*.
  Most seeded documents are deliberately templated filler; only
  `time-off-policy.md` and `expense-policy.md` are complete prose, and a broad
  question makes the assistant honestly report how thin the rest is. Every
  question in the shot list above lands on the two real documents.

---

## Why these questions

The two policy documents in the seed are written out in full — structure and
figures modelled on the GSA TTS Handbook, which is public domain under CC0 1.0
— precisely so a demo has something real to retrieve against. They carry
specific, checkable facts: accrual rates by tenure, a five-day carry-over cap,
a $75 receipt threshold, a 20% trip-budget ceiling, a five-business-day filing
deadline.

The questions above are chosen so each one shows a *different* property:

| Beat | Question | What it proves |
|---|---|---|
| 1 | Paid days off rolling over | Semantic retrieval, not keyword matching |
| 2 | Receipt for a $60 taxi | It answers *and* marks the edge of the source |
| 3 | Month-over-month trend | Real computation over the whole file |
| 4 | Executive summary | Computed figures, persisted as an artifact |
| 5 | Capital of France, then an empty Space | Off-document answers are labelled, and grounding is a setting |
