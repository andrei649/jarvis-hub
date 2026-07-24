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
Cowork's cloud container has **no GPU and no LM Studio**, so the default local backend won't
answer. Pick one:
- **Preferred — a cloud key.** Set `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`). The hybrid router
  will serve chat/routing through it, so agents actually reason and B/B2/D/E become real tests.
  This is the only way to grade *conversation quality* (Test-Drive Session 2, the "Hermes gap").
- **Fallback — no key.** You can still test every surface that needs no model: HUD rendering,
  Mission Control, the approval **dry-run** funnel, security guards, parity, honest empty states,
  audit log. Chat turns will degrade — **record that as an environment limitation, not a bug.**

State which backend you used in the run record (`§0` LLM backend field). A run with no model
answers a smaller set of items honestly; that's fine — just don't claim B2 passed without one.

---

## 2. Environment setup & boot

Run from the repo root. The container has Python 3.12, Node, and Chromium (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`) preinstalled — **do not** run `playwright install`.

```bash
# 1. deps (one install, full feature set). If system PyYAML conflicts, add: --ignore-installed PyYAML
pip install -r requirements-beta.txt

# 2. a model backend (pick one; skip for the no-model subset)
export ANTHROPIC_API_KEY=...        # or GEMINI_API_KEY=...

# 3. tokens so you can exercise the admin/user auth surfaces (§G)
export JARVIS_ADMIN_TOKEN=devadmin
export JARVIS_USER_TOKEN=devuser

# 4. boot on :8080 (background so you keep driving)
python serve.py &                   # → http://127.0.0.1:8080
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
> be reproduced inside a single Cowork container. Record those as **skipped — needs a second host**.

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
- **No destructive AI-OS actions.** §N (browser/desktop/house/camera operators) needs the owner's
  isolated hardware and explicit sign-off (`MANUAL_TESTING.md` §N warning). Cowork **skips** these.
- **Redact.** If any personalized `SOUL.local.md`, family data (Frigga), secrets, or camera frames
  surface, redact them in screenshots and the report.
- **Honest coverage.** A short, truthful run ("boot + HUD + B0 + memory passed; everything needing
  tokens/hardware skipped") is worth far more than a checklist ticked from assumptions. Silence is
  not success — if you didn't run it, say so.
```
