# AI System Prompt — Repo Architecture Analysis (jarvis-hub / Nerva)

> Generated architecture analysis + actionable system prompt for AI-driven development in this
> repository. Canonical sources it condenses: `AGENTS.md` (workflow policy), `docs/ARCHITECTURE.md`
> (module index + lifecycle), `NERVA.md` (architecture overview), `MOONSHOT.md` §5 (non-negotiables),
> `docs/AI_CONTEXT.md` (context-loading tiers), `BACKLOG.md` (priority truth). When this file and
> those disagree, **the canonical sources win** — fix this file.

---

## 1. Executive Repo Summary

**Core Purpose:** Nerva (repo codename *jarvis-hub*) is a **local-first Personal Intelligence
Operating System**: a multi-agent AI orchestration engine with 18 active agents (4 tiers) plus 14
dormant bench agents, coordinated by a prime orchestrator ("Jarvis"), with long-term memory,
governed autonomy, voice, smart-home ("House Brain"), camera intelligence, and a governed
capability-acquisition pipeline.

**Tech Stack:**

| Layer | Technology |
|---|---|
| Backend runtime | Python 3.12 + FastAPI + uvicorn (port 8080), pure-Python core |
| Local LLM | LM Studio (OpenAI-compatible API, port 1234) and Ollama; two-slot fast/deep model tiering |
| Cloud LLM (opt-in, per agent) | Anthropic Claude, Google Gemini (with context cache), OpenAI-compatible providers |
| Memory | Conversation JSONL + vector store (in-memory numpy 768-dim / optional Qdrant) + knowledge graph (in-memory / optional Neo4j) + Reciprocal Rank Fusion recall + LivingMemory tiers |
| Persistence | SQLite everywhere (WAL, `PRAGMA user_version` migrations): checkpoints, settings, audit (Merkle chain), autonomy queue, analytics |
| Frontend HUD | React 18 + TypeScript + Vite; Vitest + Playwright; OpenAPI→TS typegen (`schema.gen.ts`) |
| Mobile | React Native (Expo-style, Jest tests) — read-mostly parity surfaces (`mobile/PARITY.md`) |
| Voice | Browser loop (mic→`/api/voice/stt` Whisper→`/tts` clone chain) + server pipeline (openWakeWord, faster-whisper, XTTS→ElevenLabs→Fish→edge-tts→Kokoro) |
| Channels | Web SSE, Voice, Telegram, Discord, Slack, Email (SMTP/IMAP), webhook bridges (WhatsApp/Signal/Matrix/Teams/Google Chat) |
| Integrations | ~25 plugins (Gmail, Google Calendar, Spotify, Tavily/SearXNG, n8n, Homebridge, Tuya, Twilio, Notion, RevenueCat, Meta Ads, Postiz, …) behind a per-agent permission gate |
| Protocols | MCP client (stdio/SSE) **and** MCP server (governed route tools); A2A inbound (HMAC + contract) |
| Sibling stack | **WorldView** (4D OSINT) under `worldview/`: Vite/Next + CesiumJS + Fastify (ports 3000/4000, Docker); shares *no* runtime — bridged only via the versioned read-only contract `docs/contracts/worldview-bridge.md` through the **Argus** agent |
| Tooling | pytest (`asyncio_mode=auto`, offline, socket-blocked), Ruff, Bandit, vulture; `scripts/code_health.py`; `scripts/status_sync.py` (generated counters) |

**Architecture Pattern:** **Modular multi-agent monolith** — a single FastAPI app-shell
(`agents/web.py`, 9 inline routes) mounting **~66 per-domain `APIRouter`s**, all traffic funneled
through one `Orchestrator` main loop; **plugin/skill/channel adapter registries**; **event-loop-safe
hot path** (per-turn writes via `asyncio.to_thread` + WAL SQLite); and a **contract + Action-Kernel
governance layer** (every mutating effect passes identity → permission → typed contract → kernel
GRANT → durable audit). Autonomy is a queue/worker/policy state machine with a risk-tiered
ACT/NOTIFY/ASK gate and budgeted interrupts (≤4/day).

---

## 2. Directory Map & Core Data Flow

### Key Modules

```
serve.py                       Uvicorn launcher (entry point, web)
agents/run.py                  CLI REPL entry point → Orchestrator.handle_input
agents/web.py                  FastAPI app shell + lifespan; mounts ~66 routers; guards (_user_guard/_admin_guard)
agents/_system/agents.yaml     Canonical agent registry (id, tier, status, plugins, llm_policy)
agents/<id>/SOUL.md            Agent identity prompt (public template; personal data → gitignored SOUL.local.md)
agents/core/
  routers/                     THE HTTP surface — ~66 per-domain APIRouters (~405 routes); _deps.py = lazy auth guards
  orchestrator.py              Main loop: classify → gather plugins → route → call agents → synthesize
  agent.py                     Single agent runtime (SOUL loader, process/synthesize)
  router.py                    Deterministic keyword intent classifier (bilingual RO/EN)
  llm/                         Backends (LMStudio/Ollama/Claude/Gemini) + HybridRouter tiering + governed lifecycle control
  memory/                      Conversation + vector + graph + RRF fusion + LivingMemory persistence
  ingestion/                   "Howard" digital-twin pipeline (embedder w/ LRU+disk cache, FB/WhatsApp parsers, stylometry)
  autonomy/                    Proactive cortex: SQLite TaskQueue, worker, risk policy, decision inbox, digests, watchers
  kernel/                      Action Kernel budgets (BudgetLedger, LoopDetector) + binding
  security/                    Guardrails (WARN/REDACT/BLOCK), secret/PII scanners, SSRF, Merkle audit, quarantine/taint/rag_guard
  channels/                    ChannelAdapter implementations + Gateway (ingress taint, rate limits)
  plugins/                     All third-party integrations (one file per service)
  skills/                      Skill loader (quarantine for generated skills), importer, marketplace, signing
  voice/                       Server-side wake/STT/TTS pipeline
  mcp/                         MCP client + governed MCP server route tools
  workflows/, learning/, observability/, house/, cameras/, ambient/, osint/, market/ …  capability packs
skills/<name>/{SKILL.md,main.py}   Skill packs, auto-discovered
frontend/src/                  React HUD (voice.ts, orb.tsx, burst.tsx, wall.tsx, panels)
mobile/                        React Native companion (read-mostly parity)
worldview/                     Separate OSINT stack (own CI/tests; only coupling = bridge contract)
tests/                         pytest suite (~6,900+ backend tests, offline by default)
memory_logs/                   All persistent state (SQLite DBs, JSONL, embedding cache) — gitignored
scripts/                       status_sync.py, code_health.py, check_ai_workflow_policy.py, runtime_supervisor.py
```

### Core Data Flow (request lifecycle — `Orchestrator.handle_input[_stream]`)

```
Channel ingress (web SSE /chat/stream, CLI, Telegram, voice, …)
  └─ Gateway.route → taint-marks untrusted inbound; binds Action origin
1. memory.add_turn(session, "user", text)                 # JSONL + optional auto-embed
2. skills.parse_command(text)        → skill match? execute + return early
2b. detect_llm_control(text)         → LM Studio/Ollama lifecycle intent? full authority
    chain (permission → HOST_CONTROL_CONTRACT → Action Kernel GRANT → audit) → controller
    → narrate REAL result + return early (kill-switch gated)
3. router.classify(text)             → Intent (deterministic keywords, RO/EN)
4. _gather_plugin_data(text, intent) → weather/news/calendar/email/websearch in parallel
5. _route_candidates(intent)         → learning loop reranks; unhealthy agents filtered
6. llm_router.select_backend(agent)  → LOCAL_ONLY floor → registry llm_policy → auto
                                       (local slot 1 → deep slot 2 on heavy → Gemini flash/pro)
7. _call_agents_parallel             → prompt = persona + history + plugin/recall/rag blocks
                                       (recall = RRF fusion of vector ⊕ graph, fenced by rag_guard)
                                       120s timeout per agent; streaming strips <think> live
8. multi-agent? _synthesize(responses)
9. memory.add_turn(session, "assistant", answer)
10-13. off-loop bookkeeping via asyncio.to_thread: debounced checkpoint, session log,
       learning/bench records, audit row, LivingMemory/cognition hooks
```

**Autonomy loop (proactive path):** observers/watchers → `TaskQueue` (SQLite) →
`AutonomyWorker.tick` → `AutonomyPolicy` risk gate (ACT / NOTIFY / ASK) → decision cards to the
inbox/channels within the interrupt budget → executor dispatch, all kernel-mediated and audited.

---

## 3. AI Agent Conventions & Guardrails

### Coding Standards

- **Python 3.12, async-first.** Route handlers and agent paths are `async def`; blocking work
  (SQLite, file I/O, embedding calls) goes through `asyncio.to_thread` — never block the event loop.
- **Ruff is the law:** rules `E,F,W,I,B,UP,SIM,C4`, line length 100, `target-version = py312`,
  max complexity 12 (`pyproject.toml` + `ruff-baseline.toml`). Entry-point `sys.path`/env setup
  before imports is allowed (E402 ignored).
- **Typed errors:** raise/return `JarvisError` + `E_*` codes (`agents/core/errors.py`); logging via
  `agents/core/log.py` (`setup_logging`, `log_error`). External calls wrap in
  `resilience.resilient_call` (circuit breaker + retry) where flakiness matters.
- **Env parsing:** never `int(os.environ[...])` / ad-hoc truthiness — use the shared
  `agents/core/env_config.py` helpers (`env_int`, `env_flag`, `env_float`, `env_list`,
  `env_json_object`); malformed values must fall back, not crash (AUD-14 ratchet tests enforce this).
- **Settings:** startup config in `agents/_system/agents.yaml`; runtime-mutable settings in
  `settings_db.py:DEFAULTS`, read via `orch.get_setting("category.key", default)` (30s reload).
- **SQLite schema changes:** append-only `_MIGRATIONS` via
  `agents/core/persistence/migrations.py:apply_migrations`; never edit or reorder a shipped migration.
- **Frontend:** TypeScript strict (`tsc --noEmit` must pass), React function components, API types
  from generated `frontend/src/api/schema.gen.ts` (regenerated from `/openapi.json`; CI diffs it).
- **Honesty in surfaces:** UI/API cells render proven data or an explicit empty state (`—`) — never
  mock/fabricated values presented as live.

### Strict Guardrails (non-negotiable — MOONSHOT.md §5 + AGENTS.md)

1. **Local-first:** `frigga`, `ultron`, `howard`, `hestia` are `LOCAL_ONLY_AGENTS`
   (`llm/hybrid_router.py`) — code-enforced, never routed to cloud, fail closed. Every cloud hop is
   an explicit, auditable opt-in.
2. **No ungoverned mutation:** any effect on the host, money, external services, memory purge, or
   channels passes identity → permission (`PermissionGate`) → typed automation contract
   (`automation_contracts.py` family) → enabled/bound **Action Kernel GRANT** → durable
   `AuditLogger` row *before* the effect. `DENY`/`QUEUE`/missing gate = refuse with no side effect.
3. **No secrets/personal data in the repo:** credentials come from `.env`/OAuth store; personal
   agent data lives only in gitignored `SOUL.local.md`/`HEARTBEAT.local.md`; public `SOUL.md`
   files stay generic templates.
4. **Route discipline:** new endpoints go in `agents/core/routers/<domain>.py` mounted from
   `web.py` — **never** new inline `@app.*` routes. Any route-surface change must re-seed
   `python tests/test_route_parity_guard.py --update` in the same PR, and update `mobile/PARITY.md`
   / `docs/design/HUD_V2_REMAINING.md` for user-facing capability changes.
5. **Untrusted input stays untrusted:** channel/inbound content is taint-marked
   (`security/taint.py`); retrieved memory is fenced as DATA via `rag_guard.wrap_memory` before
   prompting; a tainted action escalates GRANT→QUEUE. Never bypass these choke points.
6. **Tests ship with the feature** (production-grade, not demo-grade); tests are offline
   (pytest-socket blocks non-loopback), inject fake backends, and never require a live LLM.
7. **Governed capability growth only:** generated skills land quarantined `PENDING_REVIEW`
   (CDX-8) and require explicit approval; sandbox → verification → approval → registry is the only
   path; unrestricted self-modification is permanently out.
8. **Autonomy is budgeted:** reversible work may act silently; interrupts respect the ≤4/day
   budget (`BudgetLedger`); money/locks/security actions never rise above the approval queue.
9. **Workflow:** feature branch + PR into `main` (direct push disabled); classify risk R0–R3 per
   `.github/ai-development-policy.json`; evidence receipts bind to the exact head SHA; never
   describe an unrun suite as passing. Don't touch `BACKLOG.md`/generated status in
   inspection-only tasks; **do** sync `BACKLOG.md` in the same PR that delivers roadmap items.
10. **Generated counters are generated:** test/route counts in `STATUS.md`/`NERVA.md` are synced
    by `scripts/status_sync.py` — don't hand-edit them.

### Validation (primary terminal commands)

```bash
# Install (backend runs from source, not as a package)
pip install -r requirements-beta.txt        # runtime (locked: requirements-beta.lock)
pip install -r requirements-dev.txt         # dev/test tooling

# Backend tests (offline, asyncio_mode=auto, 30s per-test timeout)
python -m pytest tests/<targeted_test>.py -q   # targeted — preferred first
python -m pytest -q                            # full suite (~6,900+ tests)
make test                                      # same as full suite

# Lint / health / policy
ruff check .                                   # or the full pass:
python scripts/code_health.py                  # lint + format + dead-code, identical to CI
python scripts/check_ai_workflow_policy.py     # AGENTS.md ↔ machine policy consistency
python scripts/status_sync.py                  # resync generated counters after surface changes

# Frontend (from frontend/)
npm install && npm run typecheck && npm test && npm run build   # vitest + tsc + vite build
npm run e2e                                    # Playwright suites

# Mobile (from mobile/): npx jest && npx tsc --noEmit

# Run the app
python serve.py                                # FastAPI on http://127.0.0.1:8080 (LM Studio on :1234)
python scripts/install_smoke.py                # fast real-boot smoke (fake local LLM, /readyz, one turn)
```

---

## 4. Task Execution Checklist

Standard workflow for any feature or refactor in this repository:

1. **Load context by tier, not raw** (repo ≈ 2M tokens): `CLAUDE.md` → `AGENTS.md` →
   `docs/ARCHITECTURE.md` → `MOONSHOT.md` → `STATUS.md` → `NERVA.md`, then **one** task bundle from
   `docs/AI_CONTEXT.md` (backend module + router + matching tests / frontend / voice / security /
   WorldView). `BACKLOG.md` is the priority truth when docs disagree.
2. **Safe start:** inspect `git status`, current branch, and pre-existing changes; preserve other
   agents' work; check for overlapping open PRs (draft PR = visibility signal, not a lock).
3. **Classify risk** (`R0`–`R3` per `.github/ai-development-policy.json`) — it determines tests,
   review, and merge controls. Record goal, non-goals, likely paths, tests, rollback before
   non-trivial implementation.
4. **Branch:** create a feature branch; one coherent, independently revertible slice per PR
   (security/authority changes always separate).
5. **TDD where a regression is demonstrable:** write the failing test first
   (`tests/test_<module>.py`, sys.path header pattern, fake backends, offline); for orchestrator
   units use `Orchestrator.__new__(Orchestrator)` + manual attributes, not full init.
6. **Implement within conventions:** per-domain router (not `web.py` inline), guards from
   `routers/_deps.py` (`_user_guard`/`_admin_guard`), shared env parsers, settings in
   `settings_db.py:DEFAULTS`, append-only migrations, contract + kernel + audit gates on any
   mutating effect, taint/rag-guard on any untrusted text.
7. **Sync the coupled surfaces in the same PR:** route-parity snapshot (`--update`),
   OpenAPI→TS typegen if the API changed, `mobile/PARITY.md` or HUD-V2 ledger for user-facing
   capabilities, `scripts/status_sync.py` for counters, `BACKLOG.md` checkboxes for delivered
   roadmap items.
8. **Validate before push:** targeted pytest → adjacent sweep → ruff/`code_health` →
   frontend/mobile typecheck+tests when touched → `check_ai_workflow_policy.py`. Never report an
   unrun suite as passing.
9. **PR with evidence:** exact commands + exit codes bound to the head SHA, risk tier, changed
   paths, rollback note. Any new commit stales prior evidence — re-establish it.
10. **Review & merge:** max two consolidated review rounds, then escalate; `R3` requires separate
    builder/reviewer/integrator; finish with explicit states
    (`delivery=… ci=… governance=… lease=none head=<sha> next=…`).
