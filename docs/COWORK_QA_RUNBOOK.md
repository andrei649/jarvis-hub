# Cowork QA Runbook — drive & test the whole project like a human

> **What this is.** A self-contained brief a **Claude Cowork** session can follow to boot Nerva
> (jarvis-hub) and exercise it end-to-end *the way a person would* — open the HUD in a real
> browser, click through every surface, chat with the agents, approve/reject a governed action,
> and write up what's broken or confusing. It is the **execution wrapper** around the two runbooks
> that already exist:
>
> - [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md) — the **checklist audit** (areas A–N, the 1.0 sign-off gate). *The source of truth for WHAT to verify.*
> - [`docs/OWNER_TEST_DRIVE.md`](OWNER_TEST_DRIVE.md) — the **driving script** (6 sessions, "do X → should happen Y"). *The source of truth for HOW a human drives it.*
>
> This doc does **not** duplicate their content — it tells Cowork how to set up, which of them to
> run, how to capture findings, and what to hand back. Read both linked docs before starting.

---

## 0. TL;DR for the Cowork session

1. **Boot** Nerva on `:8080` with a working model backend and the cognition brain **on**.
2. **Sanity gate** — `/readyz` + one real chat turn + the offline suite green. If this fails, stop and report; don't test on a broken boot.
3. **Drive** the [`OWNER_TEST_DRIVE.md`](OWNER_TEST_DRIVE.md) sessions in a real browser (Chromium is preinstalled), grading each interaction and capturing every deviation in the `DID/GOT/EXPECTED/HURT` format.
4. **Audit** the no-secrets-needed rows of [`MANUAL_TESTING.md`](MANUAL_TESTING.md) §§A, B, C, D, E, G, H (skip anything marked 🔑 you don't have credentials for — record it as **skipped**, never as passed).
5. **Report** — produce a triaged findings file (blocker / annoying / cosmetic) plus a filled §0 run record, and open it as a draft PR or paste it back, per the owner's preference.

**The golden rule (this project's non-negotiable):** *an honest "can't / not configured / no data" is a PASS; fabricated data shown as real is a BLOCKER.* Most of what you're judging is whether degraded states are visible and truthful. See `MANUAL_TESTING.md` → "Notes on automated coverage".

---

## 1. Recommended model for this run

This test has two distinct "models" — don't conflate them:

### 1a. The Claude model Cowork runs as (the tester)
**Use `claude-sonnet-5` as the workhorse.** The job is long, mechanical, and browser-heavy —
boot the server, drive dozens of clicks, follow a checklist, grade replies against an honesty
rubric. Sonnet 5 is fast and cheap enough to run the whole pass without burning budget, and
capable enough for the judgment calls (is this state honest? did routing pick a sensible agent?).

**Escalate to `claude-opus-4-8` for two things only:**
- the **final triage & root-cause** pass (turning raw findings into a ranked blocker/annoying/cosmetic backlog with likely-cause pointers), and
- any **deep debugging** when a finding needs tracing through the codebase.

Rule of thumb: **Sonnet drives, Opus diagnoses.** Running the entire pass on Opus is wasteful;
running the final synthesis on Sonnet leaves quality on the table. Switch with `/model` between phases.

### 1b. The LLM backend Nerva uses to answer chats during the test
This depends on **where Cowork runs** — and the two are very different:

**Primary scenario — Cowork on the owner's own machine (recommended).** This is the point of
Nerva: Cowork runs locally and drives the real laptop as the owner would, so the **real local
backend is available**. Nerva is multi-provider by design (exactly the Hermes-style setup), so
configure all of them and let the hybrid router tier between them:
- **Local model, primary — `$0`, private.** Load a model in **LM Studio** (`:1234`) or **Ollama**.
  This is what `auto`-policy agents use first, and what strict-local agents (`frigga`, `ultron`,
  `howard`) use *only* — verifying they never leave the machine is itself a test (§B2, §G).
- **Cloud keys, for tiering/escalation — opt-in per agent.** Set any of:
  - `ANTHROPIC_API_KEY` — heavy-reasoning agents (`vision`, `steve`, `argus`) route to Claude.
  - `GEMINI_API_KEY` — large-context / `cloud`-policy agents (`athena`) route to Gemini Flash/Pro.
  - `OPENAI_API_KEY` — reached through `CloudLLMPlugin` (Anthropic/OpenAI/Gemini fallback). For
    first-class OpenAI-compatible routing, use **OpenRouter** (`OPENROUTER_API_KEY` + `OPENROUTER_BASE_URL`,
    one key → GPT and many models) or an `openai-compatible` provider profile — see the H20 provider
    registry (`agents/core/llm/providers/`, `openrouter.py`). Point the base URL at
    `https://api.openai.com/v1` to use your OpenAI subscription directly.

  The router stays **local-first**: cloud is only used when a cloud-policy agent is hit or the
  prompt is oversized (`llm.cloud_fallback` governs escalation). So a laptop run exercises the real
  thing — local for the everyday, cloud where the agent policy says so — which is exactly what you
  want to QA. **This scenario can run the whole runbook.**

**Alternative scenario — Cowork in a cloud container (like a headless CI runner).** *Then* there is
no GPU/LM Studio, so set a cloud key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` via OpenRouter /
`GEMINI_API_KEY`) so chat still reasons; the strict-local agents will fail closed (no local backend)
— **record that as an environment limitation, not a bug**. Surfaces that need no model (HUD, Mission
Control, dry-run approvals, security guards, parity, honest empty states, audit log) still test fully.

State which scenario + backend(s) you used in the run record (`§0` LLM backend field). Grading
*conversation quality* (Test-Drive Session 2, the "Hermes gap") needs at least one working
backend — don't claim §B2 passed without one.

---

## 2. Environment setup & boot

Run from the repo root. Needs Python 3.12, Node, and a browser (Chromium). On the owner's laptop use
the installed browser; in a preconfigured container Chromium is at `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`
— **do not** run `playwright install`.

```bash
# 1. deps (one install, full feature set). If system PyYAML conflicts, add: --ignore-installed PyYAML
pip install -r requirements-beta.txt

# 2a. LOCAL backend (owner's machine): load a model in LM Studio (:1234) or Ollama first.
#     Nerva auto-detects it — no env needed. This is the primary path.
# 2b. CLOUD tiering (optional, multi-provider — like Hermes). Set any you have:
export ANTHROPIC_API_KEY=...        # Claude tier (vision/steve/argus)
export GEMINI_API_KEY=...           # Gemini tier (athena, large context)
export OPENAI_API_KEY=...           # via CloudLLMPlugin fallback
# first-class OpenAI-compatible routing (recommended for an OpenAI subscription):
export OPENROUTER_API_KEY=...        # one key → GPT + many models
# export OPENROUTER_BASE_URL=https://api.openai.com/v1   # or point straight at OpenAI

# 3. tokens so you can exercise the admin/user auth surfaces (§G)
export JARVIS_ADMIN_TOKEN=devadmin
export JARVIS_USER_TOKEN=devuser

# 4. boot on :8080 (background so you keep driving)
python serve.py &                   # → http://127.0.0.1:8080
```

Confirm the backend the router actually picked before testing chat quality:
```bash
curl -s http://127.0.0.1:8080/status | python -m json.tool | grep -iE "model|backend"
# or the HUD's top-right Model badge — it names the live loaded model.
```

**Turn the brain on** (default-OFF; most "feels dumb" impressions come from testing with it off —
see Test-Drive Session 0). Either set the posture before boot or flip it live:

```bash
# PUT /api/admin/settings/{category} with body {"values": {<key>: <value>}}
curl -s -X PUT http://127.0.0.1:8080/api/admin/settings/product \
  -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"values":{"posture":"companion_wave1"}}'
# verify: posture provenance + cognition enabled
curl -s http://127.0.0.1:8080/api/security/posture -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN"
curl -s http://127.0.0.1:8080/api/cognition
```

> Note: `serve.py` runs on localhost, so tokenless requests from the same box are allowed by design
> — that's why the LAN-auth checks in `MANUAL_TESTING.md` §G (403/401 from *another* device) can't
> be reproduced from the one machine Cowork runs on. Record those as **skipped — needs a second host**
> (or drive them from the owner's phone on the same LAN if available).

---

## 3. The sanity gate (do this before any driving)

If any of these fail, **stop** — report the boot failure with logs; a broken boot invalidates the rest.

```bash
# a. readiness + version truth
curl -s http://127.0.0.1:8080/readyz
curl -s http://127.0.0.1:8080/status | python -m json.tool   # {version, agents, status:"ok"}

# b. the new Mission Control surface (H34.1) loads + its feed answers
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mission-control   # 200
curl -s http://127.0.0.1:8080/api/swarm/summary | python -m json.tool | head -30

# c. one real chat round-trip (needs a model backend)
curl -s -X POST http://127.0.0.1:8080/chat -H "Content-Type: application/json" \
  -d '{"message":"say hello in one word"}'

# d. the offline suite is green at the pinned count (proves the build itself is sound)
python -m pytest -q      # count must match project-status.json; explain any declared skips
```

The fast alternative for (a)+(c)+(d) in one shot is `python scripts/install_smoke.py --dev` (boots a
real orchestrator with a fake local backend, hits `/readyz`, runs a deterministic turn, then the suite).

---

## 4. Drive it like a human (the main event)

Open `http://127.0.0.1:8080/` in Chromium and work through
**[`docs/OWNER_TEST_DRIVE.md`](OWNER_TEST_DRIVE.md)** sessions 0–6 **in order**. That doc is the script
— each step says what to do and *what should happen*, so every deviation is a finding. Highlights of
what Cowork specifically drives with the browser:

- **Session 1 — first run as a stranger:** open a **fresh/incognito** context (clean `localStorage`)
  so the Command Center first-run gate appears; click **run** on "Say hello"; confirm the dismiss
  persists across reload.
- **Session 2 — conversation quality (the measured "Hermes gap"):** ask the 8 prompts in RO **and**
  EN, grade each 1–5, and note *what a better agent would have done*. **Needs a model backend.**
- **Session 3 — governed autonomy (the product's core):** ask for a task with one irreversible step,
  confirm the reversible part runs but the irreversible step **blocks with a dry-run preview +
  irreversibility flag**, **Approve** one and **Reject** another, open the audit log (Console → Trust),
  and hit the **kill-switch** mid-run. This is also the **⭐ B0 flagship demo** in `MANUAL_TESTING.md`
  — worth a screen recording.
- **Session 4 — memory:** tell it 3 facts, recall them in a new session (better across days), then
  **forget** one and confirm it stays gone after a restart.
- **Sessions 5–6 — proactivity & optional surfaces:** heartbeats/interrupt budget (≤4/day), and only
  the channels you have tokens for.

### Cowork browser-driving notes
- Chromium is at `/opt/pw-browsers/chromium`; launch via Playwright without downloading. If a
  project pins a different `@playwright/test`, use `executablePath` rather than re-fetching.
- Use **two contexts**: one incognito for the first-run gate (Session 1), one normal for the rest.
- **Screenshot every visual finding** and every honest/degraded state you're judging — the report is
  far more useful with before/after frames. Send them back with `SendUserFile`.
- Watch the browser console + the server log for silent errors while you click — a 200 that renders
  seed data instead of live data is the classic "wrong-but-not-failing" wiring bug this project warns about.

---

## 5. Checklist audit (the no-secrets subset)

After the drive, sweep the **credential-free** rows of [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md).
These need only a running server (+ a model for the 🤖 ones), no external tokens:

| § | Area | Cowork can run without secrets? |
|---|------|---------------------------------|
| A | Setup & onboarding | ✅ (quickstart timing, `/status` version truth) |
| B | Core chat & routing | ✅ with a model backend |
| B2 | Per-agent smoke (16) | ⚠️ the non-🔑 agents only (Jarvis, Stark, Steve, Ultron, Hephaestus, Howard…); skip Gmail/Spotify/n8n/health ones |
| C | HUD tabs & dashboards | ✅ rendering + live round-trip (analytics, cognition, arena, review queue, action approvals) |
| D | Workflows | ✅ build/run a pipeline, exercise the step kinds; AI-step-builder has a keyword fallback with no model |
| E | Autonomy & approvals | ✅ the **dry-run + approve/reject + payments-cap denial** paths (no real money moves); Telegram/escalation rows are 🔑 → skip |
| G | Security & secrets | ✅ guardrail redaction, admin-token accept/reject, secret-broker JIT; LAN-device rows → skip (single host) |
| H | Memory & RAG | ✅ notes injection, chat rooms, data spaces, A2A enable→pending gate; Qdrant/Neo4j rows are 🔑 → skip |
| F | Channels | 🔑 mostly — skip unless a token is provided |
| I | Mobile / PWA | ⚠️ responsive HUD + `/sw.js` installability via device emulation; push is 🔑 |
| N | AI-OS owner-host v1 (A8) | ❌ needs real Windows/HA/Frigate/media hardware — **skip, record as owner-host gate** |

For every ✅ you run, tick the box in a copy of the §0 table. For every 🔑/❌ you can't run, mark it
**skipped** with the reason. **Never tick a box you didn't actually exercise.**

---

## 6. Capture & report

Keep a raw findings file open the whole time, one block per observation (the `OWNER_TEST_DRIVE.md` format):

```
DID:       (what you clicked/typed / the request)
GOT:       (what happened — paste errors verbatim, attach screenshot if visual)
EXPECTED:  (what should have happened, per the runbook)
HURT:      blocker / annoying / cosmetic
```

"If you hesitated, that's a finding too" — record confusion, not just crashes.

**Deliverable at the end:**
1. A **filled §0 run record** from `MANUAL_TESTING.md` (build SHA from `/status`, model backend used, per-area pass/total, and the §K blocker table).
2. A **triaged findings report** — group the raw blocks into blocker / annoying / cosmetic, most-severe first, each with a repro and (Opus pass) a likely-cause pointer into the codebase.
3. The **screenshots/recording** of the B0 demo and any visual finding.

Hand it back per the owner's preference — either paste the report into the session, or (repo
convention) open it as a **draft PR** adding a dated run under `docs/qa-runs/` and updating the §K
blocker table. Do **not** file findings straight into `BACKLOG.md`; the owner triages first (that's
the operating model in `OWNER_TEST_DRIVE.md` → "When done").

---

## 7. Guardrails for the Cowork session

- **Local only.** Everything runs against `127.0.0.1:8080`. Do not point the test at any real
  external service, send real messages on a live channel, or move real money — the payments rail is
  a no-op by design; keep it that way.
- **AI-OS operators — owner-opt-in, safe subset only.** Since Cowork runs on the owner's own laptop,
  the §N operators (governed browser, Windows desktop actuation, house/camera) *can* be exercised —
  but **only** the reversible, safe subset with the owner's explicit go-ahead, per the `MANUAL_TESTING.md`
  §N warning (no occupied exterior lock, nothing whose rollback is uncertain, isolated targets). Default
  to **skipping** §N unless the owner opts in for a specific item; every action stays governed
  (approval queue + audit + kill-switch), so `ungoverned_actions == 0` must hold.
- **Redact.** If any personalized `SOUL.local.md`, family data (Frigga), secrets, or camera frames
  surface, redact them in screenshots and the report.
- **Honest coverage.** A short, truthful run ("boot + HUD + B0 + memory passed; everything needing
  tokens/hardware skipped") is worth far more than a checklist ticked from assumptions. Silence is
  not success — if you didn't run it, say so.

---

## 8. The launch prompt (paste this to a fresh Cowork/Sonnet session)

Copy the block below verbatim into a new Cowork session **running on the owner's machine**. It is
designed for **minimal intervention**: the agent auto-detects everything it can, asks for the few
decisions it genuinely needs **once, up front, with defaults** (so "go" is a valid answer), then runs
autonomously — including the day-long passive proactivity session — for up to ~12 hours.

```text
You are a QA agent testing Nerva (jarvis-hub) end-to-end, like a human would. Run as claude-sonnet-5.

FIRST, read these three files and follow them as the authority (do not re-derive):
  docs/COWORK_QA_RUNBOOK.md   (how you set up, drive, and report — your master plan)
  docs/OWNER_TEST_DRIVE.md    (the 6-session driving script)
  docs/MANUAL_TESTING.md      (the checklist audit + §0 run record + §K blockers)

THEN do an autonomous INTAKE (no questions yet — detect everything you can):
  1. Is a local model up? Probe LM Studio (127.0.0.1:1234/v1/models) and Ollama. Note the loaded model.
  2. Which cloud keys exist? Check env + .env for ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY,
     OPENROUTER_API_KEY (and OPENROUTER_BASE_URL).
  3. Which channel tokens exist (Telegram/Slack/Discord/WhatsApp/Email)? — determines what F can test.
  4. pip install -r requirements-beta.txt; set JARVIS_ADMIN_TOKEN + JARVIS_USER_TOKEN (generate if unset);
     turn the brain on (product.posture=companion_wave1); boot serve.py on :8080.
  5. Run the sanity gate (§3 of the runbook): /readyz, /status, one real chat turn, /mission-control +
     /api/swarm/summary, and `pytest -q`. If the boot or sanity gate fails, STOP and report that only.

THEN send me ONE consolidated message — the only time you interrupt me — containing:
  - what you detected (backend, keys, channels, sanity-gate result, build SHA from /status), and
  - these decisions, each WITH A DEFAULT so I can just reply "go":
      a) Model backend to use for the run  [default: detected local model + any cloud keys, local-first].
      b) Channels to actually round-trip in §F  [default: none — skip all, record as skipped].
      c) §N AI-OS operators (governed browser / desktop) — opt in to the SAFE, reversible subset?
         [default: SKIP all of §N].
      d) Report delivery  [default: open a DRAFT PR adding docs/qa-runs/<date>-cowork-run.md + the filled
         §0 record + §K blockers; do NOT edit BACKLOG.md — the owner triages].
      e) Time budget  [default: up to ~12h, including the Session-5 passive proactive-day sampling].
  If I reply "go" (or anything that doesn't override a default), proceed with the defaults.

THEN run autonomously to completion. Rules while running:
  - DO NOT ask me anything else unless an action is genuinely destructive/irreversible and outside the
    approved defaults. Anything you lack (a token, a service, hardware) → record it as SKIPPED with the
    reason and MOVE ON. Never block, never tick a box you didn't actually exercise.
  - Keep a running findings file qa-findings-<date>.md, one block per observation:
        DID: / GOT: (paste errors verbatim; screenshot visual issues via SendUserFile) / EXPECTED: / HURT: blocker|annoying|cosmetic
    Checkpoint it after every session so nothing is lost if you're interrupted.
  - Drive the real browser (open the HUD at 127.0.0.1:8080). Work OWNER_TEST_DRIVE sessions 0→6 in order,
    then the credential-free MANUAL_TESTING subset (§5 table in the runbook: A,B,B2 non-🔑,C,D,E,G,H).
    Screenshot the ⭐B0 governed-autonomy demo and every visual finding.
  - This is what fills ~12h: after the active sessions, leave the server running and run Session 5
    (passive proactive day) — sample the HUD/logs every ~1–2h, confirm the morning brief fires once and
    interrupts stay ≤4/day, and note whether ANY proactive output was actually useful. Post a one-line
    progress note to me at each sample (no questions), so I can see it's alive without steering it.
  - The golden rule: an honest "can't / not configured / no data" is a PASS; fabricated data shown as
    real is a BLOCKER. Most of what you grade is whether degraded/empty states are visible and truthful.

AT THE END, deliver: (1) the filled MANUAL_TESTING §0 run record + §K blocker table, (2) a TRIAGED report
— findings grouped blocker / annoying / cosmetic, most-severe first, each with a repro and a likely-cause
pointer into the codebase (switch to claude-opus-4-8 for this synthesis pass if you can), (3) the
screenshots/recording, delivered per decision (d). Local-only throughout: never move real money, send a
real message on a live channel, or run an unapproved §N action; redact any SOUL.local/family/secret/camera data.
```

Notes for the owner:
- If you want to skip the intake entirely, pre-set the keys/tokens in `.env`, load your model in LM
  Studio, and reply **"go"** to the agent's one message — it proceeds on the defaults.
- **Sonnet drives, Opus diagnoses:** the run is cheap on Sonnet; only the final triage benefits from
  Opus. If your Cowork session can't switch models mid-run, running the whole thing on Sonnet is fine.
- The agent posts a progress line at each passive-day sample so you can confirm it's alive without
  intervening — that's the "runs 12h, minimal touch" shape.
