# Jarvis Hub — Delivery History

> Narrative record of what was built, when, by whom, and notable events.
> Active backlog: [BACKLOG.md](../BACKLOG.md) · Go-live plan: [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md)

---

## Decision — Product rename to Nerva executed in-product (2026-07-19)

Owner decision (MOONSHOT §7.4): the product identity is **Nerva** (published by Digitaholic),
per [NERVA_VISION.md](../NERVA_VISION.md) §2, and the rename was executed across every
user-facing surface: HUD chrome + titles, the packaged executable (`nerva[.exe]`,
`%LOCALAPPDATA%\Programs\Nerva`, data folder `Documents/Nerva`), landing page, README hero,
logo (`docs/brand/nerva-mark.svg` — the "neural N"), wake words (`nerva` added), and
architecture doc (`JARVIS.md` → `NERVA.md`). Deliberately KEPT: agent persona names (Jarvis
stays the prime-orchestrator agent — "existing named agents remain as specialist roles"),
the `jarvis-hub` repo/engine codename, python package paths, and the `JARVIS_*` env prefix
(compatibility; engine-level). Still owner-only: the GitHub repo rename
([docs/OWNER_TASKS.md](OWNER_TASKS.md)). Rationale: resolves the Marvel/Disney naming risk
flagged in [BRAND_BOOK.md](BRAND_BOOK.md) §2 ahead of Phase 2.

---

## North-Star Instrumentation + Year-One Review — Sprint 2026-06-20

> The MOONSHOT §6 metric set was defined but never computed in one place. This sprint
> added the aggregator + endpoint, and a candid year-one retrospective.

- **North-star aggregator** (`agents/core/observability/north_star.py`, `compute_north_star`):
  folds the existing autonomy `TaskQueue` (accepted/`done`, `rejected`, `pushed`),
  `RunHistory.locality()`, and the `Tracer` per-turn `total_ms` into one dashboard dict —
  weekly autonomous actions *accepted* per active user + the four counter-metrics
  (interrupt rate, reject rate, %-local, p95 non-LLM latency). Pure function over injected
  stores; no schema change, no behaviour change. Single-user honest (`active_users` 0/1,
  never fabricates a fleet; every metric `null` when its source has no data).
- **Endpoint** `GET /api/metrics/north-star?days=1-90` (`agents/core/routers/analytics.py`,
  open like the sibling `analytics/locality` + `cost` + `traces` meters; mapped to the
  Observe HUD surface). +8 offline tests (`tests/test_north_star.py`).
- **Docs:** `docs/METRICS.md` (field definitions + n=1 caveat); MOONSHOT §6 marked
  "Now instrumented".
- **`docs/REVIEW_YEAR_ONE.md`** — owner-facing candid year-one review (status, the 12
  learnings, the gap between code-complete and a *desirable* product, next-90-days plan).
- **Doc reconciliation:** swept stale counts to current values across the canonical docs
  (routes ~253/~296 → ~299 from the route snapshots; backend tests 2,156/2,288 → ~2,400),
  and registered the two new docs in MOONSHOT §8, CLAUDE.md, and docs/AI_CONTEXT.md.

---

## HUD v2 Voice — Sprint 2026-06-07

> Browser-side hands-free voice for the HUD (`/v2`). The engines (Whisper STT, edge-tts/XTTS)
> already existed but were wired for a host-attached mic; the browser loop that lets you talk
> to Jarvis *in the interface* did not. Full doc: [VOICE.md](VOICE.md).

| Item | PR | Status |
|------|----|--------|
| Browser voice loop — mic → local Whisper (`POST /api/voice/stt`, raw body) → chat → TTS playback (server `/tts` cloned voice + local `speechSynthesis` fallback), hands-free; `frontend/src/voice.ts` `useVoice` | #162 | ✅ |
| Honest `GET /api/voice/capabilities` + STT `503`-with-hint (never a fabricated transcript); `tests/test_voice_stt.py` (+4 mocked) | #162 | ✅ |
| Voice settings (hands-free/PTT, speak server/browser/off, lang auto/RO/EN) persisted in `hud.voice`; respects `JARVIS_MIC_MUTED` | #162 | ✅ |
| Opt-in barge-in (default off, experimental) + SPEAK `CLONED`→`SERVER` honesty rename | #164 | ✅ |
| Docs: `docs/VOICE.md` (new), ARCHITECTURE §3 + Doc Map; BACKLOG H5.16 corrected | docs | ✅ |

**Honesty note:** the H5.16 backlog correction *claimed* in #162's commit/PR never actually landed
(the edit was made on a stale checkout and discarded by a `git reset` during a container-resync,
then not re-applied) — it is corrected for real in the docs PR. Live mic/audio + barge-in tuning
are verifiable only on a real device, not in headless CI.

---

## H7 Hardening + H8 Personal Memory — Sprint 2026-06-02 (v0.9.2, Live ✅)

> Echipă: 5 agenți Claude în paralel (wave dispatch cu git worktrees). Durata: 1 sesiune.

### Wave A — CI/CD, HTTP Client, Docs (PR #29–33)

| Item | PR | Status |
|------|----|--------|
| H7.1 Hermetic test suite (`JARVIS_TESTING` gate, conftest, pytest-timeout) | #31 | ✅ |
| H7.2 CI/CD pipeline (ubuntu+windows matrix, ruff, CodeQL) | #31 | ✅ |
| H7.3 PluginHTTPClient + circuit breaker (14+ pluginuri migrate) | #32 | ✅ |
| H7.8 + H7.9 Docs truth + Onboarding (LICENSE, CONTRIBUTING, docker-compose, release.yml) | #30 | ✅ |
| H8.4 Embedding model upgrade (mxbai-embed-large) | #33 | ✅ |
| H8.7 ARCHITECTURE.md actualizat (port, agent count, embed model) | #33 | ✅ |
| docs HISTORY.md creat, BACKLOG trim, GO_LIVE_PLAN gaps (H8.5, H10.21) | #29 | ✅ |

### Wave B — SQLite Hardening, Exception Logging, Learning Loop (PR #34)

| Item | PR | Status |
|------|----|--------|
| H7.4 SQLite thread-safety (`check_same_thread=False`, WAL, asyncio.Lock — 6 fișiere) | #34 | ✅ |
| H7.6 Excepții silențioase curățate (20+ `except: pass` → `logger.warning`) | #34 | ✅ |
| H7.11 Learning Loop (`agents/core/learning_loop.py`, job săptămânal, gated) | #34 | ✅ |

### Wave C — Input Validation, Mock Removal, Cost Analytics (PR #38)

| Item | PR | Status |
|------|----|--------|
| H7.5 Input validation Pydantic (message 4096, code 32KB, limit 1–200 → 422) | #38 | ✅ |
| H7.7 Elimină mock data (`/tasks` empty, iot_control `_mock: true`) | #38 | ✅ |
| H7.10 Cost & Usage Analytics (`cost_tracker.py`, `GET /api/analytics/cost`) | #38 | ✅ |

### Wave D — Personal Memory Store (PR #37)

| Item | PR | Status |
|------|----|--------|
| H8.1 Profile extractor (regex rules, `ProfileFact`, `process_conversation`) | #37 | ✅ |
| H8.2 MemoryStore SQLite (`agents/core/memory/store.py`, upsert/get/search/delete) | #37 | ✅ |
| H8.6 Weekly digest (`agents/core/memory/digest.py`, `generate_digest`) | #37 | ✅ |

### Wave E — Recall HUD + Model Tier HUD (PR #43)

| Item | PR | Status |
|------|----|--------|
| H8.3 Recall HUD (`GET /api/memory/profile`, `/api/memory/recall`, admin Memory tab) | #43 | ✅ |
| H8.5 Model Tier HUD (`GET /api/analytics/model-tiers`, admin Cost tab) | #43 | ✅ |

### Metrici sesiune

| Metric | Valoare |
|--------|---------|
| PRs deschise | 15 (5 waves × 3 agenți paraleli max) |
| PRs merged | 15 / 15 ✅ |
| Teste noi | +192 (1100+ total) |
| CI verde | ubuntu ✅ windows ✅ CodeQL ✅ |
| BUG-1 (`_dashboard_cache` lock) | ✅ rezolvat (PR #36, wave externă) |
| Versiune lansată | 0.9.1 → **0.9.2** |

---

## Foundation — Sprint 0 + H1–H4 (v0.5-beta, Live ✅)

### H1 — Voice, Channels & OAuth

| Item | SP | Acceptance Criteria |
|------|----|---------------------|
| H1.1 Voice Channel (STT → orchestrator → TTS) | 8 | Pipeline complet funcțional |
| H1.2 Telegram Channel (webhook + polling) | 5 | Bot răspunde direct, session per chat_id |
| H1.3 Web Channel robust (SSE streaming) | 3 | Text → LLM → tokens streamuite în HUD |
| H1.4 OAuth wiring (Google Calendar, Gmail, Spotify) | 5 | Token refresh + OAuth lifecycle complet |
| H1.5 Admin DB → Runtime (settings watcher 30s) | 5 | Schimb temp din admin → efect imediat |
| S0.1 Model Tiering (Claude API for heavy, local for light) | 3 | Vision/Steve → Claude; rest → local; Frigga → strict local |
| S0.2 Heartbeat Sanity (intervals ≥60 min) | 2 | Steve la 2h, Ultron de 2x/zi, rest OK |
| S0.3 Smoke Test + CI pe push | 2 | GitHub Actions pytest + server smoke |

### H2 — Core Agent Capabilities (12 items)

| Item | SP | Acceptance Criteria |
|------|----|---------------------|
| H2.1 Pepper Calendar | 5 | „adaugă meeting" → eveniment creat |
| H2.2 Pepper Gmail Triage | 5 | „ce e nou în inbox?" → listă priorizată |
| H2.3 Friday Brief Pipeline | 8 | Briefing complet structurat la cerere |
| H2.4 Hercules Health Data | 5 | „cum am dormit?" → durată, calitate, trend |
| H2.5 Jerome Spotify | 3 | „pune ceva focus" → track din library |
| H2.6 Gecko Balance Reader | 8 | „câți bani am?" → sumă + mock când neconfigurat |
| H2.7 Hephaestus PM | 8 | „status Cosmina?" → fază, milestone, blockeri |
| H2.8 Frigga Local Store | 8 | „cât a dormit Max?" → ore, calitate. Zero network |
| H2.9 Vision Web Research | 5 | „cercetează piața X" → raport cu surse |
| H2.10 Veronica Drafting | 3 | „scrie post LinkedIn" → draft complet |
| H2.11 Stark GA4 Analytics | 5 | KPI summary + mock când neconfigurat |
| H2.12 Hybrid LLM Router (local ↔ Gemini) | 13 | Rutează per request după token count + agent policy |

### H3 — Intelligence & Memory (6 items)

| Item | SP | Acceptance Criteria |
|------|----|---------------------|
| H3.1 Qdrant Vector DB | 5 | Căutare similaritate pe conversații |
| H3.2 Neo4j Knowledge Graph | 8 | „unde lucrează Andrei?" → răspunde din graph |
| H3.3 Session Persistence cross-channel | 5 | Mesaj web → întrerup → Telegram → același context |
| H3.4 Learning Loop live | 8 | După 100 interacțiuni → sugerează promovare bench |
| H3.5 Heartbeat System (APScheduler) | 5 | 07:00 Jarvis face morning brief fără trigger |
| H3.6 Bench Agent Activation | 8 | 20 query-uri Vision → Bruce devine activ |

### H4 — Platform & Security (11 items)

| Item | SP | Acceptance Criteria |
|------|----|---------------------|
| H4.1 Discord Channel | 5 | Agent trimite mesaj pe Discord |
| H4.2 Email Channel (SMTP/IMAP) | 3 | „trimite raport pe email" → trimis |
| H4.3 Slack Channel | 3 | Stark vede mențiuni Slack |
| H4.4 Ultron Security Monitoring | 8 | „status securitate?" → devices, ports, threats |
| H4.5 Steve System Monitor | 8 | „cum e sistemul?" → metrics + alerts |
| H4.6 Oracle n8n Workflow Designer | 5 | „creează workflow vreme" → creat |
| H4.7 MCP Client real (stdio; the SSE half was never implemented — see DRA-25) + admin-wiring | 8 | Server adăugat din admin → disponibil ca plugin |
| H4.8 Sandbox Docker | 5 | „rulează Python" → container, output |
| H4.9 Guardrails (REDACT/BLOCK) | 5 | Prompt injection → blocat; PII → redactat |
| H4.10 Admin Charts & Audit | 8 | Admin arată ultimele 100 interacțiuni, latență |
| H4.11 Context Cache + Metrics | 5 | 50 mesaje → 80% cache hit |

### Cross-cutting / Security / Bugfixes

**Cross-cutting (6):** Session Manager thread-safe, Error taxonomy, CHANGELOG.md, Integration tests per agent (15), Plans per agent, Load test 15 agenți <30s.

**Securitate (5):** Admin env masked, Admin guard (token/localhost), SSRF protection, Gemini stream raise_for_status, OAuth PKCE+state+Fernet.

**Bugfixes (17):** 17 bugs fixed (admin.js, app.js, web.py, orchestrator.py, css) — detalii în archive commit `4e3bae5`.

---

## ORIZONT 5 — Next Wave (v0.6–v0.9-beta, ✅ 17/17 Complet)

### Delivery Timeline

**2026-06-01 — Sesiunea Claude:**
- H5.15 ✅ Daily Reflection + H5.6 ✅ Multi-Agent Workflows + H5.14 Task4 ✅ `/api/memory/search` + HUD Fused Recall. Merged în `main` (PR #13, commit `6eaac77`).

**2026-06-01 — Antigravity:**
- H5.1 ✅ Howard Stark Digital Twin + H5.2 ✅ Mobile HUD / PWA + H5.3 ✅ i18n RO/EN + H5.4 ✅ Premium UI Overhaul + H5.7 ✅ New Plugins + H5.8 ✅ Agent Marketplace.

**2026-06-01 — Sesiunea Claude (LM Studio recall fix):**
- Brațul vectorial al fused recall era mort — `/api/memory/search` trimitea `embedding=None`. Fix: `Embedder` capătă backend LM Studio (`/v1/embeddings`) + fallback hash determinist. +9 teste offline (809 passed, 9 skipped).

### Item Specs (complete)

**H5.1 ✅ — Howard: Fine-Tuning + Voice Clone + Continuous Ingestion (S:13)**
RAG pipeline (`ingestion/pipeline.py`, `watcher.py`), Facebook/WhatsApp parsers, `Embedder` cu caching (H5.17), TTS fallback chain (edge-tts/XTTS/ElevenLabs), IngestionWatcher wired în orchestrator.
*Fine-tuning model: necesită export date personale Andrei — infra 100% gata.*

**H5.2 ✅ — Mobile HUD / PWA (S:8)**
Dashboard responsive, mobile-first, offline support (Service Worker), push notifications.

**H5.3 ✅ — Multi-Language / i18n (S:5)**
Extrage stringuri RO hardcodate în fișiere de traducere, suport EN/RO, detectare automată limbă.

**H5.4 ✅ — UI Overhaul (S:8)**
Teme, layout îmbunătățit, componente reutilizabile, animații, accesibilitate.

**H5.5 ✅ — Performance & Robustness (S:8)**
`@resilient_call` decorator cu retry + exponential backoff, `CircuitBreaker` tri-state (closed/open/half-open), `ResilienceMetrics` per agent+backend. Integrat în CloudLLMPlugin (Anthropic, Gemini, OpenAI) și pluginuri HTTP. Expus în `/api/admin/stats` + admin UI charts. Load test: 50 apeluri paralele cu 10% failure rate.

**H5.6 ✅ — Multi-Agent Workflows (S:13) — LIVRAT 2026-06-01**
`core/workflows/`: `WorkflowEngine` (DAG topological sort, parallel batches via asyncio.gather, template substitution `{step_id}`), `Pipeline`/`WorkflowStep`, `WorkflowRegistry` (3 built-ins: finance_report, research_and_brief, security_digest). Endpoints `GET /api/workflows` + `POST /api/workflows/run`. 16 teste offline (`tests/test_workflows.py`).

**H5.7 ✅ — New Integrations / Plugins (S:8)**
Pluginuri noi: notificări SMS, CRM sync, social media posting, IoT control.

**H5.8 ✅ — Agent Marketplace / Skill Sharing (S:13)**
Catalog de skills partajabile, import dintr-un registry, versionare skills, publish workflow.

**H5.9 ✅ — Resilience Tab in Main HUD (S:3)**
Tab în SystemsPanel cu starea circuit breakerelor și retry metrics (endpoint `/api/resilience`).

**H5.10 ✅ — Live Data Wiring (S:5)**
Memory, Plugins, Learning, Security tabs → endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`).

**H5.11 ✅ — Missing Widgets (S:5)**
Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live.

**H5.12 ✅ — Secured Shell Task Executor (S:5)**
`RemediationRunner` (`core/autonomy/remediation.py`): allowlist + permission gate + no-shell (`create_subprocess_exec`) + bounded timeout + audit. Wired ca handler `restart_service` în executor.

**H5.13 ✅ — Proactive Event Watchers (S:8)**
`EventWatcher` + `EmailProbe`/`CalendarProbe`/`FinanceProbe`/`HealthProbe` (`core/autonomy/watchers.py`). Probe injectabile, testate offline (`tests/test_event_watchers.py`).

**H5.14 ✅ — Retrieval Fusion Engine (S:5)**
`core/memory/fusion.py`: `reciprocal_rank_fusion(ranked_lists, k=60, weights, top_k)` — RRF pur, rank-based, cu provenance (`sources`) și payload merge; `HybridRetriever(vector_store, graph)`. Task4: endpoint public `/api/memory/search` + `FusedRecallBox` în HUD. 9 teste (`tests/test_retrieval_fusion.py`).

**H5.15 ✅ — Daily Reflection & Graph Consolidation (S:8) — LIVRAT 2026-06-01**
`core/autonomy/reflection.py`: `DailyReflector` — gather context (last 60 turns) → LLM prompt → JSON `{entities, relations, lessons}` → `add_fact()` în Neo4j. Idempotent per zi. Fereastră 22:00–07:00, gated `system.reflection_enabled`. Endpoints `/api/reflection/status` + `/api/reflection/run`. 10 teste offline.

**H5.16 ✅ — Sentence-level TTS & Audio Barge-in (S:8)**
edge-tts backend, dynamic speech button (🔊), global audio window manager (`window.activeJarvisAudio`), hands-free live voice interaction (auto-submit + auto-speak). `ThinkingStreamFilter` + `strip_thinking()` pentru modele reasoning. Fallback `reasoning_content` în `generate_stream()`.

**H5.17 ✅ — Batch & Cache Embeddings Pipeline (S:5)**
`EmbeddingCache` (cheie `sha256(namespace\x00text)`, sharding pe 2 hex, scriere atomică temp→rename); `Embedder.embed_batch(texts, batch_size)` cu dedup + paralel + retry/backoff + degrade la hash. 9 teste offline (`tests/test_embedding_pipeline.py`).

---

## ORIZONT 6 — Jarvis Autonom (✅ 7/7 Complet)

**Design:** `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`
**Research:** `docs/research/2026-05-31-autonomous-proactive-agents.md`

### Delivery Notes (2026-05-31 / 2026-06-01)

**Audit MCU (2026-05-31):** Intent router rescris (determinist, scored, bilingv RO/EN, fără substring-bug, fallback LLM opțional). Detalii: `docs/gap-analysis-mcu-jarvis.md`.

**Livrat 2026-06-01:** Handler real `restart_service` (H5.12 — `RemediationRunner`) și event-watchers email/calendar/finanțe/health (H5.13 — `EventWatcher`) implementate, wired și testate.

**Setări noi** (categoria `autonomy` în admin): `owner_chat_id`, `cap_per_action`, `daily_ceiling`, `interrupt_budget`, `night_shift/start/end`, `system.autonomy_tick`.

**UPDATE CHAT ANTIGRAVITY (2026-06-01) ✅:** Core TTS & Hands-Free Live Voice Interaction implementat complet.

**Bug-uri rezolvate în H6:**
1. Eroare runtime stale pycache (`SecurityEventType.LLM_CALL` missing) — curățare pycache + repornire.
2. `t_s0 is not defined` în `handle_input_stream` — inițializare explicită de cronometru.
3. Scurgeri thinking/reasoning blocks în stream — `ThinkingStreamFilter` + `strip_thinking()`.
4. Crash `TypeError` în event handler `submit` al UI — securizare `textOverride` tip string.

**QA PASS CLAUDE (2026-06-01) ✅:** 740 passed, 9 skipped (după fix); 749 cu H5.14.
- Verificat: TTS/voice Antigravity (PR #11), `/tts` endpoint, `ThinkingStreamFilter`, fallback `reasoning_content`.
- Descoperit & sincronizat: H5.12 + H5.13 erau implementate dar nemarcate în backlog → marcate ✅.
- Bug CI reparat: 2 eșecuri ordine-dependente din scurgerea globalei `web.orch` între fișiere de test. Fix: lifecycle simetric (guarded) în `web.py` + save/restore în helperul de resilience.

---

## ORIZONT 7 — Performanță Cale Fierbinte (✅ 5/5 Complet, 2026-06-02)

**Sursa:** profiling 2026-06-02 al căii per-turn (NU generarea LLM). Bottleneck non-LLM = scrieri sincrone SQLite pe event-loop. Detalii + măsurători: `docs/research/2026-06-02-perf-hotpath.md`.

**Câștig măsurat:** commit SQLite 3317µs → 92µs (~36×) cu WAL+`synchronous=NORMAL`.

| # | Item | SP | Detalii |
|---|------|----|---------|
| H7-PERF.1 ✅ | SQLite WAL + `synchronous=NORMAL` | 1 | `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`. Commit-uri ~36× mai ieftine. |
| H7-PERF.2 ✅ | Offload scrieri blocante de pe event-loop | 3 | `checkpoints.save` / `audit.log` / `_record_interactions` via `asyncio.to_thread`. Thread-safe cu `check_same_thread=False` + `threading.Lock`. |
| H7-PERF.3 ✅ | Debounce / frecvență checkpoint | 2 | `_maybe_checkpoint()` salvează la `memory.checkpoint_every` (default 5) turns; `_flush_checkpoint()` forțat pe `new_session()` + `aclose()`. |
| H7-PERF.4 ✅ | Query-embedding cache + fast-fail | 2 | `Embedder.from_env(cache_dir=…)` + LRU in-process (`_PROC_CACHE`, 256); `max_retries=1` fast-fail. |
| H7-PERF.5 ✅ | Strategie fast/heavy model | 8 | `is_heavy_request()` (token threshold 2000 + keywords RO/EN) escaladează în `hybrid_router.select_backend()` POLICY_AUTO; flag `JARVIS_AUTO_DEEP`. |

**Livrat în paralel** (3 streams Claude Code în worktree izolat: A=H7-PERF.2+H7-PERF.3, B=H7-PERF.4, C=H7-PERF.5), integrat secvențial cu rezolvare conflicte. +49 teste offline noi.

**Setări noi:** `memory.checkpoint_every` (runtime), env `EMBED_CACHE_DIR`, `JARVIS_AUTO_DEEP`.

**Caveat-uri:** checkpoint poate întârzia ≤N turns (flush pe boundary sesiune); `get_model(agent_id)` NU escaladează (nu are prompt) — escaladarea trăiește în `select_backend()`. H7-PERF.5 validabil complet doar live pe System76 cu 2 sloturi LM Studio.

---

## ORIZONT 8 — Tech Debt Notes (2026-06-02)

> Inconsistențe găsite la scrierea `docs/ARCHITECTURE.md` — REZOLVATE:

1. ✅ **Model real, nu hardcodat:** `LLMRouter.detect()` auto-detectează modelul încărcat în LM Studio/Ollama (`/v1/models`, `/api/tags`) și îl folosește; fallback la `/admin → llm.default_model`. Doc-urile aliniate.
2. ✅ **`agents.yaml`:** eliminat duplicatul `howard` din `bench:` (rămâne doar în `agents:`, activ).
3. ✅ **Claude model din `/admin`:** nou setting `llm.claude_model` (settings_db) citit de `hybrid_router` în loc de constanta hardcodată.
4. ✅ **`handle_input_stream`:** `agent_id` și `t_s0` pre-inițializate înainte de buclă — fără `UnboundLocalError` când `target` e gol.

**README.md** rămăsese în urmă (test count 181/39, v0.2.1, linia Memory fără embeddings/graph) — actualizat în sesiunea 2026-06-02.

**Viziunea Howard (context):** Howard = digital twin care „știe ce știe Claude despre Andrei" — alimentat de memoria personală (H8.1) + arhiva ingerată (H5.1). Rămas în mâna lui Andrei: antrenarea unui LLM pe conversațiile din Facebook/WhatsApp (pipeline de ingestie + fine-tuning e H5.1, infra gata).

---

## ORIZONT 9 — Agent Ops: Visual Workflows & Observability (✅ 3/3 Complet)

**Context & decizie arhitecturală (2026-06-02):** Evaluare tool-uri externe (Flowise, Langflow, CrewAI, Autogen, SuperAGI, OpenWebUI, LangSmith, Dust.tt). **Decizie:** NU adoptăm tool extern — Jarvis Hub acoperă deja orchestrarea, routing-ul hibrid local↔cloud, rolurile/tier-urile de agenți, autonomia, securitatea și memoria. Împrumutăm doar 2 idei unde avem gap real: builder vizual de workflow-uri (Flowise/Langflow) și observability/eval (LangSmith), construite nativ.

| # | Item | SP | Livrat |
|---|------|----|--------|
| H9.1 ✅ | Visual Workflow Builder | 13 | Tab HUD canvas SVG, noduri = pași/agenți, muchii = `depends_on`; CRUD + run. `Pipeline.from_dict`, persistență CRUD, endpoints `/api/workflows` POST/PUT/DELETE. |
| H9.2 ✅ | Observability — Trace Explorer | 8 | Store trace-uri per-request (classify→route→model→tokens→latență→cost); `/api/traces[/{id}]` + tab HUD. |
| H9.3 ✅ | Offline Eval Harness | 8 | Seturi de prompturi prin orchestrator (LLM injectabil), scor pass/criterii, tracking regresie; `core/observability/eval.py`. |

---

## ORIZONT 10 — Competitive Edge (Context Research)

**Research complet (2026-06-02):** Deep research adversarial pe 8 competitori (Flowise, Langflow, CrewAI, AutoGen/AG2, SuperAGI, OpenWebUI, LangSmith, Dust.tt) — surse verificate.
**Doc complet:** `docs/research/2026-06-02-competitor-research-h10.md`

**Principiu:** Nu adoptăm tool extern. Împrumutăm idei concrete unde avem gap real față de industrie. Toate construite peste ce avem (Python-first, local-first).

**Teme cross-cutting (≥4 competitori):** prompt versioning · cost tracking · MCP server mode · model quality comparison · agentic RAG · embeddable interface · action-level HITL · workflow termination.

---

## ORIZONT 12 — Personal-AI Category Research (Context Research)

**Research complet (2026-06-02):** Deep research (5 agenți paraleli + verificare adversarială independentă) pe categoria *reală* a moonshot-ului — **asistenți personali proactivi & privați** — pe care H10 (8 framework-uri de developeri) NU o acoperise.
**Doc complet:** `docs/research/2026-06-02-personal-ai-competitors.md` · **Backlog:** ORIZONT 12 (14 items, ~89 SP)

**Constatări-cheie:**
- **Rival direct ratat anterior:** **OpenClaw** (viral nov-2025, ~180k★, self-hosted, local-capable, proactiv) — aceeași teză ca Jarvis. Eșecul lui (secrete în plaintext, fără guvernanță acțiuni, marketplace nemoderat → ținta #1 a infostealerelor în feb-2026) = exact wedge-ul Jarvis (alternativa guvernată).
- **Cimitirul device-urilor „knows-you"** (Humane mort feb-2025; Dot închis oct-2025; Rewind/Limitless → Meta dec-2025; Pi/Inflection → B2B) — toate cloud-dependente → validează local-first + software-first.
- **Claim de diferențiere îngustat dar apărabil:** Amazon Bee combină proactivitate+memorie (cloud); Omi e local dar pasiv. Corectat în `GO_LIVE_PLAN.md` §3 + `MOONSHOT.md` §2.

---

## Decision Log (MOONSHOT §7.4)

> Decizii strategice semnificative, cu dată + rațiune, ca moonshot-ul să aibă audit trail.

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-02 | **Păstrăm toate cele 6 principii non-negociabile; adoptăm funcționalitățile de tip OpenClaw (multi-channel, marketplace de skills, autonomie low-friction) DOAR sub guvernanță.** | Evaluat dacă rivalul viral OpenClaw justifică relaxarea principiilor. Concluzie: niciuna dintre funcționalitățile lui interesante nu cere renunțarea la un non-negociabil — fiecare e livrabilă în interiorul principiilor (ORIZONT 12), iar varianta guvernată e strict mai bună. Criza de securitate OpenClaw *validează* „production-grade + governance" (teza #3), nu o contestă. |
| 2026-07-11 | **The v1.0 gate expands to the full AI-OS vision** — six capability pillars pulled *into* 1.0 (MOONSHOT rewritten; `NERVA_VISION.md` created; ORIZONT 27–33 planned; version line extended v0.21.0–v0.27.0). **Hermes strategy:** adopt its execution-plane mechanisms under governance (the ORIZONT 20 precedent, MIT) — never rebuild feature-by-feature — and define a measurable superiority bar (NERVA_VISION §8, S1–S8). The proof track (⭐B0, 72h soak, design partners) is preserved as the trust half of the gate; MOONSHOT gains principle #7 (capability growth is governed). Owner accepts ~1 year to 1.0. | "Productionized + proven" undersold the owned-AI-OS bet the owner actually holds (house brain, media, cameras, operator, self-extension). Execution planes are adoptable commodities (Hermes, MIT); governance + the personal-world model is the moat — so unique engineering goes to kernel/registry/house/media/cameras/ambient. Provenance: [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](research/2026-07-11-ai-os-vision-and-hermes-strategy.md). |
| 2026-07-12 | **Two parallel vision drafts merged into one canonical doc + the Nerva brand adopted.** #661 (`docs/NERVA_VISION.md` — Nerva/Digitaholic brand architecture, Cortex/Atlas/Synapse/Vision/Ultron sub-brands, Programs A–G, but a *narrow* v1.0) and #662 (`AI_OS_VISION.md` — six pillars, S1–S8 Hermes bar, ORIZONT 27–33, *expanded* v1.0) collided. Owner decisions: (1) the **expanded 1.0 gate stands** (supersedes #661 §8); (2) **Nerva is the product brand everywhere** (`jarvis-hub` stays the repo codename until the deliberate rename — owner task); (3) **one canonical vision doc** — root `NERVA_VISION.md` (merged), `docs/NERVA_VISION.md` reduced to a pointer stub; core loop settled on Observe→Understand→**Decide**→Act→Verify→Learn. | Two contradictory canon docs is exactly the "documentation as state" failure the 2026-07-11 audit flagged; the merge keeps #661's brand architecture and success scenarios, #662's grounded gaps/horizons/superiority bar, and one authoritative gate statement (MOONSHOT §4 + BACKLOG version roadmap). |
| 2026-09-01 | **H23.23 ratified — option (A): Nerva 1.0 is single-user per install.** Per-user isolation stays a post-1.0 horizon that opens only when a design partner needs multiple distinct people on one shared install; boundary notes (SECURITY.md, COMPATIBILITY.md, THREAT_MODEL.md, FAQ.md) land in one doc-only PR. [Decision doc](decisions/2026-07-11-single-user-1.0.md). | (A) writes down the shape the build already has and the H23.30 public-demo spec assumes (install-per-user); (B) is a large security-sensitive surface that contradicts "don't add scope; the constraint is proof". v1.0.0 is not tagged yet — this is the recorded default, not "already shipped". |
| 2026-09-01 | **No real payment rail for 1.0 (ratified).** `PaymentBroker.settle()` keeps auditing "settled (no real rail)", no money moves, no AP2/ACP/x402 adapter, `PaymentRail` protocol or `NullRail` gets written. Reopen only when a concrete consumer of agent-initiated spending exists and the owner is ready to open a merchant account, supply credentials, accept liability and name a production mandate ceiling. | The repo's own research says adopt the abstraction, not the rail (all three are beta); the governance layer is already built rail-agnostically with no auto-approve at any amount; MOONSHOT §5 #7 keeps money below the approval queue regardless. Zero-regret option. |
| 2026-09-01 | **0.61 ratified — stay on SQLite + WAL; re-evaluate only on the four named triggers** (per-user isolation scoped; live second-device sync; verified write-contention in a soak; Pi-5 shared reads); if one fires, libSQL embedded replicas, never the hosted tier. [Decision doc](decisions/2026-07-11-db-future-check.md). | Every store plus backup/export/purge and the H23.7 migration framework are built on local files; Turso's value is its hosted/replicated tier, which conflicts with local-first / opt-in cloud / no third-party relay. The single-user decision removes the multi-writer argument. |
| 2026-09-01 | **Hosted Pro: wait for pull.** No hosted Pro tier before or at v1.0; re-open only when ≥3 design partners / WTP-survey respondents explicitly ask for managed hosting/sync, or ~750 active self-host installs (VALUATION §9.1 cross-over) — then prototype on serverless per-second GPU, never a dedicated fleet. | MOONSHOT places Hosted Pro in Phase 3 (post-1.0) and phase boundaries are gates; GTM_PLAN's hard rule not to bet on hosted-AI subscriptions; §9.1 shows the hosted line loses money below ~150–200 users; zero demand evidence today. |
| 2026-09-01 | **B3 / Continuity Core: Jarvis's own Identity Manifest gets its own issue — #1008** ("Continuity Core — Jarvis's own Identity Manifest (E4 identity-boundary lane, not Howard)", under program #757, body from #731 §1 + acceptance criteria 1 and 10). #762 stays scoped to Howard preference-prediction only; no authority change — identity changes are versioned proposals through the approval queue, Ultron stays sole privileged-action authority. | Folding into #762 would fuse the companion identity with Howard (#731's own non-goal) and chain the manifest to Howard's blocked E4→E3 schedule; declining contradicts the roadmap's "give it a destination issue". A new issue is pure tracking — zero code, zero authority. |
| 2026-09-01 | **E731 evaluation suite runs on the E9 Research Lab harness** — the accepted E9.0 `nerva.benchmark.v1` store/harness with its privacy lanes, as a future separately-scoped `evaluation_only` suite package that does not enter E9's serialized #854 repair queue; acceptance ownership of each metric stays with its destination epic (E3/E6/E12 recall, contradiction, abstention; E11 model-replacement/migration parity). | E9.0 already provides privacy classes and an `owner_private_local` lane; `nerva.benchmark.v1` is pinned evaluation-only; E6.1 (#817) is precedent for another epic reusing the harness. A destination mapping only — not a queue-jump, not an acceptance of merged code. |
| 2026-09-01 | **E731 acceptance criterion 6 (Frigga family-domain isolation) is owned under RISKS.md PRIV-02** with its existing E2/E3/E4/E10 owners (E2 #760 primary, Frigga leakage fixture mandatory); recorded in the reconciliation doc only — no epic acceptance list is edited. | Declaring it out of scope would be dishonest: read-scope isolation via `data_spaces.py` is default-open, so nothing today proves family memories cannot leak; a new issue would duplicate PRIV-02's owner set. Lowest-regret, no code, no authority. |
| 2026-09-01 | **B7 / PR #918 RETAINED** (merge b5e52c6, reviewed source 6eed5a7) on `main` under a recorded bounded owner exception — default-off (`JARVIS_TASK_MEDIATION` unset ⇒ off), no revert, no successor PR; #757/#778/#818 and BACKLOG reconciled. **B7 stays not program-accepted**; E5/E8 stay blocked until #906 is provisioned or re-scoped by a separate owner decision. | Terminal-green CI plus a distinct R3 PASS bound to 6eed5a7 (comment 5313004564) were met before merge; the only unmet gate was the #906 live-authority hold, whose mandatory status the owner retired 2026-08-29. The bytes ship dark; reverting would reopen the two #912 BLOCK findings #918 closed. |
| 2026-09-01 | **SEC-B8 / PR #911 RETAINED** (merge 790a725) — post-merge "SEC-B8 Post-Merge Security Reviewer" audit commissioned (agent reviewer distinct from the builder, bound to 790a725) — **PASS/HOLD: pending**; a PASS closes #905, a HOLD authorizes one bounded corrective successor PR, never a revert. **PR #916 RETAINED** (merge 519dca0) — the existing exact-head reviewer receipt (PR #916 comment 5308830474, head a2438d8) is recorded as its attestation; no new review commissioned. Neither is governance-complete on this decision alone. | #911 closes the #905 self-approval hole in the shipped default — a revert would reopen a security defect; what is missing is an attestation bound to the merged bytes, a separate role's act. #916 is an inert library with no importer outside its tests; its receipt already reproduced 109 tests + 7,380 review-event sequences + 5,000 hostile states. |
| 2026-09-01 | **v1.0.0 tag ordering confirmed** (the 2026-08-28 "gates removed" directive governs): the tag is two owner commands — the A5 licence flip, then the tag on `main`; the A1 MANUAL_TESTING §0 runbook is **post-tag proof**, not a tag precondition. MANUAL_TESTING §0, GO_LIVE_PLAN (incl. the stale A8 row) and OWNER_TASKS reconciled to that single ordering. | Three surfaces still read the runbook as "no tag ships without it" while A9 and the owner directive said two commands; one ordering, written once, ends the contradiction. The A1 §0 run record is still owed as proof. |
| 2026-09-01 | **2026-07-07 pre-go-live sync decisions ratified / superseded:** 3, 4, 7 ratified as written; 2 ratified minus the unbuilt clause (partner installs = signed release tag + hardened posture by default, never `main`, owner soaks each tag ≥1 week, monthly cadence — the "automatic pre-upgrade snapshot / refuse to migrate without one" clause is dropped until Gate-2 🚧5 ships); 1 superseded by the A7 close-out (2026-08-28); 5 superseded by the A7 close-out + the H23.30 public-demo approval; 6 (support contract / SLA) stays PENDING owner wording (T-0.55 open). [Meeting note](meetings/2026-07-07-pre-go-live-sync.md). | A7 closed with partners recruited while 0 tags exist and Gate-2 🚧5/6/8/9 are open, so 1 and 5 were overridden in practice; 2/3/4/7 remain valid and partly executed (WorldView opt-in, first-run Command Center loop, honesty rules). |
| 2026-09-01 | **Wall transcript privacy: never visible with other people present.** The spoken-line transcript stays HIDDEN by default on every screen (`TRANSCRIPT_DEFAULT_VISIBLE=false`); the per-screen one-click toggle is an owner-alone-in-the-room convenience only; no per-room allowlist or config gets built. | The wall has no room identity — the opt-in is a per-browser localStorage flag — so "allow in named rooms" would invent per-room config before the wall is validated in even one room; default-hide is the audience-safe, local-first choice already reaffirmed in the wall reviews. |
| 2026-09-01 | **H23.30 public web demo spec APPROVED — v1 as written** ([spec](decisions/2026-08-24-public-web-demo-digitaholic.md)): session-only disposable install as the save slot, in-memory stores, cloud LLM only, no external-transmit plugin and no `LOCAL_ONLY` agent reachable, no durable cross-visit save, smallest roster that demonstrates the loop. Risk tiers: roster-overlay slice **R2**, deploy slice **R3**. Public box posture: `JARVIS_HARDENED=1` + off-box `JARVIS_AUDIT_KEY` + `NERVA_PUBLIC_PROFILE=1` + `JARVIS_PLUGIN_GRANTS` empty; personal install unchanged. Calls 3–4 (LLM provider/key, container host) stay open. | Both code blockers the spec asked for are shipped and tested (seed gate #967, malformed-flag boot guard); the v1 shape reuses H23.23's install-per-user unit, keeps GDPR exposure at zero by refusing durable saves, and rolls back by "stop routing the page". An internet-facing box holding an LLM key and an audit key, auto-redeployed from `main`, is R3 by AGENT_WORKFLOW's own rule. |
| 2026-09-01 | **CDX-12 / CDX-11 posture:** `JARVIS_HARDENED=1` + off-box `JARVIS_AUDIT_KEY` is **required** on the public demo box and any hosted/multi-tenant box, the **default** on design-partner boxes via the `design_partner` bootstrap (consistent with sync decision 2), and **off** on the owner's personal install. CDX-11 grants: empty on the public box; the personal-install grant list stays OPEN until hardening there is decided. | `hardened.py` was built for a design-partner / multi-tenant deployment and never invents policy; the personal install would need a plugin:agent grant matrix nobody has authored and would lose mutating MCP / non-REDACT guardrails the owner relies on. |
| 2026-09-01 | **Action Kernel default-rail criteria** ([decision doc](decisions/2026-09-01-action-kernel-default-rail.md)): `JARVIS_ACTION_KERNEL=1` + `JARVIS_UNIFIED_ACTION_API=1` become shipped defaults (flags kept as kill-switches) in one agent PR only after (a) four consecutive weeks of opt-in dogfood on the owner box with both flags set, (b) zero kernel-caused false DENYs / ungoverned actions in `GET /api/metrics/kernel` over that window, (c) one 72h PASS soak with both flags on; the A8 owner-host proof is not a precondition. | ON is not pure hardening (a kernel GRANT rewrites ask→act; the unified flag arms real side effects) and SEC-01 is still OPEN, so the flip must rest on measurements; every criterion is measurable with instruments that already exist. |
| 2026-09-01 | **Hermes evaluation scope:** the four productivity-skill subtrees carrying separate Anthropic terms (`skills/productivity/docx`, `pdf`, `powerpoint`, `xlsx`) are **not accepted / out of scope** and are removed from the shipped importer allowlist (`hermes_pin_v1.json`); a **static-only** fresh review (OSV/CVE re-query, transitive-licence closure, SBOM/provenance, platform review) is commissioned against the exact pinned artifact v2026.8.3 / 3c27eb6 / OCI `sha256:1678…2c9e` with inspection-only access — **PASS/HOLD: pending**; pull-for-execution, install and execute stay **WITHHELD**. E8.1c (#804) stays EXECUTING ADAPTER BLOCKED — runtime/egress may be re-requested only after the review PASS, the B7 enforce mode actually working, and a fixture matching the preflight's isolation list. | The runtime is MIT (already reused) and the only restrictive-licence finding is the four subtrees, which the head-to-head tasks never touch; transitive licences, SBOM and 6 CVE groups are still not_verified, so neither "accept everything" nor "refuse forever" is honest. An inspection-only pull of a pinned digest is trivially reversible; a live execution surface ahead of its authority boundary is not. |
| 2026-09-01 | **AUD-0 scope decision recorded:** the owner declined to narrow — on 2026-07-11 he chose the expanded six-pillar 1.0 gate (NERVA_VISION.md §10) instead of a 5–6-feature cut — and the ~44 governed-but-Null-railed modules stay reachable-but-Null-railed by choice (no flag-park code change). A2's automated "AUD-0 = audit-verify failures" definition is a separate metric, not this decision. | The audit's ask was "pick the 5–6 features that are the product and park the rest"; the owner's 2026-07-11 call answered it, and the park mechanism is machine-enforced as H23.28. Recording the mapping is the honest closure; "superseded by A2" would be false because A2 is a soak threshold. |
| 2026-09-01 | **E1.2b owner inputs 3, 4, 5 decided** (`docs/nerva2/CORTEX_E1_2.md` § Owner decisions for E1.2b): (3) sampling rule `consecutive-distinct-eligible-tasks` over 2026-08-01..2026-08-31 UTC, `role=user` turns in timestamp order, predeclared exclusions (excluded, not normalised); (4) retention/access/deletion policy `owner-local-e1-2-v1` for all five artifact classes (owner's OS account on the owner box only, one git-ignored local directory excluded from backups, kept until the owner deletes, secure deletion of every copy; raw prompts and digests never copied/quoted/published — aggregates and privacy-minimised report text may be shared); (5) exactly one owner-local measured run permitted (one warm-up + five retained runs, pinned `main`), conditional on inputs 1–4 and the policy's filesystem controls — evaluation-only, earns no E1/B2/program/release decision. Inputs 1 and 2 (dataset, per-case acceptable routes/categories) are written at the desk; the gate stays open until the run has executed. | RES-01 names hand-picked prompts as a HIGH/HIGH risk, so the rule and window must be predeclared; the policy id and rule identifier are the repo's own fixtures; the run's authority is fixed `evaluation_only` with every routing/authorization/execution boolean false and migration-free rollback. |
| 2026-09-01 | **TASK-3 (taint through memory-derived actions) stays OPEN, rescoped** to the bounded slice BACKLOG already names — wrap email/web-webhook channel input in `TaintedValue` at the channel boundary and gate irreversible tool calls through `QuarantinePolicy.check_step`; full through-LLM data-flow taint propagation is **not commissioned** now, and the "sufficient?" judgment stays with RISKS.md SEC-05 (E2/E3/E8/E11 owners). | Taint cannot honestly be propagated through an LLM (CDX-7); the kernel already escalates GRANT→QUEUE on any untrusted declared origin and inbound channels are origin-bound by construction, so the residual is defense-in-depth, not a live threat; the naive hook already broke once. |
| 2026-09-01 | **GAP-0 — distribution is still the binding constraint.** First-value path = the one-step design-partner bootstrap (Gate-2 🚧1) + the first-30-minutes fully-local zero-key loop (🚧4), measured as **activation rate**; the H23.30 public demo is sequenced after it as reach. The row's stale "0 partners / A7 ⬜" premise is corrected to A7 ✅ 2026-08-28. | The repo's own definition of first value already exists (sync decision 4, GTM_PLAN activation metric; "the gap is not capability; it is packaging, posture, and the support loop"); the install path is the only option that is local-first and needs no open owner calls. |
| 2026-09-01 | **MEM-03 memory taint check promoted into E3 Episodes #761's formal acceptance** — only the narrow line "every production-recall admission decision records a taint/provenance reason" (proposed via a comment on #761 for the epic owner to add); the "cannot lower an approval floor or trigger execution" half stays with the kernel / SEC-05 owners; E6/E12 remain register co-owners. | The taint check is an admission-time decision on recall — E3's home; prior art already lives on the recall path (`rag_tool._hit_tainted`, SEC-B5 recall taint → QUEUE), so the criterion is testable today; leaving it in the register only keeps the #731 close bar unmet. |
| 2026-09-01 | **Python floor stays 3.12+ (official).** The docs contradiction is fixed instead: `docs/COMPATIBILITY.md` notes the numpy marker in `requirements-beta.txt` is a courtesy that keeps installs working on 3.11 boxes, but 3.11 is unsupported and untested in CI; no CI-matrix change, marker not removed. Closes 2026-07-07 sync action item 10. | One official floor, honestly documented, beats a straddle; the marker costs nothing to keep and the partner boxes it helps are not promised support. |

---

## PR & Merge History (2026-06-02 session)

| PR | Title | Status |
|----|-------|--------|
| #11 | feat(voice): TTS + hands-free voice interaction (H5.16) | ✅ Merged |
| #13 | feat: H5.15 + H5.6 + H5.14 (Reflection + Workflows + Fused Recall) | ✅ Merged |
| #15 | feat(security): Romanian PII detection — CNP, IBAN, phone | ✅ Merged 2026-06-02 |
| #16 | feat: recall cu embeddings reale (LM Studio) + ORIZONT 7 perf | ✅ Merged |
| #17 | docs: ARCHITECTURE.md (AI navigation) + ORIZONT 8 backlog | ✅ Merged |
| #18 | feat: ORIZONT 9 — Visual Workflow Builder + Observability | ✅ Merged |
| #19 | tests: HUD + human-interface HTTP integration tests (47 tests) | ✅ Merged 2026-06-02 |
| #20 | feat: LogBugScanner scheduled pipeline (25 tests) | ✅ Merged 2026-06-02 |
| #21 | research(h10): competitor analysis — 30 sprint items from 8 competitors | ✅ Merged 2026-06-02 |
| #22 | docs(coord): onboard Antigravity into parallel-work protocol | ✅ Merged 2026-06-02 |
| #23 | feat: deep-think model tier for async foundation agents | ✅ Merged 2026-06-02 |
| #24 | feat(h5): Daily Reflection + Multi-Agent Workflows + Task4 | ✅ Merged 2026-06-02 |
| #25 | docs(backlog): sync stale counters — H5 17/17, 909 tests, H5.1 ✅ | ✅ Merged 2026-06-02 |
| #28 | docs: GO_LIVE_PLAN.md — feature inventory, roadmap & marketing brief | ✅ Merged 2026-06-02 |
| #49 | research(competitors): personal-AI category analysis + ORIZONT 12 + doc enrichment | 🚧 Draft |
