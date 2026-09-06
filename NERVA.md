# Jarvis — AI Agent Orchestration System

## Overview

Jarvis is a local-first multi-agent AI orchestration system. 18 active agents across 4 tiers (incl. Argus, the WorldView bridge, Howard, the emerging digital twin, and Hestia, the House Brain), coordinated by Jarvis (prime orchestrator). Pure Python, runs on Windows via LM Studio with GPU acceleration (RTX 5090 24GB VRAM, 192GB DDR5).

> **Related stack — WorldView (4D OSINT):** a separate, self-contained Next.js + Fastify product under [`worldview/`](worldview/) (ports 3000/4000, Docker infra) that shares **no runtime** with this Python system. The **Argus** agent (`agents/argus/`) is the read-only, governed bridge between JARVIS and WorldView; the entire integration surface is the versioned contract in [`docs/contracts/worldview-bridge.md`](docs/contracts/worldview-bridge.md) (6 read-only endpoints, contract-tested on both sides). It is installed and auto-started by `INSTALL.bat`/`START.bat`. See [`worldview/README.md`](worldview/README.md).

**Stack:** Python 3.12 + FastAPI + LM Studio (OpenAI-compatible API)  
**Server:** http://127.0.0.1:8080  
**Model:** auto-detected from the model actually loaded in LM Studio/Ollama at startup (`LLMRouter.detect`); falls back to `/admin → llm.default_model` (default `google/gemma-4-31b-a4b`)  
**Claude model:** `/admin → llm.claude_model` (admin-configurable)  
**LLM Backend:** LM Studio on port 1234 (TdrDelay=8 to prevent GPU driver timeout)

> 🧭 **AI navigation:** `docs/ARCHITECTURE.md` is the AI-navigable map (entry points, request
> lifecycle, full module index, how-to recipes). This file is the architecture overview; that one
> is the "where does X live / how do I change it" guide.

---

## Directory Structure

```
agents/
├── _system/
│   ├── agents.yaml          # Agent registry (18 active, 14 bench)
│   └── agents.yaml.latest   # Auto-generated backup
├── core/
│   ├── agent.py             # Single agent runtime (SOUL.md + model call)
│   ├── orchestrator.py      # Main loop: classify → route → synthesize
│   ├── router.py            # Keyword-based intent classifier
│   ├── config.py            # YAML config loader → JarvisConfig
│   ├── checkpoint.py        # SQLite checkpoint manager
│   ├── sandbox.py           # Docker + subprocess sandboxed execution
│   ├── bench.py             # Latency/throughput benchmark recorder
│   ├── plugin_gate.py       # Plugin permission gate
│   ├── llm/
│   │   ├── base.py          # LLMBackend abstract + LMStudioBackend + OllamaBackend
│   │   └── router.py        # Auto-detect: LM Studio → Ollama → none
│   ├── skills/
│   │   ├── loader.py        # Skill discovery + execution
│   │   └── importer.py      # Import skills from Hermes/OpenClaw/GitHub
│   ├── memory/
│   │   ├── manager.py       # Memory orchestration + embed/remember/recall
│   │   ├── conversation.py  # Conversation history (JSONL)
│   │   ├── persistence.py   # JSON session persistence
│   │   ├── store.py         # Vector store (768-dim numpy, degrades without numpy)
│   │   ├── graph.py         # Knowledge graph (InMemory / Neo4j)
│   │   ├── seed_graph.py    # Seeds the graph with base entities/relations
│   │   ├── fusion.py        # Fused recall — Reciprocal Rank Fusion (vector ⊕ graph, H5.14)
│   │   └── qdrant_store.py  # Qdrant vector backend (optional)
│   ├── ingestion/
│   │   ├── embedder.py      # Embeddings (LM Studio /v1/embeddings, Ollama, hash fallback; disk+LRU cache)
│   │   ├── pipeline.py      # Howard ingestion pipeline + RAG search
│   │   └── normalizer.py    # Message normalization
│   ├── autonomy/           # Proactive cortex (ORIZONT 6): queue, worker, policy, inbox,
│   │   │                    #   digest, observer, watchers, remediation, preferences, reflection
│   │   └── ...
│   ├── learning/
│   │   └── loop.py          # Learning loop (interaction records, prompt optimization)
│   ├── security/
│   │   ├── types.py         # ScanFinding, ThreatLevel enums
│   │   ├── scanner.py       # SecretScanner (10 patterns) + PIIScanner (9 patterns, incl. RO CNP/IBAN, checksum-validated)
│   │   ├── ssrf.py          # SSRF protection (private IP blocking)
│   │   ├── audit.py         # AuditLogger (SQLite + Merkle hash chain)
│   │   └── guardrails.py    # GuardrailsEngine (WARN/REDACT/BLOCK)
│   ├── channels/
│   │   ├── base.py          # ChannelAdapter abstract class
│   │   ├── web.py           # WebChannel (SSE streaming)
│   │   ├── voice.py         # Voice channel (silero TTS)
│   │   ├── telegram.py      # Telegram bot channel
│   │   ├── discord.py       # Discord bot channel
│   │   ├── email.py         # Email channel (SMTP + IMAP)
│   │   ├── slack.py         # Slack bot channel
│   │   └── gateway.py       # Message routing gateway
│   ├── plugins/
│   │   ├── weather.py       # Weather plugin (wttr.in)
│   │   ├── news.py          # News plugin (BBC RSS)
│   │   ├── cloud_llm.py     # Cloud LLM plugin (Anthropic/OpenAI)
│   │   ├── spotify_plugin.py
│   │   ├── gmail_plugin.py
│   │   ├── telegram_bot.py
│   │   └── whatsapp_bridge.py
│   ├── voice/
│   │   ├── pipeline.py      # Voice pipeline
│   │   ├── tts.py           # Text-to-speech (edge-tts)
│   │   ├── stt.py           # Speech-to-text (faster-whisper)
│   │   └── wake_word.py     # Wake word detection (openWakeWord)
│   └── mcp/
│       └── client.py        # MCP client
├── web.py                   # FastAPI web app (route surface counted live in STATUS.md — see docs/ARCHITECTURE.md)
├── run.py                   # CLI REPL entry point
├── jarvis/
│   └── SOUL.md              # Jarvis agent soul (identity prompt)
├── friday/
│   └── SOUL.md
├── pepper/
│   └── SOUL.md
├── ... (18 agent dirs total)
└── .venv/                   # Python virtual environment
serve.py                     # Uvicorn launcher
memory_logs/                 # Sessions, checkpoints, learning records
```

---

## Agent Tiers

| Tier | Agents | Role |
|---|---|---|
| **Command** | Jarvis, Friday, Pepper, Jerome | Orchestration, daily ops, staff |
| **Business** | Athena, Stark, Veronica, Vision, Argus | Strategy, intel, comms, geoint (WorldView bridge) |
| **Tech** | Steve, Oracle, Ultron | Infra, workflows, security |
| **Foundation** | Gecko, Hercules, Hephaestus, Frigga, Howard | Finance, fitness, builds, family, digital twin |

---

## Web Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Dashboard HTML |
| `/chat` | POST | Send message (returns JSON) |
| `/chat/stream` | POST | SSE streaming chat |
| `/status` | GET | System status |
| `/agents` | GET | Agent list |
| `/skills` | GET | Loaded skills |
| `/sessions` | GET | Session list |
| `/memory` | GET | Memory state |
| `/memory/clear` | POST | Clear current session |
| `/api/memory/search` | GET | Fused recall (embedded query: vector ⊕ graph) |
| `/api/memory/remember` | POST | Store a fact in long-term memory (embedded) |
| `/learning` | GET | Learning records |
| `/security` | GET | Security audit status |
| `/bench` | GET | Benchmark stats |
| `/sandbox/status` | GET | Sandbox availability |
| `/sandbox/execute` | POST | Execute code in sandbox |
| `/skills/import` | POST | Import skill from URL |
| `/skills/imported` | GET | Imported skills |
| `/dashboard` | GET | Dashboard data (JSON) |

---

## LLM Integration

**Current setup:**
- LM Studio on port 1234 with `google/gemma-4-31b-a4b` (MoE) — see §default model
- Auto-detection checks LM Studio first, then Ollama
- Model has extended thinking (produces `reasoning_content` + `content`)
- Backend handles both fields; `llm.max_tokens` default 2048 (deep route: `llm.deep_max_tokens` 8192). On a length-truncated turn with no answer the backend returns `""` instead of leaking the raw reasoning trace
- **Governed lifecycle control:** Jarvis can start/load/unload LM Studio and Ollama from chat (`lms` fixed argv for LM Studio; fixed `ollama serve` + localhost residency API for Ollama). MCP requires `ask_jarvis` plus verified owner/local-boundary identity. Every mutation additionally requires `system-control`, the host contract, `JARVIS_ACTION_KERNEL=1` with an explicit `GRANT`, and durable audit preflight; `ASK`/`OFF`, kill-switch, failed audit, or live control revocation stop effects. See `docs/ARCHITECTURE.md` §5. The legacy master kill-switch is `JARVIS_LMSTUDIO_CONTROL=0` or live `llm.control_enabled=false` (chat-only: `JARVIS_LMSTUDIO_CHAT_CONTROL` / `llm.chat_control`).

**Recall embeddings (long-term memory):**
- `MemoryManager.embed/remember/recall` turn text into vectors for fused recall (vector ⊕ graph, RRF — H5.14)
- Engine via `EMBED_BACKEND`: `lmstudio` (default, OpenAI-compatible `/v1/embeddings` on :1234) or `ollama` (e.g. `mxbai-embed-large`)
- Degrades to a deterministic hash embedding if the backend is unreachable, so recall never hard-fails
- `/api/memory/search` embeds the query; `POST /api/memory/remember` stores a fact; `MEMORY_EMBED_TURNS=true` auto-embeds every turn
- **RAG injection:** setting `memory.recall_enabled` (default off) injects recalled memories into the prompt for all agents (`memory.recall_top_k`, default 5); pair with `MEMORY_EMBED_TURNS` or `/api/memory/remember` to have content to recall

**To add Claude API as cloud fallback:**
- Get API key from https://console.anthropic.com
- Add key to `agents/core/plugins/cloud_llm.py` (look for `anthropic_api_key`)
- Configure `cloud_llm_agents` list in `agents.yaml` (agents that can use cloud)
- Agents already set: jarvis, athena, stark, vision, veronica
- Frigga has `cloud_fallback: false` (hard rule, never uses cloud)

---

## Key Design Decisions

1. **Fast/heavy model tiering** (H7.5) — slot 1 (fast, 100% VRAM) for light requests; slot 2 (deep, DDR5 spillover) for heavy reasoning. `hybrid_router.is_heavy_request()` escalates by complexity (token count + RO/EN keywords); toggle with `JARVIS_AUTO_DEEP`. Supersedes the old "one model for all agents" rule.
2. **MoE over dense** — Gemma 4 26B-A4B (MoE) is 6x faster than dense 31B with comparable quality
3. **Extended thinking** — Both Gemma 4 and Qwen 3.5 produce reasoning_content; backend merges it
4. **Pure Python** — No Rust, no cloud dependency for core functionality
5. **TdrDelay=8** — Required to prevent DPC_WATCHDOG_VIOLATION on GPU driver during model load
6. **Hot-path stays off the event loop** (H7.1–H7.3) — per-turn SQLite writes use WAL + `synchronous=NORMAL`, run via `asyncio.to_thread`, and the full checkpoint is debounced (`memory.checkpoint_every`), so commits never stall concurrent requests
7. **Recall never hard-fails** — embeddings degrade to a deterministic hash; recall query is cached (disk + in-process LRU, H7.4)

---

## Common Commands

```powershell
# Start server
cd C:\Users\andre\cabinet
python serve.py

# LM Studio management
lms server start                    # Start API server
lms load <model> --identifier <id>  # Load model
lms unload <id>                     # Unload model
lms ps                              # List loaded models
lms load <model> --estimate-only    # Check VRAM requirements

# Test
curl.exe http://127.0.0.1:8080/status
```

---

## Quick Stats

<!-- project-status:jarvis-stats:start -->
- 18 active agents; registry-derived
- 454 HTTP routes; parity-snapshot-derived
- Tests: backend **8,123** · frontend **974** · mobile **110**
- Version: **v1.0.0** · source commit `c16d84e989ff`
- Backlog ledger: 250 done · 38 delivered (runtime proof pending) · 13 open or blocked of 301 horizon rows
- Runtime proof pending: H10 — 29 done · 1 delivered (runtime proof pending) · 0 open
- Runtime proof pending: H12 — 21 done · 3 delivered (runtime proof pending) · 2 open
- Runtime proof pending: H19 — 2 done · 33 delivered (runtime proof pending) · 0 open
- Runtime proof pending: H30 — 7 done · 1 delivered (runtime proof pending) · 0 open
- H23 roll-up: 28/30 done, 0 delivered (runtime proof pending), 1 blocked, 1 open; release gates: A1, A3, A4, A6
<!-- project-status:jarvis-stats:end -->

---

## What Claude Can Help With

1. **Cloud LLM integration** — Wire up Anthropic/OpenAI APIs as fallback
2. **UI improvements** — Dashboard, chat interface, agent management
3. **New agent souls** — Write SOUL.md for bench agents (Howard, Bruce, Wanda, etc.)
4. **Testing** — Write comprehensive test suite
5. **Performance** — Optimize prompt templates, agent handoff, memory retrieval
6. **Plugin development** — New integrations (Google Calendar, Apple Health, etc.)
7. **Bug fixes** — Any issues discovered during use
