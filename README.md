# Andrei's Cabinet

> 15 specialized AI agents orchestrated through Jarvis, running on Bonobo WS + Pi 5, controlled by voice and web.

---

## What this is

A personal AI mesh that handles the cross-section of Andrei's life: work at Raiffeisen + Digitaholic, family with Alexandra and Max, the BMW E93, the build at Cosmina de Sus, fitness, finance, content. Each domain has a dedicated agent. They talk to each other through Jarvis. They learn from interactions.

## Architecture

**Pure local Python + opt-in plugin layer.** No OpenClaw. No cloud dependency by default. Every third-party service is an explicit, scope-limited, audit-able, disable-able plugin.

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
- **Memory:** conversation history (JSONL) + numpy vector store + SQLite checkpoints
- **Channels:** web (SSE), voice, telegram, discord, email, slack
- **Security:** PII/secret scanner, SSRF protection, audit log (Merkle chain), guardrails (WARN/REDACT/BLOCK)

## Run

### Windows 11 — one-click (no terminal needed)

1. **`UPDATE.bat`** — double-click to pull the latest from GitHub, install
   dependencies, and run the tests. Run this whenever you want the newest version.
2. **`START.bat`** — double-click to launch the server and open the HUD in your
   browser. Keep its window open; close it to stop the server.

### Manual (any OS)

```bash
pip install -r requirements-beta.txt
pip install tiktoken beautifulsoup4 psutil pytest-asyncio   # extras used by newer code
python serve.py              # http://127.0.0.1:8000
python -m pytest             # 181 passed, 8 skipped
```

- **HUD:** http://127.0.0.1:8000/
- **Admin panel:** http://127.0.0.1:8000/admin
- **CLI REPL:** `python agents/run.py`

## Status

**v0.2.1** — 15 agents across 4 tiers, fully-offline HUD, admin panel, SQLite settings,
10 plugins, 6 channels, skills + sandbox + learning loop. 39 tests passing.

See `STATUS.md` and `.opencode/plans/qa-bugs.md` for details.
