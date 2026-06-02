# Jarvis Hub — Go-Live Plan

> Generated: 2026-06-02 · Version target: v1.0.0 · Owner: Andrei
> North star (vision & phase gates): [MOONSHOT.md](MOONSHOT.md)
> Source of truth for backlog: [BACKLOG.md](BACKLOG.md)

---

## 1. Existing Features

### Channels & Interface

- **Web HUD** — React (vanilla, no JSX), SSE streaming, mobile PWA, offline support
- **Telegram** — webhook + polling, inline Approve/Edit/Reject/Postpone buttons, ≤4 push/day budget
- **Discord, Slack, Email** — SMTP/IMAP, full two-way
- **Voice** — faster-whisper STT → edge-tts / XTTS / ElevenLabs / Kokoro TTS, <1.5s first audio, hands-free barge-in, global audio window manager
- **Sandbox** — Docker code execution with allowlist + timeout + audit
- **Admin panel** — runtime settings watcher (30s refresh), audit log, 100-interaction history, latency charts

---

### 15 Specialist Agents (4 Tiers)

| Tier | Agent | Role |
|------|-------|------|
| Command | **Jarvis** | Prime orchestrator — routing, synthesis, escalation |
| Command | **Friday** | Daily operations — morning brief + evening digest |
| Command | **Pepper** | Personal assistant — Google Calendar CRUD + Gmail triage |
| Command | **Jerome** | Entertainment & wellness — Spotify control |
| Business | **Vision** | Strategic research — Tavily web search, sourced reports |
| Business | **Athena** | High-reasoning — cloud-only (Claude API) |
| Business | **Stark** | Analytics — GA4 KPI summaries, trend analysis |
| Business | **Veronica** | Content & comms — LinkedIn posts, articles, drafting |
| Tech | **Steve** | System health — CPU/GPU/RAM/temp monitoring + alerts |
| Tech | **Oracle** | Workflow automation — n8n designer + webhook triggers |
| Tech | **Ultron** | Security & audit — port scanning, threat detection |
| Foundation | **Gecko** | Finance — ING/Libra/CSV balance reader |
| Foundation | **Hercules** | Health & fitness — Apple HealthKit (sleep, HRV, steps) |
| Foundation | **Hephaestus** | Project management — milestones, blockers, status |
| Foundation | **Frigga** | Family records — strict local-only, zero network |
| Emerging | **Howard** | Personal digital twin — voice clone, RAG, fine-tuning candidate |

---

### Memory & Intelligence

- **Neo4j Knowledge Graph** — entity/relation storage, factual queries
- **Qdrant Vector DB** — conversational similarity search
- **Fused Recall (RRF)** — reciprocal rank fusion: vector ⊕ graph, single ranked result list, weight-tunable, `/api/memory/search`
- **Daily Reflection** — every night: last 60 turns → LLM → JSON `{entities, relations, lessons}` → Neo4j; idempotent per day, 22:00–07:00 window
- **Real embeddings** — LM Studio `/v1/embeddings` backend + disk cache + graceful hash fallback (recall never hard-fails)
- **Session persistence** — cross-channel context (web → Telegram → same session)
- **Learning loop** — after 100 interactions, promote bench agents; approve/reject preference scoring per (agent, kind, tier)

---

### Autonomous Cortex

- **Self-tasking queue** — SQLite state machine: proposed → approved → running → done/failed/blocked, retry cap 3, two queues (manual/generated)
- **Risk gate & 4-tier policy** — read-only / reversible / external / irreversible-or-money; reversibility + blast-radius + signal-quality scoring
- **Decision inbox on Telegram** — inline Approve/Edit/Reject/Postpone per blocked task
- **Preference learning** — track approve/reject patterns → auto-suggest autonomy raise after N reversible approvals
- **Night shift** — reversible-only execution (max tier 1) during configurable 22:00–07:00 window
- **Proactive OS Observer** — CPU/RAM/disk/TCP liveness probes, debounced state-change alerts, inject into queue once per state transition
- **Event watchers** — Email/Calendar/Finance/Health probes, eșantionate în autonomy loop, gated `system.watchers_enabled`
- **Daily Review Ritual** — 07:00 morning brief + 20:00 evening retro, Telegram + HUD `/autonomy/brief`
- **LogBugScanner** — 15-min/hourly/daily scheduled log analysis; writes `memory_logs/reports/bug-report-YYYY-MM-DD.md`

---

### Workflows & Observability

- **Visual Workflow Builder** — canvas SVG, vanilla React, drag-drop step placement, DAG cycle validation, CRUD (`/api/workflows`)
- **Multi-agent DAG engine** — topological sort, parallel batches via `asyncio.gather`, `{step_id}` template substitution
- **3 built-in pipelines** — `finance_report`, `research_and_brief`, `security_digest`
- **User-defined workflows** — save/update/delete via API, persisted to `WorkflowStore`, live-registered
- **Trace Explorer** — per-request: classify → route → model → tokens → latency → cost; `/api/traces`, HUD tab, ring buffer (max 500)
- **Offline Eval Harness** — prompt sets, LLM-injectable scoring, regression tracking (H9.3)
- **Resilience tab** — retry metrics + circuit breaker states live in HUD

---

### Security & Robustness

- **Guardrails Engine** — REDACT PII, BLOCK injection, WARN; configurable per request
- **Romanian PII detection** — CNP (checksum-validated), IBAN (ISO 7064 mod-97), phone (`07…` / `+407…`)
- **SecuredShell Executor** — allowlist + no-shell (`create_subprocess_exec`) + bounded timeout + audit (`RemediationRunner`)
- **Circuit breaker + retry** — per-plugin, `@resilient_call` decorator, tri-state (closed/open/half-open), resilience metrics in HUD
- **MCP Client** — stdio/SSE, admin-wired, pluggable external tools
- **OAuth 2.0 + PKCE** — Google Calendar, Gmail, Spotify; token refresh + state + Fernet

---

### Performance (H7 — Production-Grade)

- **36× SQLite speedup** — WAL + `synchronous=NORMAL` (3317µs → 92µs/commit)
- **Async I/O offload** — blocking writes (checkpoint, audit, interactions) via `asyncio.to_thread`
- **Checkpoint debounce** — save every N turns (default 5); reduces hot-path write pressure
- **Fast/heavy model tiering** — 2000-token threshold + bilingual RO/EN keyword set → local-fast vs local-deep (LM Studio slot 1 vs slot 2)
- **Embedding LRU + disk cache** — 256-entry in-process LRU + sharded disk cache; dedup + parallel batching; degrades to hash on backend failure
- **Context cache** — 50 messages = ~80% cache hit

---

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI (async) |
| Database | SQLite (WAL), Neo4j (graph), Qdrant (vector) |
| LLM (local) | LM Studio (OpenAI-compatible, dual-slot), Ollama |
| LLM (cloud) | Claude API (Anthropic), Gemini API |
| Frontend | Vanilla React (`createElement`, no JSX), SSE |
| Voice STT | faster-whisper |
| Voice TTS | edge-tts (primary), XTTS, ElevenLabs, Kokoro |
| Integrations | Google OAuth 2.0, Spotify, Tavily, Apple HealthKit, n8n, Discord, Slack, Telegram, Docker |
| Infrastructure | RTX 5090 24GB VRAM, 192GB DDR5, Windows/Linux/Mac |

**Total operating cost: $0/month** (all free tiers).

---

### Test Coverage

| Category | Count |
|----------|-------|
| Total passing | 909 tests |
| Skipped | 9 (test_spotify HTTP-router, pending spotify.py) |
| Frontend | 0% (identified gap: ~6,000 LOC React HUD, no Jest/Playwright) |

---

## 2. Future Features

### H8 — Personal Memory (0/8, 48 SP) — Next Milestone

| # | Feature | SP | Priority |
|---|---------|-----|---------|
| H8.1 | **User Profile Memory** — persistent facts/preferences/people/projects extracted from conversations, versioned, injected into agent prompts | 8 | P1 |
| H8.1b | **Entity Memory Store** — auto-extract entities (persons, projects, concepts, locations) into searchable structured store | 5 | P1 |
| H8.2 | **Privacy & Forget Controls** — selective deletion, JSON export, retention policy, strict-local scope | 5 | P1 |
| H8.3 | **Recall ON by default + Memory HUD** — activate `memory.recall_enabled`, tab with facts (search/edit/delete), sources & scores | 5 | P2 |
| H8.3b | **Agentic RAG Tool** — `search_memory` as LLM tool call; model decides when/how to search, can retry with different query | 8 | P2 |
| H8.4 | **Quality Embeddings** — dedicated model (`mxbai-embed-large` or TEI container), benchmark vs hash fallback | 5 | P2 |
| H8.5 | **Live fast/heavy validation + Model Tier HUD** — confirm on System76 with 2 LM Studio slots loaded; expose tiering decisions (fast↔deep) in `/bench` + HUD | 5 | P2 |
| H8.6 | **Proactive Personal Briefs** — morning/evening briefs personalized from profile + recall | 5 | P2 |
| H8.7 | **AI-Navigable Docs upkeep** — `docs/ARCHITECTURE.md` as single source; PR checklist for docs sync | 2 | P3 |

---

### H7 — Hardening & Release Readiness (0/11, 51 SP) — v1.0 Gate

> **Naming note:** The completed perf-hotpath work (SQLite WAL, async offload, checkpoint debounce, embedding LRU, fast/heavy tiering) was also labeled "H7" internally but is fully delivered — see "Performance (H7)" in Existing Features above. This section is the separate **PROPUS hardening track** (H7.1–H7.11), a required gate for v1.0 stable. Full delivery history: [docs/HISTORY.md](docs/HISTORY.md).

| # | Feature | SP | Priority |
|---|---------|-----|---------|
| H7.1 | **Hermetic test suite** — gate network calls on `JARVIS_TESTING`, `pytest-timeout`, function-scoped fixtures | 5 | P0 |
| H7.2 | **CI/CD on PRs** — `pull_request` trigger, Ubuntu + Windows matrix, ruff + mypy + pytest-cov | 5 | P0 |
| H7.3 | **Centralized HTTP client** — `PluginHTTPClient` with consistent timeouts + `@resilient_call` + pooling | 8 | P1 |
| H7.4 | **SQLite thread safety** — `check_same_thread=False` + locks on checkpoint/settings/queue/preferences | 5 | P1 |
| H7.5 | **Input validation on endpoints** — Pydantic limits (message len, `limit` bounds, sandbox code size) | 3 | P1 |
| H7.6 | **Clean silent exceptions** — replace `except: pass` in security/autonomy with structured logging | 5 | P1 |
| H7.7 | **Remove misleading mock data** — `/tasks` dummy tasks, transparent IoT mock flag | 2 | P1 |
| H7.8 | **Documentation truth** — single version source in `agents/__init__.py`, fix all cross-doc contradictions | 3 | P1 |
| H7.9 | **Onboarding & release** — `LICENSE`, `CONTRIBUTING.md`, quickstart, `docker-compose.yml`, README badges, release workflow | 5 | P1 |
| H7.10 | **Cost & Usage Analytics** — $/request per model + aggregate per agent, burn projection, HUD tab | 5 | P2 |
| H7.11 | **Learning-Loop activation** — weekly job proposes agent promote/demote via decision inbox | 5 | P2 |

---

### H10 — Competitive Edge (0/30, 188 SP)

#### H10.A — Observability & Eval
- APM cost dashboard (tokens + $ per agent/model)
- Cost tracking per request (stored in trace)
- Model Arena — blind A/B quality comparison, vote, leaderboard
- Dataset regression tracking — JSONL versioned, score per dataset-version, CI integration
- Agent prompt version control — SOUL.md versioned, compare UI, A/B on dataset, rollback
- Live quality monitor — LLM-as-judge on live traces, alert on score decline
- Per-agent run history timeline
- Human review queue with rubric + thumbs up/down

#### H10.B — MCP & Integrations
- **MCP Server mode** — expose Jarvis agents + workflows as MCP tools (consumable by Claude Desktop, Cursor, other Jarvis instances)
- Inbound webhook triggers — `/api/webhooks/{id}` → agent/workflow activation
- Natural language scheduling — "every weekday at 7am" → cron auto-parse
- Embeddable chat widget — drop-in JS snippet for websites

#### H10.C — Memory & RAG
- Write-back integrations — agents write to Notion, GitHub Issues, Google Calendar natively
- **H10.21 Conversation Notes** (3 SP, P3) — rich text editor in HUD attached to current session; content injected as persistent context for any agent; "Rewrite with AI" inline action

#### H10.D — Workflow Engine
- Termination conditions (LLM judge, keyword match, max-iterations)
- Pydantic structured agent outputs with schema validation
- Critic agent pattern — built-in critic node (accept/retry/escalate)
- Dynamic LLM router — coordinator decides next agent at runtime
- Visual trace overlay — canvas nodes colored by status, per-step output inline
- Cyclic workflow support — loop-back edges with iteration count + exit condition
- AI-assisted workflow builder — describe step → LLM generates `WorkflowStep` config
- Python flow decorator API — `@jarvis_flow`, `@listen(step_id)`, `@router`
- Nested sub-workflows inside `WorkflowStep`
- Workflow transform nodes — Formatter, Validator, JSONExtractor, Summarizer
- Agent config preview — test agent behavior before saving to SOUL.md
- Guardrails as workflow node

#### H10.E — UX & Multi-user
- Agent templates library — research assistant, email triage, code reviewer, daily brief
- Action-level approval UI — live per-tool-call approval tab
- Chat channels/rooms — Discord-like with @agent mentions, pipeline per channel
- Data spaces — per-agent data source scope with permissions

---

## 3. Marketing Brief

### The Problem

Every AI tool today is either a chatbot or a workflow builder.

Chatbots are **reactive** — they wait for you. Workflow builders are **rigid** — they run what you programmed. Neither learns your preferences, monitors your world proactively, or builds a growing understanding of your life over time. And they all want your data in someone else's cloud.

---

### The Product

**Jarvis Hub is your personal AI operating system** — 15 specialist agents that work 24/7, proactively, on your hardware.

It doesn't wait to be asked. It monitors your system health, watches your email and calendar, scans its own logs for bugs, and consolidates every conversation into a knowledge graph every night. Every morning at 07:00 it delivers a prioritized brief.

When it needs a decision, it sends a Telegram message with one-tap Approve/Reject. When you approve the same type of task 10 times in a row, it stops asking.

---

### Core Value Props

**Privacy by design**
Frigga — the family memory agent — never touches the internet. No exceptions. Every other agent has an explicit cloud opt-in toggle. Your data doesn't train anyone's model.

**Proactive, not reactive**
Jarvis runs a self-tasking queue 24 hours a day. It finds its own work, executes reversible tasks autonomously, and escalates irreversible or costly actions to you on Telegram. You spend 10 minutes reviewing a digest, not managing 100 notifications.

**It knows you better over time**
Every night, Jarvis reads the last 60 conversations, extracts entities and relationships, and writes them into a knowledge graph. Every query fuses vector recall and graph recall. The more you use it, the more useful it becomes — without you configuring anything.

**Runs on your machine**
LM Studio + Ollama on local GPU. Zero API cost for 99% of tasks. Athena escalates to Claude API for heavy reasoning — everything else runs at home. Total operating cost: **$0/month**.

**Production-grade under the hood**
909 tests. 36× database speedup. Circuit breakers per plugin. Reciprocal rank fusion for hybrid recall. Fast/heavy model tiering based on prompt complexity. This isn't a demo.

---

### Differentiation vs. 8 Competitors

| Capability | Jarvis | Flowise | Langflow | CrewAI | AutoGen | OpenWebUI | LangSmith | Dust.tt |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Local-first + autonomy | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Preference learning | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Daily reflection → knowledge graph | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Fused recall (vector ⊕ graph RRF) | ✅ | ◐ | ❌ | ◐ | ❌ | ◐ | ❌ | ❌ |
| Night shift / reversibility gating | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Strict local agent (family privacy) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Visual workflow builder (DAG) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Trace explorer + offline eval | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Pure Python + open source | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

No competitor combines **autonomy + memory + observability + preference learning** in a single local-first system.

---

### Headline Options

> *"The AI that works while you sleep."*

> *"15 agents. One system. Your data stays home."*

> *"Finally: an AI assistant that learns what to stop asking you."*

> *"From chat to cortex — the operating system for your life."*

---

### Key Metrics at Launch

| Metric | Value |
|--------|-------|
| Active agents | 15 (+ 15 bench) |
| Channels | 7 (web, voice, Telegram, Discord, Slack, email, sandbox) |
| Tests passing | 909 |
| API endpoints | 17+ |
| Monthly cost | $0 |
| SQLite speedup | 36× |
| Story points delivered | 481 / 712 total (68%) |

---

### v1.0 Launch Checklist

| Item | Priority | SP | Status |
|------|----------|----|--------|
| CI/CD on PRs (H7.2) | P0 | 5 | ❌ Not started |
| Hermetic test suite (H7.1) | P0 | 5 | ❌ Not started |
| Input validation on endpoints (H7.5) | P1 | 3 | ❌ Not started |
| Clean silent exceptions (H7.6) | P1 | 5 | ❌ Not started |
| Fix dashboard cache race (BUG-1) | LOW | 1 | ❌ Not started |
| LICENSE + CONTRIBUTING.md (H7.9) | P1 | 5 | ❌ Not started |
| docker-compose.yml (H7.9) | P1 | — | ❌ Not started |
| README badges + screenshot (H7.9) | P1 | — | ❌ Not started |
| Personal Memory H8 (7 items) | P1 | 43 | ❌ Not started |

**Estimated gap to v1.0: ~67 SP — approximately 5–7 weeks at current velocity.**

---

### Roadmap Summary

| Version | Status | Milestone |
|---------|--------|-----------|
| v0.5-beta | 🟢 Live | H1–H4 foundation complete |
| v0.9.1-beta | 🟢 Live | H7 perf hotpath + real embeddings |
| v1.0.0 | 🎯 Q3 2026 | H7 hardening + CI/CD + onboarding + H8 memory |
| v1.1.0 | Planned | H10 competitive edge (30 items) |

---

*Full backlog: [BACKLOG.md](BACKLOG.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Competitor research: [docs/research/2026-06-02-competitor-research-h10.md](docs/research/2026-06-02-competitor-research-h10.md)*
