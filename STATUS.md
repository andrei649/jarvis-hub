# Jarvis Hub — Status Snapshot

> **Current version:** v0.11.0 (feature-complete + refactor done; productionizing toward 1.0) · **Tests:** ~3,600 passed (6 skipped) + frontend **163 vitest** + Playwright HUD/flow suites (HUD-v3 Console port complete: every blueprint surface + the north-star Decision Inbox + native Neural-Mesh canvas + cinema mode) · **Agents:** 17 active (16 cabinet incl. Howard + Argus, the WorldView bridge; + 17 bench) · **HTTP routes:** 363 (+ feedback widget/summary, H23.21; + onboarding, H23.20; +`/api/metrics/capabilities`, V2; + `/api/security/loop-breaker` status/reset, K3; + `/api/metrics/kernel`, Gate-K observability) — `web.py` decomposed into **45 per-domain routers** (CLN-3, #296); only 9 app-shell/chat/admin routes remain inline (4,636→1,282 LOC)
> **The version is the roadmap.** Every feature horizon (H1–H22 + WorldView O19) is delivered — that's **0.10.0**; the **0.11.0** refactor (CLN-3 `web.py` split + CLN-2 `orchestrator.py` managers) is done (#293/#296). There is no "audit gate" version: 1.0 is a real destination reached by finishing the productionization layer (**H23**: agentic-safety budgets, DB migrations, backup/restore + export-delete, operability, quality + user docs) **and** proving it with real design-partner users. The plan is the version line in [BACKLOG.md](BACKLOG.md#version-roadmap); strategy in [MOONSHOT.md](MOONSHOT.md) §4. Manual testing/audit ([docs/MANUAL_TESTING.md](docs/MANUAL_TESTING.md), [docs/AUDIT.md](docs/AUDIT.md)) is the release step that tags a version. GPU-gated dev (H12.14, H13.3, Howard) is its own minor (0.18). HUD deep write-controls tracked in [docs/design/HUD_V2_REMAINING.md](docs/design/HUD_V2_REMAINING.md).
>
> The version labels in the feature tables below (`v0.2.0`, `v0.2.1`) record *when* each capability first
> landed (provenance), not the current release. For live priorities and the version roadmap, BACKLOG.md is the source of truth.
>
> **Year-one review (candid, owner-facing):** [docs/REVIEW_YEAR_ONE.md](docs/REVIEW_YEAR_ONE.md) — status, the 12 learnings, the gap between *code-complete* and *desirable product*, and the next-90-days plan.

---

## ORIZONT 26 Update — 2026-07-04

O26 Phase 0, P1.1, P2.1, P2.2, P2.3, P2.4, and P2.5 are complete on `main`.
O26-P3.1 preview modes is merged in #505; O26-P3.3 eval-baseline persistence is delivered in #506.
O26-P3.2 HUD punch-list reconciliation is open as draft PR #507.

| Item | Status | Verified result |
|------|--------|-----------------|
| O26-P1.1 one-turn pipeline | ✅ merged | `Agent.build_prompt()` is shared by plain/stream paths; `_build_agent_turn_text()` injects persona + runtime truth + history/plugins/recall for both; `_complete_llm_turn()` centralizes memory/checkpoint/log/learning+bench/run-history/audit/cognition; `PersonaModule.nudge()` runs once per completed LLM turn when affect is enabled. |
| O26-P2.1 config consolidation | ✅ merged | `agents/core/env_config.py` is now the single boolean/env parsing leaf; ad-hoc env truthiness is ratcheted by tests. |
| O26-P2.2 memory consolidation | ✅ merged (#501) | `_complete_llm_turn()` records LivingMemory + decay entries only when `cognition.enabled && cognition.memory_enabled`; LivingMemory stores session/agent/channel, a turn reference, text digest, and size counters rather than duplicating raw transcript text. `SchedulerService` registers `memory-consolidation-decay` and `run_memory_maintenance()` performs NREM/REM consolidation plus decay candidate inspection without auto-deletion. |
| O26-P2.3 dormant disposition | ✅ merged (#502) | `load_agents()` now registers active agents into `PersonaModule` + `EnsembleModule`; `cognition.learning_enabled` is proven live through the autonomy calibration hook; `profile_extractor.legacy_status()` marks the old regex extractor parked with no production callers. |
| O26-P2.4 product posture | ✅ merged (#503) | `product.posture` defaults OFF; selecting `companion_wave1` or `design_partner` overlays wave-1 memory/cognition flags at runtime and surfaces provenance in security posture, onboarding wizard, and support bundle. Wave 2 kernel/budget/REDACT hardening remains future scope. |
| O26-P2.5 install smoke | ✅ merged (#504) | `scripts/install_smoke.py` provides the fast install path: real orchestrator boot with one fake local LLM backend, `/readyz` check, deterministic chat turn; `--dev` runs the full pytest suite after the smoke succeeds. |
| O26-P3.1 live preview modes | ✅ merged (#505) | The six preview modes now feed LIVE/SEED mode keys: Build reads workflows/marketplace/sandbox; Comms reads rooms plus registered Discord/Slack channel status and renders an honest empty state; Finance reads saved watchlist/payments while refusing mock balances; Health/Knowledge/Family require configured Apple Health/websearch/WhatsApp plugins. `/plugins` now reports runtime `configured`; `/status` reports channels. Owner live-data/plugin setup and self-hosted fonts remain. |
| O26-P3.3 eval baseline persistence | ✅ delivered (#506) | `.github/workflows/eval-nightly.yml` restores/saves the companion eval `DatasetStore` via pinned `actions/cache/{restore,save}` and an explicit `JARVIS_EVAL_STORE`; `companion_eval --ci-gate --store-root` records to that store, so baseline compare is no longer inert after the first successful scheduled/manual run. |
| O26-P3.2 HUD punch-list reconciliation | 🟡 draft PR #507 | `docs/design/HUD_V2_REMAINING.md` now distinguishes shipped controls from real remaining work, and `hud-p3-2-reconciliation.test.ts` pins that shipped TTS/mic/cognition/trust and Console controls are not re-listed as missing. |
| Local verification | ✅ targeted green | P2.2 focused sweep was 33 passed before #501 merge; P2.3 red/green tests (+4) plus ensemble, governed learning, persona, and memory-store suites are 48 passed before #502 merge. P2.4 focused posture/onboarding/security/support/lifespan/settings sweep was 39 passed locally; PR #503 full CI matrix green before merge. P2.5 smoke tests were green, `python scripts/install_smoke.py --json` exited 0 locally, and PR #504 full CI matrix was green before merge. P3.1 focused checks and full PR CI were green. P3.3 companion eval suites are green (19 passed), CLI store-root gate exits 0, and ruff/py_compile are clean. P3.2 red doc-guard is now green locally. |

---

## ORIZONT 25 Update — 2026-07-03

Integrated Codex development batch for the M1/M2 substrate and truth gates:

| Item | Status | Verified result |
|------|--------|-----------------|
| M1.1 K3 budget unification | ✅ done | Shared `BudgetLedger` now reports named dimensions; interrupt, mission, payment, and handler token usage feed the kernel view. |
| M1.2 `Action.origin` threading | ✅ done | `Gateway.route` classifies trusted web/voice vs inbound channels; brokers carry the current origin so inbound actions escalate through the kernel. |
| M2.1 chat/voice flow E2E | ✅ done | Playwright covers chat send→SSE→stop plus mocked voice push-to-talk into a chat turn. |
| M2.3 OpenAPI→TS typegen | ✅ done | Generated `frontend/src/api/schema.gen.ts`; CI regenerates from live `/openapi.json` and fails on diff. |
| M2.4 scheduled eval gate | 🟡 partial | Deterministic `companion_eval --ci-gate`, the schedule, and cache-backed persistent eval storage are wired, so baseline compare bites after the first successful scheduled/manual run. Live-model mode still needs a persistent/live runner. |

The 2026-07-03 local batch that bundled M1.3/M1.4/M1.5/M2.2/M2.4/M2.6 is recorded in `BACKLOG.md` as a protocol exception, not a precedent. Future ORIZONT 25 work returns to one item = one PR.

---

## ✅ Agents — 17 active (15 classic cabinet + Howard emerging + Argus WorldView bridge)

| Agent | Role | Tier | SOUL.md | HEARTBEAT.md |
|-------|------|------|---------|-------------|
| Jarvis | Prime Orchestrator | command | ✅ | ✅ morning |
| Friday | Daily Intel | command | ✅ | ✅ morning |
| Pepper | Chief of Staff | command | ✅ | ✅ morning + weekly |
| Jerome | Leisure & DJ | command | ✅ | ❌ reactive |
| Athena | External Strategy | business | ✅ | ✅ weekly |
| Stark | Corporate Intel | business | ✅ | ✅ morning |
| Veronica | The Voice | business | ✅ | ❌ reactive |
| Vision | Deep Research | business | ✅ | ✅ weekly |
| Steve | CTO & Builds | tech | ✅ | ✅ 5-min health |
| Oracle | n8n Workflows | tech | ✅ | ❌ reactive |
| Ultron | Security | tech | ✅ | ✅ hourly |
| Gecko | Finance | foundation | ✅ | ✅ daily |
| Hercules | Fitness | foundation | ✅ | ✅ daily |
| Hephaestus | Builder | foundation | ✅ | ✅ daily |
| Frigga | Family | foundation | ✅ | ✅ daily |
| Argus | Geoint (WorldView bridge, read-only) | business | ✅ | ❌ reactive |
| Howard | Digital Twin (emerging, local-only) | foundation | ✅ | ❌ reactive |

---

## ✅ Core Features (since v0.2.0)

| Feature | Module | Status |
|---------|--------|--------|
| Config loader | `core/config.py` | ✅ |
| Agent runtime | `core/agent.py` | ✅ |
| Orchestrator (full rewrite) | `core/orchestrator.py` | ✅ |
| Intent router | `core/router.py` | ✅ |
| Heartbeat scheduler | `core/heartbeat.py` | ✅ |
| Permission Gate | `core/plugin_gate.py` | ✅ |
| LLM backends (Ollama + LM Studio) | `core/llm/` | ✅ |
| Memory (conversation + vector + persistence) | `core/memory/` | ✅ |
| Voice pipeline | `core/voice/` | ✅ |
| MCP client | `core/mcp/client.py` | ✅ |

### New in v0.2.0

| Feature | Module | Status |
|---------|--------|--------|
| Skills System (discover, execute, generate, parse) | `core/skills/loader.py` | ✅ |
| Checkpointing (SQLite, WAL mode) | `core/checkpoint.py` | ✅ |
| Structured Session Storage | `core/checkpoint.py` (sessions table) | ✅ |
| Unified Gateway (rate limit, health) | `core/channels/gateway.py` | ✅ |
| Agent-to-Agent Handoff (`[handoff:agent_id]`) | `core/orchestrator.py` | ✅ |
| Promotion/Demotion Engine (5-failure threshold) | `core/agent.py` | ✅ |
| Parallel Agent Calls (per-model timeout) | `core/orchestrator.py` | ✅ |
| Graceful LLM Unavailability | `core/orchestrator.py` + `core/agent.py` | ✅ |
| Learning Loop (DSPy-style optimization) | `core/learning/loop.py` | ✅ |

### Ported from OpenJarvis v0.2.1

| Feature | Module | Status |
|---------|--------|--------|
| Security Guardrails (PII/secret scanner, SSRF, audit) | `core/security/` | ✅ |
| Skills Import (Hermes/OpenClaw/GitHub/agentskills.io) | `core/skills/importer.py` | ✅ |
| Sandboxed Code Execution (Docker + subprocess) | `core/sandbox.py` | ✅ |
| Discord Channel Adapter | `core/channels/discord.py` | ✅ |
| Email Channel Adapter (SMTP + IMAP) | `core/channels/email.py` | ✅ |
| Slack Channel Adapter | `core/channels/slack.py` | ✅ |
| Benchmark System (latency/throughput/success) | `core/bench.py` | ✅ |

### Channel Adapters

| Channel | File | Status |
|---------|------|--------|
| Base adapter | `core/channels/base.py` | ✅ |
| Telegram (long-poll) | `core/channels/telegram.py` | ✅ |
| Voice (wake → STT → TTS) | `core/channels/voice.py` | ✅ |
| Web (SSE, multi-client) | `core/channels/web.py` | ✅ |
| Discord | `core/channels/discord.py` | ✅ |
| Email (SMTP + IMAP) | `core/channels/email.py` | ✅ |
| Slack | `core/channels/slack.py` | ✅ |

### Plugin Implementations

| Plugin | File | Status |
|--------|------|--------|
| Weather (wttr.in) | `core/plugins/weather.py` | ✅ |
| News (BBC RSS) | `core/plugins/news.py` | ✅ |
| Cloud LLM (Anthropic/OpenAI) | `core/plugins/cloud_llm.py` | ✅ |
| Telegram bot | `core/plugins/telegram_bot.py` | ✅ |
| Gmail API | `core/plugins/gmail_plugin.py` | ✅ |
| WhatsApp local bridge | `core/plugins/whatsapp_bridge.py` | ✅ |
| Spotify control | `core/plugins/spotify_plugin.py` | ✅ |

---

## ✅ Web Endpoints (17) — All Smoke Tested PASS *(historical v0.2 snapshot — the current surface is ~299 routes; full index in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))*

| Endpoint | Route | Status |
|----------|-------|--------|
| Index | `GET /` | ✅ HTML served |
| Chat | `POST /chat` | ✅ (graceful LLM-down fallback) |
| Chat Stream | `POST /chat/stream` | ✅ |
| Status | `GET /status` | ✅ (includes learning, bench, security) |
| Agents | `GET /agents` | ✅ |
| Skills | `GET /skills` | ✅ |
| Skills Import | `POST /skills/import` | ✅ (hermes/openclaw/github) |
| Skills Imported | `GET /skills/imported` | ✅ (list imported) |
| Sessions | `GET /sessions` | ✅ |
| Memory | `GET /memory` | ✅ |
| Memory Clear | `POST /memory/clear` | ✅ |
| Learning | `GET /learning` | ✅ (stats + optimizations) |
| Security | `GET /security` | ✅ (guardrails, scanners, audit) |
| Bench | `GET /bench` | ✅ (latency, throughput, success rate) |
| Sandbox Status | `GET /sandbox/status` | ✅ (docker availability) |
| Sandbox Execute | `POST /sandbox/execute` | ✅ (Python + shell) |
| Dashboard | `GET /dashboard` | ✅ (cached plugin data + learning) |

---

## ✅ QA — Phases 1-3

| Phase | Scope | Result |
|-------|-------|--------|
| Phase 1 | 41/41 Python files compile, 21/21 module imports, 5/5 instantiation | ✅ PASS |
| Phase 2 | 8/8 integration suites (checkpoint, skill, gateway, memory, config, orchestator, agent, filesystem) | ✅ PASS |
| Phase 3b | 7/7 edge case suites (conversation memory, vector store, persistence, plugin gate, heartbeat, serialization, config) | ✅ PASS |
| Web smoke | Server starts, 8/8 endpoints respond (no LLM backend) | ✅ PASS |

---

## 🐛 Bugs Found & Fixed (3)

| Bug | File | Fix |
|-----|------|-----|
| `core/plugins.py` shadowed by `core/plugins/` package | `core/plugins.py` | Renamed to `plugin_gate.py`, re-exported via `__init__.py` |
| `ConversationMemory.get_history(last_n=0)` returned all turns | `core/memory/conversation.py` | Changed `if last_n:` to `if last_n is not None:` |
| `HeartbeatScheduler.load_all()` crashed on missing directory | `core/heartbeat.py` | Added `exists()` guard |

---

## 🟡 Known Gaps

| Gap | vs | Impact |
|-----|----|--------|
| ✅ Security Guardrails (v0.2.1) | OpenJarvis | Pure-Python PII/secret scanner, SSRF, audit |
| ✅ Sandbox (v0.2.1) | OpenJarvis (Docker + WASM) | Docker + subprocess execution |
| ✅ Skills Import (v0.2.1) | OpenJarvis (agentskills.io) | Hermes/OpenClaw/GitHub import |
| ✅ Multi-Channel (v0.2.1) | OpenJarvis (18+) | Now 6 channels (web, voice, telegram, discord, email, slack) |
| ✅ Bench System (v0.2.1) | OpenJarvis | Latency/throughput/success tracking |
| ❌ Desktop App | OpenJarvis (Tauri) | No native desktop UI |
| ❌ Rust Extension | OpenJarvis (14 crates) | No Rust — pure Python only |
| ❌ SFT/GRPO Training | OpenJarvis | No model fine-tuning (needs GPU) |
| ❌ WASM Sandbox | OpenJarvis (wasmtime) | Docker-only sandbox |

> **Real-category parity (2026-06-02 — vs personal/proactive/private AI competitors, not just the OpenJarvis ancestor; full analysis: `docs/research/2026-06-02-personal-ai-competitors.md`):**

| Gap | vs | Impact |
|-----|----|--------|
| ⚠️ Direct rival — governance wedge | **OpenClaw** | Same thesis (self-hosted, proactive, local-capable); we are the *governed/secure* alternative (H12.1) |
| ❌ Multi-surface passive capture | **Pieces.app** | Only text conversations ingested; no opt-in browser/clipboard/files → KG (H12.7) |
| ❌ Frictionless folder → doc-chat onboarding | **GPT4All / Khoj** | Config-heavy first run (H12.2) |
| ❌ Polished local-model management UX | **Jan.ai** | No one-click model browse/download/switch (H12.9) |
| ❌ Local voice hardware + Wyoming interop | **Home Assistant** | No satellite-mic / Wyoming support (H12.4, H12.8) |

---

## Decisions — resolved 2026-05-11

1. Wake words: **both** `jarvis` + `hub` ✅
2. Addressing: **"sir"** ✅
3. Frigga WhatsApp: **local bridge + manual entry fallback** ✅
4. Cloud LLM: **local by default, on-demand cloud for approved agents** ✅
   - Approved for cloud fallback: Jarvis, Athena, Stark, Vision, Veronica
