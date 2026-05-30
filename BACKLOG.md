# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v          # 130 tests (all passing)
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

## ORIZONT 2: Core Agent Capabilities (P1)

### H2.12 — Hybrid LLM Router: Local Gemma 4 ↔ Gemini API (S:13) ✅
Router inteligent care alege backend-ul optim per request: local (LM Studio) sau cloud (Gemini API).

**Arhitectură multi-factor:**
1. **Token Budget** — estimează contextul înainte de rutare:
   - `< 8K tokeni` → **LM Studio** (Gemma 4) — rapid, privat, 0 latență
   - `8K – 128K` → **Gemini 2.5 Flash** — context mediu, cost redus
   - `> 128K` → **Gemini Pro** — context masiv
2. **Agent Policy** — Frigga/Ultron local-only, Vision/Athena cloud-only, rest auto
3. **Graceful degradation** — cloud down → fallback local; local down → try cloud; ambele down → RuntimeError
4. **Per-agent routing** — fiecare request alege backend-ul după agent policy + token count

**Componente:**
- `agents/core/llm/gemini.py` — Backend Gemini (generate + generate_stream)
- `agents/core/llm/hybrid_router.py` — Router cu decizie multi-factor (extinde LLMRouter)
- `agents/core/llm/tokenizer.py` — Estimator tokeni (tiktoken cl100k_base → char fallback)
- `agents/core/plugins/cloud_llm.py` — Extins cu suport Gemini API
- `GEMINI_API_KEY` + `gemini_model`/`hybrid_local_max`/`hybrid_flash_max` în `.env` + settings DB
- `agents.yaml` — `llm_policy: local` (Frigga), `llm_policy: cloud` (Vision, Athena)

### H2.1 — Pepper: Google Calendar Integration (S:5, Dep: H1.4)
Skill `calendar-manager` — citește, crează, modifică evenimente.
**AC:** „Pepper, adaugă meeting mâine 10-11" → eveniment creat în Google Calendar

### H2.2 — Pepper: Email Triage Gmail (S:5, Dep: H1.4)
Citește etichete Gmail, prioritizează, sugerează acțiuni.
**AC:** „Pepper, ce e nou în inbox?" → listă scurtă priorizată

### H2.3 — Friday: Morning Brief Pipeline (S:8, Dep: —)
Colectează vreme + știri + piață zilnic la 06:30, livrează la 07:00.
**AC:** briefing complet structurat la cerere

### H2.4 — Hercules: Apple Health Data Loop (S:5, Dep: H1.4)
Sleep/HRV/HR/steps/workouts din `apple_health.py` + pattern detection.
**AC:** „Hercules, cum am dormit?" → durată, calitate, trend 7 zile

### H2.5 — Jerome: Spotify Control (S:3, Dep: H1.4)
Play/pause/skip/queue + playlist suggestion.
**AC:** „Jerome, pune ceva focus" → track din library cu tag „focus"

### H2.6 — Gecko: Balance Reader (S:8, Dep: API bănci)
Solduri ING + Libră (API sau spreadsheet sync), burn rate, runway.
**AC:** „Gecko, câți bani am în cont?" → sumă exactă cu valută

### H2.7 — Hephaestus: Project Manager (S:8, Dep: —)
Project tracker Cosmina (faze, termene, contractori) + BMW E93 (piese, service).
**AC:** „Hephaestus, status Cosmina?" → fază, milestone, blockeri

### H2.8 — Frigga: Local Data Store (S:8, Dep: —)
SQLite local pentru Max (somn/HRV/mâncare/vaccinuri), Alexandra (B&B), pisici.
**AC:** „Frigga, cât a dormit Max?" → ore, calitate, trend. Zero external network.

### H2.9 — Vision: Web Research + OSINT (S:5, Dep: —)
Căutări web, extrage conținut, sumarizează cu citări (firecrawl sau similar).
**AC:** „Vision, cercetează piața MarTech CEE" → raport structurat cu surse

### H2.10 — Veronica: Content Drafting (S:3, Dep: —)
Drafturi LinkedIn, Digitaholic blog, email în ton specificat.
**AC:** „Veronica, scrie un post LinkedIn despre AI în banking" → draft complet

### H2.11 — Stark: GA4 + Firebase (S:5, Dep: access API)
Conectare GA4 API și Firebase Analytics. Raportează KPIs.
**AC:** „Stark, cum a performat campania Q2?" → metrics vs target

---

## ORIZONT 3: Intelligence & Memory (P2)

### H3.1 — Memory: Qdrant Vector DB (S:5, Dep: Qdrant pornit)
Conversații indexate semantic, căutare similaritate.
**AC:** „Ce am discutat despre Cosmina luna trecută?" → găsește și rezumă

### H3.2 — Memory: Neo4j Knowledge Graph (S:8, Dep: Neo4j pornit)
Entități, relații, fapte persistate. Scrie pe confirmare explicită.
**AC:** „Unde lucrează Andrei?" → răspunde din graph

### H3.3 — Session Persistence (S:5, Dep: H3.1)
Salvează/restaurează sesiuni cross-channel.
**AC:** mesaj pe web → întrerup → întreb pe Telegram → același context

### H3.4 — Learning Loop live (S:8, Dep: H3.1, H3.3)
Analizează interacțiuni (succes/eșec), ajustează routing, promovează/demovează agenți.
**AC:** după 100 interacțiuni, sugerează promovare agent bench

### H3.5 — Heartbeat System (S:5, Dep: —)
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

### H4.5 — Steve: System Monitor (S:8, Dep: —)
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
| Session Manager thread-safe | 3 | — | P1 | 2 sesiuni simultane nu se corup |
| Error taxonomy + logging structurat | 5 | — | P1 | ✅ |
| CHANGELOG.md | 1 | — | P1 | ✅ |
| Integration tests per agent | 15 (1/agent) | H2.x | P2 | fiecare agent are test end-to-end |
| Plan per agent în `.opencode/plans/` | 15 | H2.x | P2 | skills, tools, memory definite per agent |
| Load test — 15 agenți simultan | 5 | H2.x | P3 | 15 requests paralele <30s total |

---

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

## Summary

| Horizon | Items | Total S | P0 | P1 | P2 | P3 |
|---------|-------|---------|----|----|----|----|
| H1 Foundation | 5 | 26 | 5 ✅ | — | — | — |
| H2 Core Agent | 12 | 76 | 1 | 11 | — | — |
| H3 Intelligence | 6 | 39 | — | — | 6 | — |
| H4 Platform | 11 | 63 | — | — | — | 11 |
| Cross-cutting | 6 | 44 | — | 3 | 2 | 1 |
| **Total** | **40** | **248** | **1** | **14** | **8** | **12** |

**Echipă 3-4 agenți paralel:** H2+H3 ≈ 2-3 luni · Totul ≈ 4 luni
