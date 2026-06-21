# Manual Testing Guide

> **Why this exists.** The automated suite (~2,400 tests) runs fully offline with
> mocked LLMs, channels, and hardware. It proves the *logic* is correct, but it
> **cannot** verify anything that needs a real model, a live channel token, a
> browser, an external service (Qdrant/Neo4j/n8n), or a human looking at the HUD.
> This document lists everything a human should verify by hand before trusting a
> release, grouped by area, with prerequisites, steps, and expected results.

**How to use it:** work top-to-bottom. Each item has a checkbox. Anything marked
**🔑 needs secrets/services** requires real credentials or running infra;
**🤖 needs LLM** requires a working model backend (Ollama/local or a cloud key);
**👁 visual** means "look at the HUD and confirm it renders/behaves".

Legend for coverage: ✅ logic covered by automated tests (you're only checking the
real-world wiring) · ⚠️ partially covered · ❌ no automated coverage (test carefully).

---

## 0. Run record & 1.0 sign-off

> This runbook **is the release step that tags a version** (the human verification before any tag, 1.0 included). A clean pass — every critical area ✅
> with no open ❌ blocker — *plus* the green offline suite (**~2,400 passed, 2 skipped**) is what
> clears tagging `v1.0.0`. Record results inline (tick the box; for any ❌/⚠️ add a one-line note
> and log it in **§K Blockers**). Fill this header on each run.

| Field | Value |
|---|---|
| Date / tester | |
| Build (`/status` version + git sha) | |
| Hardware | e.g. RTX 5090 box (Bonobo WS) |
| LLM backend + model | e.g. LM Studio · `google/gemma-4-12b` |
| Services up | Qdrant ☐ · Neo4j ☐ · n8n ☐ |

| § | Area | Pass / Total | Open blockers |
|---|---|---|---|
| ⭐ | Governed demo (§B0) | pass ☐ | |
| A | Setup & onboarding | / | |
| B | Core chat & routing | / | |
| B2 | Per-agent smoke | / 16 | |
| C | HUD tabs | / | |
| D | Workflows | / | |
| E | Autonomy & approvals | / | |
| F | Channels | / | |
| G | Security & secrets | / | |
| H | Memory & RAG | / | |
| I | Mobile / PWA | / | |

**Sign-off:** ☐ all critical areas pass · ☐ no open ❌ blocker (§K) → **cleared to tag `v1.0.0`.**  Signed: ____________

---

## ⭐ B0. The governed-autonomy demo  (flagship — also your launch demo)

The single end-to-end story that proves the wedge — *capability + governance + audit, visibly, in one flow.* Worth screen-recording (this is your demo GIF / Show-HN clip).

- [ ] Ask Jarvis to do a **real multi-step task with one irreversible step** (e.g. "draft and send an email to <you>", "pay invoice X").
- [ ] **Reversible** steps run autonomously; the **irreversible** step **blocks** with a decision card (Telegram / HUD) showing a **dry-run preview + irreversibility flag**.
- [ ] **Approve** it → it executes. Trigger another and **Reject** → it does not.
- [ ] Open the **audit log** (`/security` / `GET /api/admin/audit`) → every tool call is recorded and hash-chained (tamper-evident).
- [ ] Hit the **kill-switch** mid-run → autonomy halts immediately.
- [ ] (Privacy) a **Frigga** (family) interaction makes **zero outbound network calls**.

---

## A. Setup & onboarding  (H7.9)

Prerequisites: a clean machine (or fresh clone), Docker optional.

- [ ] **Quickstart from scratch** ❌ — Follow `README.md` on a clean Linux/Mac.
  Target: a running server in **under 10 minutes**. Note any step that stalls.
- [ ] **`docker-compose up`** 🔑 — Brings up server + Qdrant + Neo4j + n8n.
  Expected: all containers healthy; `GET /status` returns `{version, agents, status:"ok"}`.
- [ ] **Env vars / secrets** — Copy `.env.example` (if present) and set the keys
  you intend to use (LLM backend, channel tokens). Confirm the server logs show
  each integration as enabled/disabled correctly (no silent failures).
- [ ] **Version truth (H7.8)** ✅ — `GET /status` version matches
  `agents/__init__.py` `__version__`. (Single source of truth.)
- [ ] **Release workflow** — Push a tag; confirm the GitHub Release is created
  (`.github/workflows/release.yml`).

---

## B. Core chat & agent routing  🤖

Prereq: working LLM backend.

- [ ] **Basic chat** ❌ — Open the HUD (`/`), send a message, get a coherent reply.
- [ ] **Agent routing quality** 🤖 — Send domain-specific prompts (finance, code,
  etc.) and confirm they route to sensible agents. (Routing *logic* is tested;
  *quality* of selection needs human judgement.)
- [ ] **Streaming** ❌👁 — Confirm `/chat` streaming renders token-by-token in the HUD.
- [ ] **Multi-agent synthesis** 🤖 — A prompt that fans out to several agents
  returns a single coherent synthesized answer.
- [ ] **Conversation history** ✅ — Reload the HUD; prior turns persist for the session.

---

## B2. Per-agent smoke  🤖

One signature action per agent against a **real** backend. Tick each; note any that misroute, error, or claim a capability they don't have.

- [ ] **Jarvis** — synthesizes a multi-domain prompt into one coherent answer
- [ ] **Friday** — morning brief (weather + news + market signal)
- [ ] **Pepper** — calendar read + Gmail triage summary 🔑
- [ ] **Jerome** — Spotify now-playing / playback control 🔑
- [ ] **Athena** — a strategy / brand answer (cloud-escalated) 🤖
- [ ] **Stark** — a KPI / analytics summary
- [ ] **Veronica** — drafts a post/email in a chosen voice profile
- [ ] **Vision** — a **cited** web-research synthesis 🔑
- [ ] **Steve** — system-health report (CPU/GPU/RAM/temp)
- [ ] **Oracle** — an n8n workflow action 🔑
- [ ] **Ultron** — a security / port-scan / threat note
- [ ] **Gecko** — a balance read (ING/Libra/CSV) — **confirm the IBAN is masked (`…NNNN`)**
- [ ] **Hercules** — health/fitness (sleep / HRV / steps) 🔑
- [ ] **Hephaestus** — a project / PM status update
- [ ] **Frigga** — a family record — **confirm strict-local: zero network calls**
- [ ] **Howard** — personal-twin recall / RAG answer

---

## C. HUD tabs & dashboards  👁

All backends are automated-tested; **these checks are about the UI rendering and
the live round-trip.**

- [ ] **Dashboard / agents / ticker** 👁 — Cards render, agent count is correct,
  live ticker updates.
- [ ] **Cost & Usage Analytics (H7.10)** 🤖👁 — `GET /api/analytics/cost`. After a
  few real LLM calls, the tab shows per-agent cost + monthly projection from
  **real** token data (local models should show ~$0).
- [ ] **Cognition / APM / run history (H10.16/17)** 👁 — Traces and timings appear
  for recent requests.
- [ ] **Live Quality Monitor (H10.23)** ⚠️👁 — `GET /api/quality`. After traffic,
  the rolling average populates; force low-quality replies and confirm the
  **alert fires** when avg drops below threshold (`POST /api/quality/threshold`).
- [ ] **Model Arena (H10.19)** 🤖👁 — Run the same query against 2+ models, confirm
  responses show **anonymized** (A/B, no model names), vote, and the leaderboard
  ELO/win-rate updates. `POST /api/arena/run`, `/vote`, `GET /api/arena/leaderboard`.
- [ ] **Human Review Queue (H10.25)** ⚠️👁 — Low-scoring traces auto-appear; flag one
  manually; score against the rubric; thumbs up/down; "add to dataset" and confirm
  it lands in an eval dataset. `GET /api/review/queue`, `POST /api/review/{id}/vote`,
  `/dataset`.
- [ ] **Action-Level Approval (H10.18)** ⚠️👁 — Pending tool-calls show in the live
  tab with a dry-run preview; Approve/Reject each; confirm a blocked tool flow
  unblocks on approval. `GET /api/actions/pending`, `POST /api/actions/{id}/decide`.

---

## D. Workflows  (H5.6, H10.x)  🤖

Prereq: working LLM for agent steps; transform/guardrail steps are deterministic.

- [ ] **Visual Builder** 👁 — Build a pipeline in the HUD, save, run, and watch the
  live trace overlay (H10.2) light up each step.
- [ ] **AI step builder (H10.7)** 🤖 — In the builder, describe a step in plain
  language (`POST /api/workflows/step/generate`); confirm it returns a sensible
  step config (e.g. "redact secrets" → a `guardrail` step). With no LLM the
  deterministic keyword fallback still returns a usable step.
- [ ] **Step kinds end-to-end** 🤖 — In one pipeline exercise each:
  - `agent` (normal), `router` (H10.13 — picks a route), `critic` (H10.15 — scores
    + retries), `transform` (H10.3 — formatter/validator/json_extract/summarize),
    `guardrail` (H10.4 — redacts/blocks a secret you plant), `loop` (H10.6 —
    iterates until condition), `subflow` (H10.14 — nested sub-pipeline runs).
- [ ] **Hierarchical workflow (H10.11)** 🤖 — `POST /api/workflows/hierarchical` with
  a manager + crew; confirm it runs the crew, **redistributes to a fallback on a
  forced failure**, and synthesizes a final answer.
- [ ] **Python flow decorator (H10.9)** — Define a flow with `@jarvis_flow`/`@step`/
  `@listen`/`@router`, `build_flow(cls)`, run it — confirm it behaves like a
  builder-authored pipeline.
- [ ] **Structured outputs / termination (H10.10/12)** ✅⚠️ — Confirm schema'd steps
  expose typed fields and a `terminate_when` guard halts the pipeline.

---

## E. Autonomy, approvals & escalation  (H6.x, H12.x)

- [ ] **Decision inbox via Telegram (H6.2)** 🔑 — A proactive task pushes a decision
  card to Telegram with Approve/Reject buttons; tapping one transitions the task.
- [ ] **Dry-run preview (H12.5)** ✅ — The decision card / `POST /api/autonomy/preview`
  shows what the action *would* do + irreversibility, **before** approval.
- [ ] **Governed payments (H16.3)** ✅ — Create a mandate (`POST /api/payments/mandates`)
  with a per-payment + total cap and a payee allowlist. Confirm a request over
  the cap / to an unlisted payee is **denied** (never pending); an admissible one
  is **pending** and only **settles after explicit approve**; cumulative spend
  can't exceed the total. (No real rail — nothing actually moves money.)
- [ ] **Escalation channels (H12.11)** 🔑 — Configure `autonomy.escalation_channels`;
  `POST /api/autonomy/escalate` delivers to the allowed channels only (Slack/Discord/
  WhatsApp/…), best-effort. Verify each configured channel actually receives it.
- [ ] **NL scheduling (H10.27)** ⚠️ — `POST /api/schedule/parse` with "every weekday
  at 7am" / "în fiecare luni la 9" → correct cron. Then schedule a real job and
  confirm **it actually fires** at the time (needs `apscheduler` installed).
- [ ] **Learning loop (H7.11)** ⚠️ — Generate enough interactions to a source agent,
  run `POST /api/learning/propose` (or wait for the weekly job), confirm a gated
  `agent_promotion` proposal lands in the decision inbox, and **approving it
  activates the bench agent**. Verify the cadence via
  `autonomy.learning_loop_interval_hours`.

---

## F. Channels  🔑  (H1.3 + adapters)

Each needs a real token/account and a live round-trip (send → receive → reply).

- [ ] **Telegram** 🔑 — Inbound message handled; outbound reply received.
- [ ] **Slack** 🔑 — Same round-trip.
- [ ] **Discord** 🔑 — Same round-trip.
- [ ] **WhatsApp / Signal** 🔑 — Same round-trip (if configured).
- [ ] **Email** 🔑 — Inbound parsed; outbound sent.
- [ ] **Voice / TTS** 🔑❌ — Speech in/out works; latency acceptable.
- [ ] **Embeddable chat widget (H10.1)** ⚠️👁 — Issue a token (admin
  `POST /api/admin/widgets`), embed `<script src=".../api/widget/{token}">` on a
  **separate** test HTML page, confirm the bubble renders with your theme and a
  message round-trips via `/api/widget/{token}/message`. Check CORS from the
  external origin.

---

## G. Security & secrets  (H4.9, H12.1, H15.x)

- [ ] **Secret broker JIT injection (H15.4)** ⚠️ — Store a secret
  (`POST /api/secrets/broker`), put its `{{secret:NAME}}` handle in an agent
  config/prompt, and confirm: (a) the **handle never resolves to plaintext in the
  agent context / logs**, (b) the real value is injected **only at action time
  behind approval**, (c) `POST /api/secrets/broker/redact` masks any leaked value.
- [ ] **Guardrails (H4.9)** ✅ — Send a prompt containing a fake API key / email;
  confirm scanners redact/block per mode, globally and as a workflow node (H10.4).
- [ ] **Admin-guarded endpoints** ✅🔑 — Confirm admin routes (widgets, quality
  threshold, action decide, escalate, learning propose, secrets) reject without a
  valid `X-Admin-Token` and accept with it. Set a strong `ADMIN_TOKEN` in prod.
- [ ] **User-guarded endpoints (HF-1)** ✅🔑 — From **another device on the LAN**
  (not localhost), hit `/chat`, `/api/memory/remember`, `/sandbox/execute` with
  **no** token: expect **403** when `JARVIS_USER_TOKEN` is unset, and **401**
  when it's set but the header is missing/wrong. Set `JARVIS_USER_TOKEN`, open
  the HUD from the phone, enter the token at the prompt, and confirm chat +
  memory work. Localhost still works with no token.
- [ ] **Sandbox (code execution)** ❌🔑 — Run a sandboxed snippet; confirm isolation
  limits (size cap H7.5, timeouts) hold.
- [ ] **Rate limit + CORS (HF-2)** ✅🔑 — From **another LAN device** with no token,
  hammer any endpoint past `JARVIS_RATE_LIMIT` (default 120/min) → expect **429
  + Retry-After**; confirm localhost and a valid `X-User-Token` are **not**
  throttled. If `JARVIS_CORS_ORIGINS` is unset, a cross-origin `fetch` from a
  foreign page is blocked; set it and confirm the allowed origin works.

---

## H. Memory, RAG & integrations  🔑

- [ ] **Vector memory / RAG (Qdrant)** 🔑🤖 — Ingest documents; ask a question whose
  answer is only in them; confirm grounded retrieval.
- [ ] **Knowledge graph (Neo4j)** 🔑 — Entities/relations populate and are queryable.
- [ ] **Data Spaces / agent scope (H10.26)** ✅ — Define a space over some memory
  categories (`POST /api/memory/spaces`), assign an agent (`/assign`), then
  `GET /api/memory/profile?agent=<id>` returns **only** those categories; an
  unassigned agent (or no `agent`) sees everything.
- [ ] **Ingestion pipeline** 🔑 — Feed a source; confirm it lands in memory/graph.
- [ ] **MCP server mode (H10.5)** 🔑 — Connect an MCP client; confirm Jarvis agents
  are exposed as governed tools (LAN-only by default).
- [ ] **Webhooks / ambient triggers (H10.8)** 🔑 — `POST` to `/api/webhooks/...`;
  confirm it routes into the escalation inbox.
- [ ] **A2A endpoint (H16.2)** ✅🔑 — With `JARVIS_A2A_ENABLED` unset, confirm
  `/.well-known/agent-card` and `POST /api/a2a/task` return 404. Enable it,
  allowlist a peer (`POST /api/a2a/peers`), and confirm a task signed with that
  peer's secret lands in `GET /api/a2a/inbox` as **pending** (never auto-run),
  while a wrong/absent signature is 401. Approve one via `/decide`.
- [ ] **Conversation notes (H10.21)** ✅⚠️ — Set a note (`PUT /api/notes`), send a
  chat turn, confirm the note is injected as context (e.g. "always reply in
  French" changes behavior); "Rewrite with AI" (`POST /api/notes/rewrite`) works.
- [ ] **Chat rooms (H10.20)** ✅⚠️👁 — Create a room with an agent roster, `@mention`
  a specific agent, confirm the turn routes to it and room context is applied;
  history persists.

---

## I. Mobile / PWA  👁

- [ ] **Responsive HUD** 👁 — Open on a phone; layout adapts.
- [ ] **PWA install / service worker (`/sw.js`)** 👁 — Installable; offline shell loads.
- [ ] **Push / proactive notifications** 🔑 — Proactive messages reach the device.

---

## J. Regression smoke (each release)

- [ ] `pytest tests/` is green — **~2,400 passed, 2 skipped** (the 1 skip is the optional
  heartbeat path). `apscheduler` is bundled in `requirements-beta.txt`, so the suite runs
  clean from the one-command install (`./install.sh` / `INSTALL.bat`).
- [ ] `GET /status` → `ok`. HUD loads. A chat round-trip works.
- [ ] No secrets in logs (grep the log for any planted secret value).

---

## K. Blockers found  (fill during the run)

| # | § | Severity | What broke | Repro | Owner / fix |
|---|---|----------|------------|-------|-------------|
|   |   |          |            |       |             |

**1.0 sign-off rule:** the run clears `v1.0.0` when this table has **no open blocker** — every
row is either fixed or explicitly accepted as out-of-1.0 scope (say which).

---

### Notes on automated coverage

The following are **fully logic-tested offline** — manual checks are only to
confirm real-world wiring (tokens, models, rendering), not correctness:
arena scoring/ELO, quality scoring + alert, review-queue state machine, action
approvals (incl. async await), escalation routing/allowlist, secret broker
inject/redact, NL→cron parsing, notes store + injection, rooms routing,
all workflow step kinds (transform/guardrail/loop/subflow/router/critic),
hierarchical manager redistribution, flow-decorator compilation, learning-loop
proposal gating, dry-run irreversibility classification, widget store + snippet.

If a manual check fails but its automated test passes, the bug is almost always
in the **wiring** (config, token, model backend, CORS, service availability),
not the core logic — start there.
