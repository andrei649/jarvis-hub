# Jarvis — AI Agent Orchestration System

## Overview

Jarvis is a local-first multi-agent AI orchestration system. 15 agents across 4 tiers, coordinated by Jarvis (prime orchestrator). Pure Python, runs on Windows via LM Studio with GPU acceleration (RTX 5090 24GB VRAM, 192GB DDR5).

**Stack:** Python 3.12 + FastAPI + LM Studio (OpenAI-compatible API)  
**Server:** http://127.0.0.1:8000  
**Model:** `google/gemma-4-26b-a4b` (MoE, ~4B active params, 16.76 GB VRAM)  
**LLM Backend:** LM Studio on port 1234 (TdrDelay=8 to prevent GPU driver timeout)

---

## Directory Structure

```
agents/
├── _system/
│   ├── agents.yaml          # Agent registry (15 agents, 15 bench)
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
│   │   ├── manager.py       # Memory orchestration
│   │   ├── conversation.py  # Conversation history (JSONL)
│   │   ├── persistence.py   # JSON session persistence
│   │   └── store.py         # Vector store (768-dim numpy, degrades without numpy)
│   ├── learning/
│   │   └── loop.py          # Learning loop (interaction records, prompt optimization)
│   ├── security/
│   │   ├── types.py         # ScanFinding, ThreatLevel enums
│   │   ├── scanner.py       # SecretScanner (10 patterns) + PIIScanner (6 patterns)
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
├── web.py                   # FastAPI web app (17 endpoints)
├── run.py                   # CLI REPL entry point
├── jarvis/
│   └── SOUL.md              # Jarvis agent soul (identity prompt)
├── friday/
│   └── SOUL.md
├── pepper/
│   └── SOUL.md
├── ... (15 agent dirs total)
└── .venv/                   # Python virtual environment
serve.py                     # Uvicorn launcher
memory_logs/                 # Sessions, checkpoints, learning records
```

---

## Agent Tiers

| Tier | Agents | Role |
|---|---|---|
| **Command** | Jarvis, Friday, Pepper, Jerome | Orchestration, daily ops, staff |
| **Business** | Athena, Stark, Veronica, Vision | Strategy, intel, comms |
| **Tech** | Steve, Oracle, Ultron | Infra, workflows, security |
| **Foundation** | Gecko, Hercules, Hephaestus, Frigga | Finance, fitness, builds, family |

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
- LM Studio on port 1234 with `google/gemma-4-26b-a4b` (MoE, 16.76 GB VRAM)
- Auto-detection checks LM Studio first, then Ollama
- Model has extended thinking (produces `reasoning_content` + `content`)
- Backend handles both fields, defaults to 1024 token limit

**Recall embeddings (long-term memory):**
- `MemoryManager.embed/remember/recall` turn text into vectors for fused recall (vector ⊕ graph, RRF — H5.14)
- Engine via `EMBED_BACKEND`: `lmstudio` (default, OpenAI-compatible `/v1/embeddings` on :1234) or `ollama` (e.g. `mxbai-embed-large`)
- Degrades to a deterministic hash embedding if the backend is unreachable, so recall never hard-fails
- `/api/memory/search` embeds the query; `POST /api/memory/remember` stores a fact; `MEMORY_EMBED_TURNS=true` auto-embeds every turn

**To add Claude API as cloud fallback:**
- Get API key from https://console.anthropic.com
- Add key to `agents/core/plugins/cloud_llm.py` (look for `anthropic_api_key`)
- Configure `cloud_llm_agents` list in `agents.yaml` (agents that can use cloud)
- Agents already set: jarvis, athena, stark, vision, veronica
- Frigga has `cloud_fallback: false` (hard rule, never uses cloud)

---

## Key Design Decisions

1. **One model for all agents** — LM Studio loads one model at a time; multi-model not practical with 24GB VRAM
2. **MoE over dense** — Gemma 4 26B-A4B (MoE) is 6x faster than dense 31B with comparable quality
3. **Extended thinking** — Both Gemma 4 and Qwen 3.5 produce reasoning_content; backend merges it
4. **Pure Python** — No Rust, no cloud dependency for core functionality
5. **TdrDelay=8** — Required to prevent DPC_WATCHDOG_VIOLATION on GPU driver during model load

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
curl.exe http://127.0.0.1:8000/status
```

---

## Quick Stats

- 15 active agents, 15 bench (reserved)
- 34 models downloaded (1.24 TB total)
- 17 API endpoints
- 7 ported features from OpenJarvis (security, skills, sandbox, multi-channel, bench, learning, streaming)
- VRAM: ~17 GB used by primary model, ~7 GB free
- Response time: ~4-5s per query

---

## What Claude Can Help With

1. **Cloud LLM integration** — Wire up Anthropic/OpenAI APIs as fallback
2. **UI improvements** — Dashboard, chat interface, agent management
3. **New agent souls** — Write SOUL.md for bench agents (Howard, Bruce, Wanda, etc.)
4. **Testing** — Write comprehensive test suite
5. **Performance** — Optimize prompt templates, agent handoff, memory retrieval
6. **Plugin development** — New integrations (Google Calendar, Apple Health, etc.)
7. **Bug fixes** — Any issues discovered during use
