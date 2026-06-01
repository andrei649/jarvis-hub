# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 740 passed, 9 skipped
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
| **0.6-beta** | Next | Howard fine-tuning + voice clone + continuous ingestion | H5.1 |
| **0.7-beta** | Next | Mobile PWA + i18n + UI Overhaul | H5.2, H5.3, H5.4 |
| **0.8-beta** | Next | Performance & robustness + multi-agent workflows | H5.5, H5.6 |
| **0.9-beta** | Next | New integrations + agent marketplace | H5.7, H5.8 |
| **1.0.0** | 🎯 Stable | All H5 done, documented, CI/CD, onboarding docs | All above + polishing |

---

## Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H1–H4 + Sprint 0 + Cross-cutting + Sec + Bugs** | 67 | **67** | 248 | **248** | **100%** |
| **H5 Next Wave** (P2–P3) | 17 | **8** | 128 | **47** | **36.7%** |
| **H6 Jarvis Autonom** (P1) | 7 | **7** | 60 | **60** | **100%** |
| **Total general** | **88** | **82** | **423** | **355** | **83.9%** |

**Test count:** 749 passed, 9 skipped (QA 2026-06-01: +H5.12/H5.13 confirmate livrate, fix izolare teste, +H5.14 Retrieval Fusion)

---

## Active: ORIZONT 6 — Jarvis Autonom / Proactive Cortex (P1) — 0/6

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

> **ORIZONT 6 COMPLET ✅** — bucla autonomă end-to-end + executor real per task-kind (research→websearch, restul→LLM pipeline), ritual zilnic, preference learning, night shift, **+ Proactive OS Observer (H6.7)**. Suită 715 passed.
> **Audit MCU (2026-05-31):** intent router rescris (determinist, scored, **bilingv RO/EN**, fără substring-bug, fallback LLM opțional) — vezi `docs/gap-analysis-mcu-jarvis.md`. **Rămas ✅ (livrat 2026-06-01):** handler real `restart_service` (H5.12 — `RemediationRunner`, allowlist + no-shell + audit) și event-watchers email/calendar/finanțe/health (H5.13 — `EventWatcher`, același pattern ca observer-ul) sunt acum implementate, wired și testate.
> **Setări noi** (categoria `autonomy` în admin): owner_chat_id, cap_per_action, daily_ceiling, interrupt_budget, night_shift/start/end + `system.autonomy_tick`.
>
> **UPDATE CHAT ANTIGRAVITY (2026-06-01) ✅**: Core TTS & Hands-Free Live Voice Interaction implementat complet + unit teste adăugate și 100% verzi.
> **Bug-uri rezolvate:** 
> 1. Eroare runtime stale pycache (`SecurityEventType.LLM_CALL` missing) rezolvată prin curățare pycache + repornire.
> 2. `t_s0 is not defined` în `handle_input_stream` rezolvată prin inițializare explicită de cronometru.
> 3. Scurgeri de thinking/reasoning blocks streamuite (rezolvat cu `ThinkingStreamFilter` + `strip_thinking()`).
> 4. Crash de tip `TypeError` în event handlerul `submit` al UI-ului atunci când se dădea click pe Transmit (rezolvat prin securizarea `textOverride` tip string).
>
> **QA PASS CLAUDE (2026-06-01) ✅**: Suită rulată end-to-end → **740 passed, 9 skipped** (după fix); **749** cu H5.14.
> - **Verificat:** TTS/voice Antigravity (PR #11) — `/tts` endpoint, `ThinkingStreamFilter`, fallback `reasoning_content` în `generate_stream`; cod solid, teste verzi.
> - **Descoperit & sincronizat:** **H5.12 + H5.13** erau deja implementate, wired și testate (commit `6cafc9d`) dar nemarcate în backlog → marcate ✅ acum.
> - **Bug reparat (CI roșu → verde):** 2 eșecuri ordine-dependente din scurgerea globalei `web.orch` între fișiere de test. Cauză: `lifespan` nu reseta `orch`/`gateway` la shutdown (4 fișiere cu `with TestClient(web.app)` scurgeau un orchestrator real) + `_admin_response` din `test_resilience_integration.py` nu restaura globala (MagicMock). Fix: lifecycle simetric (guarded) în `web.py` + save/restore în helperul de resilience. Suita e acum deterministă.
> - **Următoarea dezvoltare livrată:** **H5.14 Retrieval Fusion Engine** (RRF vector⊕graph) — engine + wiring + 9 teste offline.

---

## 🔴 Auto-Generated Diagnostic Tasks

> [!NOTE]
> These tasks are auto-generated from active runtime failures in `problems.jsonl`.
> Sync runs automatically during the autonomy observer check.

✓ No active runtime failures detected in the last 48 hours.
## ORIZONT 5 — Next Wave (P2–P3) — 8/17

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.
>
> **Următoarele (0.8, deps satisfăcute):** **H5.17** Batch & Cache Embeddings → **H5.15** Daily Reflection & Graph Consolidation (poate folosi `hybrid_search` din H5.14). Apoi headline 0.8: **H5.6** Multi-Agent Workflows. Opțional: Task 4 din H5.14 (endpoint `/api/memory/search` + HUD).

| # | Item | S | Dep | Target version |
|---|------|---|-----|---------------|
| H5.1 | Howard: fine-tuning + voice clone + continuous ingestion | 13 | — | 0.6 |
| H5.2 | Mobile HUD / PWA (responsive, offline, push) | 8 | — | 0.7 |
| H5.3 | Multi-Language / i18n (RO/EN switch) | 5 | — | 0.7 |
| H5.4 | UI Overhaul (teme, layout, accesibilitate) | 8 | H5.2 | 0.7 |
| H5.5 ✅ | **Performance & Robustness** (retry, circuit breaker, rate limit, caching, resilience metrics) | 8 | — | 0.8 ✅ |
| H5.6 | Multi-Agent Workflows (handoff, paralel, pipeline) | 13 | H5.5 | 0.8 |
| H5.7 | New Integrations / Plugins (SMS, CRM, IoT, social) | 8 | — | 0.9 |
| H5.8 | Agent Marketplace / Skill Sharing (registry, publish) | 13 | H5.6 | 0.9 |
| H5.9 ✅ | **Resilience Tab in Main HUD** — tab live în SystemsPanel cu retry metrics + circuit breaker states, endpoint public `/api/resilience` | 3 | H5.5 | 0.8 ✅ |
| H5.10 ✅ | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`) | 5 | H5.9 | 0.8 ✅ |
| H5.11 ✅ | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 ✅ |
| H5.12 ✅ | **Secured Shell Task Executor** — `RemediationRunner` (allowlist, permission gate, no-shell `exec`, audited) wired ca handler `restart_service` în executor. `core/autonomy/remediation.py` | 5 | H6.7 | 0.8 ✅ |
| H5.13 ✅ | **Proactive Event Watchers** — `EventWatcher` + Email/Calendar/Finance/Health probes, eșantionate în bucla de autonomie (gated `system.watchers_enabled`). `core/autonomy/watchers.py` | 8 | H6.7 | 0.8 ✅ |
| H5.14 ✅ | **Retrieval Fusion Engine** — `reciprocal_rank_fusion()` + `HybridRetriever` (vector⊕graph RRF, weight-tunable, injectabil) + `MemoryManager.hybrid_search()`. `core/memory/fusion.py`, 9 teste offline. *(Task 4 — endpoint `/api/memory/search` + HUD — opțional, rămas.)* | 5 | H3.1, H3.2 | 0.8 ✅ |
| H5.15 | **Daily Reflection & Graph Consolidation** — auto-reflecție nocturnă, lessons learned store promovat în Neo4j | 8 | H6.6, H3.2 | 0.8 |
| H5.16 ✅ | **Sentence-level TTS & Audio Barge-in** — integration edge-tts, play/stop barge-in sync, auto-speak, unit tested | 8 | H1.1, H5.5 | 0.8 ✅ |
| H5.17 | **Batch & Cache Embeddings Pipeline** — pipeline ingestie optimizat cu paralelizare, rate limit și local cache | 5 | H5.5 | 0.8 |

---

## ✅ Arhivă — Tot ce e livrat în 0.5-beta

> Toate itemurile de mai jos sunt complet implementate, testate și funcționale.

### Foundation (H1) + Sprint 0

| Item | S | AC |
|------|---|----|
| **H1.1** Voice Channel (STT → orchestrator → TTS) | 8 | Pipeline complet funcțional |
| **H1.2** Telegram Channel (webhook + polling) | 5 | Bot răspunde direct, session per chat_id |
| **H1.3** Web Channel robust (SSE streaming) | 3 | Text → LLM → tokens streamuite în HUD |
| **H1.4** OAuth wiring (Google Calendar, Gmail, Spotify) | 5 | Token refresh + OAuth lifecycle complet |
| **H1.5** Admin DB → Runtime (settings watcher 30s) | 5 | Schimb temp din admin → efect imediat |
| **S0.1** Model Tiering (Claude API pentru grei, local pt ușori) | 3 | Vision/Steve → Claude; rest → local; Frigga → strict local |
| **S0.2** Heartbeat Sanity (intervale ≥60 min) | 2 | Steve la 2h, Ultron de 2x/zi, rest OK |
| **S0.3** Smoke Test + CI pe push | 2 | GitHub Actions pytest + server smoke |

### Core Agent Capabilities (H2) — 12 items

| Item | S | AC |
|------|---|----|
| **H2.1** Pepper Calendar | 5 | „adaugă meeting" → eveniment creat |
| **H2.2** Pepper Gmail Triage | 5 | „ce e nou în inbox?" → listă priorizată |
| **H2.3** Friday Brief Pipeline | 8 | Briefing complet structurat la cerere |
| **H2.4** Hercules Health Data | 5 | „cum am dormit?" → durată, calitate, trend |
| **H2.5** Jerome Spotify | 3 | „pune ceva focus" → track din library |
| **H2.6** Gecko Balance Reader | 8 | „câți bani am?" → sumă + mock când neconfigurat |
| **H2.7** Hephaestus PM | 8 | „status Cosmina?" → fază, milestone, blockeri |
| **H2.8** Frigga Local Store | 8 | „cât a dormit Max?" → ore, calitate. Zero network |
| **H2.9** Vision Web Research | 5 | „cercetează piața X" → raport cu surse |
| **H2.10** Veronica Drafting | 3 | „scrie post LinkedIn" → draft complet |
| **H2.11** Stark GA4 Analytics | 5 | KPI summary + mock când neconfigurat |
| **H2.12** Hybrid LLM Router (local ↔ Gemini) | 13 | Rutează per request după token count + agent policy |

### Intelligence & Memory (H3) — 6 items

| Item | S | AC |
|------|---|----|
| **H3.1** Qdrant Vector DB | 5 | Căutare similaritate pe conversații |
| **H3.2** Neo4j Knowledge Graph | 8 | „unde lucrează Andrei?" → răspunde din graph |
| **H3.3** Session Persistence cross-channel | 5 | Mesaj web → întrerup → Telegram → același context |
| **H3.4** Learning Loop live | 8 | După 100 interacțiuni → sugerează promovare bench |
| **H3.5** Heartbeat System (APScheduler) | 5 | 07:00 Jarvis face morning brief fără trigger |
| **H3.6** Bench Agent Activation | 8 | 20 query-uri Vision → Bruce devine activ |

### Platform & Security (H4) — 11 items

| Item | S | AC |
|------|---|----|
| **H4.1** Discord Channel | 5 | Agent trimite mesaj pe Discord |
| **H4.2** Email Channel (SMTP/IMAP) | 3 | „trimite raport pe email" → trimis |
| **H4.3** Slack Channel | 3 | Stark vede mențiuni Slack |
| **H4.4** Ultron Security Monitoring | 8 | „status securitate?" → devices, ports, threats |
| **H4.5** Steve System Monitor | 8 | „cum e sistemul?" → metrics + alerts |
| **H4.6** Oracle n8n Workflow Designer | 5 | „creează workflow vreme" → creat |
| **H4.7** MCP Client real (stdio/SSE) + admin-wiring | 8 | Server adăugat din admin → disponibil ca plugin (endpoints testate `tests/test_mcp_admin.py`) |
| **H4.8** Sandbox Docker | 5 | „rulează Python" → container, output |
| **H4.9** Guardrails (REDACT/BLOCK) | 5 | Prompt injection → blocat; PII → redactat |
| **H4.10** Admin Charts & Audit | 8 | Admin arată ultimele 100 interacțiuni, latență |
| **H4.11** Context Cache + Metrics | 5 | 50 mesaje → 80% cache hit |

### Cross-cutting (6) / Securitate (5) / Bugfixes (17)

**Cross-cutting:** Session Manager thread-safe, Error taxonomy, CHANGELOG.md, Integration tests per agent (15), Plans per agent, Load test 15 agenți <30s.

**Securitate:** Admin env masked, Admin guard (token/localhost), SSRF protection, Gemini stream raise_for_status, OAuth PKCE+state+Fernet.

**Bugfixes:** 17 bugs fixed (admin.js, app.js, web.py, orchestrator.py, css) — vezi detalii în archive commit `4e3bae5`.

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
## 🔴 Auto-Generated Diagnostic Tasks

> [!NOTE]
> These tasks are auto-generated from active runtime failures in `problems.jsonl`.
> Sync runs automatically during the autonomy observer check.

✓ No active runtime failures detected in the last 48 hours.
## ORIZONT 5: Next Wave (P2–P3) — 0/8

> Scop: extindere capabilități după foundation stabil. Fiecare item are spec + plan propriu.

### H5.1 — Howard: Fine-Tuning + Voice Clone + Continuous Ingestion (S:13, Dep: —)
Ollama backend (`ollama_howard.py`), embedder RAG, voice cloning XTTS, watch `data/` for new exports.
**AC:** Howard răspunde în vocea lui Andrei, cu RAG din arhivă, via Ollama.

### H5.2 — Mobile HUD / PWA (S:8, Dep: —)
Dashboard responsive, mobile-first, offline support (Service Worker), push notifications.
**AC:** HUD-ul funcționează pe telefon fără pierderi de funcționalitate.

### H5.3 — Multi-Language / i18n (S:5, Dep: —)
Extrage stringuri RO hardcodate în fișiere de traducere, suport EN/RO, detectare automată limbă.
**AC:** UI-ul comută între RO și EN după preferință.

### H5.4 — UI Overhaul (S:8, Dep: H5.2)
Teme, layout îmbunătățit, componente reutilizabile, animații, accesibilitate.
**AC:** HUD-ul arată modern și e utilizabil și pe ecrane mici.

### H5.5 ✅ — Performance & Robustness (S:8, Dep: —)
Resilience patterns: `@resilient_call` decorator with retry + exponential backoff, CircuitBreaker with tri-state (closed/open/half-open), ResilienceMetrics per agent+backend. Integrated into CloudLLMPlugin (Anthropic, Gemini, OpenAI) and HTTP plugins (weather, gmail, calendar, spotify). Exposed in `/api/admin/stats` endpoint + admin UI charts. Load test verifies 50 parallel calls with 10% failure rate.
**AC:** Sistemul nu crapă la overload și se recuperează automat.

### H5.6 — Multi-Agent Workflows (S:13, Dep: H5.5)
Agent handoff avansat, execuție paralelă, pipeline-uri compuse, rezultate intermediate partajate.
**AC:** Un query complex (ex: "analizează finanțele și trimite raport") se execută în <15s.

### H5.7 — New Integrations / Plugins (S:8, Dep: —)
More plugins: notificări SMS, CRM sync, social media posting, IoT control.
**AC:** 3+ pluginuri noi funcționale, testate, cu admin configurator.

### H5.8 — Agent Marketplace / Skill Sharing (S:13, Dep: H5.6)
Catalog de skills partajabile, import dintr-un registry, versionare skills, publish workflow.
**AC:** Un skill scris de altcineva se instalează cu o comandă.

### H5.9 ✅ — Resilience Tab in Main HUD (S:3, Dep: H5.5)
Adăugare tab în SystemsPanel din HUD cu starea circuit breakerelor și retry metrics (endpoint `/api/resilience`).
**AC:** Interfața arată live degradarea grațioasă a conexiunilor.

### H5.10 ✅ — Live Data Wiring (S:5, Dep: H5.9)
Conectare taburi Memory, Plugins, Learning, Security la endpoint-uri reale din backend în loc de mock.
**AC:** Toate graficele și listele de securitate din HUD prezintă datele reale din DB/Logs.

### H5.11 ✅ — Missing Widgets (S:5, Dep: H5.10)
Ticker feed în HUD, status OAuth integrat, widget de task-uri curente și CognitionPanel funcțional.
**AC:** Toate widgeturile din interfață sunt active și interactive.

### H5.12 ✅ — Secured Shell Task Executor (S:5, Dep: H6.7)
`RemediationRunner` (`core/autonomy/remediation.py`) execută `restart_service` aprobat prin patru straturi independente: **allowlist** (rulează doar argv-ul allowlistat, ignoră `cmd` din payload), **permission gate** (`system-control` → steve/ultron/jarvis), **no-shell** (`create_subprocess_exec(*argv)`), **bounded + audited** (timeout + recovery probe + audit). Wired ca handler `restart_service` în executor (`orchestrator.py`). I/O injectabil → testat offline (`tests/test_autonomy_remediation.py`).
**AC ✅:** Aprobarea unui restart din Telegram execută comanda shell reală în siguranță, în loc de fallback LLM.

### H5.13 ✅ — Proactive Event Watchers (S:8, Dep: H6.7)
`EventWatcher` + `EmailProbe`/`CalendarProbe`/`FinanceProbe`/`HealthProbe` (`core/autonomy/watchers.py`), construite din pluginurile active și eșantionate în `_autonomy_loop` (gated `system.watchers_enabled`). Același pattern debounce ca OS Observer-ul; probe injectabile, testate offline (`tests/test_event_watchers.py`).
**AC ✅:** Evenimentele externe sunt observate, injectând alerte/taskuri automate în coada de autonomie.

### H5.14 ✅ — Retrieval Fusion Engine (S:5, Dep: H3.1, H3.2)
`core/memory/fusion.py`: `reciprocal_rank_fusion(ranked_lists, k=60, weights, top_k)` — RRF pur, rank-based (fără normalizare între scale diferite), cu provenance (`sources`) și payload merge; `HybridRetriever(vector_store, graph)` adaptează formele reale (`{id,score,metadata}` vector / `{name,type,properties}` graph), injectabil → testat offline cu `InMemoryVectorStore`+`InMemoryGraph`; `MemoryManager.hybrid_search(embedding, keyword, top_k)`. Plan: `docs/superpowers/plans/2026-06-01-h5.14-retrieval-fusion.md`. 9 teste (`tests/test_retrieval_fusion.py`).
**Rămas (opțional, Task 4):** endpoint public `/api/memory/search` + setări `memory.fusion_*` + box „Fused recall" în HUD.
**AC ✅:** un singur query întoarce o listă rankată care împletește similaritatea conversațională (vector) cu hit-urile factuale din graf; fuziune deterministă, weight-tunable, rulează offline.

### H5.15 — Daily Reflection & Graph Consolidation (S:8, Dep: H6.6, H3.2)
Buclă nocturnă autonomă de consolidare care reflectă asupra chat-urilor zilei, extrage highlights și lecții noi, stocându-le ca noduri/relații în Neo4j.
**AC:** Knowledge Graph-ul se extinde organic după fiecare noapte prin auto-reflecție.

### H5.16 ✅ — Sentence-level TTS & Audio Barge-in (S:8, Dep: H1.1, H5.5)
Pipeline de voce optimizat: streaming audio fragmentat la nivel de propoziție și barge-in instant la wake word în timpul redării.
**AC:** Latența de prim sunet scade sub 1.5s, iar redarea se oprește la detectarea vocii utilizatorului. S-a implementat edge-tts backend, dynamic speech button (🔊), global audio window manager și hands-free live voice interaction (auto-transmitere și auto-speak).

### H5.17 — Batch & Cache Embeddings Pipeline (S:5, Dep: H5.5)
Sistem de procesare batch pentru embedder (`ingestion/embedder.py`) cu caching pe disc, rezistent la API rate-limits.
**AC:** Ingestia masivă pentru digital twin-ul Howard decurge fluid și stabil.

---

**Total cost lunar:** $0 (toate serviciile au tier gratis sufficient pentru uz personal)
