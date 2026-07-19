# Jarvis Hub — Full Architecture Dump for Gemini

You are reviewing the full architecture of Jarvis Hub, a local-first multi-agent AI orchestration system. Use this document to reason about architecture, plan implementations, and make decisions. Do not write code unless explicitly asked.

---

## PROJECT IDENTITY

- **Owner:** Andrei (Romanian, UTC+2)
- **Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX)
- **LLM Backend (primary):** LM Studio on `localhost:1234`, model `google/gemma-4-26b-a4b` (MoE, ~4B active params, 16.76 GB VRAM, RTX 5090 24GB)
- **LLM Backend (Howard):** Ollama on `localhost:11434`, model `howard-lora-qwen-14b` (fine-tuned digital twin)
- **Cloud LLM (optional):** Gemini API (used for certain agents when local unavailable or for heavy context)
- **Web Dashboard:** `http://127.0.0.1:8080`, Admin: `/admin`
- **Start command:** `python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080`
- **Test command:** `python -m pytest tests/ -v` (181 tests, all passing)
- **Key decisions:**
  - One model at a time on LM Studio (24GB VRAM cannot hold 2 large models)
  - MoE over dense — Gemma 4 26B-A4B is 6x faster than dense 31B
  - Pure Python, no Rust, no cloud dependency for core
  - TdrDelay=8 to prevent DPC_WATCHDOG_VIOLATION on GPU driver

---

## FILE STRUCTURE

```
cabinet/
├── agents/
│   ├── _system/
│   │   └── agents.yaml              # Full agent registry (16 active, 15 bench)
│   ├── core/
│   │   ├── agent.py                 # Single agent runtime: load SOUL, process, synthesize
│   │   ├── orchestrator.py          # Main loop: classify → route → call agents → synthesize
│   │   ├── router.py                # Keyword-based IntentRouter (wake words → keywords → general)
│   │   ├── config.py                # YAML config → JarvisConfig
│   │   ├── checkpoint.py            # SQLite checkpoint persistence
│   │   ├── sandbox.py               # Docker/subprocess code execution sandbox
│   │   ├── bench.py                 # Latency/throughput benchmark recorder
│   │   ├── plugin_gate.py           # Permission gate for agent→plugin access
│   │   ├── settings_db.py           # SQLite settings DB with runtime refresh
│   │   ├── errors.py                # Error taxonomy (E_* constants)
│   │   ├── log.py                   # Structured logging
│   │   ├── lock.py                  # Component-level locking (30min stale timeout)
│   │   ├── heartbeat.py             # APScheduler-based heartbeat scheduler
│   │   ├── llm/
│   │   │   ├── base.py              # LLMBackend abstract + LMStudioBackend + OllamaBackend
│   │   │   ├── hybrid_router.py     # Multi-factor routing (token budget + agent policy + availability)
│   │   │   ├── router.py            # Auto-detect: LM Studio → Ollama → none
│   │   │   ├── gemini.py            # Gemini API backend (with streaming, context caching)
│   │   │   ├── tokenizer.py         # Token estimation for routing decisions
│   │   │   └── ollama_howard.py     # [PLANNED] Howard-specific Ollama backend
│   │   ├── skills/
│   │   │   ├── loader.py            # Skill discovery + execution from skills/ dirs
│   │   │   └── importer.py          # Import skills from external sources
│   │   ├── memory/
│   │   │   ├── manager.py           # Memory orchestration (conversation + context)
│   │   │   ├── conversation.py      # Conversation history (JSONL)
│   │   │   ├── persistence.py       # JSON session persistence
│   │   │   └── store.py             # VectorStore (768-dim numpy, cosine similarity)
│   │   ├── ingestion/               # [NEW — Howard pipeline]
│   │   │   ├── pipeline.py          # Full pipeline: parse → normalize → analyze → store
│   │   │   ├── parser_facebook.py   # Parse Facebook DYI JSON exports
│   │   │   ├── parser_whatsapp.py   # Parse WhatsApp .txt exports (RO + EN formats)
│   │   │   ├── normalizer.py        # NormalizedMessage dataclass
│   │   │   ├── stylometry.py        # VoiceProfile + StylometryAnalyzer
│   │   │   ├── knowledge.py         # Entity/relationship/decision extraction
│   │   │   └── embedder.py          # Text embedding for vector store
│   │   ├── learning/
│   │   │   └── loop.py              # Learning loop (interaction recording, demotion)
│   │   ├── security/
│   │   │   ├── types.py             # ScanFinding, ThreatLevel, RedactionMode
│   │   │   ├── scanner.py           # SecretScanner (10 patterns) + PIIScanner (6 patterns)
│   │   │   ├── ssrf.py              # SSRF protection (private IP blocking)
│   │   │   ├── audit.py             # AuditLogger (SQLite + Merkle hash chain)
│   │   │   └── guardrails.py        # GuardrailsEngine (WARN/REDACT/BLOCK)
│   │   ├── channels/
│   │   │   ├── base.py              # ChannelAdapter abstract class
│   │   │   ├── web.py               # WebChannel (SSE streaming, polling)
│   │   │   ├── voice.py             # Voice channel (wake word → STT → orchestrator → TTS)
│   │   │   ├── telegram.py          # Telegram bot (webhook + polling, per-chat_id sessions)
│   │   │   ├── discord.py           # Discord bot channel
│   │   │   ├── email.py             # Email channel (SMTP + IMAP)
│   │   │   ├── slack.py             # Slack bot channel
│   │   │   └── gateway.py           # Message routing gateway
│   │   ├── plugins/
│   │   │   ├── weather.py           # Weather (wttr.in)
│   │   │   ├── news.py              # News (BBC RSS)
│   │   │   ├── cloud_llm.py         # Cloud LLM plugin (Anthropic/OpenAI/Gemini)
│   │   │   ├── spotify_plugin.py    # Spotify API
│   │   │   ├── gmail_plugin.py      # Gmail API
│   │   │   ├── google_calendar.py   # Google Calendar API
│   │   │   ├── apple_health.py      # Apple Health bridge
│   │   │   ├── websearch.py         # Web search (Tavily / SearXNG / DuckDuckGo)
│   │   │   ├── telegram_bot.py      # Telegram bot plugin
│   │   │   ├── whatsapp_bridge.py   # WhatsApp bridge
│   │   │   ├── homebridge.py        # Homebridge/smart home
│   │   │   ├── oracle_bridge.py     # Oracle/n8n bridge
│   │   │   └── oauth.py             # OAuth flows (Google, Spotify) with auto-refresh
│   │   ├── voice/
│   │   │   ├── pipeline.py          # Voice pipeline coordinator
│   │   │   ├── tts.py               # TTS (edge-tts + Kokoro)
│   │   │   ├── stt.py               # STT (faster-whisper)
│   │   │   └── wake_word.py         # Wake word detection (openWakeWord)
│   │   └── mcp/
│   │       └── client.py            # MCP client for external MCP servers
│   ├── web.py                       # FastAPI app (17+ endpoints)
│   ├── run.py                       # CLI REPL entry point
│   ├── jarvis/SOUL.md               # Jarvis agent soul
│   ├── friday/SOUL.md
│   ├── pepper/SOUL.md
│   ├── jerome/SOUL.md
│   ├── athena/SOUL.md
│   ├── stark/SOUL.md
│   ├── veronica/SOUL.md
│   ├── vision/SOUL.md
│   ├── steve/SOUL.md
│   ├── oracle/SOUL.md
│   ├── ultron/SOUL.md
│   ├── gecko/SOUL.md
│   ├── hercules/SOUL.md
│   ├── hephaestus/SOUL.md
│   ├── frigga/SOUL.md
│   ├── howard/SOUL.md               # [NEW] Digital Twin agent soul
│   └── ...
├── skills/                          # Skill directories (one per skill)
│   ├── brief/                       # Friday morning brief
│   ├── calendar/                    # Pepper calendar
│   ├── content/                     # Veronica content drafting
│   ├── family_store/                # Frigga family data
│   ├── health/                      # Hercules health
│   ├── pm/                          # Hephaestus project management
│   ├── spotify/                     # Jerome Spotify
│   ├── weather/                     # Weather skill
│   └── user_greeting_055711/        # Auto-generated skill example
├── tests/                           # 181 pytest tests (pytest-asyncio, auto mode)
│   ├── conftest.py
│   ├── test_hybrid_router.py
│   ├── test_routing.py
│   ├── test_chat.py
│   ├── test_errors.py
│   ├── test_endpoints.py
│   ├── test_startup.py
│   ├── test_sandbox_gating.py
│   ├── test_settings_db.py
│   ├── test_oauth.py
│   ├── test_websearch.py
│   ├── test_heartbeat.py
│   ├── test_calendar.py
│   ├── test_brief.py
│   ├── test_health.py
│   ├── test_content.py
│   ├── test_pm.py
│   ├── test_spotify.py
│   ├── test_spotify_skill.py
│   └── test_family_store.py
├── memory_logs/                     # Session data, tokens, learning, archive
├── design_handoff_jarvis_hub/       # Design handoff docs (HUD, admin)
├── .opencode/
│   └── plans/
│       ├── howard_spec.md           # Howard full specification
│       └── ...                      # Other agent plans
├── BACKLOG.md                       # Master backlog with horizon tracking
├── CHANGELOG.md
├── NERVA.md                        # Project README
├── PARALLEL_WORKFLOW.md
├── pytest.ini
├── requirements-beta.txt
├── requirements.txt
├── serve.py                         # Uvicorn launcher
├── lock.py                          # Component locking
├── .env.example                     # All config keys template
└── install.ps1                      # One-click install script
```

---

## AGENT REGISTRY (agents/_system/agents.yaml)

### Active Agents (16 total)

| Agent | Tier | Channel | Plugins | LLM Policy | Heartbeat | Status |
|-------|------|---------|---------|------------|-----------|--------|
| **jarvis** | command | voice | cloud-llm, telegram | auto | yes | active |
| **friday** | command | voice | telegram | auto | yes | active |
| **pepper** | command | voice | google-calendar, gmail, telegram | auto | yes | active |
| **jerome** | command | voice | spotify | auto | no | active |
| **athena** | business | web-dashboard | cloud-llm | **cloud** | yes | active |
| **stark** | business | telegram | gmail | auto | yes | active |
| **veronica** | business | telegram | cloud-llm | auto | no | active |
| **vision** | business | web-dashboard | cloud-llm, websearch | **cloud** | yes | active |
| **steve** | tech | telegram | — | auto | yes | active |
| **oracle** | tech | web-dashboard | — | auto | no | active |
| **ultron** | tech | log-only | — | **local** | yes | active |
| **gecko** | foundation | telegram | — | auto | yes | active |
| **hercules** | foundation | telegram | apple-health | auto | yes | active |
| **hephaestus** | foundation | telegram | — | auto | yes | active |
| **frigga** | foundation | local-only | whatsapp-bridge | **local** | yes | active |
| **howard** | foundation | telegram | — | **local** | no | active |

### Bench Agents (15 reserved, triggered by usage)

bruce (Data Science), wanda (R&D), shuri (Hardware), natasha (Security Audit), thor (Escalation), loki (Devil's Advocate), heimdall (Monitor), happy (Driver/Logistics), bucky (Operations), apollo (Music), hermes (Cross-Channel Router), atlas (Batch), prometheus (Innovation), artemis (Lead Gen), demeter (Nutrition), aria (Music Curation), hera (Family)

### Routing Policies

```
LOCAL_ONLY  = {frigga, ultron, howard}     → never use cloud, never use internet
CLOUD_ONLY  = {vision, athena}              → always use cloud API
AUTO         = everyone else                 → route based on token budget + availability
OLLAMA_PREFERRED = {howard}                  → use Ollama (port 11434, model howard-lora-qwen-14b)
```

### Promotion/Demotion Rules
- **Promote:** ≥20 uses/month + distinct tone + dedicated channel
- **Demote:** ≤5 uses/month for 2 consecutive months, or ≥5 consecutive failures
- **Cap:** 18 active agents maximum
- **Howard** was promoted from bench on 2026-05-30 (trigger: "15 years of personal data ingested")

---

## ORCHESTRATION FLOW

### Request Lifecycle

```
User Input → channel_handler(text, channel="web"/"telegram"/"voice")
  ├── Check for /skills command → parse_command() → execute skill
  ├── 1. IntentRouter.classify(text)
  │     Stage 1: Wake word match ("howard, ..." → ["howard"])
  │     Stage 2: Keyword match (ROUTING_TABLE + INTENT_KEYWORDS)
  │     Stage 3: Fallback → ["jarvis"]
  │     Returns → Intent(target_agents=["howard"], is_general=False, context={keywords_found:...})
  ├── 2. Gather plugin data
  │     If "weather" keywords → WeatherPlugin.get_weather()
  │     If "news" keywords → NewsPlugin.summarize()
  │     If "calendar" keywords → GoogleCalendarPlugin.get_today_events()
  │     If "email" keywords → GmailPlugin.list_messages()
  │     If "research"/"search" → WebSearchPlugin.search()
  ├── 3. Call agents in parallel (_call_agents_parallel)
  │     For each target agent:
  │       a. Build prompt: context + history + plugin data + agent context
  │       b. Agent.process(text, context)
  │          ├── _load_soul() → system prompt from SOUL.md
  │          ├── hybrid_router.select_backend(agent_id, prompt)
  │          │   ├── if howard → _select_howard_backend(): Ollama or fallback
  │          │   ├── if local-only policy → local backend only
  │          │   ├── if cloud-only policy → Gemini API only
  │          │   ├── if auto + token ≤ 8K → local
  │          │   ├── if auto + token ≤ 128K → cloud-flash
  │          │   └── else → cloud-pro
  │          └── backend.generate(model, prompt, system, max_tokens, temperature)
  │     Returns → {agent_id: response_text, ...} with latency tracking
  ├── 4. Detect handoff
  │     If response contains "[handoff:agent_id]" → call agent_id
  ├── 5. Synthesize multi-agent responses
  │     If 1 response → return it directly
  │     If multiple → jarvis.synthesize(responses, intent)
  │       → Prompts Jarvis with all agent reports → single coherent reply
  ├── 6. Post-processing
  │     ├── Add to memory (add_turn)
  │     ├── Save checkpoint
  │     ├── Record learning (success/failure/latency)
  │     ├── Run bench stats
  │     ├── Check for demotion (≥5 consecutive failures)
  │     ├── Detect skill learning ("[learn: desc | steps | cmd]")
  │     └── Log audit event
```

### IntentRouter Keywords (router.py INTENT_KEYWORDS)

| Keyword | Target Agents |
|---------|--------------|
| weather, news | friday |
| calendar, meeting, schedule | pepper |
| email | pepper, veronica, stark |
| write, draft, linkedin, instagram | veronica |
| research, search | vision |
| kpi, raiffeisen, board | stark |
| strategy, career, digitaholic | athena |
| money, finance, budget | gecko |
| sleep, workout, fitness | hercules |
| cosmina, bmw, car | hephaestus |
| max, family, alexandra, beads | frigga (+ veronica for beads) |
| howard, archive, digital twin, "what would i", "what did i", "what have i", "what do i", remember, "who is", "how would i", voice, "what do you know about" | howard |
| music, playlist, game | jerome |
| infrastructure, server, backup | steve |
| security | ultron |
| automation, workflow | oracle |
| route, "what can you", "who are you", hello, morning, help | jarvis |

---

## LLM BACKEND ARCHITECTURE

### HybridRouter (agents/core/llm/hybrid_router.py)

Three backends possible:
1. **LM Studio** (`localhost:1234`) — primary local, model `google/gemma-4-26b-a4b`, handles all non-Howard agents
2. **Ollama** (`localhost:11434`) — dedicated for Howard, model `howard-lora-qwen-14b` (fine-tuned QLoRA)
3. **Gemini API** — cloud fallback for cloud-only agents (vision, athena) and heavy-context for auto-policy agents

Detection order on startup: LM Studio → Ollama → Gemini API

Token thresholds: LOCAL_MAX = 8K, FLASH_MAX = 128K

### Per-request routing logic:

```
if agent_id == "howard":
    if ollama available → "ollama-howard"
    elif lm_studio available → "local-fallback"
    elif gemini available → "cloud-fallback" (LAST RESORT — Howard's SOUL says LOCAL ONLY)
    else → RuntimeError

elif agent in LOCAL_ONLY_AGENTS:
    if lm_studio available → "local"
    elif gemini available → "cloud-fallback" (graceful degradation)

elif agent in CLOUD_ONLY_AGENTS:
    if gemini available → "cloud"
    elif lm_studio available → "local-fallback"

else (POLICY_AUTO):
    if tokens ≤ 8K and local → "local"
    elif tokens ≤ 128K and cloud → "cloud-flash"
    elif cloud → "cloud-pro"
    elif local → "local-fallback"
    else → RuntimeError
```

---

## SKILLS SYSTEM

### Skill structure (under skills/<name>/)

```
skills/calendar/
├── __init__.py
└── skill.py
```

Skills are auto-discovered by SkillLoader from `skills/` dirs.
Each skill exposes `command` for parsing and `execute()` for running.
Skills can be parsed from user text with `/` prefix: `/calendar add meeting...`

### Auto-learning
Agents can auto-generate skills by including `[learn: task_desc | step1,step2,step3 | command_name]` in their responses.
The orchestrator detects this and calls `skills.generate_skill()`.

---

## MEMORY & VECTOR STORE

### MemoryManager
- Conversation history (JSONL) per session
- `add_turn(session_id, role, text, agent_id)` — append
- `get_context(session_id, last_n)` — last N turns
- `get_agent_context(agent_id)` — agent-specific memory

### VectorStore (store.py)
- **768-dim numpy**, cosine similarity search
- Degrades gracefully to naive Python if numpy unavailable
- Methods:
  - `search(query, k)` — top-k by cosine similarity
  - `search_by_sender(sender, k)` — filter by metadata.sender
  - `search_by_text_subset(query, sender, k)` — search + sender filter [NEW for Howard]
  - `add(record_id, vector, metadata)` — insert
  - `remove(record_id)` — delete by ID

### Planned Upgrades
- **Qdrant** (H3.1, Docker on Pi 5) — persistent vector DB, 6333
- **Neo4j** (H3.2) — knowledge graph for entities/relationships
- **Session Persistence** (H3.3) — cross-channel session save/restore

---

## HOWARD — DIGITAL TWIN AGENT (ACTIVE WORKSTREAM)

### Overview
Howard ingests 15+ years of Facebook Messenger and WhatsApp conversations, extracts a stylometric voice profile, and can respond "as Andrei" via RAG + fine-tuned LLM. Fully local (zero cloud, zero internet).

### Pipeline (agents/core/ingestion/)
1. **Facebook Parser** → `data/facebook/messages/inbox/<conversation>/message_N.json`
2. **WhatsApp Parser** → `data/whatsapp/<conversation>.txt` (RO + EN formats)
3. **Normalizer** → `NormalizedMessage` dataclass (common format)
4. **Embedder** → Text → 768-dim vectors for VectorStore [PLANNED — not yet created]
5. **Stylometry** → `VoiceProfile`: top_words, bigrams, signature_phrases, ro_ratio, en_ratio, code_switch_rate, emoji_usage, avg_message_length, formality_score (0.0-1.0)
6. **Knowledge Extractor** → entities (topics, mention counts), relationships (person→type→confidence), decisions (decision triggers)

### Output destinations:
- `memory_logs/archive/archive.db` — SQLite index
- `memory_logs/archive/messages.jsonl` — training data export
- `memory_logs/archive/voice_profile.json` — stylometric fingerprint
- `memory_logs/archive/knowledge.json` — entities + relationships
- `memory_logs/archive/ingestion_summary.json` — run stats

### Query Flow:

```
"Howard, what did I say about..."
  → IntentRouter → target: ["howard"]
  → Agent("howard").process()
  → HybridRouter → selects Ollama (howard-lora-qwen-14b)
  → RAG: embed query → search VectorStore top-5 messages by sender=Andrei
  → Few-shot injection into prompt
  → Howard generates response in Andrei's voice
```

### Fine-tuning Plan:
- Base: Qwen 2.5 14B-Instruct (GGUF Q4_K_M)
- Method: QLoRA via Unsloth, rank 16-32, 3-5 epochs
- Data: ShareGPT format from archive (Andrei=assistant, others=user)
- Deploy as Ollama model: `howard-lora-qwen-14b`

### Status — Files:
- ✅ `agents/howard/SOUL.md` — created
- ✅ `agents/_system/agents.yaml` — Howard active, promoted from bench
- ✅ `agents/core/ingestion/__init__.py` — created
- ✅ `agents/core/ingestion/pipeline.py` — full pipeline orchestrator
- ✅ `agents/core/ingestion/normalizer.py` — NormalizedMessage class
- ✅ `agents/core/ingestion/parser_facebook.py` — Facebook parser
- ✅ `agents/core/ingestion/parser_whatsapp.py` — WhatsApp parser
- ✅ `agents/core/ingestion/stylometry.py` — StylometryAnalyzer + VoiceProfile
- ✅ `agents/core/ingestion/knowledge.py` — KnowledgeExtractor
- ✅ `agents/core/ingestion/embedder.py` — Text embedder [created]
- ✅ `agents/core/router.py` — Howard keywords in routing table
- ✅ `agents/core/llm/hybrid_router.py` — Ollama backend + Howard routing
- ✅ `agents/core/memory/store.py` — search_by_sender, search_by_text_subset
- ✅ `agents/core/agent.py` — Howard model detection
- ⬜ `agents/core/llm/ollama_howard.py` — Dedicated Howard LLM backend [TODO]
- ⬜ Fine-tuning pipeline execution [TODO]
- ⬜ Actual data ingestion run [TODO]

---

## HORIZON STATUS

| Horizon | Done/Total | Story Points | % |
|---------|-----------|--------------|---|
| H1 Foundation (P0) | 5/5 | 26/26 | 100% |
| H2 Core Agent (P1) | 8/12 | 53/76 | 70% |
| H3 Intelligence (P2) | 0/6 | 0/39 | 0% |
| H4 Platform (P3) | 0/11 | 0/63 | 0% |
| Cross-cutting | 2/6 | 6/44 | 14% |
| Sec. hardening | 3/5 | — | 60% |
| Bugs | 17/17 | — | 100% |
| **TOTAL** | **35/62** | **85/248** | **34%** |

### H2 Remaining (4 items)
| Item | S | Dep | Status |
|------|---|-----|--------|
| H2.2 Pepper Email Triage | 5 | H1.4 (done) | 🔜 Ready |
| H2.9 Vision Web Research | 5 | — | 🔜 Ready |
| H2.6 Gecko Balance | 8 | Bank API | 🔴 Blocked |
| H2.11 Stark GA4 | 5 | GA4 API access | 🔴 Blocked |

### Sprint 0 Priorities (P0, ~1-2h each)
| Item | S | Description |
|------|---|-------------|
| S0.1 Model Tiering | 3 | Claude API for heavy agents (Vision, Steve), local 7B for light agents |
| S0.2 Heartbeat Sanity | 2 | Change intervals to ≥60 min (currently 1-15 min causing thrashing) |
| S0.3 CI Smoke Test | 2 | GitHub Actions: pytest on push to main |

### Cross-cutting Remaining
| Item | S |
|------|---|
| Session Manager thread-safe | 3 |
| Integration tests per agent | 15 |
| Plan per agent in `.opencode/plans/` | 15 |
| Load test — 15 agents simultaneously | 5 |

---

## TESTING APPROACH

- **Framework:** pytest + pytest-asyncio (auto mode via pytest.ini)
- **Config:** `pytest.ini` sets `asyncio_mode = auto`, `testpaths = tests`
- **Total:** 181 tests all passing
- **Pattern:** Each agent has a test file in `tests/test_<agent>.py`
- **Skills:** Each skill gets a test file
- **Fixtures:** `tests/conftest.py` with isolated fixtures
- **Run:** `python -m pytest tests/ -v`

---

## SECURITY POSTURE

| ID | Issue | Status |
|----|-------|--------|
| S1 | `/api/admin/env` exposed all `os.environ` | ✅ Guarded + masked |
| S2 | Zero auth on all `/api/admin/*` | ✅ localhost-only or token |
| S3 | SSRF in `websearch.py` | ✅ Pre + post fetch validation |
| S4 | `gemini.py` stream no `raise_for_status` | ⬜ P1 hardening |
| S-PKCE | OAuth no PKCE, state unhashed, token unencrypted | ⬜ P1 hardening |

---

## EXISTING PLUGINS

| Plugin | Source | API Keys Needed |
|--------|--------|----------------|
| WeatherPlugin | wttr.in (free) | None |
| NewsPlugin | BBC RSS | None |
| CloudLLMPlugin | Anthropic/OpenAI/Gemini | Keys in .env |
| GmailPlugin | Gmail API (OAuth) | Token auto-refreshed from `memory_logs/tokens/` |
| GoogleCalendarPlugin | Google Calendar API (OAuth) | Same token as Gmail |
| SpotifyPlugin | Spotify API (OAuth) | Client ID + Secret, auto-refresh |
| AppleHealthPlugin | HTTP bridge | `APPLE_HEALTH_BRIDGE_URL` |
| WebSearchPlugin | Tavily/SearXNG/DuckDuckGo | Tavily key (optional) |
| WhatsAppBridgePlugin | Local bridge | `WHATSAPP_BRIDGE_URL` |
| HomebridgePlugin | Homebridge | URL + token |
| OracleBridgePlugin | GitHub | `GITHUB_TOKEN` |

---

## CONVENTIONS

- **Naming:** Archetypes from Marvel + Greek/Norse mythology + occasional pop culture
- **Agent Soul:** Each agent has `agents/<id>/SOUL.md` with identity, mission, scope, voice, rules, dependencies
- **Skills:** Standard pattern — inherit from Skill base, implement `execute(intent, orch)` returning response text
- **Tests:** Each skill/agent gets pytest file, uses async/await, follows `test_<name>` naming
- **Language in code:** English for identifiers, Romanian in user-facing strings (agents.yaml has bilingual keywords)
- **No comments:** Code is self-documenting; only add comments when essential
- **Dependencies:** Check existing codebase for libraries before adding new ones
- **Secrets:** Never commit `.env` or token files; `.env.example` is the template

---

## COMMON COMMANDS

```powershell
# Start server
python serve.py

# Run all tests
python -m pytest tests/ -v

# Install deps
pip install -r requirements-beta.txt

# Check if server is running
netstat -ano | findstr ":8080 "

# Reload after Python changes: Ctrl+C, restart server
# Reload after JS/CSS changes: Ctrl+F5 in browser
```

---

**END OF ARCHITECTURE DUMP** — Use this as context for architectural reasoning about Jarvis Hub.
