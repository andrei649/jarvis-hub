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

- **Orchestration:** Python 3 + asyncio + APScheduler
- **LLM inference:** Ollama (local), optional Claude Sonnet plugin
- **Models:** DeepSeek-R1 32B (heavy), Qwen 2.5 14B + 7B (specialist)
- **Voice:** openWakeWord + faster-whisper large-v3 + Kokoro 82M ONNX
- **Memory:** Qdrant (episodic) + Neo4j (semantic) + Letta (working/archival)
- **Channel routing:** Telegram plugin, WhatsApp bridge (Frigga only, local), voice, web

## Status

**v0.1.0** — All 15 SOUL.md + 11 HEARTBEAT.md are written. Core Python orchestrator is partially built. Next session: finish core modules, plugin layer, new install.sh.

See `STATUS.md` for details.
