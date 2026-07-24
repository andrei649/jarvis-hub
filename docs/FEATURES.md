# Jarvis Hub — Features, Install & What's Next

> The one-page product sheet: everything that ships today, how to get it running, and what comes
> next on the road to 1.0. Numbers verified against `project-status.json` / `STATUS.md` on
> **2026-07-24** (v0.11.0). Deep dives: [README](../README.md) · [MOONSHOT.md](../MOONSHOT.md)
> (vision) · [NERVA_VISION.md](../NERVA_VISION.md) (AI-OS capability program) ·
> [BACKLOG.md](../BACKLOG.md) (the live plan — always wins on priorities).

---

## 1. Features at a glance

### Governed autonomy — the reason this exists

- **Risk-gated actions** — an always-on risk-tier policy holds money/social/external actions
  for approval; the unifying **Action Kernel** mediation point (budgeted, auditable, revocable)
  is rolling out behind `JARVIS_ACTION_KERNEL` (opt-in while it hardens).
- **Reversible/irreversible approval queue** — safe work happens silently; anything irreversible
  or costly waits for your one-tap approval (web, Telegram, or the mobile app). With earned
  autonomy switched on (`autonomy.earned_autonomy_enabled`, default off), approving the same
  kind of action enough times lets the system *earn* the right to stop asking.
- **Tamper-evident audit log** — hash-chained (Merkle), with a one-call integrity check.
- **Kill-switch, loop-breaker, quarantine, signed skills** — brakes that are code, not policy text.
- **High-risk automation contracts** — payments, outbound calls, social posting, host control,
  channel sends, MCP writes and more each pass an explicit contract gate before preview/enqueue.
- **Interrupt budget** — proactive ≠ noisy: urgent pushes are capped (≤4/day by default).
- **Provenance & taint tracking** — inbound content from untrusted channels is tainted at ingress
  and can never silently escalate to autonomous action.

### Local-first & private

- Runs on **your GPU** via **LM Studio / Ollama** — or any OpenAI-compatible endpoint (OpenRouter
  included). Cloud models are a per-agent, auditable **opt-in**, never the default. **$0/month**
  for the vast majority of tasks.
- **Strict-local agents** — family (Frigga), security (Ultron), digital twin (Howard) are
  code-enforced to never reach the cloud. A guarantee with a test, not a setting.
- **PII/secret scanner, SSRF protection, guardrails** (WARN/REDACT/BLOCK), encrypted secrets.
- **Backup/restore, full data export, delete/forget** — one call purges a fact from live memory
  *and* at rest.

### The cabinet — 17 specialist agents

4 tiers — command (Jarvis, Friday, Pepper, Jerome), business (Athena, Stark, Veronica, Vision,
Argus), tech (Steve, Oracle, Ultron), foundation (Gecko, Hercules, Hephaestus, Frigga, Howard) —
plus a bench of 17 more, promotable at runtime. Agents ship as templates and **personalize
themselves in your first session**; your private personality overlays stay gitignored on your
machine.

### Living memory

- Vector recall with real embeddings ⊕ a **bi-temporal knowledge graph**, fused per query (RRF).
- **Nightly consolidation** — the system reads the day, extracts people/projects/facts, decays
  what stopped mattering. It compounds: the longer you run it, the more it understands.
- Every fact **inspectable, editable, deletable**.
- A strict-local, default-off **per-turn learning loop** that distills durable facts and proposes
  skills — through quarantine and your approval, never around them.

### Proactive intelligence

- A self-tasking **autonomous cortex** finds its own work 24/7; heartbeats per agent; a
  prioritized **morning brief** + unified digest with caring follow-ups.
- **Workflow engine, model arena, quality monitor, review queue** — the operations layer that
  keeps autonomy honest.

### Channels & surfaces

- **HUD V2 cockpit** (web, SSE) · **voice** — browser-mic loop (faster-whisper STT →
  edge-tts/Kokoro TTS) ships today; the server-side wake-word pipeline is optional and needs
  extra native deps · **Telegram · email** built in; **Discord · Slack** work once their SDKs
  are installed (`pip install discord.py slack_sdk`).
- **Mobile companion app** — approvals, tasks, comms inbox, memory + knowledge graph, security
  posture (read-only where it should be).
- CLI REPL and admin panel; **400 HTTP routes** with OpenAPI→TypeScript typegen.

### Skills, plugins & execution

- **Skills system** — discover, execute, generate; import from Hermes / OpenClaw / GitHub formats;
  marketplace with signing + quarantine.
- **Sandboxed code execution** (Docker + subprocess) with environment scrubbing and output caps.
- **Plugin layer** — weather, news, Gmail, WhatsApp local bridge, Spotify, Telegram bot, cloud
  LLM… every third-party service is explicit, scope-limited, audited, and disable-able — and an
  unconfigured integration self-reports **MOCK/degraded** instead of pretending to work.
- Governed **MCP client** and Tool-RPC over an allowlist.
- **Capability Registry + unified Action API** (ORIZONT 27, code-complete) — every capability
  machine-registered and verified against reality. The `perform()` facade and *earned*
  per-capability autonomy ship **default-off** (`JARVIS_UNIFIED_ACTION_API` +
  `JARVIS_ACTION_KERNEL`; `autonomy.earned_autonomy_enabled`) until hardened.

### WorldView + Signal Layer (opt-in companions)

- **WorldView** — a time-scrubbable 4D OSINT globe (Next.js + Deck.gl), fully separate stack,
  installed only with `JARVIS_WORLDVIEW=1`, demo data clearly badged.
- **Signal Layer** (`:8787`) — provider-neutral situational awareness: evidence → signals →
  briefs → approval-gated recommendations. **Argus** bridges it read-only, governed.

### Production-grade operations

- `/healthz` + `/readyz`, graceful degradation when the local LLM is down, log rotation, systemd
  templates, release artifacts with SBOM + checksums + optional signatures.
- **5,300+ backend tests** (pytest, offline), 370 frontend (Vitest), 96 mobile (Jest), Playwright
  HUD/flow suites — the install runs the suite to prove itself.

---

## 2. How to install

### Windows 11 — one-click, no terminal

1. **`INSTALL.bat`** — first run on a clean PC: checks/installs Python + Git, gets the code,
   builds the environment, runs the tests.
2. **`START.bat`** — launches Jarvis on `http://127.0.0.1:8080` and opens the HUD.
3. **`UPDATE.bat`** — pulls the latest, reinstalls deps, re-runs tests. Anytime.

### Linux / macOS (Apple Silicon supported)

```bash
./install.sh    # venv + dependencies + test suite
./start.sh      # server + HUD (+ WorldView/Signal Layer when enabled)
```

### Manual (any OS)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt
python serve.py              # → http://127.0.0.1:8080
python -m pytest             # full offline suite
```

**Model choice by VRAM** — any LM Studio/Ollama model works: 8–12 GB → `qwen2.5:7b` /
`llama3.1:8b`; 16 GB → `qwen2.5:14b`; 24 GB+ → `gemma-4-31b-a4b` (the reference experience);
CPU-only works too (slow). The onboarding model picker tells you honestly what's reachable.
Optional companions: `JARVIS_WORLDVIEW=1` (4D globe, `:3000`), Signal Layer on `:8787` (on by
default, `JARVIS_SIGNAL_LAYER=0` to disable). Details: [README → Run](../README.md#run) ·
[USER_GUIDE.md](USER_GUIDE.md) · [COMPATIBILITY.md](COMPATIBILITY.md).

---

## 3. What's next — the road to 1.0

**Where we are: v0.11.0.** The original feature backlog (H1–H22 + WorldView) is code-complete and
the big refactor is done. **1.0 is a real destination**, gated on two tracks that run in parallel
(full table: [BACKLOG.md → Version Roadmap](../BACKLOG.md#version-roadmap)):

### Track A — the proof track (v0.12 → v0.20)

| Theme | State |
|-------|-------|
| Harden what shipped (review fixes, taint tracking) | in flight |
| Agentic-safety completeness — budgets, loop detection, HUD kill-switch, eval release gate | next |
| Upgrade & data durability — backup/restore, export, schema migrations, delete/forget | ✅ shipped |
| Operability — health endpoints, graceful shutdown, systemd, release artifacts + SBOM | ✅ shipped |
| HUD depth + observability UI (north-star panel, network monitor, LIVE/SEED truth) | mostly shipped |
| Local performance ceiling (concurrency, model-manager LRU) | queued |
| Digital twin & fine-tune — Howard's first real training run (GPU-gated) | queued |
| Quality gates + user docs (E2E, load/soak, a11y; USER_GUIDE/FAQ/UPGRADE ✅) | partial |
| **Product proof** — 1–3 design partners ≥2 weeks, north-star measured on real usage | the true critical path |

### Track B — the AI-OS capability program (v0.21 → v0.27)

| Phase | Capability |
|-------|-----------|
| ✅ ORIZONT 27 | **Capability Registry + unified Action API** — code-complete; `perform()` facade + earned autonomy stay opt-in until hardened |
| ORIZONT 28 | **Computer & browser operator** — governed Playwright + desktop actuation |
| ORIZONT 29 | **Media director** — `present()` fabric, Chromecast, session etiquette |
| ORIZONT 30 | **House brain** — Home Assistant graph, presence, governed actuation |
| ORIZONT 31 | **Camera intelligence** — privacy contract *first*, then local detection + NL clip retrieval |
| ORIZONT 32 | **Capability acquisition** — gap→search→generate→sandbox→approve→register loop |
| ORIZONT 33 | **Ambient intelligence** — the ignore/remember/monitor/act/ask/interrupt ladder |

**1.0 ships when both tracks are done** — proof with real users *and* the six pillars at their v1
bar — plus the owner's legal/brand pass and the manual-test/audit release step. The product this
becomes is **Nerva** ([NERVA_VISION.md](../NERVA_VISION.md)); `jarvis-hub` remains the repo
codename until the deliberate rename.

---

*One sentence: **a private AI that works while you sleep — owned by the person it serves.***
*Repo: <https://github.com/andrei649/jarvis-hub>*
