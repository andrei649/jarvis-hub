# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

> **North Star (vision, principles, phase gates):** [MOONSHOT.md](MOONSHOT.md) — re-rank this backlog against it
> **Go-Live Plan (features, roadmap, marketing brief):** [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md)
> **Delivery History (H1–H8 completed sprints):** [docs/HISTORY.md](docs/HISTORY.md)

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 1100+ passed, 9 skipped
```

> Cele 8 skipped sunt din `tests/test_spotify.py` (pattern HTTP-router, opencode) care
> așteaptă `agents/core/skills/spotify.py` — neimplementat. Spotify (H2.5) **funcționează**
> via `skills/spotify/main.py` (pattern loader, acoperit de `tests/test_spotify_skill.py`).

**După modificări JS/CSS:** Ctrl+F5 în browser (cache bust).
**După modificări Python:** repornire server (Ctrl+C, re-execută comanda uvicorn).
**Server curent** (dacă e pornit): PID vezi `netstat -ano | findstr ":8080 "`.
**Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX).

---

## Version Roadmap

| Version | Target | Milestone | Items |
|---------|--------|-----------|-------|
| **0.5-beta** | 🟢 Live | Foundation complete. All H1–H4, cross-cutting, security, bugs done. | H1–H4, Sprint 0, Cross-cutting, Sec, Bugs |
| **0.6-beta** | 🟢 Live | Howard fine-tuning + voice clone + continuous ingestion | H5.1 |
| **0.7-beta** | 🟢 Live | Mobile PWA + i18n + UI Overhaul | H5.2, H5.3, H5.4 |
| **0.8-beta** | 🟢 Live | Performance & robustness + multi-agent workflows | H5.5, H5.6 |
| **0.9-beta** | 🟢 Live | New integrations + agent marketplace | H5.7, H5.8 |
| **0.9.1-beta** | 🟢 Live | Recall cu embeddings reale + perf cale fierbinte | H7.1–H7.5 (perf) |
| **0.9.2-beta** | 🟢 Live | Hardening complet, CI/CD, memorie personală, cost analytics, onboarding | H7 (11 iteme) + H8 (7 iteme) + BUG-1 |
| **1.0.0** | 🎯 Stable | Tot backlogul terminat: H10 + H11 + **H12** + BUG-2 (frontend tests). H12.1 (P0 securitate) = wedge anti-OpenClaw. Plan: [docs/plan-v1-dispatch.md](docs/plan-v1-dispatch.md) | H10 (30) + H11 (4) + H12 (14) + BUG-2 |

---

## Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H1–H4 + Sprint 0 + Cross-cutting + Sec + Bugs** | 67 | **67** | 248 | **248** | **100%** |
| **H5 Next Wave** (P2–P3) | 17 | **17** | 128 | **128** | **100%** |
| **H6 Jarvis Autonom** (P1) | 7 | **7** | 60 | **60** | **100%** |
| **H7 Perf Cale Fierbinte** (P1–P2) | 5 | **5** | 16 | **16** | **100%** |
| **H7 Hardening & Release Readiness** (P0–P2) | 11 | **11** | 51 | **51** | **100%** |
| **H8 Memorie Personală** (P1–P3) | 7 | **7** | 48 | **48** | **100%** |
| **H9 Agent Ops: Workflows & Observability** (P2) | 3 | **3** | 29 | **29** | **100%** |
| **H10 Competitive Edge** (P1–P3) | 30 | **0** | 188 | **0** | **0%** |
| **H11 Platform Parity** (Known Gaps, P3) | 4 | **0** | 55 | **0** | **0%** |
| **Total general** | **151** | **117** | **823** | **580** | **71%** |

**Test count:** 1100+ passed, 9 skipped (2026-06-02: +H7 hardening 192 teste noi; +H8 memorie 16 teste noi)

> **Orizont 7 Hardening — Drumul spre 1.0.0:** 11/11 COMPLET ✅ (livrat 2026-06-02)

---

## ✅ ORIZONT 7 — Drumul spre 1.0.0 (Hardening, Release Readiness & Observability) — 11/11 COMPLET

> Backlog-ul de features e la 100% (H1–H6). Faza spre **1.0.0 stable** nu adaugă scope orizontal —
> face produsul **de încredere, testabil, documentat și măsurabil**. Bazat pe auditul multi-agent
> 2026-06-01 (docs/release, CI/hermeticitate, calitate cod, scoping features) + `docs/gap-analysis-1.0.md`.
>
> **Design complet:** `docs/superpowers/specs/2026-06-01-horizon7-road-to-1.0-design.md`
> **Constatări-cheie:** `pytest tests/` atârnă >18 min offline (Oracle GitHub watcher la lifespan);
> CI rulează doar pe push/Windows (nu pe PR-uri); ~44 `except: pass` în security/autonomy;
> docs se contrazic (README „181" vs „39" teste; port 8000↔8080; model 26b↔31b; „15" vs 16 agenți;
> fără LICENSE/CONTRIBUTING).

### Track A — Test Hermeticity & CI/CD (P0, blochează restul)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 | **Suită de teste hermetică** — gate watchers/canale externe pe `JARVIS_TESTING`; `conftest` autouse (env + socket guard); `pytest-timeout` în pytest.ini; TestClient module-level → fixtures function-scoped (`test_cognition_api/test_tts/test_systems_api/test_resilience_integration`) | 5 | P0 | — | `pytest tests/` rulează offline, verde, <90s, fără hang; apel real de rețea → eșec imediat |
| H7.2 | **CI/CD pentru 1.0** — trigger `pull_request`; matrix `ubuntu+windows`; `ruff` + `mypy` (non-blocking) + `pytest-cov`; healthcheck robust (poll, nu sleep) | 5 | P0 | H7.1 | fiecare PR rulează CI pe Linux+Windows cu lint+teste+coverage |

### Track B — Code Hardening (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.3 | **Client HTTP centralizat + retry/circuit-breaker** — `PluginHTTPClient` (timeouts coerente, `@resilient_call` H5.5, pooling); migrează 14+ pluginuri | 8 | P1 | H5.5 | un singur client/policy; metrici reziliență per plugin |
| H7.4 | **SQLite thread-safety & igienă conexiuni** — `check_same_thread=False` + lock pe checkpoint/settings_db/queue/preferences; WAL consistent | 5 | P1 | — | acces concurent sigur; `test_load.py` fără erori de thread/corupere |
| H7.5 | **Validare input pe endpoint-uri** — limite Pydantic: message len, `limit` bounds, `task_id` numeric, sandbox code size | 3 | P1 | — | input invalid/oversize → 422, fără OOM/DoS |
| H7.6 | **Curățare excepții înghițite silențios** — `except: pass`/`return None` orbe din log/channels/autonomy/security → logging structurat + fallback explicit | 5 | P1 | — | nicio cădere silențioasă în security/autonomy; fiecare logată cu context |
| H7.7 | **Elimină date mock/dummy înșelătoare** — `/tasks` dummy tasks (web.py); flag transparent pe iot_control mock | 2 | P1 | — | UI nu primește date false ne-marcate |

### Track C — Docs & Release Hygiene (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.8 | **Adevăr în documentație** — single source of truth versiune (`agents/__init__.py` + `/status`); reparat test counts, versiune, port, model, agent count, endpoint count | 3 | P1 | — | zero contradicții cross-doc; CI verifică versiunea unică |
| H7.9 | **Onboarding & release** — `LICENSE`, `CONTRIBUTING.md`, quickstart Linux/Mac, `docker-compose.yml` (server+Qdrant+Neo4j+n8n), README badges+screenshot, release workflow (tag→Release) | 5 | P1 | H7.2 | dev nou rulează în <10 min pe Linux/Mac; tag → GitHub Release |

### Track D — Observability & Product Polish (P2, câștiguri rapide high-ROI)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.10 | **Cost & Usage Analytics** — preț per model + agregare tokens/cost per agent (local vs cloud) + burn lunar; `GET /api/analytics/cost` + tab HUD | 5 | P2 | H5.5 | dashboard arată cost/agent + proiecție lunară din date reale |
| H7.11 | **Activare Learning-Loop (auto promote/demote)** — job săptămânal care propune evoluția agenților prin decision inbox (reversibil, gated) | 5 | P2 | H3.4, H6.5 | după N interacțiuni → propunere în inbox; aprobarea activează agentul |

> **Total Orizont 7:** ~51 SP. **Secvențiere:** H7.1 → H7.2 → (Track B ∥ Track C) → Track D.
> **Stretch → Orizont 8 (post-1.0):** voice clone (XTTS), Howard fine-tuning, multi-user/family,
> mobile offline voice, n8n NLU→workflow, desktop Tauri, advanced guardrails DSL, eval/regression harness.

---

## ✅ ORIZONT 6 — Jarvis Autonom / Proactive Cortex (P1) — 7/7 COMPLET

> Viziune: Jarvis își găsește singur de lucru, lucrează continuu, îmi scrie pe telefon (Telegram)
> doar când are nevoie de o decizie, și susține un review zilnic de 10–30 min (morning brief + evening retro).
> Autonomia crește în timp pe măsură ce învață ce aprob.
>
> **Design:** `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`
> **Research (cu surse):** `docs/research/2026-05-31-autonomous-proactive-agents.md`
> **Politică implicită:** ECHILIBRAT — act autonom pe reversibil/sigur (research, drafturi, organizare);
> aprobare pe ireversibil sau bani. **Buget întreruperi: ≤4 push-uri urgente/zi**, restul în review.
> **Principiu:** ambient agent (trigger → coadă → gating → inbox), NU auto-prompt loop (anti-AutoGPT).

| # | Item | S | Dep | AC |
|---|------|---|-----|----|
| H6.1 ✅ | **Autonomy Loop & Self-Tasking Queue** — coadă SQLite cu state-machine (`proposed→approved→running→done\|failed\|blocked`), worker pe loop, retry cap 3, 2 cozi manual/generated. `core/autonomy/queue.py` + `worker.py`, endpoints `/autonomy/*` | 13 | H3.5 | ✅ task trece prin tot ciclul; eșec ×3 → `failed`, nu reintră |
| H6.2 ✅ | **Decision Inbox pe Telegram** — card cu butoane inline Aprob/Editez/Resping/Amân pe task-uri blocate; buget ≤4 push/zi; rest în batch. `core/autonomy/inbox.py` + callback în `channels/telegram.py` | 8 | H6.1, H1.2 | ✅ task money/ireversibil → push cu 4 butoane → „Aprob" → running |
| H6.3 ✅ | **Risk Gate & Autonomy Dial** — `policy.py`: 4 tiers (read_only/reversible/external/irreversible_or_money) + scoring (reversibility, blast_radius, signal_quality, time_sensitivity); cap/ceiling bani | 8 | H6.1, H4.9 | ✅ reversibil → act fără întrebare; money peste cap → ask |
| H6.4 ✅ | **Daily Review Ritual** — morning brief 07:00 + evening retro 20:00 (cron), batch list; endpoint `/autonomy/brief`. `core/autonomy/digest.py` | 8 | H6.1, H3.5 | ✅ digest construit din coadă, trimis pe Telegram, expus în HUD |
| H6.5 ✅ | **Preference Learning & Decision Journal** — scor approve/reject per (agent,kind,tier), `suggest_autonomy_raise` (doar tier 1–2), jurnal JSONL append-only. `core/autonomy/preferences.py` + endpoint `/autonomy/preferences/suggestions` | 13 | H6.1, H3.4 | ✅ după N aprobări reversibile → sugerează ridicarea autonomiei |
| H6.6 ✅ | **Night Shift** — fereastră wrap-midnight; `tick(max_tier=1)` rulează batch doar reversibil/read-only. `worker.is_night_window` + filtru `queue.runnable(max_tier)` | 5 | H6.1, H6.3 | ✅ noaptea rulează doar muncă reversibilă; extern/ireversibil așteaptă |
| H6.7 ✅ | **Proactive OS Observer** (trigger layer) — `core/autonomy/observer.py`: eșantionează resurse (CPU/RAM/disk via psutil) + liveness servicii (TCP), **debounce pe schimbare de stare**, injectează în coada existentă (alertă→READ_ONLY auto-act, vizibilă în HUD/brief; remediere→tier-3 ASK→decision inbox). Probe injectabile (offline-testable). Endpoints `/autonomy/observer[/run]`. | 5 | H6.1, H6.3 | ✅ serviciu căzut → card „restart?" în inbox **o singură dată**; resursă în prag → alertă în brief |

> **ORIZONT 6 COMPLET ✅** (2026-05-31/06-01) — H6.1–H6.7 livrate. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

---

## 🔴 Auto-Generated Diagnostic Tasks

> [!NOTE]
> These tasks are auto-generated from active runtime failures in `problems.jsonl`.
> Sync runs automatically during the autonomy observer check.

✓ No active runtime failures detected in the last 48 hours.

## 🐛 Known Bugs (non-critical, not yet scheduled)

| # | Bug | Severity | Notes |
|---|-----|----------|-------|
| ~~BUG-1~~ ✅ | `_dashboard_cache` module-level dict has no `asyncio.Lock` — concurrent `/dashboard` requests can race on the weather/calendar cache update, producing a double-fetch or partial write under high load. **Fixed 2026-06-02:** `_dashboard_lock = asyncio.Lock()` guards both refresh blocks with double-checked locking; weather block now also sets `cached_at` (was refetching every request). +1 regression test (`test_dashboard_concurrent_refresh_fetches_weather_once`). | ~~LOW~~ | Found during HUD test sprint 2026-06-02 |
| BUG-2 ✅ | ~~Frontend test infrastructure missing — 0% coverage on React HUD (~5 000 LOC).~~ **Done 2026-06-02:** Vitest + JSDOM harness (`tests/frontend/`) that loads the real shipped global scripts (vendored React 18 UMD + static files) — no bundler/build step. **156 tests / 20 spec files · ~66% measured line coverage (target 60% met)**, gated in CI (`frontend` job runs `npm run test:coverage`, fails under 60%). Coverage of the in-JSDOM scripts is measured via istanbul pre-instrumentation + nyc (see `coverage.mjs`) with a badge (`coverage-badge.svg`). Covers all of `components.js`, `i18n.js`, `data.js`, `cognition.js`, `dossier-modal.js`, `network.js`, `enhancements.js`, `observability.js`; `admin.js` (full `AdminApp` mount + nav sweep + save flow); `systems.js`/`workflows.js`/`observability.js` panels (mount + tab sweep); and `app.js` incl. the **P1 chat flow** (send→SSE stream→render) and **P2 polling** intervals. Plan alignment per `docs/plan-bug2-frontend-tests.md`: runner = Vitest (chosen over Jest), measured coverage ✅, P1 Chat ✅, P2 polling ✅. **Caught a real shipped bug on first run:** `systems.js` `ResilienceTab` missing closing brace → the entire Systems panel failed to parse/load in the browser (present on `main`); fixed + regression-guarded (`resilience.test.js`). **Deferred (P3 follow-up):** voice/`useTTS`, Workflow drag-drop pointer events, and browser E2E (Playwright). See `tests/frontend/README.md`. | ~~MEDIUM~~ | Identified in test coverage audit 2026-06-02; backend gap closed (121 tests added on branch `claude/hud-human-interface-testing-r8IQS`) |

## ✅ ORIZONT 5 — Next Wave (P2–P3) — 17/17 COMPLET

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.
>
> **ORIZONT 5 COMPLET ✅** (2026-06-01) — 17/17 items livrați. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

| # | Item | S | Dep | Target version |
|---|------|---|-----|---------------|
| H5.1 ✅ | **Howard: Fine-Tuning + Voice Clone + Continuous Ingestion** — RAG pipeline (`ingestion/pipeline.py`, `watcher.py`), Facebook/WhatsApp parsers, `Embedder` cu caching (H5.17), TTS fallback chain (edge-tts/XTTS/ElevenLabs), IngestionWatcher wired în orchestrator. *(Fine-tuning model: necesită export date personale Andrei — infra 100% gata)* | 13 | — | 0.6 ✅ |
| H5.2 ✅ | **Mobile HUD / PWA** (responsive, offline, push) | 8 | — | 0.7 ✅ |
| H5.3 ✅ | **Multi-Language / i18n (RO/EN switch)** | 5 | — | 0.7 ✅ |
| H5.4 ✅ | **UI Overhaul (teme, layout, accesibilitate)** | 8 | H5.2 | 0.7 ✅ |
| H5.5 ✅ | **Performance & Robustness** (retry, circuit breaker, rate limit, caching, resilience metrics) | 8 | — | 0.8 ✅ |
| H5.6 ✅ | **Multi-Agent Workflows** (handoff, paralel, pipeline) — `WorkflowEngine` + `Pipeline`/`WorkflowStep` (DAG, topological sort, parallel batches) + `WorkflowRegistry` (3 built-in: finance_report, research_and_brief, security_digest) + endpoints `/api/workflows` + `/api/workflows/run`. 16 teste offline. | 13 | H5.5 | 0.8 ✅ |
| H5.7 ✅ | **New Integrations / Plugins (SMS, CRM, IoT, social)** | 8 | — | 0.9 ✅ |
| H5.8 ✅ | **Agent Marketplace / Skill Sharing** (registry, publish) | 13 | H5.6 | 0.9 ✅ |
| H5.9 ✅ | **Resilience Tab in Main HUD** — tab live în SystemsPanel cu retry metrics + circuit breaker states, endpoint public `/api/resilience` | 3 | H5.5 | 0.8 ✅ |
| H5.10 ✅ | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`) | 5 | H5.9 | 0.8 ✅ |
| H5.11 ✅ | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 ✅ |
| H5.12 ✅ | **Secured Shell Task Executor** — `RemediationRunner` (allowlist, permission gate, no-shell `exec`, audited) wired ca handler `restart_service` în executor. `core/autonomy/remediation.py` | 5 | H6.7 | 0.8 ✅ |
| H5.13 ✅ | **Proactive Event Watchers** — `EventWatcher` + Email/Calendar/Finance/Health probes, eșantionate în bucla de autonomie (gated `system.watchers_enabled`). `core/autonomy/watchers.py` | 8 | H6.7 | 0.8 ✅ |
| H5.14 ✅ | **Retrieval Fusion Engine** — `reciprocal_rank_fusion()` + `HybridRetriever` (vector⊕graph RRF, weight-tunable, injectabil) + `MemoryManager.hybrid_search()`. `core/memory/fusion.py`, 9 teste offline. **Task4 ✅:** `GET /api/memory/search` + `FusedRecallBox` în MemoryTab. | 5 | H3.1, H3.2 | 0.8 ✅ |
| H5.15 ✅ | **Daily Reflection & Graph Consolidation** — `DailyReflector` (`core/autonomy/reflection.py`): gather context → LLM reflection → JSON entities/relations/lessons → promote to Neo4j graph; idempotent per zi; hookuit în `_autonomy_loop` (fereastră 22:00–07:00, gated `system.reflection_enabled`). Endpoint `/api/reflection/status` + `/api/reflection/run`. 10 teste offline. | 8 | H6.6, H3.2 | 0.8 ✅ |
| H5.16 ✅ | **Sentence-level TTS & Audio Barge-in** — integration edge-tts, play/stop barge-in sync, auto-speak, unit tested | 8 | H1.1, H5.5 | 0.8 ✅ |
| H5.17 ✅ | **Batch & Cache Embeddings Pipeline** — `EmbeddingCache` (content-addressed, sharded, crash-safe) + `Embedder.embed_batch` (dedup + paralel) + retry/backoff (degradare la hash) + cache stats în pipeline. `core/ingestion/embedder.py` | 5 | H5.5 | 0.8 ✅ |

---

## ORIZONT 7 — Performanță Cale Fierbinte (P1–P2)

> Sursă: profiling 2026-06-02 al căii per-turn (NU generarea LLM). Bottleneck
> non-LLM = scrieri sincrone SQLite pe event-loop-ul async (checkpoint + audit +
> worker autonomie). Detalii + măsurători: `docs/research/2026-06-02-perf-hotpath.md`.
> **Câștig măsurat:** commit SQLite `3317 µs → 92 µs` (~36×) cu WAL+`synchronous=NORMAL`.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **SQLite WAL + `synchronous=NORMAL`** pe DB-urile scrise per-turn — `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`. Durabil (WAL crash-safe; NORMAL sigur sub WAL). | 1 | P1 | — | ✅ commit-uri ~36× mai ieftine; suite persistență/autonomy/securitate verzi |
| H7.2 ✅ | **Offload scrieri blocante de pe event-loop** — `checkpoints.save` / `audit.log` / `_record_interactions` / `_log_session` prin `asyncio.to_thread` în toate cele 3 call-site-uri per-turn; `checkpoint.py` cu `check_same_thread=False` + `threading.Lock`. | 3 | P1 | H7.1 | ✅ handlerele per-turn nu mai fac I/O sqlite/fișier sincron pe loop; thread-safe sub `to_thread` |
| H7.3 ✅ | **Debounce / frecvență checkpoint** — `_maybe_checkpoint()` salvează doar la `memory.checkpoint_every` (default 5) turns; `_flush_checkpoint()` forțat pe `new_session()` + `aclose()` (shutdown). Reduce I/O și CPU (`json.dumps` al state-ului). | 2 | P2 | H7.2 | ✅ checkpoint scris ≤1×/N turns; restart curat nu pierde sesiunea activă |
| H7.4 ✅ | **Query-embedding cache + fast-fail (recall)** — `Embedder.from_env(cache_dir=…)` default `memory_logs/embedding_cache/recall` + LRU in-process (`_PROC_CACHE`, 256) cheie `(backend,model,text)`; `max_retries=1` fast-fail. | 2 | P2 | — (recall) | ✅ query repetat = cache hit (fără network/disk); embeddings down → recall degradează instant |
| H7.5 ✅ | **Strategie fast/heavy model** — `is_heavy_request()` (token threshold 2000 + keywords RO/EN) escaladează în `hybrid_router.select_backend()` POLICY_AUTO de la slotul rapid (VRAM) la slotul deep (DDR5); flag `JARVIS_AUTO_DEEP`. | 8 | P2 | — | ✅ task ușor → model rapid `local`; task greu → `local-deep`/DEFAULT_DEEP_MODEL; nu afectează cloud/claude/local-only |

> **ORIZONT 7 PERF COMPLET ✅** (2026-06-02) — 5/5 items, +49 teste offline. Detalii: [docs/HISTORY.md](docs/HISTORY.md).

---

## Active: ORIZONT 8 — Memorie Personală & Personalizare („Jarvis te cunoaște") (P1) — 0/7

> **Viziune:** Jarvis își construiește în timp o **memorie despre Andrei** — fapte, preferințe,
> decizii, oameni, proiecte — extrasă din conversații, consolidată periodic (ca reflection-ul H5.15),
> versionată și injectată în context la fiecare agent, ca răspunsurile să fie personalizate fără
> să repet de fiecare dată cine sunt și ce vreau. Construit pe infrastructura livrată: fused recall
> (H5.14), embeddings reale + cache (H7.4), daily reflection (H5.15).
>
> **Principii:** local-first (ethos Frigga — datele personale rămân pe LAN), **inspectabil & editabil**
> (pot vedea/șterge orice fapt), opt-in pentru orice plecare spre cloud. Personalizarea crește în timp,
> dar controlul rămâne la mine.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H8.1 | **Memorie despre Andrei (User Profile Memory)** — store structurat persistent (facts / preferences / decisions / people / projects) construit din conversații (extragere LLM + consolidare idempotentă, pattern H5.15), versionat, injectat în prompt la toți agenții. `core/memory/profile.py` + `/api/profile`. | 13 | P1 | H5.14, H5.15, H7.4 | după câteva conversații, Jarvis cunoaște preferințe/fapte despre Andrei și le folosește; profilul e inspectabil în HUD |
| H8.2 | **Privacy & Forget Controls** — pentru memoria personală: export JSON, forget/redact selectiv per fapt, retention policy, scope strict-local. | 5 | P1 | H8.1 | pot șterge un fapt anume; export complet; nimic personal nu pleacă în cloud fără opt-in explicit |
| H8.3 | **Recall ON by default + Memory HUD** — activează `memory.recall_enabled` cu cache-ul H7.4; tab HUD cu faptele memorate (search/edit/delete), surse și scoruri (extinde Fused Recall). | 8 | P2 | H7.4, H8.1 | recall activ în chat din oficiu; HUD afișează și editează memoria personală |
| H8.4 | **Embeddings de calitate (model dedicat)** — `mxbai-embed-large` sau container TEI; benchmark calitate retrieval vs hash/nomic; degradare grațioasă păstrată. | 5 | P2 | H7.4 | retrieval măsurabil mai bun pe un set de probe; fallback intact |
| H8.5 | **Validare live fast/heavy (H7.5) + Model Tier HUD** — confirmă pe System76 cu 2 sloturi LM Studio încărcate; expune deciziile de tiering (fast↔deep) în `/bench` + HUD. | 5 | P2 | H7.5 | comutare fast↔deep vizibilă; latențe per tier măsurate |
| H8.6 | **Proactive Personal Briefs** — morning/evening brief (H6.4) personalizate din profil + recall: ce contează pentru Andrei azi (proiecte, oameni, deadline-uri). | 5 | P3 | H8.1, H6.4 | briefurile referă proiectele/oamenii din profilul personal |
| H8.7 | **AI-Navigable Docs upkeep** — `docs/ARCHITECTURE.md` ca sursă unică de navigare pentru asistenți AI; checklist „docs la zi" în template-ul de PR. | 2 | P3 | — | doc-ul reflectă codul curent; PR-urile mari ating și ARCHITECTURE.md |

---

## Active: ORIZONT 9 — Agent Ops: Visual Workflows & Observability (P2)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H9.1 ✅ | **Visual Workflow Builder** — tab HUD (canvas SVG, vanilla React) PESTE `WorkflowEngine` (H5.6): noduri = pași/agenți, muchii = `depends_on`; creează/editează/salvează workflow-uri user-defined + rulare. Backend: `Pipeline.from_dict`, persistență (CRUD) + endpoints `/api/workflows` POST/PUT/DELETE, register în registry. | 13 | P2 | H5.6 | pot compune vizual un workflow, îl salvez, îl rulez din HUD; DAG invalid → eroare clară |
| H9.2 ✅ | **Observability — Trace Explorer** — store de trace-uri per-request (classify→route→model→tokens→latență→cost), nu doar `last_cognition`; endpoint `/api/traces[/{id}]` + tab HUD de inspecție. Extinde `bench.py` + CognitionPanel. | 8 | P2 | — | fiecare request lasă un trace inspectabil; pot vedea unde se duce timpul/tokenii pe pași |
| H9.3 ✅ | **Offline Eval Harness** — rulează seturi de prompturi prin orchestrator (LLM injectabil), scor pass/criterii, tracking de regresie; `core/observability/eval.py` + CLI/endpoint. | 8 | P2 | H9.2 | un set de probe produce scor reproductibil offline; regresii vizibile între rulări |

---

## ORIZONT 10 — Jarvis Competitive Edge (P1–P3) — 0/30

### H10 — Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H10 Competitive Edge** | 30 | **0** | 188 | **0** | **0%** |

### H10.A — Observability & Eval (P1 — fundație)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.16 | **APM Dashboard** — metrici org în Admin HUD: tokens totali consumați (cu cost $ estimat), runs totale, breakdown per agent și per model. Extinde `/admin` + `bench.py`. | 5 | P1 | H9.2 | SuperAGI |
| H10.24 | **Cost Tracking per Agent** — calcul $ per request (tokens × preț per provider/model), stocat în trace, vizibil per agent/zi în HUD. `PRICE_TABLE` configurabil în `agents.yaml`. | 5 | P1 | H9.2 | LangSmith |
| H10.19 | **Model Arena / Blind Comparison** — tab HUD: același query trimis la 2 modele, răspunsuri side-by-side anonimizate, buton vot, leaderboard quality score agregat. `/api/arena/run` + `/api/arena/vote`. | 8 | P1 | H7.5 | OpenWebUI |
| H9.3b | **Dataset Regression Tracking** (ext. H9.3) — datasets de eval persistente cu versiuni (JSONL), track scor per dataset-version, comparare rulări în HUD; integrabil în CI. | 5 | P1 | H9.3 | LangSmith |
| H10.22 | **Agent Prompt Version Control** — SOUL.md versionat cu history (git-tags sau DB), UI de comparare 2 versiuni, A/B eval pe un dataset, rollback. | 13 | P1 | H9.3b | LangSmith |
| H10.23 | **Live Quality Monitor** — evaluatori (LLM-as-judge + heuristic) care rulează pe trace-urile live după fiecare request; scor per request în trace; alertă când avg_score scade sub threshold. | 13 | P2 | H9.2, H10.24 | LangSmith |
| H10.17 | **Per-Agent Run History** — în HUD per agent: timeline run-uri, acțiuni din fiecare run, durată, tokens, status (success/fail/partial). `/api/agents/{id}/runs`. | 8 | P2 | H9.2 | SuperAGI |
| H10.25 | **Human Review Queue** — UI sistematic: trace-urile flagate (scor mic sau manual) apar într-o coadă de review cu rubric, vot thumbs up/down, adăugare la dataset eval. | 5 | P3 | H9.3b | LangSmith |

### H10.B — MCP & Integrare (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.5 | **MCP Server Mode** — Jarvis expune agenți + workflow-uri ca tool-uri MCP (stdio/SSE); orice client MCP (Claude Desktop, Cursor, alt Jarvis) poate apela agenți Jarvis ca tool-uri. `core/mcp/server.py`. | 8 | P1 | H4.7 | Langflow |
| H10.8 | **Inbound Webhook Triggers** — endpoint `/api/webhooks/{id}` (POST) activează un agent sau workflow pre-configurat cu payload-ul ca input; autentificat cu token. Interfacă în Admin pentru creare/gestionare webhook-uri. | 3 | P2 | H5.6 | Langflow + Dust |
| H10.27 | **NL Scheduling** — în locul cron manual în APScheduler, câmp de text "every weekday at 7am" / "în fiecare luni la 9" → parse → cron expression. `core/autonomy/nl_schedule.py`. | 3 | P2 | H3.5 | Dust |
| H10.1 | **Embeddable Chat Widget** — endpoint `/api/widget/{token}` returnează snippet JS + CSS care embed-uiește chat-ul Jarvis pe orice website; theming configurabil din Admin. | 3 | P2 | H1.3 | Flowise |
| H10.30_writebacks | **Write-Back Integrations** — agenții pot scrie înapoi în sisteme externe (Notion, GitHub Issues, Google Calendar) ca tool-uri native; Pepper/Hephaestus primii candidați. | 8 | P3 | H2.1, H2.7 | Dust |

### H10.C — Memory & RAG (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H8.1b | **Entity Memory Store** (ext. H8.1) — extragere LLM automată de entități (persoane, proiecte, locuri, concepte) din conversații într-un store structurat separat, searchable, afișat în HUD Memory tab. `core/memory/entity.py`. | 5 | P1 | H8.1, H5.14 | CrewAI |
| H8.3b | **Agentic RAG Tool** (ext. H8.3) — recall nu mai e injectat fix (top_k); devine tool call LLM-callable (`search_memory(query)`); modelul decide când/cum să caute și poate retry cu query diferit. | 8 | P2 | H8.3, H7.4 | OpenWebUI |
| H10.21 | **Conversation Notes** — rich text editor (textarea + markdown preview) în HUD atașat la sesiunea curentă; conținut injectat ca context persistent la orice agent; acțiune „Rescrie cu AI" inline. | 3 | P3 | H1.3 | OpenWebUI |

### H10.D — Workflow Engine (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.12 | **Workflow Termination Conditions** — WorkflowStep poate defini o condiție de stop (LLM judge: "task rezolvat?", keyword match, max-iterations), nu doar completare normală. `WorkflowStep.stop_condition`. | 3 | P2 | H5.6 | AutoGen |
| H10.10 | **Structured Agent Outputs (Pydantic)** — SOUL.md sau config poate specifica un JSON schema; orchestratorul validează output-ul agentului și returnează eroare structurată la caller dacă nu e conform. | 5 | P2 | H5.6 | CrewAI |
| H10.15 | **Critic Agent Pattern** — built-in workflow node tip `critic`: primește output-ul pasului anterior, îl evaluează pe criterii configurabile, decide `accept`/`retry`(max N)/`escalate`. | 5 | P2 | H5.6, H10.12 | AutoGen |
| H10.13 | **Dynamic Agent Router** — WorkflowStep de tip `router_llm`: un agent coordinator decide la runtime care agent urmează, pe baza output-ului precedent (nu DAG fix). | 8 | P2 | H5.6 | AutoGen |
| H10.2 | **Visual Workflow Trace Overlay** — la fiecare rulare de workflow în HUD, nodurile pe canvas se colorează (verde=success, roșu=error, galben=running) și afișează output-ul per pas inline. | 5 | P2 | H9.1, H9.2 | Flowise |
| H10.28 | **Agent Config Preview** — în HUD Admin, înainte de save la SOUL.md sau config agent, un modal interactiv permite testarea comportamentului cu un query sandbox (fără a afecta producția). | 5 | P2 | H1.5 | Dust |
| H10.4 | **Guardrails Node în Visual Builder** — GuardrailsEngine expus ca nod plug-in în WorkflowBuilder; configurabil per workflow, nu doar global. | 2 | P3 | H4.9, H9.1 | Flowise |
| H10.6 | **Cyclic Workflow Support** — loop-back edges în WorkflowEngine cu contor de iterații și condiție de exit; util pentru retry loops și iterative refinement. | 8 | P3 | H5.6, H10.12 | Langflow |
| H10.7 | **AI-Assisted Workflow Builder** — în Visual Builder, câmp "Descrie ce vrei să facă acest pas" → LLM generează WorkflowStep config (agent, tool, prompt template). | 5 | P3 | H9.1 | Langflow |
| H10.9 | **Python Flow Decorator API** — `@jarvis_flow`, `@listen(step_id)`, `@router` pentru definire workflow-uri în cod Python (nu doar YAML/JSON); complement al Visual Builder. | 5 | P3 | H5.6 | CrewAI |
| H10.11 | **Hierarchical Workflow Manager** — workflow de tip `hierarchical`: auto-creează un manager agent care coordonează crew-ul, validează rezultate și redistribuie dacă un pas eșuează. | 8 | P3 | H5.6, H10.15 | CrewAI |
| H10.14 | **Nested Workflow Steps** — un WorkflowStep poate conține el însuși un sub-workflow; util pentru task decomposition recursivă. | 8 | P3 | H5.6 | AutoGen |
| H10.3 | **Workflow Transform Nodes** — noduri native în Visual Builder: Formatter, Validator, JSONExtractor, Summarizer — transformă output-ul unui pas înainte de a-l transmite mai departe. | 5 | P3 | H9.1 | Flowise |

### H10.E — UX & Multi-user (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.29 | **Agent Templates Library** — librărie de configurații pre-built pentru agenți comuni (research assistant, email triage, code reviewer, daily brief); importabile și clonabile din Admin. | 3 | P3 | — | Dust |
| H10.18 | **Action-Level Approval UI** — în HUD, tab live cu tool call-urile pending approval (granularitate sub-task); buton Aprob/Resping per acțiune individuală. Extinde H6.2. | 5 | P3 | H6.2 | SuperAGI |
| H10.20 | **Chat Channels / Rooms** — canale de chat tematice în HUD (per proiect/context); în fiecare canal poți @mention agenți specifici; pipeline complet (tools, RAG, filters). | 8 | P3 | H1.3 | OpenWebUI |
| H10.26 | **Data Spaces / Agent Data Scope** — organizează sursele de date (memory segments, plugin outputs, knowledge) în "spații" cu permisiuni per agent; complement la `LOCAL_ONLY_AGENTS`. | 13 | P3 | H8.1, H4.7 | Dust |

---

## ORIZONT 11 — Platform Parity (Known Gaps vs OpenJarvis) (P3) — 0/4

> Capabilități prezente în OpenJarvis dar absente în Jarvis Hub (vezi `STATUS.md` → Known Gaps).
> Toate P3 — nice-to-have, niciuna nu blochează 1.0.0. Mai multe au cost mare (GPU, Rust, build nativ).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H11.1 | **Desktop App (Tauri)** — UI nativ desktop (Windows/macOS/Linux) care împachetează HUD-ul existent; tray icon, wake-word listener local, auto-start. Alternativă la rularea în browser. | 13 | P3 | — | OpenJarvis (Tauri) |
| H11.2 | **Rust Extension / Hot-Path Crates** — port în Rust al căilor fierbinți (embeddings, vector search, parsing) ca extensii native (PyO3); pure-Python rămâne fallback. OpenJarvis are 14 crates. | 21 | P3 | H7 | OpenJarvis (14 crates) |
| H11.3 | **SFT/GRPO Training Pipeline** — fine-tuning local pe modele (SFT + GRPO) din trace-urile colectate; necesită GPU. Closing the loop pe Learning Loop (H7.11). | 13 | P3 | H7.11 | OpenJarvis |
| H11.4 | **WASM Sandbox (wasmtime)** — backend de execuție WASM pentru sandbox, complementar Docker; izolare mai bună și portabilă, fără daemon Docker. `core/sandbox.py` (backend nou). | 8 | P3 | — | OpenJarvis (wasmtime) |

---

## ORIZONT 12 — Categoria Reală: Asistent Personal Privat & Proactiv (P0–P3) — 0/14

> Bazat pe research-ul din [docs/research/2026-06-02-personal-ai-competitors.md](docs/research/2026-06-02-personal-ai-competitors.md):
> H10 a comparat Jarvis cu 8 **framework-uri de developeri**; categoria reală a moonshot-ului (asistent
> personal, proactiv, privat) nu fusese niciodată analizată. Idei derivate din competitorii **reali**
> (OpenClaw, Khoj, Leon, Omi, Bee, Pieces, Home Assistant, Jan, Tana) — fiecare verificată față de
> [principiile non-negociabile](MOONSHOT.md#5-non-negotiable-principles-the-guardrails).
>
> **Wedge-ul defensiv:** OpenClaw (rivalul direct viral) a eșuat exact unde Jarvis e puternic — secrete în
> plaintext, fără guvernanță acțiuni, marketplace nemoderat → ținta #1 a infostealerelor. Jarvis = alternativa guvernată.

### Track A — Securitate ca Diferențiator (P0, anti-OpenClaw)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.1 | **Securitate ca feature de prim rang** — criptează secretele at-rest (fără `SOUL`/memory în plaintext), skills semnate + sandboxed, expune coada de aprobare reversibil/ireversibil ca "povestea anti-OpenClaw". Pachetizează guardrails + PII scanner + sandbox existente. | 8 | **P0** | H6.2, Sec | OpenClaw (eșecuri) |

### Track B — Memorie & Onboarding (P1)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.2 | **Onboarding "drop folder → chat privat cu documentele"** — un singur pas: alegi un folder, Jarvis îl indexează local (PDF/MD/docx) și poți discuta cu el offline. Reduce frecarea primului contact. | 3 | P1 | H8.3 | GPT4All LocalDocs, Khoj |
| H12.3 | **KG interogabil & editabil (UX)** — graful de cunoștințe ca suprafață de prim rang: vizualizează, caută, editează, șterge entități/relații. Implementează direct "inspectable & forgettable" (H8.2). | 8 | P1 | H8.2 | Tana supertags |
| H12.4 | **Suport protocol Wyoming** — Jarvis vorbește Wyoming → interoperează cu sateliți Voice PE ($59) și ecosistemul vocal local Home Assistant; decuplează STT/TTS/wake. | 5 | P1 | — | Home Assistant, Rhasspy |

### Track C — Proactivitate & Observabilitate (P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.5 | **Preview / dry-run pentru autonomie** — arată ce *ar* face o acțiune înainte să aprobi pattern-ul; închide și gap-ul de observabilitate (nicio acțiune oarbă). Extinde H6.2. | 5 | P2 | H6.2 | Dust config preview |
| H12.6 | **Update-uri KG incrementale (nu doar nocturne)** — extracție ușoară de entități per-tură ca memoria să apară în aceeași sesiune, nu doar după consolidarea de noapte. | 5 | P2 | H5.15, H8.1 | Mem, Tana |
| H12.7 | **Captură pasivă multi-suprafață (opt-in, local)** — browser/clipboard/fișiere → KG, doar local. ⚠️ STRICT opt-in + inspectabil; nimic nu pleacă de pe mașină. | 8 | P2 | H8.1 | Pieces nanomodels, Omi |
| H12.8 | **Split sateliți-mic → server-inferență pe GPU-ul de acasă** — mai multe endpoint-uri ieftine de microfon partajează un singur GPU Jarvis. | 8 | P2 | H12.4 | Willow (WIS) |
| H12.9 | **UX management modele locale** — răsfoiește/descarcă/comută modele dintr-un click în HUD. | 5 | P2 | — | Jan.ai |
| H12.10 ✅ | **Indicator mute hardware / strict-local** — semnal vizibil, auditabil "mic off / strict-local" în HUD + voce. Semnal de încredere ieftin. | 2 | P2 | — | Voice PE (mute fizic) |
| H12.11 | **Canale de escaladare extinse** (dincolo de Telegram: WhatsApp/Signal/Slack/Discord) — *guvernate*, spre deosebire de OpenClaw. Adaptoarele de canal există deja. | 3 | P2 | H1.3 | OpenClaw (multi-channel) |

### Track D — Platformă & Ecosistem (P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.12 | **Marketplace de skills curat & semnat** (anti-ClawHub moderat) — extinde skills importer cu semnături + review. ⚠️ moderat/semnat obligatoriu. | 8 | P3 | Skills | OpenClaw ClawHub (sigur) |
| H12.13 | **Sync E2E opt-in între device-uri** (GPU acasă ↔ telefon) — ⚠️ obligatoriu E2E + opt-in; nu sparge local-first. | 13 | P3 | — | Reflect / Limitless |
| H12.14 | **Model agentic mic, fine-tuned** (task-uri router/tool) — overlap cu H11.3 (pipeline SFT/GRPO); $0 COGS. | 8 | P3 | H11.3 | Jan-nano |

> **Total ORIZONT 12:** 14 items, ~89 SP. **Acțiune imediată recomandată:** H12.1 (P0) — e simultan hardening real
> ȘI wedge-ul de marketing (alternativa securizată la OpenClaw). Restul Track B (P1) ridică cel mai mult valoarea per efort.

---

## ✅ Arhivă — H1–H4 + Sprint 0 (livrat în 0.5-beta)

> Toate itemurile H1–H4 sunt complet implementate. Detalii complete (67 items, 248 SP): [docs/HISTORY.md](docs/HISTORY.md).

---

## Testing Guide

> Cum testezi fiecare feature. Pentru comenzi rapide, vezi `docs/features/`.

```
Feature               Test command                          Ce verifici
─────────────────────────────────────────────────────────────────────────
All tests             python -m pytest tests/ -q            Toate feature-urile
Voice                 python tests/test_voice.py -v         STT → TTS pipeline
Telegram              python tests/test_telegram.py -v      Webhook + polling
OAuth                 python tests/test_oauth.py -v         Token refresh + PKCE
Calendar (Pepper)     python tests/test_calendar.py -v      CRUD evenimente
Gmail (Pepper)        python tests/test_gmail.py -v         Etichete, triage
Spotify (Jerome)      python tests/test_spotify_skill.py -v Play/pause/queue
Health (Hercules)     python tests/test_apple_health.py -v  Sleep/HRV/steps
Gecko (balance)       python tests/test_balance.py -v       ING/Libra/CSV/mock
Stark (analytics)     python tests/test_analytics.py -v     GA4 KPIs + mock
Security (Ultron)     python tests/test_security.py -v      Porturi, threats
System (Steve)        python tests/test_system.py -v        CPU/GPU/RAM/temp
n8n (Oracle)          python tests/test_n8n.py -v           CRUD workflow-uri
Sandbox               python tests/test_sandbox_gating.py -v Docker exec
Guardrails            python tests/test_guardrails.py -v    PII redact, injection block
Charts (admin)        python tests/test_admin_stats.py -v   Endpoint metrics
Learning              python tests/test_learning_live.py -v Health routing + promovare
Session               python tests/test_session*.py -v      Persistență + cross-channel
Bench                 python tests/test_bench_activation.py Bench promovare
Integration           python tests/test_agents_integration.py -v Toți agenții (SOUL+router+process)
Load                  python tests/test_load.py -v          15 paralel <30s
Smoke                 powershell smoke.ps1                  Server start + pytest
```

---

## Dependencies

| Resursă | Pentru | Cost |
|---------|--------|------|
| Google Cloud OAuth 2.0 | Pepper Gmail | Gratuit |
| Spotify Developer App | Jerome Spotify | Gratuit |
| Tavily API | Vision Research | Gratuit (1000/lună) |
| Discord Bot Token | Discord channel | Gratuit |
| Slack App Token | Slack channel | Gratuit |
| Docker (Qdrant, Neo4j, n8n) | H3.1, H3.2, H4.6 | Gratuit |
| n8n API Key | Oracle | Gratuit |
