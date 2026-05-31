# Jarvis Hub v0.5-beta — Feature Reference

> Cum folosești și testezi fiecare feature. Toate presupun serverul pornit (`python serve.py`).

---

## Foundation

### Voice Channel
- **Ce face:** Wake word → Whisper STT → orchestrator → Kokoro TTS → speaker
- **Test:** `python tests/test_voice.py -v`
- **Folosire:** Vorbești wake word-ul, apoi comanda. Răspunsul e citit cu voce.

### Telegram Channel
- **Ce face:** Bot Telegram cu webhook + polling, inbound → orchestrator
- **Test:** `python tests/test_telegram.py -v`
- **Folosire:** Mesajezi botul pe Telegram, răspunde în același chat.

### Web Channel (HUD)
- **Ce face:** Chat UI la `http://localhost:8080/` cu SSE streaming
- **Test:** Deschide browser-ul, scrie un mesaj. Vezi stream-ul de tokeni.
- **Settings:** `llm.temperature`, `llm.max_tokens`, `llm.default_model` în admin panel

### OAuth (Google Calendar, Gmail, Spotify)
- **Ce face:** `/api/oauth/auth-url` → redirect Google → token salvat în `memory_logs/tokens/`
- **Test:** `python tests/test_oauth.py -v`
- **Folosire:** Admin panel → OAuth → authorize. Token-ul se reîmprospătează automat.

### Admin Panel
- **URL:** `http://localhost:8080/admin`
- **Ce face:** Settings DB (toggles, text, numbers, selects), env vars (mascate), OAuth status, charts

---

## Agents

### H2.1 Pepper — Calendar
- **Test:** `python tests/test_calendar.py -v`
- **Exemplu:** "Pepper, adaugă meeting mâine 10-11 cu echipa"

### H2.2 Pepper — Gmail
- **Test:** `python tests/test_gmail.py -v`
- **Exemplu:** "Pepper, ce e nou în inbox?"

### H2.3 Friday — Morning Brief
- **Test:** `python tests/test_friday.py -v`
- **Exemplu:** "Friday, dă-mi briefing-ul de azi"

### H2.4 Hercules — Health Data
- **Test:** `python tests/test_apple_health.py -v`
- **Exemplu:** "Hercules, cum am dormit?"

### H2.5 Jerome — Spotify
- **Test:** `python tests/test_spotify_skill.py -v`
- **Exemplu:** "Jerome, pune ceva focus"

### H2.6 Gecko — Balance Reader
- **Test:** `python tests/test_balance.py -v`
- **Exemplu:** "Gecko, câți bani am?"
- **Notă:** Returnează mock data dacă nu sunt configurate API keys în Admin → Plugins

### H2.7 Hephaestus — PM
- **Test:** `python tests/test_hephaestus.py -v`
- **Exemplu:** "Hephaestus, status Cosmina?"

### H2.8 Frigga — Family Data
- **Test:** `python tests/test_frigga.py -v`
- **Exemplu:** "Frigga, cât a dormit Max?"
- **Notă:** Zero network. Totul în SQLite local.

### H2.9 Vision — Web Research
- **Test:** `python tests/test_vision.py -v`
- **Exemplu:** "Vision, cercetează piața MarTech CEE"

### H2.10 Veronica — Drafting
- **Test:** `python tests/test_veronica.py -v`
- **Exemplu:** "Veronica, scrie un post LinkedIn despre AI în banking"

### H2.11 Stark — Analytics
- **Test:** `python tests/test_analytics.py -v`
- **Exemplu:** "Stark, cum a performat campania Q2?"
- **Notă:** Returnează mock KPIs fără GA4 Service Account configurat

### H2.12 — Hybrid LLM Router
- **Ce face:** Alege automat între local (LM Studio), Gemini API sau Claude API per request
- **Test:** `python tests/test_hybrid_router.py -v`
- **Policy:** Frigga/Ultron → local-only; Vision/Athena → cloud; rest → auto (token budget)

---

## Intelligence & Memory (H3)

### Qdrant Vector DB
- **Test:** `python tests/test_qdrant.py -v`
- **Exemplu:** "Ce am discutat despre Cosmina luna trecută?"
- **Require:** Docker cu `qdrant/qdrant` pe port 6333

### Neo4j Knowledge Graph
- **Test:** `python tests/test_neo4j.py -v`
- **Exemplu:** "Unde lucrează Andrei?"
- **Require:** Docker cu `neo4j` pe port 7474

### Session Persistence
- **Test:** `python tests/test_session_persistence.py -v`
- **Cross-channel:** `python tests/test_cross_channel_sessions.py -v`
- **Folosire:** Mesaj pe web → întrerupi → întrebi pe Telegram → același context (cu flag `memory.cross_channel_sessions = true`)

### Learning Loop
- **Test:** `python tests/test_learning_live.py -v`
- **Endpoint:** `GET /learning` — vezi health scores și promotion suggestions
- **Auto-promovare:** `POST /learning/promote` (admin) — promovează un agent bench

### Heartbeat System
- **Ce face:** APScheduler rulează agenți la ore configurate (Jarvis 07:00, Friday 06:30, etc.)
- **Test:** Verifică log-urile la orele respective

### Bench Activation
- **Test:** `python tests/test_bench_activation.py -v`
- **Endpoint:** `POST /learning/promote` (cu `_admin_guard`)

---

## Platform & Security (H4)

### Discord, Email, Slack Channels
- **Test:** `python tests/test_channels.py -v`
- **Require:** Token-uri în `.env` (`DISCORD_BOT_TOKEN`, SMTP/IMAP, `SLACK_BOT_TOKEN`)

### Ultron Security Monitor
- **Test:** `python tests/test_security.py -v`
- **Exemplu:** "Ultron, status securitate?"
- **Ce verifică:** Porturi LISTEN, device-uri ARP, Pi-hole stats, threat euristics

### Steve System Monitor
- **Test:** `python tests/test_system.py -v`
- **Exemplu:** "Steve, cum e sistemul?"
- **Ce verifică:** CPU/GPU/RAM/disk/temp + auto-recovery alerts

### Oracle n8n
- **Test:** `python tests/test_n8n.py -v`
- **Exemplu:** "Oracle, creează workflow vreme zilnic"
- **Require:** `N8N_BASE_URL` + `N8N_API_KEY` în `.env`

### MCP Client
- **Test:** `python tests/test_mcp.py -v`
- **Folosire:** Admin panel → MCP → Add server → disponibil ca plugin imediat

### Sandbox Docker
- **Test:** `python tests/test_sandbox_gating.py -v`
- **Exemplu:** "Steve, rulează acest Python" (cu `DEV_MODE=true`)
- **Endpoint:** `POST /sandbox/execute`

### Guardrails
- **Test:** `python tests/test_guardrails.py -v`
- **Ce face:** Detectează PII, secrete, prompt injection → WARN/REDACT/BLOCK

### Admin Charts
- **Endpoint:** `GET /api/admin/stats`
- **UI:** Admin panel → Charts tab — per-agent metrics, daily timeseries, route distribution, cost estimates

### Context Cache (Gemini)
- **Test:** `python tests/test_cache.py -v`
- **Ce face:** Token caching pentru Gemini API → reduce cost cu ~80% pe sesiuni lungi

---

## Run All Tests

```bash
# All features
python -m pytest tests/ -q

# Specific feature
python -m pytest tests/test_<name>.py -v

# Load test (15 agents parallel)
python -m pytest tests/test_load.py -v

# Smoke
powershell smoke.ps1
```
