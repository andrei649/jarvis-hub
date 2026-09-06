# Jarvis Hub — your AI cabinet

![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)
<!-- project-status:badges:start -->
![Backend tests](https://img.shields.io/badge/backend_tests-8123-brightgreen?logo=pytest)
![Version](https://img.shields.io/badge/version-1.0.0-orange)
<!-- project-status:badges:end -->

> 17 specialized AI agents orchestrated through Jarvis, running on **your own hardware**, controlled by voice and web.

**A private AI OS that cannot silently act beyond the authority you grant it.** Local-first and governed: every autonomous action is risk-gated — a reversible/irreversible **approval queue** for anything consequential, a tamper-evident **audit log**, budgets and a kill-switch, converging on one **Action Kernel** mediation point (opt-in via `JARVIS_ACTION_KERNEL` while it hardens) — and it runs entirely on your own hardware (LM Studio / Ollama on your GPU), **$0/month, no cloud by default**, with a **family agent that never touches the internet**. Where other local agent systems prioritize extensibility and raw autonomy, this system prioritizes governed execution, local ownership, and inspectability. The product it is becoming is **Nerva** (published by Digitaholic; `jarvis-hub` remains the repo codename until the deliberate rename) — the long-term product & capability vision (house brain, media director, cameras, computer operator, self-extension) is in [`NERVA_VISION.md`](NERVA_VISION.md).

**Get running in minutes →** [Quickstart](#run) · one-click `INSTALL.bat` on Windows.

<!-- TODO(launch): demo GIF above the fold — 30–60s of a real task incl. one approved irreversible step -->

---

## What this is

A personal AI mesh that handles the cross-section of *your* life: the day job and the side business, the family, the car and the house projects, fitness, finance, content. Each domain has a dedicated agent. They talk to each other through Jarvis. They learn from interactions.

**The agents ship as templates and personalize themselves in your first session:** guided onboarding (drop-folder import + profile memory) teaches Jarvis your people, projects, and preferences, every learned fact is inspectable and deletable, and each agent's personality is editable. Your personalized souls live in gitignored `agents/<id>/SOUL.local.md` overlays — the public repo stays generic, your instance stays yours. The roster below shows each agent's *role*; the specifics become yours.

## Architecture

**Pure local Python + opt-in plugin layer.** *Not* OpenClaw — deliberately: where the viral 2026 rival stores secrets in plaintext and runs ungoverned community skills (widely reported in 2026 as a major infostealer target — analysis: [`docs/research/2026-06-02-personal-ai-competitors.md`](docs/research/2026-06-02-personal-ai-competitors.md)), here every action is gated by a reversible/irreversible approval queue, guardrails, and an audit log. No cloud dependency by default. Every third-party service is an explicit, scope-limited, audit-able, disable-able plugin.

## The cabinet

**CNS (Command tier)** — 4 agents:
- **Jarvis** — Prime Orchestrator. The voice you wake.
- **Friday** — Daily Intel. Weather + news + market signal.
- **Pepper** — Chief of Staff. Calendar + meetings + reflection.
- **Jerome** — Leisure & Soundtrack. Music, retro tech, decompression.

**Business tier** — 5 agents:
- **Athena** — External Strategist. Your side business, personal brand, career trajectory.
- **Stark** — Internal Corporate Intel. Day-job KPIs, board prep, channels.
- **Veronica** — The Voice. Drafts emails, posts, captions in 5 voice profiles.
- **Vision** — Deep Researcher + OSINT. Cited synthesis, regulatory watch.
- **Argus** — Geoint Sentinel. Read-only, governed bridge to WorldView (4D OSINT) and the Signal Layer.

**Tech tier** — 3 agents:
- **Steve** — CTO + Infrastructure. Bonobo + Pi + models + backups.
- **Oracle** — Pipeline Weaver. n8n workflows, silent when working.
- **Ultron** — The Shield. Firewall, GDPR/ATT, smart home VLAN.

**Foundation tier** — 5 agents:
- **Gecko** — Capital Allocator. Numbers cold; no advice.
- **Hercules** — Physical Engine. Sleep, recovery, training prep.
- **Hephaestus** — Builder & Mechanic. Your project car and house build.
- **Frigga** — The Matriarch. Family memory and care — names, dates, routines. Strictly local-only.
- **Howard** — Digital Twin (emerging). Voice clone, personal RAG, fine-tune candidate. Local-only.

## Hardware

**What model should I run?** Jarvis works with any LM Studio / Ollama model — pick by VRAM:

| Your GPU | Recommended local model | Expectation |
|----------|------------------------|-------------|
| 8–12 GB (3060/3080) | `qwen2.5:7b` / `llama3.1:8b` (Q4) | solid daily chat; deep-think slot off |
| 16 GB (4080/4070Ti S) | `qwen2.5:14b` / `gemma2:27b` (Q4) | good quality, one model slot |
| 24 GB+ (3090/4090/5090) | `gemma-4-31b-a4b` (MoE) + a deep slot | the full reference experience |
| CPU-only | `qwen2.5:3b` | it works; expect slow replies |

No GPU rule is enforced — the model picker (`/api/onboarding/command-center`, HUD → Start) tells you honestly whether a model is reachable. The measurement protocol and the per-tier table live in [`docs/HARDWARE_BENCHMARKS.md`](docs/HARDWARE_BENCHMARKS.md) — the numbers themselves are not measured yet (owner hardware), and that page stays blank rather than guessing. The reference rig below is what the project is developed on, **not a requirement**:

- **Bonobo WS** (Pop!_OS) — Intel Core Ultra 9, 192GB DDR5, RTX 5090 24GB, 4× NVMe + 18TB HDD
- **Pi 5** — always-on services (Qdrant, Neo4j, n8n, Homebridge)

**Providers & platforms.** Any OpenAI-compatible endpoint works, not just LM Studio/Ollama:
**OpenRouter** and other OpenAI-compatible backends ship today (`agents/core/llm/openrouter.py`,
switch with `/model`). **Apple Silicon (M1–M4)** is covered — `install.sh` handles macOS; run
local models via LM Studio/Ollama on unified memory (owner smoke-tests tracked as FB1). Running
on a lean box or a server/TUI? Use the **`headless`** usage profile (`JARVIS_SYSTEM_PROFILE=headless`)
— heavy media features off, background autonomy on, local-light models. Full platform/provider
support: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md); tester-level answers: [alpha FAQ](marketing/alpha-testing/FAQ.md).

## Stack

- **Orchestration:** Python 3.12 + asyncio + FastAPI
- **LLM inference:** LM Studio (OpenAI-compatible, primary) → Ollama (fallback) → optional cloud (Anthropic/OpenAI) for approved agents
- **Model:** `google/gemma-4-31b-a4b` (MoE, ~4B active params) on RTX 5090
- **Voice:** browser-mic HUD loop ships; server engines are optional manual installs (openWakeWord wake word, faster-whisper STT, edge-tts / Kokoro TTS) — no install path ships them ([`docs/VOICE.md`](docs/VOICE.md))
- **Memory:** conversation history (JSONL) + vector store (real embeddings via LM Studio/Ollama, hash fallback) + knowledge graph + fused recall (RRF, vector ⊕ graph) + SQLite checkpoints (WAL)
- **Channels:** web (SSE), voice, telegram, discord, email, slack
- **Security:** PII/secret scanner, SSRF protection, audit log (Merkle chain), guardrails (WARN/REDACT/BLOCK)

### WorldView (4D OSINT) + Signal Layer

A separate, self-contained **Next.js + Deck.gl + Fastify** stack under [`worldview/`](worldview/) (frontend `:3000`, API `:4000`, infra via Docker: Redpanda/TimescaleDB/Redis) — a time-scrubbable 3D globe fusing air/sea/space/cyber OSINT. It shares no runtime with `agents/` and is **opt-in**: install with `JARVIS_WORLDVIEW=1 ./install.sh` and start with `JARVIS_WORLDVIEW=1` (same variable for `START.bat`). Out of the box it has **no live feeds** — run `npm run db:seed` for clearly-badged demo data; live providers are owner-configured. The **Argus** agent queries it read-only and governed. No Mapbox token or API keys are needed for the demo (`npm run db:seed`). See [`worldview/README.md`](worldview/README.md).

The **Jarvis Signal Layer** is the provider-neutral situational-awareness API at `:8787`. It turns provider data into evidence, signals, relevance, assessments, briefs, and approval-gated recommendations. It starts in deterministic replay mode by default and can later use a WorldMonitor sidecar as provider #1. Keep WorldMonitor off `:3000`; Jarvis convention is `:3100` because WorldView already owns `:3000`. See [`docs/worldview/worldview-worldmonitor-fusion.md`](docs/worldview/worldview-worldmonitor-fusion.md).

## Run

<!-- project-status:run:start -->
Generated test matrix: backend **8,123** · frontend **974** · mobile **110**. Route surface: **454**.
<!-- project-status:run:end -->

**One step per OS.** Every path ends the same way: a `.venv` with the **hash-pinned**
dependency set, a passed **install smoke** (real boot + `/readyz` + one deterministic chat turn),
and the Command Center open at `http://127.0.0.1:8080/v2` — bound to **loopback only**. No cloud
key is asked for at any point. Requires **Python 3.12+**; a local model runtime (Ollama / LM Studio)
is detected, never installed.

```bash
# Linux / macOS — hosted one-liner (clones into ~/nerva, or $NERVA_DIR)
curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash

# …or, from a checkout
./install.sh                 # venv + locked deps + smoke, then starts Nerva and opens /v2
```

**Windows 11:** double-click **`INSTALL.bat`** — it checks for Python 3.12 (offers `winget` when
missing), builds the environment from the lock, and then offers to start Nerva; **`START.bat`**
launches it later. *(PowerShell / packaged executable: `packaging\windows\install.ps1 -Launch`.)*

```bash
# Docker, if you would rather not touch the host at all (loopback posture, same as native)
docker compose -f docker-compose.quickstart.yml up --build

# Something not working? One command, named reasons, exit 0/1
python scripts/doctor.py
```

Full per-OS detail: **[`docs/INSTALL.md`](docs/INSTALL.md)**. Reaching the HUD from your phone or a
second device on the LAN — what the boot guards refuse and the one supported way through:
**[`docs/PHONE_ACCESS.md`](docs/PHONE_ACCESS.md)**.

_Manual, if you prefer to drive it yourself:_

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt                 # one install — full feature set
python serve.py              # → http://127.0.0.1:8080
python -m pytest             # full offline suite — current count auto-synced in STATUS.md
```

_Also on Windows:_ **`UPDATE.bat`** pulls the latest and reinstalls. The optional companions are
**opt-in** on every platform: `JARVIS_WORLDVIEW=1` also starts the 4D OSINT globe (`:3000`),
`JARVIS_SIGNAL_LAYER=1` also starts the Signal Layer (`:8787`).

_Changed your mind?_ `./uninstall.sh --confirm` (`UNINSTALL.bat` on Windows) removes the
installer-created software footprint (`.venv/`, WorldView's `node_modules/` + env files).
Your data is never touched unless you also pass `--purge-data`.

- **HUD:** http://127.0.0.1:8080/ — the **V2 cockpit** (primary HUD; legacy HUD at `/v1`, override with `JARVIS_HUD=v1`)
- **WorldView (4D OSINT):** http://localhost:3000 (separate stack, auto-started by START.bat/start.sh — see above)
- **Signal Layer:** http://127.0.0.1:8787/healthz (replay mode by default; opt out with `JARVIS_SIGNAL_LAYER=0`)
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`

## Docs

- **`docs/FEATURES.md`** — the one-page product sheet: every feature that ships today, how to install, and what's next on the road to 1.0.
- **`MOONSHOT.md`** — the north star: vision, principles, phase gates, and how the project stays on track. Read this first for the *why* and *where we're going*.
- **`NERVA_VISION.md`** — the Nerva product & capability vision: the brand architecture (Cortex/Atlas/Synapse/Vision/Ultron), the six pillars (perception, communication, action, house, media, capability evolution), the target architecture, the capability registry, graduated autonomy, and the measurable "superior to Hermes" bar.
- **`docs/ARCHITECTURE.md`** — AI-navigable map of the codebase (entry points, request lifecycle, module index, how-to recipes). Start here to find where things live.
- **`docs/AI_CONTEXT.md`** — context-loading map for large-context AI (what to load, in which order, per-task bundles with token estimates).
- **`docs/OWNER_TASKS.md`** — the human-gated queue: everything only the owner can do (hardware runs, GitHub settings, decisions).
- **`docs/RELEASE.md`** — how a release is cut (tag → source bundle + SBOM + checksums + optional signatures) and how to verify a download.
- **`SECURITY.md`** · **`docs/THREAT_MODEL.md`** · **`docs/PRIVACY.md`** — the trust trio: disclosure policy, what Jarvis defends against (with the mechanism for each threat), and the local-first data/telemetry stance.
- **`docs/USER_GUIDE.md`** · **`docs/FAQ.md`** · **`docs/UPGRADE.md`** — the user docs: install/run/daily-use, quick answers, and how to upgrade safely.
- **`JARVIS.md`** — architecture & directory structure · **`AGENTS.md`** — assistant conventions · **`BACKLOG.md`** — priorities & tasks.
- **`GO_LIVE_PLAN.md`** — features + marketing brief + v1.0 launch checklist · **`docs/VALUATION_AND_PRICING.md`** — valuation, pricing & unit economics.
- **`docs/MANUAL_TESTING.md`** — human pre-release checklist: everything the offline test suite can't verify (real LLMs, channels, services, HUD rendering).
- **`docs/2026-06-08-future-developments-report.md`** — forward roadmap: remaining v1.0 gate, WorldView follow-ups, audit-debt hardening, post-1.0 horizons (Hermes, Cognition), and recommended sequencing.
- **`worldview/README.md`** — the WorldView (4D OSINT) companion stack.
- **`docs/worldview/worldview-worldmonitor-fusion.md`** — how Jarvis fuses WorldView, WorldMonitor, Signal Layer, and Argus without collapsing their boundaries.

## Status

<!-- project-status:readme-status:start -->
Generated status: **v1.0.0** · backend **8,123** · frontend **974** · mobile **110** · **454** routes · **18** active agents · open release gates: **A1, A3, A4, A6** · backlog: **250 done · 38 delivered (runtime proof pending) · 13 open or blocked of 301 horizon rows** · source commit `c16d84e989ff`. Full data: [`project-status.json`](project-status.json).
<!-- project-status:readme-status:end -->

**v1.0.0 — the proof track is closed** (the version line is the roadmap — see [BACKLOG.md](BACKLOG.md#version-roadmap): productionization done, the 72h soak now grades itself, design partners running on non-owner installs, owner-host proof passed. The AI-OS capability program, [`NERVA_VISION.md`](NERVA_VISION.md), continues past 1.0 as roadmap rather than as a gate). 18 specialist agents (incl. **Argus** for WorldView geoint, **Howard**, the emerging digital twin, and **Hestia**, the House Brain; + 14 bench) across 4 tiers; real-embeddings recall (LM Studio) + fused recall +
RAG injection; hot-path perf (SQLite WAL, event-loop offload, checkpoint debounce, query-embedding
cache, complexity-based model tiering); autonomous proactive cortex (ORIZONT 6); security wedge (encrypted
secrets, signed skills, reversible/irreversible approval split, quarantine/capability/kill-switch); competitive edge
(workflow engine, model arena, quality monitor, review queue); living memory (bi-temporal KG, decay-forgetting,
sleep-time consolidation). **Full offline test suite green** — current counts auto-synced in [STATUS.md](STATUS.md) (+ frontend JS tests).

**Road to v1.0:** the original feature backlog (H1–H17) is **code-complete at 194/196 items (≈99% by story points)** —
the only two open items (H12.14 fine-tuned agentic model, H13.3 speculative decoding) need the GPU host
(runbook: `docs/GPU_RUNBOOK.md`). What stands between `0.11.0` and the `1.0.0` tag is now two-fold:
**(a) the proof track** — the **productionization layer** (H23: agentic-safety budgets, DB migrations,
backup/restore + export-delete, operability, quality + user docs — see the
[version roadmap](BACKLOG.md#version-roadmap)) proven with real design-partner users — **and (b) the
AI-OS capability program** (ORIZONT 27–33: capability registry, computer/browser operator, media
director, house brain, cameras, capability acquisition, ambient intelligence —
[`NERVA_VISION.md`](NERVA_VISION.md), gate expanded 2026-07-11); manual testing
([`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md)) + code audit
([`docs/AUDIT.md`](docs/AUDIT.md)) are the release step that tags a version. The HUD V2 cockpit is the default UI;
deep write-controls for ~37 newer backend surfaces are tracked in
[`docs/design/HUD_V2_REMAINING.md`](docs/design/HUD_V2_REMAINING.md). See
[BACKLOG.md](BACKLOG.md#status-general) + [MOONSHOT.md](MOONSHOT.md) §4.

See `STATUS.md`, `BACKLOG.md`, and `docs/ARCHITECTURE.md` for details.
