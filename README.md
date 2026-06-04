# Andrei's Cabinet

![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-1559%20passed-brightgreen?logo=pytest)
![Version](https://img.shields.io/badge/version-9.9.9-orange)

> 16 specialized AI agents orchestrated through Jarvis, running on Bonobo WS + Pi 5, controlled by voice and web.

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

**Business tier** — 4 agents:
- **Athena** — External Strategist. Digitaholic, personal brand, CMO trajectory.
- **Stark** — Internal Corporate Intel. Raiffeisen KPIs, board prep, channels.
- **Veronica** — The Voice. Drafts emails, posts, captions in 5 voice profiles.
- **Vision** — Deep Researcher + OSINT. Cited synthesis, regulatory watch.

**Tech tier** — 3 agents:
- **Steve** — CTO + Infrastructure. Bonobo + Pi + models + backups.
- **Oracle** — Pipeline Weaver. n8n workflows, silent when working.
- **Ultron** — The Shield. Firewall, GDPR/ATT, smart home VLAN.

**Foundation tier** — 4 agents:
- **Gecko** — Capital Allocator. Numbers cold; no advice.
- **Hercules** — Physical Engine. Sleep, recovery, snowboard prep.
- **Hephaestus** — Builder & Mechanic. BMW E93 N54 + Cosmina build.
- **Frigga** — The Matriarch. Max + Alexandra + Beads & Blush. Local-only.

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

## Run

### Windows 11 — one-click (no terminal needed)

1. **`INSTALL.bat`** — first time on a clean PC. Checks/installs Python + Git
   (via winget), gets the code, builds the environment, installs everything,
   runs the tests. Double-click and follow the prompts.
2. **`UPDATE.bat`** — double-click to pull the latest from GitHub, install
   dependencies, and run the tests. Run this whenever you want the newest version.
3. **`START.bat`** — double-click to launch the server and open the HUD in your
   browser. Keep its window open; close it to stop the server.

### Manual (any OS)

```bash
pip install -r requirements-beta.txt
pip install tiktoken beautifulsoup4 psutil pytest-asyncio   # extras used by newer code
python serve.py              # http://127.0.0.1:8080
python -m pytest             # 1559 passed, 9 skipped
```

- **HUD:** http://127.0.0.1:8080/
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`

## Docs

- **`MOONSHOT.md`** — the north star: vision, principles, phase gates, and how the project stays on track. Read this first for the *why* and *where we're going*.
- **`docs/ARCHITECTURE.md`** — AI-navigable map of the codebase (entry points, request lifecycle, module index, how-to recipes). Start here to find where things live.
- **`JARVIS.md`** — architecture & directory structure · **`AGENTS.md`** — assistant conventions · **`BACKLOG.md`** — priorities & tasks.
- **`GO_LIVE_PLAN.md`** — features + marketing brief + v1.0 launch checklist · **`docs/VALUATION_AND_PRICING.md`** — valuation, pricing & unit economics.
- **`docs/MANUAL_TESTING.md`** — human pre-release checklist: everything the offline test suite can't verify (real LLMs, channels, services, HUD rendering).

## Status

**v9.9.9 — pre-1.0 audit gate.** 16 specialist agents (+ 17 bench) across 4 tiers; real-embeddings recall (LM Studio) + fused recall +
RAG injection; hot-path perf (SQLite WAL, event-loop offload, checkpoint debounce, query-embedding
cache, complexity-based model tiering); autonomous proactive cortex (ORIZONT 6); security wedge (encrypted
secrets, signed skills, reversible/irreversible approval split, quarantine/capability/kill-switch); competitive edge
(workflow engine, model arena, quality monitor, review queue); living memory (bi-temporal KG, decay-forgetting,
sleep-time consolidation). **1,559 tests passing.**

**Road to v1.0:** the feature backlog (H1–H9) plus the bulk of the competitive-edge and frontier work — the
2026-06-03 wave across H10, H12, H14, H16, H17 — is code-complete: ~166/186 backlog items (≈82% by story
points), shipped pending the `9.9.9` audit gate (a full code audit — see [`docs/AUDIT.md`](docs/AUDIT.md) —
human manual testing ([`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md)), and fixes). *Most* of what remains
needs hardware/models (local VLM, speculative decoding, GPU fine-tuning, desktop operator) or external network
surfaces (A2A, agentic payments); a handful of open items are pure software, mostly P3 (AI-assisted workflow
builder, data spaces, signed-skill marketplace, and the Tauri/Rust/WASM parity items). See
[BACKLOG.md](BACKLOG.md#status-general) + [MOONSHOT.md](MOONSHOT.md) §4.

See `STATUS.md`, `BACKLOG.md`, and `docs/ARCHITECTURE.md` for details.
