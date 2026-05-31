# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 181 tests (all passing)
```

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

### S0.2 — Heartbeat Sanity: intervale ≥60 min (S:2)
Heartbeat-uri curente la 5-15 min forțează reload constant.
- Steve (`* * * * *` → fiecare minut) → `0 */2 * * *` (la 2 ore)
- Ultron (`0 * * * *` → la oră) → `0 6,18 * * *` (de 2x/zi)
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

### H3.4 — Learning Loop live (S:8, Dep: H3.1, H3.3)
Analizează interacțiuni (succes/eșec), ajustează routing, promovează/demovează agenți.
**AC:** după 100 interacțiuni, sugerează promovare agent bench

### H3.5 — Heartbeat System (S:5, Dep: —) ✅
Cron scheduler (APScheduler) pentru jarvis 07:00, friday 06:30, pepper 20:00 Sunday.
**AC:** la 07:00 Jarvis face morning brief fără trigger manual

### H3.6 — Bench Agent Activation (S:8, Dep: H3.4)
Mecanism promovare when trigger îndeplinit (howard, bruce, wanda, etc.).
**AC:** 20 query-uri/lună către Vision → Bruce devine active

---

## ORIZONT 4: Platform & Security (P3)

### H4.1 — Discord Channel (S:5, Dep: —)
Bot Discord cu slash commands.
**AC:** agent trimite mesaj pe channel Discord

### H4.2 — Email Channel (S:3, Dep: —)
SMTP/IMAP — agent primește și trimite emailuri.
**AC:** „Trimite-mi raportul pe email" → trimis

### H4.3 — Slack Channel (S:3, Dep: Slack App)
Pentru Raiffeisen context (stark monitor).
**AC:** Stark vede mențiuni Slack și raportează

### H4.4 — Ultron: Security Monitoring (S:8, Dep: Pi-hole + firewall)
Firewall, Pi-hole logs, CVE-uri, traffic anomalies, audit trails.
**AC:** „Ultron, status securitate?" → devices, open ports, threats

### H4.5 — Steve: System Monitor (S:8, Dep: —) ✅
CPU/GPU/RAM/disk/temp Bonobo WS + Pi 5. Auto-recovery.
**AC:** „Steve, cum e sistemul?" → metrics + alerts

### H4.6 — Oracle: n8n Workflow Designer (S:5, Dep: n8n pornit)
Conectare n8n API — creează/monitorizează workflow-uri.
**AC:** „Oracle, creează workflow vreme zilnic" → workflow creat

### H4.7 — MCP Client real (S:8, Dep: —)
MCPManager conectat la MCP servers externe.
**AC:** MCP server adăugat din admin → disponibil ca plugin

### H4.8 — Sandbox containerized (S:5, Dep: Docker)
Sandbox cu Docker pentru execuție sigură de cod.
**AC:** „Steve, rulează acest Python" → container, output returnat

### H4.9 — Guardrails production (S:5, Dep: —)
Mod `REDACT`, PII detection, prompt injection, output sanitization.
**AC:** prompt injection → blocat; PII în output → redactat

### H4.10 — Admin: Charts & Audit (S:8, Dep: H3.1, H3.4)
Grafice (latency, usage, success rate), audit log search, test LLM.
**AC:** admin arată ultimele 100 interacțiuni, latență, succes rate

### H4.11 — Context Caching + Hybrid Routing Metrics (S:5, Dep: H2.12)
Optimizare costuri și vizibilitate pentru Hybrid Router.
- Context Caching API Gemini — reține istoricul sesiunii pe serverele Google (discount 75-90%)
- Auto-extindere cache pe măsură ce conversația crește
- Dashboard metrics: route folosit per request (local vs cloud flash vs cloud pro)
- Cost tracking: tokeni consumați per sesiune/lună
- AC: sesiune de 50 mesaje → 80% tokeni citiți din cache. Admin arată grafic rute utilizate.

---

## Cross-Cutting

| Item | S | Dep | P | AC |
|------|---|-----|---|----|
| Session Manager thread-safe | 3 | — | P1 | ✅ | 2 sesiuni simultane nu se corup |
| Error taxonomy + logging structurat | 5 | — | P1 | ✅ |
| CHANGELOG.md | 1 | — | P1 | ✅ |
| Integration tests per agent | 15 (1/agent) | H2.x | P2 | fiecare agent are test end-to-end |
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
| **H3 Intelligence** (P2) | 6 | **3** | 39 | **18** | **46%** | 21 | ~1.5 săpt. |
| **H4 Platform** (P3) | 11 | **1** | 63 | **8** | **13%** | 55 | ~3.5 săpt. (paralel 3) |
| **Cross-cutting** | 6 | **3** | 44 | **9** | **21%** | 35 | ~2 săpt. |
| **Securitate audit** | 5 | **5** | — | — | **100%** | 0 | — |
| **Bugfixes** | 17 | **17** | — | — | **100%** | 0 | — |
| **Sprint 0** (P0) | 3 | **3** | 7 | **7** | **100%** | 0 | — |
| **Total general** | **65** | **47** | **255** | **131** | **51%** | **124** | **~7.5 săpt.** |

**Echipă 3-4 agenți paralel:** H2+H3 ≈ 2-3 luni · Totul ≈ 3 luni (estimat)

---

## Resurse Necesare Per Item

### H2 — Core Agent Capabilities (P1) — 4/12 rămase

| Item | S | Dep | Resurse externe | Efort | Status |
|------|---|-----|-----------------|-------|--------|
| **H2.1** Pepper Calendar | 5 | H1.4 | Google Cloud Console → enable Calendar API, OAuth 2.0 Client ID. Gmail API deja activ. | ~2.5 zile | ✅ |
| **H2.2** Pepper Email Triage | 5 | H1.4 | Gmail API deja activ (H1.4). Token deja existent. | ~2.5 zile | 🔜 |
| **H2.3** Friday Morning Brief | 8 | — | OpenWeatherMap API key (gratuit). NewsAPI key (gratuit). Polygon.io / Yahoo Finance (gratuit). | ~4 zile | ✅ |
| **H2.4** Hercules Apple Health | 5 | H1.4 | iOS shortcut → HTTP POST (deja existent `apple_health.py`). Niciun API key. | ~2.5 zile | ✅ |
| **H2.5** Jerome Spotify | 3 | H1.4 | Spotify Developer → Client ID + Secret. Redirect URI. Deja configurat în OAuth. | ~1.5 zile | ✅ |
| **H2.6** Gecko Balance | 8 | API bănci | ING API (sandbox/production). Libra API. Alternativă: spreadsheet export + CSV parser. | ~4 zile | 🔴 |
| **H2.7** Hephaestus PM | 8 | — | Zero API keys. SQLite-only (local). | ~4 zile | ✅ |
| **H2.8** Frigga Local Store | 8 | — | Zero API keys. SQLite-only. Zero network. | ~4 zile | ✅ |
| **H2.9** Vision Web Research | 5 | — | Tavily API key (recomandat, deja în .env). Fallback: SearXNG (docker) sau DuckDuckGo. | ~2.5 zile | 🔜 |
| **H2.10** Veronica Drafting | 3 | — | Zero API keys. Prompt engineering + tone profiles în `agents.yaml`. | ~1.5 zile | ✅ |
| **H2.11** Stark GA4 | 5 | access API | Google Cloud → enable GA4 Data API + Firebase Analytics API. Service Account JSON. | ~2.5 zile | 🔴 |

### H3 — Intelligence & Memory (P2) — 6/6 rămase

| Item | S | Dep | Resurse externe | Efort |
|------|---|-----|-----------------|-------|
| **H3.1** Qdrant Vector DB | 5 | Qdrant pornit | Docker: `docker run -p 6333:6333 qdrant/qdrant`. Zero API key. | ~2.5 zile |
| **H3.2** Neo4j Knowledge Graph | 8 | Neo4j pornit | Docker: `docker run -p 7474:7474 -p 7687:7687 neo4j`. Zero API key (local). | ~4 zile |
| **H3.3** Session Persistence | 5 | H3.1 | Zero resurse suplimentare. Cod-only. | ~2.5 zile |
| **H3.4** Learning Loop live | 8 | H3.1, H3.3 | Zero resurse suplimentare. Cod-only. | ~4 zile |
| **H3.5** Heartbeat System | 5 | — | Zero resurse suplimentare. APScheduler deja instalat. | ~2.5 zile |
| **H3.6** Bench Activation | 8 | H3.4 | Zero resurse suplimentare. Cod-only. | ~4 zile |

### H4 — Platform & Security (P3) — 11/11 rămase

| Item | S | Dep | Resurse externe | Efort |
|------|---|-----|-----------------|-------|
| **H4.1** Discord Channel | 5 | — | Discord Developer → Bot Token + Intents. | ~2.5 zile |
| **H4.2** Email Channel | 3 | — | SMTP/IMAP credentials (gratuit). | ~1.5 zile |
| **H4.3** Slack Channel | 3 | Slack App | Slack API → App + Bot Token + Scopes. | ~1.5 zile |
| **H4.4** Ultron Security | 8 | Pi-hole + firewall | Zero API keys (citire log-uri locale). | ~4 zile |
| **H4.5** Steve Monitor | 8 | — | Zero API keys (psutil local). | ~4 zile | ✅ |
| **H4.6** Oracle n8n | 5 | n8n pornit | n8n running (Docker sau local). API key din n8n settings. | ~2.5 zile |
| **H4.7** MCP Client | 8 | — | Zero resurse externe (conectare MCP servers). | ~4 zile |
| **H4.8** Sandbox Docker | 5 | Docker | Docker instalat. | ~2.5 zile |
| **H4.9** Guardrails | 5 | — | Zero resurse suplimentare. Cod-only. | ~2.5 zile |
| **H4.10** Admin Charts | 8 | H3.1, H3.4 | Zero resurse suplimentare. Cod-only. | ~4 zile |
| **H4.11** Cache + Metrics | 5 | H2.12 | Gemini API (deja activ). Zero resurse suplimentare. | ~2.5 zile |

### Cross-cutting — 4/6 rămase

| Item | S | Dep | Resurse externe | Efort |
|------|---|-----|-----------------|-------|
| Session Manager thread-safe | 3 | — | Cod-only. | ~1.5 zile |
| Integration tests per agent | 15 | H2.x | Zero resurse. Teste Python. | ~1 săpt. |
| Plans per agent `.opencode/` | 15 | H2.x | Zero resurse. Documentație YAML. | ~1 săpt. |
| Load test 15 agenți | 5 | H2.x | Zero resurse. Script Python. | ~2.5 zile |

### Securitate hardening — 2/5 rămase

| ID | Fișier | S | Resurse | Efort |
|----|--------|---|---------|-------|
| **S4** | `gemini.py` stream | ~1 | Cod-only (`raise_for_status` pe stream) | ~0.5 zi |
| **S-PKCE** | `oauth.py` | ~3 | pkce library sau manual SHA256. Token encryption: `cryptography` sau `fernet`. | ~1.5 zile |

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
