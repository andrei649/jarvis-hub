# Jarvis Hub — "Andrei's Cabinet"

![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-2156%20passed-brightgreen?logo=pytest)
![Version](https://img.shields.io/badge/version-9.9.9-orange)

> 17 specialized AI agents orchestrated through Jarvis, running on Bonobo WS + Pi 5, controlled by voice and web.

**A local-first, _governed_ personal AI — the always-on agent the 2026 "OpenClaw" wave proved people want, with the governance, audit, and privacy it's missing.** Runs entirely on your own hardware (LM Studio / Ollama on your GPU) — **$0/month, no cloud by default**. Every autonomous action passes through a reversible/irreversible **approval queue** and a tamper-evident **audit log**, with full observability — and a **family agent that never touches the internet**.

**Get running in minutes →** [Quickstart](#run) · one-click `INSTALL.bat` on Windows.

<!-- TODO(launch): demo GIF above the fold — 30–60s of a real task incl. one approved irreversible step -->

---

## What this is

A personal AI mesh that handles the cross-section of Andrei's life: work at Raiffeisen + Digitaholic, family with Alexandra and Max, the BMW E93, the build at Cosmina de Sus, fitness, finance, content. Each domain has a dedicated agent. They talk to each other through Jarvis. They learn from interactions.

## Architecture

**Pure local Python + opt-in plugin layer.** *Not* OpenClaw — deliberately: where the viral 2026 rival stores secrets in plaintext and runs ungoverned community skills (which made it the #1 infostealer target of 2026), here every action is gated by a reversible/irreversible approval queue, guardrails, and an audit log. No cloud dependency by default. Every third-party service is an explicit, scope-limited, audit-able, disable-able plugin.

## The cabinet

**CNS (Command tier)** — 4 agents:
- **Jarvis** — Prime Orchestrator. The voice you wake.
- **Friday** — Daily Intel. Weather + news + market signal.
- **Pepper** — Chief of Staff. Calendar + meetings + reflection.
- **Jerome** — Leisure & Soundtrack. Music, retro tech, decompression.

**Business tier** — 5 agents:
- **Athena** — External Strategist. Digitaholic, personal brand, CMO trajectory.
- **Stark** — Internal Corporate Intel. Raiffeisen KPIs, board prep, channels.
- **Veronica** — The Voice. Drafts emails, posts, captions in 5 voice profiles.
- **Vision** — Deep Researcher + OSINT. Cited synthesis, regulatory watch.
- **Argus** — Geoint Sentinel. Read-only, governed bridge to WorldView (4D OSINT).

**Tech tier** — 3 agents:
- **Steve** — CTO + Infrastructure. Bonobo + Pi + models + backups.
- **Oracle** — Pipeline Weaver. n8n workflows, silent when working.
- **Ultron** — The Shield. Firewall, GDPR/ATT, smart home VLAN.

**Foundation tier** — 5 agents:
- **Gecko** — Capital Allocator. Numbers cold; no advice.
- **Hercules** — Physical Engine. Sleep, recovery, snowboard prep.
- **Hephaestus** — Builder & Mechanic. BMW E93 N54 + Cosmina build.
- **Frigga** — The Matriarch. Max + Alexandra + Beads & Blush. Local-only.
- **Howard** — Digital Twin (emerging). Voice clone, personal RAG, fine-tune candidate. Local-only.

## Hardware

- **Bonobo WS** (Pop!_OS) — Intel Core Ultra 9, 192GB DDR5, RTX 5090 24GB, 4× NVMe + 18TB HDD
- **Pi 5** — always-on services (Qdrant, Neo4j, n8n, Homebridge)

## Stack

- **Orchestration:** Python 3.12 + asyncio + FastAPI
- **LLM inference:** LM Studio (OpenAI-compatible, primary) → Ollama (fallback) → optional cloud (Anthropic/OpenAI) for approved agents
- **Model:** `google/gemma-4-31b-a4b` (MoE, ~4B active params) on RTX 5090
- **Voice:** openWakeWord + faster-whisper + edge-tts / Kokoro
- **Memory:** conversation history (JSONL) + vector store (real embeddings via LM Studio/Ollama, hash fallback) + knowledge graph + fused recall (RRF, vector ⊕ graph) + SQLite checkpoints (WAL)
- **Channels:** web (SSE), voice, telegram, discord, email, slack
- **Security:** PII/secret scanner, SSRF protection, audit log (Merkle chain), guardrails (WARN/REDACT/BLOCK)

### WorldView (4D OSINT) — companion stack

A separate, self-contained **Next.js + Deck.gl + Fastify** stack under [`worldview/`](worldview/) (frontend `:3000`, API `:4000`, infra via Docker: Redpanda/TimescaleDB/Redis) — a time-scrubbable 3D globe fusing air/sea/space/cyber OSINT. It shares no runtime with `agents/`. `INSTALL.bat`/`START.bat` (and `install.sh`/`start.sh`) set it up and auto-start it alongside JARVIS; opt out with `JARVIS_WORLDVIEW=0`. The **Argus** agent queries it read-only and governed. No Mapbox token or API keys are needed for the demo (`npm run db:seed`). See [`worldview/README.md`](worldview/README.md).

## Run

### Windows 11 — one-click (no terminal needed)

1. **`INSTALL.bat`** — first time on a clean PC. Checks/installs Python + Git
   (via winget), gets the code, builds the environment, installs everything,
   runs the tests. Double-click and follow the prompts.
2. **`UPDATE.bat`** — double-click to pull the latest from GitHub, install
   dependencies, and run the tests. Run this whenever you want the newest version.
3. **`START.bat`** — double-click to launch JARVIS (`:8080`) **and** WorldView
   (the 4D OSINT globe at `:3000`) and open the HUD. Keep its window open; close
   it to stop the server. WorldView opt-out: `set JARVIS_WORLDVIEW=0`.

### Manual (any OS)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt                 # one install — full feature set
python serve.py              # → http://127.0.0.1:8080
python -m pytest             # 2156 passed, 1 skipped
```

_Linux/macOS shortcut:_ `./install.sh` does all of the above (venv + install + tests); `./start.sh` launches the server.

- **HUD:** http://127.0.0.1:8080/ — the **V2 cockpit** (primary HUD; legacy HUD at `/v1`, override with `JARVIS_HUD=v1`)
- **WorldView (4D OSINT):** http://localhost:3000 (separate stack, auto-started by START.bat — see above)
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`

## Docs

- **`MOONSHOT.md`** — the north star: vision, principles, phase gates, and how the project stays on track. Read this first for the *why* and *where we're going*.
- **`docs/ARCHITECTURE.md`** — AI-navigable map of the codebase (entry points, request lifecycle, module index, how-to recipes). Start here to find where things live.
- **`docs/AI_CONTEXT.md`** — context-loading map for large-context AI (what to load, in which order, per-task bundles with token estimates).
- **`docs/OWNER_TASKS.md`** — the human-gated queue: everything only the owner can do (hardware runs, GitHub settings, decisions).
- **`JARVIS.md`** — architecture & directory structure · **`AGENTS.md`** — assistant conventions · **`BACKLOG.md`** — priorities & tasks.
- **`GO_LIVE_PLAN.md`** — features + marketing brief + v1.0 launch checklist · **`docs/VALUATION_AND_PRICING.md`** — valuation, pricing & unit economics.
- **`docs/MANUAL_TESTING.md`** — human pre-release checklist: everything the offline test suite can't verify (real LLMs, channels, services, HUD rendering).
- **`docs/2026-06-08-future-developments-report.md`** — forward roadmap: remaining v1.0 gate, WorldView follow-ups, audit-debt hardening, post-1.0 horizons (Hermes, Cognition), and recommended sequencing.
- **`worldview/README.md`** — the WorldView (4D OSINT) companion stack.

## Status

**v9.9.9 — pre-1.0 audit gate.** 17 specialist agents (incl. **Argus** for WorldView geoint and **Howard**, the emerging digital twin; + 17 bench) across 4 tiers; real-embeddings recall (LM Studio) + fused recall +
RAG injection; hot-path perf (SQLite WAL, event-loop offload, checkpoint debounce, query-embedding
cache, complexity-based model tiering); autonomous proactive cortex (ORIZONT 6); security wedge (encrypted
secrets, signed skills, reversible/irreversible approval split, quarantine/capability/kill-switch); competitive edge
(workflow engine, model arena, quality monitor, review queue); living memory (bi-temporal KG, decay-forgetting,
sleep-time consolidation). **2,156 tests passing** (+184 frontend JS tests).

**Road to v1.0:** the v1.0 backlog (H1–H17) is **code-complete at 194/196 items (≈99% by story points)** —
the only two open items (H12.14 fine-tuned agentic model, H13.3 speculative decoding) need the GPU host
(runbook: `docs/GPU_RUNBOOK.md`). What stands between `9.9.9` and the `1.0.0` tag is the audit gate: a full
code audit ([`docs/AUDIT.md`](docs/AUDIT.md)), human manual testing on real hardware
([`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md)), and fixes. The HUD V2 cockpit is the default UI;
deep write-controls for ~37 newer backend surfaces are tracked in
[`docs/design/HUD_V2_REMAINING.md`](docs/design/HUD_V2_REMAINING.md). See
[BACKLOG.md](BACKLOG.md#status-general) + [MOONSHOT.md](MOONSHOT.md) §4.

See `STATUS.md`, `BACKLOG.md`, and `docs/ARCHITECTURE.md` for details.
