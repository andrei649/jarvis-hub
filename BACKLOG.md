# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 538 passed, 8 skipped
```

> Cele 8 skipped sunt din `tests/test_spotify.py` (pattern HTTP-router, opencode) care
> așteaptă `agents/core/skills/spotify.py` — neimplementat. Spotify (H2.5) **funcționează**
> via `skills/spotify/main.py` (pattern loader, acoperit de `tests/test_spotify_skill.py`).

**După modificări JS/CSS:** Ctrl+F5 în browser (cache bust).
**După modificări Python:** repornire server (Ctrl+C, re-execută comanda uvicorn).
**Server curent** (dacă e pornit): PID vezi `netstat -ano | findstr ":8080 "`.
**Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX).

---

## ORIZONT 1: Foundation (P0) — ✅ Complet

### H1.1 — Voice Channel (S:8) ✅
Wake word → Whisper STT → orchestrator → Kokoro TTS → speaker.
- VoiceChannel instanțiat și înregistrat în `web.py`
- Wake words din settings DB (`general.wake_words`)
- Fallback graceful la dependențe hardware lipsă
- AC: pipeline complet funcțional

### H1.2 — Telegram Channel (S:5) ✅
Webhook + polling, inbound → orchestrator, replies back.
- TelegramChannel instanțiat cu `TELEGRAM_BOT_TOKEN`
- Session isolation per `chat_id` (`_channel_sessions`)
- AC: bot răspunde direct → session per chat_id

### H1.3 — Web Channel robust (S:3) ✅
Chat streaming end-to-end.
- temperature/max_tokens din settings DB (`llm.temperature`, `llm.max_tokens`)
- Model din settings (`llm.default_model`)
- AC: text → LLM → tokens streamuite în HUD

### H1.4 — Plugin Auth wiring (S:5) ✅
OAuth flows: Google Calendar, Gmail, Spotify.
- `core/plugins/oauth.py` — URL generation, code exchange, auto-refresh
- Endpointuri `/api/oauth/status`, `/api/oauth/callback`, `/api/oauth/auth-url`
- Refresh automat pe 401 (Gmail, Calendar, Spotify)
- Token persistence în `memory_logs/tokens/`
- AC: token refresh + OAuth lifecycle complet

### H1.5 — Admin DB → Runtime (S:5) ✅
Setări din admin aplicate activ în orchestrator.
- `load_runtime_settings()` citește SQLite settings DB
- Settings watcher loop (30s refresh)
- `get_setting(key, default)` în LLM calls
- AC: schimb temp din admin → următorul LLM call folosește noua temp

---

## Sprint 0 — Stabilitate & Performanță (P0, ~1-2h)

> Scop: eliminare thrashing, heartbeat sanity, CI de bază. ROI maxim pe timp minim.

### S0.1 — Model Tiering: Claude API pentru agenți grei, local 7b pentru ușori (S:3) ✅
15 agenți pe același `qwen3:32b` într-un laptop de 24GB VRAM → **thrashing** (un singur model 32b odată).
- Agenți grei (Vision, Steve) → **Claude API** (extern, 0 VRAM)
- Agenți uzuali (Jarvis, Pepper, Friday) → local `qwen3:7b` (cap în VRAM)
- Frigga → strict local (fără network)
- Config în `agents.yaml` per agent + `ANTHROPIC_API_KEY` în `.env`
- Backend: `agents/core/llm/anthropic.py` — ClaudeBackend cu streaming + generate
- Router: `CLAUDE_AGENTS = {"vision", "steve"}`, fallback la Gemini → local

### S0.2 — Heartbeat Sanity: intervale ≥60 min (S:2) ✅
Heartbeat-uri curente la 5-15 min forțează reload constant.
- Steve (`* * * * *` → fiecare minut) → `0 */2 * * *` (la 2 ore) ✅ aplicat în `agents/steve/HEARTBEAT.md`
- Ultron (`0 * * * *` → la oră) → `0 6,18 * * *` (de 2x/zi) ✅ aplicat în `agents/ultron/HEARTBEAT.md`
- Restul (majoritar `0 6 * * *`) OK, păstrat
- Verificare că schedulerul nu crapă la shutdown (bug APScheduler existent)

### S0.3 — Smoke Test + CI pe push (S:2) ✅
- Script `smoke.ps1`: pytest tests/ -q, verificare server pornește
- GitHub Actions workflow (`.github/workflows/smoke.yml`): pytest + server smoke
- Rulează la fiecare push pe master

---

## ORIZONT 2: Core Agent Capabilities (P1)

### H2.12 — Hybrid LLM Router: Local ↔ Gemini API (S:13) ✅
Router inteligent care alege backend-ul optim per request: local (LM Studio) sau cloud (Gemini API).

**Arhitectură multi-factor:**
1. **Token Budget** — estimează contextul înainte de rutare
2. **Agent Policy** — Frigga/Ultron local-only, Vision/Athena cloud-only, rest auto
3. **Graceful degradation** — cloud down → fallback local; local down → try cloud
4. **Per-agent routing** — fiecare request alege backend-ul după agent policy + token count

### H2.1 — Pepper Calendar (S:5) ✅
Skill `calendar-manager` — citește, crează, modifică evenimente via Google Calendar API.
**AC:** „Pepper, adaugă meeting mâine 10-11" → eveniment creat

### H2.3 — Friday Brief Pipeline (S:8) ✅
Colectează vreme + știri + piață la cerere, degradează grațios la timeout.
**AC:** briefing complet structurat la cerere

### H2.4 — Hercules Health Data Loop (S:5) ✅
Sleep/HRV/HR/steps/workouts din `apple_health.py` + pattern detection.
**AC:** „Hercules, cum am dormit?" → durată, calitate, trend 7 zile

### H2.5 — Jerome Spotify Control (S:3) ✅
Play/pause/skip/queue + playlist suggestion via Spotify API.
**AC:** „Jerome, pune ceva focus" → track din library cu tag „focus"

### H2.7 — Hephaestus PM (S:8) ✅
Project tracker Cosmina (faze, termene) + BMW E93 (piese, service) în SQLite.
**AC:** „Hephaestus, status Cosmina?" → fază, milestone, blockeri

### H2.8 — Frigga Local Data Store (S:8) ✅
SQLite local pentru Max (somn/HRV/mâncare/vaccinuri), Alexandra (B&B), pisici.
**AC:** „Frigga, cât a dormit Max?" → ore, calitate, trend. Zero external network.

### H2.10 — Veronica Drafting (S:3) ✅
Drafturi LinkedIn, Digitaholic blog, email în ton specificat, salvate local JSON.
**AC:** „Veronica, scrie un post LinkedIn despre AI în banking" → draft complet

### H2.2 — Pepper: Email Triage Gmail (S:5, Dep: H1.4) ✅
Citește etichete Gmail, prioritizează, sugerează acțiuni.
**AC:** „Pepper, ce e nou în inbox?" → listă scurtă priorizată

### H2.6 — Gecko: Balance Reader (S:8, Dep: API bănci) 🔴
Solduri ING + Libră (API sau spreadsheet sync), burn rate, runway.
**AC:** „Gecko, câți bani am în cont?" → sumă exactă cu valută

### H2.9 — Vision: Web Research (S:5) ✅
Căutări web, extrage conținut, sumarizează cu citări (Tavily/SearXNG/DDG fallback + SSRF guard — deja existent).
**AC:** „Vision, cercetează piața MarTech CEE" → raport structurat cu surse

### H2.11 — Stark: GA4 + Firebase (S:5, Dep: access API) 🔴
Conectare GA4 API și Firebase Analytics. Raportează KPIs.
**AC:** „Stark, cum a performat campania Q2?" → metrics vs target

---

## ORIZONT 3: Intelligence & Memory (P2)

### H3.1 — Memory: Qdrant Vector DB (S:5, Dep: Qdrant pornit) ✅
Conversații indexate semantic, căutare similaritate.
**AC:** „Ce am discutat despre Cosmina luna trecută?" → găsește și rezumă

### H3.2 — Memory: Neo4j Knowledge Graph (S:8, Dep: Neo4j pornit) ✅
Entități, relații, fapte persistate. Scrie pe confirmare explicită.
**AC:** „Unde lucrează Andrei?" → răspunde din graph

### H3.3 — Session Persistence (S:5, Dep: H3.1) ✅
Salvează/restaurează sesiuni cross-channel.
**AC:** mesaj pe web → întrerup → întreb pe Telegram → același context
- ✅ Persistență peste restart (`ConversationMemory` snapshot JSON + jsonl, restaurare la pornire) — cu teste (`tests/test_session_persistence.py`, 3 teste).
- ✅ Resume explicit de sesiune anume: `ConversationMemory.resume_session()` + `MemoryManager.resume_session()` + endpoint `POST /sessions/resume`.
- ✅ Continuitate cross-channel **opt-in** prin flag `memory.cross_channel_sessions` (default off → izolarea Telegram din H1.2 e păstrată; on → web↔telegram împart `session_id`). Teste: `tests/test_cross_channel_sessions.py`.

### H3.4 — Learning Loop live (S:8, Dep: H3.1, H3.3) ✅
Analizează interacțiuni (succes/eșec), ajustează routing, promovează/demovează agenți.
- **Routing live:** `LearningLoop.rank_candidates` + `is_unhealthy` → orchestrator `_route_candidates` reordonează candidații după health-score și scoate agenții cronic-eșuați când există alternativă (wake-word explicit nu se rerutează; nu rămâne niciodată lista goală)
- **Promovare bench:** `suggest_promotions` — regulă data-driven din `agents.yaml` (`bench.<id>.triggers_on`/`threshold`/`window_days`); default `bruce ← vision @ 20/30d`. Skip pentru agenți deja activi
- Expus în `get_stats` + endpoint `/learning` (`promotion_suggestions`)
- Demovarea pe eșecuri consecutive exista deja (`agent.should_demote`)
- Teste: `tests/test_learning_live.py` (13) + routing în `tests/test_routing.py` (5)
**AC:** după 100 interacțiuni, sugerează promovare agent bench ✅ (verificat: 21 query-uri Vision → sugerează Bruce)

### H3.5 — Heartbeat System (S:5, Dep: —) ✅
Cron scheduler (APScheduler) pentru jarvis 07:00, friday 06:30, pepper 20:00 Sunday.
**AC:** la 07:00 Jarvis face morning brief fără trigger manual

### H3.6 — Bench Agent Activation (S:8, Dep: H3.4) ✅
Mecanism promovare when trigger îndeplinit (howard, bruce, wanda, etc.).
- `Orchestrator.promote_bench_agent(bench_id)` — scrie SOUL stub din arhetip dacă lipsește, instanțiază `Agent`, îl adaugă în `self.agents` + router (idempotent)
- Hook auto-promovare în `_record_interactions`: rulează `suggest_promotions` și promovează doar dacă `learning.auto_promote` e on (default off → rămâne doar sugestie)
- Endpoint `POST /learning/promote` (cu `_admin_guard`)
- Teste: `tests/test_bench_activation.py` (11)
**AC:** 20 query-uri/lună către Vision → Bruce devine active ✅

---

## ORIZONT 4: Platform & Security (P3)

### H4.1 — Discord Channel (S:5, Dep: —) ✅
Bot Discord cu slash commands.
- `core/channels/discord.py` instanțiat + înregistrat în `web.py` când `DISCORD_BOT_TOKEN` e setat
**AC:** agent trimite mesaj pe channel Discord

### H4.2 — Email Channel (S:3, Dep: —) ✅
SMTP/IMAP — agent primește și trimite emailuri.
- `core/channels/email.py` instanțiat + înregistrat în `web.py` (gated pe credențiale SMTP/IMAP din env)
**AC:** „Trimite-mi raportul pe email" → trimis

### H4.3 — Slack Channel (S:3, Dep: Slack App) ✅
Pentru Raiffeisen context (stark monitor).
- `core/channels/slack.py` instanțiat + înregistrat în `web.py` când `SLACK_BOT_TOKEN` e setat
**AC:** Stark vede mențiuni Slack și raportează

### H4.4 — Ultron: Security Monitoring (S:8, Dep: Pi-hole + firewall) ✅
Firewall, Pi-hole logs, CVE-uri, traffic anomalies, audit trails.
- `skills/security_monitor/` — snapshot local-first: porturi LISTEN (psutil), device-uri ARP, Pi-hole, ufw/iptables, euristici threat. Toate sursele opționale, degradare grațioasă, zero network. (51 teste)
**AC:** „Ultron, status securitate?" → devices, open ports, threats ✅

### H4.5 — Steve: System Monitor (S:8, Dep: —) ✅
CPU/GPU/RAM/disk/temp Bonobo WS + Pi 5. Auto-recovery.
**AC:** „Steve, cum e sistemul?" → metrics + alerts

### H4.6 — Oracle: n8n Workflow Designer (S:5, Dep: n8n pornit) ✅
Conectare n8n API — creează/monitorizează workflow-uri.
- `core/plugins/n8n.py` — client async REST API v1 (list/create/activate workflows + `create_daily_weather_workflow`); `N8N_BASE_URL`/`N8N_API_KEY`; rezultat „not configured" curat când lipsesc. Înregistrat în orchestrator. (17 teste)
**AC:** „Oracle, creează workflow vreme zilnic" → workflow creat ✅

### H4.7 — MCP Client real (S:8, Dep: —) ✅
MCPManager conectat la MCP servers externe.
- ✅ Core client real: `core/mcp/client.py` — transport stdio/SSE, JSON-RPC (`initialize`/`list_tools`/`call_tool`), `MCPManager.connect_all`
- ✅ Admin wiring: REST CRUD endpoints + persistență settings DB + UI panel admin.js
- AC: MCP server adăugat din admin → disponibil ca plugin ✅

### H4.8 — Sandbox containerized (S:5, Dep: Docker) ✅
Sandbox cu Docker pentru execuție sigură de cod.
- `core/sandbox.py` + endpointuri `/sandbox/status` și `/sandbox/execute` (Python + shell), gated pe `DEV_MODE`
- Teste: `tests/test_sandbox_gating.py`
**AC:** „Steve, rulează acest Python" → container, output returnat

### H4.9 — Guardrails production (S:5, Dep: —) ✅
Mod `REDACT`, PII detection, prompt injection, output sanitization.
- `core/security/guardrails.py` — moduri `WARN`/`REDACT`/`BLOCK`, scannere `SecretScanner` + `PIIScanner`
- Wired în orchestrator + per-agent (`agent.guardrails`); `SecurityBlockError` pe BLOCK
- Notă: blocarea injection se face prin modul BLOCK pe input; nu există încă un scanner dedicat de prompt-injection (pattern-based)
**AC:** prompt injection → blocat; PII în output → redactat

### H4.10 — Admin: Charts & Audit (S:8, Dep: H3.1, H3.4) ✅
Grafice (latency, usage, success rate), audit log search, test LLM.
- ✅ `/api/admin/stats` endpoint cu per-agent metrics + daily timeseries + channel breakdown
- ✅ Admin UI panel (ChartsPage) cu SVG BarChart, Sparkline, StatsCard
- ✅ 5 teste endpoint (structură, agenți, ordonare zilnică, canale, erori)
**AC:** admin arată ultimele 100 interacțiuni, latență, succes rate ✅

### H4.11 — Context Caching + Hybrid Routing Metrics (S:5, Dep: H2.12) 🟡
Optimizare costuri și vizibilitate pentru Hybrid Router.
- ✅ **Task 1: Cost estimator module** — MODELS pricing table + estimate_cost/estimate_monthly (8 teste)
- ✅ **Task 2: Route tracking** — route_name pe InteractionRecord + orchestrator wiring (4 teste)
- ✅ **Task 3: Admin stats** — route_usage + cost_estimates în `/api/admin/stats` (2 teste)
- ✅ **Task 4: Gemini context cache** — ContextCache cu REST API + SQLite persistence (12 teste)
- 🔳 **Task 5: Wire caching** — cachedContent în GeminiBackend + orchestrator handle_input_stream
- 🔳 **Task 6: Token tracking** — token estimates + cache metadata în interaction records
- 🔳 **Task 7: Dashboard UI** — route distribution + cost cards în ChartsPage
- 🔳 **Task 8: Final verification** — full tests + BACKLOG update
- **Commits:** 6 (cost → fix cost → route tracking → admin stats → fix admin → cache module)
- **Branch:** `feat/context-cache`
- AC: sesiune de 50 mesaje → 80% tokeni citiți din cache. Admin arată grafic rute utilizate.

---

## Cross-Cutting

| Item | S | Dep | P | AC |
|------|---|-----|---|----|
| Session Manager thread-safe | 3 | — | P1 | ✅ | 2 sesiuni simultane nu se corup |
| Error taxonomy + logging structurat | 5 | — | P1 | ✅ |
| CHANGELOG.md | 1 | — | P1 | ✅ |
| Integration tests per agent | 15 (1/agent) | H2.x | P2 | ✅ `tests/test_agents_integration.py` — load SOUL + routabil + process cu LLM mock, parametrizat pe toți agenții activi |
| Plan per agent în `.opencode/plans/` | 15 | H2.x | P2 | skills, tools, memory definite per agent |
| Load test — 15 agenți simultan | 5 | H2.x | P3 | 15 requests paralele <30s total |

---

## Securitate (audit b703fc0 — sesiunea 4)

| ID | Fișier | Problemă | Status |
|----|--------|----------|--------|
| S1 | `web.py` `/api/admin/env` | Expunea tot `os.environ` (chei API, token-uri OAuth) | ✅ guard + mascare secrete |
| S2 | `web.py` toate `/api/admin/*` | Zero autentificare pe panoul admin | ✅ `_admin_guard`: token sau localhost-only |
| S3 | `websearch.py:90` | SSRF — `fetch_page` fără validare URL (IP-uri private, metadata cloud) | ✅ `check_ssrf` pre-fetch + re-check după redirect, `max_redirects=5` |
| S4 | `gemini.py` stream | (rămâne) stream fără `raise_for_status` | ✅ `raise_for_status` adăugat la stream |
| S-PKCE | `oauth.py` | OAuth fără PKCE, state needuat, token necriptat | ✅ PKCE + state verification + Fernet encryption |

## Bugs existente (din sesiunile anterioare)

| ID | Fișier | Problemă | Status |
|----|--------|----------|--------|
| B-8 | `admin.js:226` | `kind:"button"` → `onAction`; niciun setting nu e `button` | ✅ |
| IMP-5 | `admin.js` Toast | `key:Date.now()` anti-pattern React | ✅ |
| 2.2 | `app.js` | Race: poll 30s vs 10s suprascriu `sys` reciproc | ✅ |
| 5.4 | `orchestrator.py:382` | `intent.target_agents[0]` fragil | ✅ |
| W-6 | `index.html` | `data-density`/`data-scanline` nesetate deși CSS le suportă | ✅ |
| IMP-2 | `web.py` | Polling fără `Cache-Control`/`ETag` | ✅ |
| IMP-10 | `network.js` | SVG `<animate>` rulează și în tab ascuns | ✅ |
| W-7 | multiple | Stringuri RO hardcodate, fără i18n | ✅ |
| SCOPE-1 | `app.js:24` | `var _t = useState(...)` umbrește `window._t()` — pagină albă | ✅ |
| BUG-9 | `app.js` | SSE stream — `\n\n` split pe TCP chunk duce la mesaje duplicate | ✅ |
| new-4.6 | `web.py:618-622` | Table name interpolat în SQL f-string | ✅ |
| WARN-3 | `admin.js` | `AGENT_GLYPHS` duplicat între admin.js și data.js | ✅ (folosește `window.JARVIS_GLYPHS`) |
| WARN-8 | `admin.js` | Canale omit `discord`, `email`, `slack` | ✅ (toate 6 prezente) |
| WARN-9 | `app.js` | Fără indicator loading; mock persistă fără avertisment dacă API e down | ✅ (loading + apiDown există) |
| WARN-1 | `components.js`+`style.css` | `VoiceVisualizer` mort (~120 linii + 85 linii CSS) | ✅ (eliminat) |
| WARN-2 | `admin.js` | `SettingsPage` mort | ✅ (deja absent) |
| IMP-4 | `settings_db.py`+`web.py`+`admin.js` | `force=True` neexpus — adăugat endpoint + buton reseed | ✅ |

## Status General

| Horizon | Total items | ✅ Făcute | S total | S făcute | % complet | S rămase | Efort estimat |
|---------|------------|----------|---------|----------|-----------|----------|---------------|
| **H1 Foundation** (P0) | 5 | **5** | 26 | **26** | **100%** | 0 | — |
| **H2 Core Agent** (P1) | 12 | **10** | 76 | **63** | **83%** | 13 | ~1 săpt. |
| **H3 Intelligence** (P2) | 6 | **6** | 39 | **39** | **100%** | 0 | — |
| **H4 Platform** (P3) | 11 | **11** 🟡 | 63 | **58** | **92%** (H4.11 🟡 ~60%) | 5 | ~0.5 săpt. |
| **Cross-cutting** | 6 | **4** | 44 | **24** | **55%** | 20 | ~1 săpt. |
| **Securitate audit** | 5 | **5** | — | — | **100%** | 0 | — |
| **Bugfixes** | 17 | **17** | — | — | **100%** | 0 | — |
| **Sprint 0** (P0) | 3 | **3** | 7 | **7** | **100%** | 0 | — |
| **Total general** | **65** | **60** | **255** | **217** | **85%** | **38** | **~2.5 săpt.** |

**Echipă 3-4 agenți paralel:** H2+H3 ≈ 2-3 luni · Totul ≈ 3 luni (estimat)

---

## Resurse Necesare Per Item

### H2 — Core Agent Capabilities (P1) — 2/12 rămase (H2.6, H2.11 — blocate de API externe)

| Item | S | Dep | Resurse externe | Efort | Status |
|------|---|-----|-----------------|-------|--------|
| **H2.1** Pepper Calendar | 5 | H1.4 | Google Cloud Console → enable Calendar API, OAuth 2.0 Client ID. Gmail API deja activ. | ~2.5 zile | ✅ |
| **H2.2** Pepper Email Triage | 5 | H1.4 | Gmail API deja activ (H1.4). Token deja existent. | ~2.5 zile | ✅ |
| **H2.3** Friday Morning Brief | 8 | — | OpenWeatherMap API key (gratuit). NewsAPI key (gratuit). Polygon.io / Yahoo Finance (gratuit). | ~4 zile | ✅ |
| **H2.4** Hercules Apple Health | 5 | H1.4 | iOS shortcut → HTTP POST (deja existent `apple_health.py`). Niciun API key. | ~2.5 zile | ✅ |
| **H2.5** Jerome Spotify | 3 | H1.4 | Spotify Developer → Client ID + Secret. Redirect URI. Deja configurat în OAuth. | ~1.5 zile | ✅ |
| **H2.6** Gecko Balance | 8 | API bănci | ING API (sandbox/production). Libra API. Alternativă: spreadsheet export + CSV parser. | ~4 zile | 🔴 |
| **H2.7** Hephaestus PM | 8 | — | Zero API keys. SQLite-only (local). | ~4 zile | ✅ |
| **H2.8** Frigga Local Store | 8 | — | Zero API keys. SQLite-only. Zero network. | ~4 zile | ✅ |
| **H2.9** Vision Web Research | 5 | — | Tavily API key (recomandat, deja în .env). Fallback: SearXNG (docker) sau DuckDuckGo. | ~2.5 zile | ✅ |
| **H2.10** Veronica Drafting | 3 | — | Zero API keys. Prompt engineering + tone profiles în `agents.yaml`. | ~1.5 zile | ✅ |
| **H2.11** Stark GA4 | 5 | access API | Google Cloud → enable GA4 Data API + Firebase Analytics API. Service Account JSON. | ~2.5 zile | 🔴 |

### H3 — Intelligence & Memory (P2) — 0/6 rămase ✅

| Item | S | Dep | Resurse externe | Efort |
|------|---|-----|-----------------|-------|
| **H3.1** Qdrant Vector DB | 5 | Qdrant pornit | Docker: `docker run -p 6333:6333 qdrant/qdrant`. Zero API key. | ~2.5 zile | ✅ |
| **H3.2** Neo4j Knowledge Graph | 8 | Neo4j pornit | Docker: `docker run -p 7474:7474 -p 7687:7687 neo4j`. Zero API key (local). | ~4 zile | ✅ |
| **H3.3** Session Persistence | 5 | H3.1 | Zero resurse suplimentare. Cod-only. | ~2.5 zile | ✅ |
| **H3.4** Learning Loop live | 8 | H3.1, H3.3 | Zero resurse suplimentare. Cod-only. | ~4 zile | ✅ |
| **H3.5** Heartbeat System | 5 | — | Zero resurse suplimentare. APScheduler deja instalat. | ~2.5 zile | ✅ |
| **H3.6** Bench Activation | 8 | H3.4 | Zero resurse suplimentare. Cod-only. | ~4 zile | ✅ |

### H4 — Platform & Security (P3) — 1/11 rămase (H4.11)

| Item | S | Dep | Resurse externe | Efort | Status |
|------|---|-----|-----------------|-------|--------|
| **H4.1** Discord Channel | 5 | — | Discord Developer → Bot Token + Intents. | ~2.5 zile | ✅ |
| **H4.2** Email Channel | 3 | — | SMTP/IMAP credentials (gratuit). | ~1.5 zile | ✅ |
| **H4.3** Slack Channel | 3 | Slack App | Slack API → App + Bot Token + Scopes. | ~1.5 zile | ✅ |
| **H4.4** Ultron Security | 8 | Pi-hole + firewall | Zero API keys (citire log-uri locale). | ~4 zile | ✅ |
| **H4.5** Steve Monitor | 8 | — | Zero API keys (psutil local). | ~4 zile | ✅ |
| **H4.6** Oracle n8n | 5 | n8n pornit | n8n running (Docker sau local). API key din n8n settings. | ~2.5 zile | ✅ |
| **H4.7** MCP Client | 8 | — | Zero resurse externe (conectare MCP servers). | ~4 zile | ✅ |
| **H4.8** Sandbox Docker | 5 | Docker | Docker instalat. | ~2.5 zile | ✅ |
| **H4.9** Guardrails | 5 | — | Zero resurse suplimentare. Cod-only. | ~2.5 zile | ✅ |
| **H4.10** Admin Charts | 8 | H3.1, H3.4 | Zero resurse suplimentare. Cod-only. | ~4 zile | ✅ |
| **H4.11** Cache + Metrics | 5 | H2.12 | Gemini API (deja activ). Zero resurse suplimentare. | ~1 zi rămasă | 🟡 Tasks 1-4 ✅, 5-8 pending |

### Cross-cutting — 2/6 rămase

| Item | S | Dep | Resurse externe | Efort |
|------|---|-----|-----------------|-------|
| Plans per agent `.opencode/` | 15 | H2.x | Zero resurse. Documentație YAML. | ~1 săpt. |
| Load test 15 agenți | 5 | H2.x | Zero resurse. Script Python. | ~2.5 zile |

### Securitate hardening — 0/5 rămase ✅

Toate cele 5 (S1–S4 + S-PKCE) rezolvate — vezi tabelul „Securitate (audit b703fc0)" de mai sus.
S4 (`gemini.py` stream `raise_for_status`) ✅ și S-PKCE (`oauth.py` PKCE + state + Fernet) ✅.

---

## Dependențe Externe Necesare (Rezumat)

| Resursă | Pentru | Cost |
|---------|--------|------|
| Google Cloud OAuth 2.0 | H2.2 Pepper Gmail | Gratuit (quota standard) |
| Google GA4 Data API + Firebase | H2.11 Stark GA4 | Gratuit (quota standard) |
| Spotify Developer App | H2.5 Jerome Spotify ✅ | Gratuit |
| Tavily API | H2.9 Vision Research | Gratuit (1000 calls/lună) |
| ING / Libra API | H2.6 Gecko Balance | Depinde de acces |
| Discord Bot Token | H4.1 Discord | Gratuit |
| Slack App Token | H4.3 Slack | Gratuit |
| Docker (Qdrant, Neo4j, n8n) | H3.1, H3.2, H4.6 | Gratuit (deja instalat pe Pi 5) |
| n8n API Key | H4.6 Oracle | Gratuit |

**Total cost lunar:** $0 (toate serviciile au tier gratuit sufficient pentru uz personal)
