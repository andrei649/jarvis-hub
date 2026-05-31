# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 568 passed, 8 skipped
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
| **H5 Next Wave** (P2–P3) | 11 | **2** | 89 | **11** | **12%** |
| **H6 Jarvis Autonom** (P1) | 6 | **6** | 55 | **55** | **100%** |
| **Total general** | **81** | **74** | **379** | **311** | **82%** |

**Test count:** 660 passed, 8 skipped (H5.5 complet: resilience patterns)

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

> **ORIZONT 6 COMPLET ✅** — bucla autonomă end-to-end + executor real per task-kind (research→websearch, restul→LLM pipeline), ritual zilnic, preference learning, night shift. 82 teste autonomy, suită 651 passed.
> **Setări noi** (categoria `autonomy` în admin): owner_chat_id, cap_per_action, daily_ceiling, interrupt_budget, night_shift/start/end + `system.autonomy_tick`.

---

## ORIZONT 5 — Next Wave (P2–P3) — 1/8

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.

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
| H5.10 | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/api/memory/stats`, `/api/plugins`, `/api/learning/stats`, `/security/status`) | 5 | H5.9 | 0.8 |
| H5.11 | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 |

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

---

**Total cost lunar:** $0 (toate serviciile au tier gratis sufficient pentru uz personal)
