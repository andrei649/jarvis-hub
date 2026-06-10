# Prompt-uri pentru Implementare Feature-uri — Andrei's Cabinet

**Generat:** 30 Mai 2026  
**Versiune:** 0.2.1 → 0.3.0  
**Scop:** Prompt-uri gata de utilizat pentru agenți AI (Claude, Codex, etc.) pentru implementarea feature-urilor prioritare.

---

## Cum să Folosești Aceste Prompt-uri

1. **Alege feature-ul** din cuprinsul de mai jos
2. **Copiază prompt-ul** complet (inclusiv contextul)
3. **Adaugă la început:** "Ești un expert Python/FastAPI/React. Implementează următorul feature pentru proiectul Cabinet/Jarvis:"
4. **Specifică modelul** recomandat (Claude Sonnet pentru code-heavy, Gemini pentru research)
5. **Iterează** pe baza output-ului

---

## Cuprins

### Sprint 1 — Impact Imediat (1-2 săptămâni)
1. [Cloud LLM Setup Complet](#1-cloud-llm-setup-complet)
2. [Finalizare Canale Secundare (Discord/Email/Slack)](#2-finalizare-canale-secundare-discordemailslack)
3. [OAuth Token Management UI](#3-oauth-token-management-ui)
4. [Dashboard Metrics în Timp Real](#4-dashboard-metrics-în-timp-real)

### Sprint 2 — Foundation Inteligență (2-4 săptămâni)
5. [Qdrant Vector DB Deployment](#5-qdrant-vector-db-deployment)
6. [Neo4j Knowledge Graph](#6-neo4j-knowledge-graph)
7. [Learning Loop Production](#7-learning-loop-production)
8. [Context Caching Gemini API](#8-context-caching-gemini-api)

### Sprint 3 — Platform Maturity (1-2 luni)
9. [Advanced Analytics Dashboard](#9-advanced-analytics-dashboard)
10. [n8n Workflow Integration](#10-n8n-workflow-integration)
11. [Multi-User Support](#11-multi-user-support)

### Sprint 4 — Productizare (2-3 luni)
12. [Desktop App (Tauri)](#12-desktop-app-tauri)
13. [Mobile App (React Native)](#13-mobile-app-react-native)
14. [Model Fine-tuning (LoRA)](#14-model-fine-tuning-lora)

### Sprint 5 — Advanced
15. [Voice Cloning (XTTS)](#15-voice-cloning-xtts)
16. [Advanced Guardrails (REDACT mode)](#16-advanced-guardrails-redact-mode)
17. [MCP Server Integration](#17-mcp-server-integration)

---

## Sprint 1 — Impact Imediat

### 1. Cloud LLM Setup Complet

**Prioritate:** ⭐⭐⭐⭐⭐ (Critic)  
**Efort estimat:** 0.5 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Anthropic API key, Gemini API key

**Context:**
Sistemul are HybridRouter care suportă Claude API și Gemini API, dar acestea nu sunt configurate complet. Agenții grei (Vision, Steve) necesită Claude pentru research profund și debugging. Fără API keys, sistemul fallback la local (qwen3:7b) care e limitat pentru task-uri complexe.

**Prompt:**

```
Ești un expert Python cu experiență în integrarea API-urilor LLM (Anthropic Claude, Google Gemini). Lucrezi la proiectul "Andrei's Cabinet" — un sistem multi-agent AI cu 15 agenți specializați.

CONTEXT PROIECT:
- Repository: /home/iulian/proiecte/Para/cabinet
- LLM Router: agents/core/llm/hybrid_router.py
- Claude Backend: agents/core/llm/anthropic.py
- Gemini Backend: agents/core/llm/gemini.py
- Config: agents/_system/agents.yaml
- Environment: .env (nu e versionat)

STARE ACTUALĂ:
- HybridRouter detectează automat LM Studio → Ollama → Cloud
- CLAUDE_AGENTS = {"vision", "steve"} în hybrid_router.py
- POLICY_CLAUDE pentru agenții grei
- Dar: API keys nu sunt documentate clar, nu există ghid de setup

CE TREBUIE FĂCUT:

1. Actualizează `.env.example` cu toate variabilele necesare:
   - ANTHROPIC_API_KEY=sk-ant-...
   - GEMINI_API_KEY=...
   - Comentarii clare pentru fiecare (de unde se obțin, ce permisiuni necesită)

2. Creează un ghid de setup `docs/CLOUD_LLM_SETUP.md` cu:
   - Pași detaliați pentru obținerea API keys (Anthropic Console, Google Cloud Console)
   - Cost estimates (Claude: $X/1M tokens, Gemini: $Y/1M tokens)
   - Cum să testezi că funcționează (comenzi curl)
   - Troubleshooting (erori comune: 401, 403, rate limits)

3. Actualizează `agents/core/llm/anthropic.py`:
   - Adaugă logging detaliat la inițializare
   - Adaugă retry logic cu exponential backoff (max 3 retry-uri)
   - Adaugă timeout configurabil (default 60s)
   - Gestionează corect `reasoning_content` pentru modelele cu extended thinking

4. Actualizează `agents/core/llm/gemini.py`:
   - Aceleași îmbunătățiri ca la Anthropic (logging, retry, timeout)
   - Adaugă support pentru context caching (discount 75-90%)
   - Gestionează streaming corect

5. Actualizează `agents/_system/agents.yaml`:
   - Setează explicit `llm_policy: claude` pentru vision și steve
   - Adaugă comentarii care explică de ce acești agenți necesită cloud

6. Creează un script de test `tests/test_cloud_llm.py`:
   - Testează Claude API call (simple Q&A)
   - Testează Gemini API call
   - Testează fallback behavior când API key lipsește
   - Măsoară latența (trebuie să fie <5s pentru ambele)

7. Actualizează `README.md` cu o secțiune "Cloud LLM Setup":
   - Link către docs/CLOUD_LLM_SETUP.md
   - Comenzi rapide de test
   - Expected output

RESTRICȚII:
- Nu modifica logica de routing din hybrid_router.py (funcționează corect)
- Păstrează backward compatibility (sistemul trebuie să meargă și fără cloud keys)
- Folosește httpx async pentru toate call-urile HTTP
- Toate erorile trebuie logate cu logger-ul dedicat

OUTPUT AȘTEPTAT:
- Toate fișierele modificate/create listate
- Cod complet, gata de commit
- Instrucțiuni de test în fiecare fișier nou
- Commit message sugestiv la final

TEST CRITERIA:
- `python -m pytest tests/test_cloud_llm.py -v` trebuie să treacă
- `curl http://localhost:8000/chat -d '{"agent":"vision","message":"test"}'` trebuie să returneze răspuns de la Claude
- Latența medie <5s pentru cloud calls
```

---

### 2. Finalizare Canale Secundare (Discord/Email/Slack)

**Prioritate:** ⭐⭐⭐⭐  
**Efort estimat:** 1 zi  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Discord Bot Token, SMTP/IMAP credentials, Slack Bot Token

**Context:**
Canalele Discord, Email și Slack au implementarea code-level dar nu sunt configurate/testate complet. Acestea extind reach-ul sistemului la 6 canale totale.

**Prompt:**

```
Ești un expert Python cu experiență în bot development (Discord.py, Slack Bolt, SMTP/IMAP). Lucrezi la proiectul "Andrei's Cabinet" — sistem multi-agent AI.

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Canale existente: agents/core/channels/{discord,email,slack}.py
- Base adapter: agents/core/channels/base.py
- Gateway: agents/core/channels/gateway.py
- Web server: agents/web.py

STARE ACTUALĂ:
- DiscordChannel: Cod present, nu e testat cu bot real
- EmailChannel: SMTP/IMAP implementate, nu e testat cu credentials reale
- SlackChannel: Bolt bot ready, nu e deploy-at
- Toate 3 lipsesc din web.py startup sequence

CE TREBUIE FĂCUT:

PARTEA 1: Discord Channel

1. Actualizează `agents/core/channels/discord.py`:
   - Implementează corect `start()` — inițializare client Discord.py
   - Implementează `stop()` — cleanup graceful
   - Implementează `send(message, **kwargs)` — trimite mesaj pe channel
   - Adaugă slash commands: /jarvis ask, /friday brief, /status
   - Gestionează voice channels (opțional — STT prin Whisper)
   - Session isolation per channel_id (ca la Telegram)

2. Actualizează `agents/web.py`:
   - Adaugă Discord channel la startup (dacă DISCORD_BOT_TOKEN e setat)
   - Logging clar: "Discord channel wired" sau "Discord disabled — no token"

3. Creează `docs/DISCORD_SETUP.md`:
   - Cum să creezi Discord App pe Discord Developer Portal
   - Cum să inviți bot-ul pe server
   - Permisiuni necesare (Send Messages, Read Message History, etc.)
   - Cum să obții BOT_TOKEN
   - Exemple de slash commands

PARTEA 2: Email Channel

4. Actualizează `agents/core/channels/email.py`:
   - Implementează `start()` — IMAP idle listening (polling la 30s)
   - Implementează `stop()` — close connections
   - Implementează `send(message, to, subject, **kwargs)` — SMTP send
   - Parsează email-uri incoming → trimite la orchestrator
   - Session isolation per email address

5. Actualizează `agents/web.py`:
   - Adaugă Email channel la startup (dacă SMTP_HOST și IMAP_HOST sunt setate)

6. Creează `docs/EMAIL_SETUP.md`:
   - Config pentru Gmail (App Password required)
   - Config pentru Outlook/Office365
   - Config pentru SMTP custom (ex: SendGrid, Mailgun)
   - Security best practices (nu folosi password-ul principal, folosește App Password)

PARTEA 3: Slack Channel

7. Actualizează `agents/core/channels/slack.py`:
   - Implementează Slack Bolt app
   - Adaugă slash commands: /jarvis, /friday, /stark
   - Adaugă event listener pentru mentions (@jarvis)
   - Session isolation per channel_id
   - Thread support (răspunde în thread-ul original)

8. Actualizează `agents/web.py`:
   - Adaugă Slack channel la startup (dacă SLACK_BOT_TOKEN e setat)

9. Creează `docs/SLACK_SETUP.md`:
   - Cum să creezi Slack App
   - Scopes necesare (chat:write, commands, mentions)
   - Cum să obții BOT_TOKEN
   - Cum să configurezi slash commands

PARTEA 4: Testing

10. Creează `tests/test_channels_secondary.py`:
    - Test Discord: mock Discord client, verify send/receive
    - Test Email: mock SMTP/IMAP, verify send/receive
    - Test Slack: mock Slack client, verify slash commands
    - Toate testele trebuie să treacă fără credentials reale (mock-uri)

11. Actualizează `smoke.ps1`:
    - Verifică că serverul pornește și cu canalele secundare
    - Verifică că nu sunt import errors

RESTRICȚII:
- Folosește discord.py==2.3.2 (async)
- Folosește slack-bolt==1.18.0
- Pentru email, folosește aiosmtpă și imap_tools async
- Toate canalele trebuie să fie opționale (nu crapa dacă token lipsește)
- Session isolation e critică (nu amesteca conversații între users)

OUTPUT AȘTEPTAT:
- Toate fișierele modificate/create
- Cod complet, gata de commit
- Documentație clară pentru fiecare canal
- Teste care trec
- Commit message sugestiv

TEST CRITERIA:
- Serverul pornește fără erori chiar dacă niciun token nu e setat
- Când token-urile sunt setate, toate 3 canalele se inițializează
- Slash commands răspund în <3s
- `python -m pytest tests/test_channels_secondary.py -v` trece
```

---

### 3. OAuth Token Management UI

**Prioritate:** ⭐⭐⭐⭐  
**Efort estimat:** 1 zi  
**Model recomandat:** Claude Sonnet 4 (bun la React + backend)  
**Dependențe:** None (folosește infrastructura existentă)

**Context:**
OAuth tokens pentru Gmail, Spotify, Calendar expiră și necesită re-auth manual. Utilizatorii nu vor să debug OAuth în terminal. E nevoie de o pagină în admin panel care să arate status-ul token-urilor și să permită re-auth cu un click.

**Prompt:**

```
Ești un expert full-stack (Python FastAPI + React vanilla) cu experiență în OAuth flows. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Backend: agents/web.py (FastAPI)
- Admin panel: agents/web/templates/admin.html (React vanilla, fără JSX)
- OAuth module: agents/core/plugins/oauth.py
- Token storage: memory_logs/tokens/{provider}.json
- Providers: google (Gmail+Calendar), spotify

STARE ACTUALĂ:
- OAuth flow implementat în backend (auth URL, code exchange, refresh)
- Endpoints existente: GET /api/oauth/status, GET /api/oauth/callback/:provider
- Token-urile expiră și utilizatorul trebuie să facă re-auth manual prin terminal
- Nu există UI pentru a vedea status-ul token-urilor

CE TREBUIE FĂCUT:

PARTEA 1: Backend Endpoints

1. Actualizează `agents/web.py`:
   - Adaugă endpoint nou: GET /api/oauth/providers → returnează listă providers cu status
   - Adaugă endpoint nou: POST /api/oauth/revoke/:provider → revocă token (șterge fișierul)
   - Actualizează GET /api/oauth/status să includă:
     * provider name
     * token status (valid/expired/missing)
     * expiry timestamp (dacă există)
     * scopes granted
     * last refreshed timestamp

2. Actualizează `agents/core/plugins/oauth.py`:
   - Adaugă funcție `get_token_status(provider)` → dict cu status, expiry, scopes
   - Adaugă funcție `revoke_token(provider)` → șterge token file
   - Îmbunătățește logging-ul la refresh (când se întâmplă, dacă reușește)

PARTEA 2: Frontend Admin Page

3. Actualizează `agents/web/templates/admin.html`:
   - Adaugă o secțiune nouă "OAuth Tokens" în admin panel
   - Creează un component React `OAuthStatusPage` care:
     * Afișează toți provider-ii (Google, Spotify) într-un tabel
     * Pentru fiecare: status badge (green=valid, red=expired, gray=missing)
     * Buton "Re-authenticate" care deschide popup cu auth URL
     * Buton "Revoke" pentru a șterge token-ul
     * Auto-refresh la 30s pentru a verifica expiry
   - Adaugă un toast notification când re-auth reușește/eșuează

4. Implementează flow-ul de re-auth:
   - User dă click "Re-authenticate"
   - Se deschide popup cu URL-ul de la GET /api/oauth/auth-url/:provider
   - User completează OAuth flow în popup
   - Popup se închide automat la success
   - Parent page face refresh la status
   - Toast afișează "Google token refreshed successfully"

PARTEA 3: Auto-Refresh Improvements

5. Actualizează `agents/core/plugins/oauth.py`:
   - La fiecare request către un plugin (Gmail, Spotify, Calendar):
     * Verifică dacă token-ul expiră în <5 minute
     * Dacă da, face auto-refresh înainte de request
     * Dacă refresh eșuează, returnează eroare clară ("Token expired, please re-authenticate")

6. Actualizează `agents/core/plugins/gmail_plugin.py`, `spotify_plugin.py`, `google_calendar.py`:
   - Adaugă check de token validity la inițializare
   - Dacă token invalid, aruncă eroare clară cu mesaj de re-auth

PARTEA 4: Testing

7. Creează `tests/test_oauth_ui.py`:
   - Testează GET /api/oauth/providers (mock tokens)
   - Testează POST /api/oauth/revoke/:provider
   - Testează auto-refresh logic
   - Testează că UI afișează status corect

8. Actualizează `docs/OAUTH_SETUP.md`:
   - Adaugă secțiune "Managing Tokens via Admin UI"
   - Screenshot-uri cu noua pagină OAuth
   - Pași pentru re-auth când token expiră

RESTRICȚII:
- React vanilla (fără JSX, folosește React.createElement)
- Nu folosi localStorage pentru tokens (securitate)
- Token-urile rămân în memory_logs/tokens/
- Popup OAuth trebuie să fie centrat și responsive
- Toast notifications trebuie să fie non-intrusive (dispar după 5s)

OUTPUT AȘTEPTAT:
- Toate fișierele modificate/create
- Cod complet, gata de commit
- Screenshot-uri în documentație (opțional)
- Commit message sugestiv

TEST CRITERIA:
- Admin page /admin arată secțiunea OAuth Tokens
- Status badge-urile se actualizează la 30s
- Click pe "Re-authenticate" deschide popup cu auth URL
- După OAuth flow complet, status devine "valid" (green)
- Click pe "Revoke" șterge token și status devine "missing" (gray)
- `python -m pytest tests/test_oauth_ui.py -v` trece
```

---

### 4. Dashboard Metrics în Timp Real

**Prioritate:** ⭐⭐⭐  
**Efort estimat:** 2 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** None

**Context:**
Dashboard-ul actual arată status static (agenți online/offline). Utilizatorii vor să vadă ce fac agenții în timp real: activity feed, latency graphs, token usage, cost tracking.

**Prompt:**

```
Ești un expert full-stack (Python FastAPI + React vanilla + Chart.js) cu experiență în dashboard-uri real-time. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Backend: agents/web.py (FastAPI)
- Dashboard: agents/web/templates/index.html (React vanilla)
- Existing endpoints: GET /status, GET /dashboard, GET /bench
- Benchmark module: agents/core/bench.py

STARE ACTUALĂ:
- Dashboard arată status static (agenți online, sys info)
- Benchmark endpoint returnează stats agregate (latență medie, throughput)
- Nu există activity feed în timp real
- Nu există graphs pentru latency over time
- Nu există cost tracking pentru cloud API calls

CE TREBUIE FĂCUT:

PARTEA 1: Backend — Real-time Metrics

1. Actualizează `agents/core/bench.py`:
   - Adaugă metodă `record_request(agent_id, latency, tokens_used, route, cost)`
   - Stochează ultimele 1000 requests în memorie (deque cu maxlen=1000)
   - Adaugă metodă `get_recent_requests(limit=100)` → listă dicts
   - Adaugă metodă `get_latency_history(agent_id=None, minutes=60)` → time series data
   - Adaugă metodă `get_cost_summary()` → cost per agent, per route, total

2. Actualizează `agents/core/orchestrator.py`:
   - La fiecare request procesat, cheamă `self.bench.record_request(...)`
   - Include: agent_id, latency, tokens (estimate), route (local/cloud), cost (calculat)

3. Actualizează `agents/web.py`:
   - Adaugă endpoint nou: GET /api/metrics/activity → ultimele 50 requests
   - Adaugă endpoint nou: GET /api/metrics/latency → time series (last 60 min)
   - Adaugă endpoint nou: GET /api/metrics/costs → cost breakdown
   - Actualizează GET /status să includă metrics summary (requests/min, avg latency)

4. Creează `agents/core/metrics.py` (nou):
   - Class MetricsCollector cu metode statice
   - Pre-defined cost rates:
     * Claude: $3/1M input tokens, $15/1M output tokens
     * Gemini: $0.075/1M input (cache hit), $0.30/1M input (cache miss)
     * Local: $0 (dar contează VRAM usage)
   - Metodă `estimate_cost(tokens, route)` → float USD

PARTEA 2: Frontend — Dashboard Components

5. Actualizează `agents/web/templates/index.html`:
   - Adaugă 3 componente React noi:
     a) `ActivityFeed` — listă scrollabilă cu ultimele 10 requests
        * Fiecare rând: timestamp, agent, query preview, latency badge, route icon
        * Auto-refresh la 5s
     b) `LatencyGraph` — Chart.js line chart cu latența pe ultimele 60 min
        * X-axis: time (minute), Y-axis: latency (seconds)
        * One line per agent (color-coded)
        * Auto-refresh la 30s
     c) `CostTracker` — cards cu costuri (today, this week, this month)
        * Breakdown per agent (bar chart)
        * Breakdown per route (pie chart: local vs cloud)
        * Projected monthly cost

6. Actualizează `agents/web/templates/admin.html`:
   - Adaugă o pagină nouă "/admin/metrics" cu metrics avansate
   - Include:
     * Heatmap: requests per hour (7 days)
     * Top 10 queries (by frequency)
     * Agent performance ranking (success rate, avg latency)
     * Token usage trends

PARTEA 3: Real-time Updates

7. Implementează SSE pentru metrics:
   - Adaugă endpoint nou: GET /api/metrics/stream (SSE)
   - Trimite update la fiecare 5s cu:
     * New requests (since last update)
     * Updated latency averages
     * Updated cost totals
   - Frontend se subscribe la SSE stream și actualizează components

8. Actualizează frontend-ul:
   - Conectează ActivityFeed la SSE stream
   - Conectează LatencyGraph la SSE stream (append new data points)
   - Conectează CostTracker la SSE stream (update totals)

PARTEA 4: Testing

9. Creează `tests/test_metrics.py`:
   - Testează MetricsCollector (cost calculations)
   - Testează bench.record_request()
   - Testează toate endpoint-urile noi (/api/metrics/*)
   - Testează SSE stream (mock)

10. Actualizează `docs/METRICS.md` (nou):
    - Cum să interpretezi metrics
    - Cost estimates pentru diferite usage patterns
    - Cum să optimizezi costs (more local, less cloud)

RESTRICȚII:
- Chart.js pentru graphs (include via CDN în HTML)
- React vanilla (fără JSX)
- SSE pentru real-time updates (nu polling)
- Cost calculations trebuie să fie precise (2 zecimale)
- Activity feed nu trebuie să depășească 1000 rows (memory leak prevention)

OUTPUT AȘTEPTAT:
- Toate fișierele modificate/create
- Cod complet, gata de commit
- Dashboard actualizat cu 3 componente noi
- Admin page nouă cu metrics avansate
- Commit message sugestiv

TEST CRITERIA:
- Dashboard afișează activity feed care se actualizează la 5s
- Latency graph arată date istorice (60 min)
- Cost tracker afișează costuri în USD (chiar dacă 0.00 pentru local)
- SSE stream funcționează (verify în browser DevTools Network tab)
- `python -m pytest tests/test_metrics.py -v` trece
- Latența dashboard-ului <1s (nu blochează UI)
```

---

## Sprint 2 — Foundation Inteligență

### 5. Qdrant Vector DB Deployment

**Prioritate:** ⭐⭐⭐⭐  
**Efort estimat:** 3 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Docker, Qdrant image

**Context:**
Vector store-ul actual folosește NumPy (768-dim) care nu persistă embeddings la restart. Qdrant oferă persistență, scaling și search semantic cross-sesiuni.

**Prompt:**

```
Ești un expert DevOps + Python cu experiență în vector databases (Qdrant, Pinecone, Weaviate). Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Vector store actual: agents/core/memory/store.py (NumPyVectorStore)
- Memory manager: agents/core/memory/manager.py
- Docker compose: (nu există încă)

STARE ACTUALĂ:
- VectorStore e implementat cu NumPy (în memorie, nu persistă)
- La restart, toate embeddings se pierd
- Nu există search semantic cross-sesiuni
- Qdrant e menționat în BACKLOG.md ca H3.1

CE TREBUIE FĂCUT:

PARTEA 1: Qdrant Deployment

1. Creează `docker-compose.qdrant.yml`:
   ```yaml
   services:
     qdrant:
       image: qdrant/qdrant:latest
       container_name: cabinet-qdrant
       ports:
         - "6333:6333"  # REST API
         - "6334:6334"  # gRPC
       volumes:
         - ./qdrant_storage:/qdrant/storage
       restart: unless-stopped
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:6333/"]
         interval: 30s
         timeout: 10s
         retries: 3
   ```

2. Creează `docs/QDRANT_SETUP.md`:
   - Cum să pornești Qdrant: `docker-compose -f docker-compose.qdrant.yml up -d`
   - Cum să verifici că rulează: `curl http://localhost:6333/`
   - Cum să oprești: `docker-compose -f docker-compose.qdrant.yml down`
   - Backup/restore: cum să faci backup la qdrant_storage/

PARTEA 2: QdrantVectorStore Implementation

3. Creează `agents/core/memory/qdrant_store.py` (nou):
   ```python
   class QdrantVectorStore:
       def __init__(self, url="http://localhost:6333", collection_name="cabinet_memory"):
           self.client = qdrant_client.QdrantClient(url=url)
           self.collection_name = collection_name
           self._ensure_collection()
       
       def _ensure_collection(self):
           # Creează collection dacă nu există
           # Vector size: 768 (compatible with existing embeddings)
           # Distance: Cosine
       
       def add(self, text: str, embedding: np.ndarray, metadata: dict):
           # Adaugă un punct în Qdrant
       
       def search(self, query_embedding: np.ndarray, limit: int = 5) -> List[Dict]:
           # Caută similaritate
       
       def delete_session(self, session_id: str):
           # Șterge toate punctele dintr-o sesiune
       
       def count(self) -> int:
           # Returnează numărul total de puncte
   ```

4. Actualizează `agents/core/memory/store.py`:
   - Adaugă factory function: `create_vector_store()` → QdrantVectorStore sau NumPyVectorStore
   - Detectează dacă Qdrant e disponibil (HTTP request la localhost:6333)
   - Dacă Qdrant unavailable, fallback la NumPy (backward compatibility)

5. Actualizează `agents/core/memory/manager.py`:
   - La inițializare, cheamă `create_vector_store()`
   - Toate metodele existente rămân la fel (abstraction layer)

PARTEA 3: Migration

6. Creează script de migration `scripts/migrate_to_qdrant.py`:
   - Citește toate sesiunile din memory_logs/sessions/
   - Extrage text-ul din fiecare turn
   - Generează embeddings (folosind același model ca înainte)
   - Adaugă în Qdrant cu metadata (session_id, timestamp, agent_id)
   - Progress bar și logging
   - Dry-run mode (nu scrie, doar numără)

7. Actualizează `requirements-beta.txt`:
   - Adaugă `qdrant-client>=1.7.0`

PARTEA 4: Integration Testing

8. Creează `tests/test_qdrant_store.py`:
   - Testează QdrantVectorStore cu Qdrant real (Docker)
   - Testează add/search/delete
   - Testează fallback la NumPy când Qdrant unavailable
   - Testează migration script (dry-run)

9. Actualizează `smoke.ps1`:
   - Verifică că Qdrant pornește (dacă docker-compose.qdrant.yml există)
   - Verifică că serverul Jarvis pornește cu Qdrant

PARTEA 5: Documentation

10. Actualizează `README.md`:
    - Adaugă secțiune "Vector DB (Qdrant)"
    - Link către docs/QDRANT_SETUP.md
    - Beneficii: persistență, cross-session search, scaling

11. Actualizează `docs/ARCHITECTURE.md`:
    - Diagramă actualizată cu Qdrant în memory layer
    - Explică fallback mechanism

RESTRICȚII:
- Folosește qdrant-client library (official Python SDK)
- Vector size trebuie să fie 768 (compatible cu embeddings existente)
- Distance metric: Cosine
- Fallback la NumPy e obligatoriu (nu crapa dacă Qdrant unavailable)
- Migration script trebuie să fie idempotent (poate fi rulat de multiple ori)

OUTPUT AȘTEPTAT:
- docker-compose.qdrant.yml
- agents/core/memory/qdrant_store.py (nou)
- agents/core/memory/store.py (actualizat)
- scripts/migrate_to_qdrant.py (nou)
- docs/QDRANT_SETUP.md (nou)
- Teste care trec
- Commit message sugestiv

TEST CRITERIA:
- `docker-compose -f docker-compose.qdrant.yml up -d` pornește Qdrant
- `curl http://localhost:6333/` returnează 200
- `python scripts/migrate_to_qdrant.py --dry-run` arată câte sesiuni vor fi migrate
- `python scripts/migrate_to_qdrant.py` migrează toate sesiunile
- Search semantic funcționează: "ce am discutat despre Cosmina?" găsește sesiuni relevante
- `python -m pytest tests/test_qdrant_store.py -v` trece
- Dacă Qdrant oprit, sistemul fallback la NumPy fără erori
```

---

### 6. Neo4j Knowledge Graph

**Prioritate:** ⭐⭐⭐  
**Efort estimat:** 5 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Docker, Neo4j image

**Context:**
Vector DB e bună pentru similaritate, dar nu poate modela relații (Andrei → lucrează_la → Raiffeisen). Neo4j knowledge graph permite query-uri structurale și reasoning.

**Prompt:**

```
Ești un expert Python + Neo4j cu experiență în knowledge graphs și Cypher queries. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Memory layer: agents/core/memory/
- Qdrant: deja implementat (Sprint 2, Feature 5)
- Date existente: sesiuni conversații, entități menționate (persoane, companii, locații)

STARE ACTUALĂ:
- Nu există knowledge graph
- Entități și relații nu sunt modelate explicit
- Query-uri de genul "Unde lucrează Andrei?" necesită search semantic (imprecis)
- Neo4j menționat în BACKLOG.md ca H3.2

CE TREBUIE FĂCUT:

PARTEA 1: Neo4j Deployment

1. Creează `docker-compose.neo4j.yml`:
   ```yaml
   services:
     neo4j:
       image: neo4j:5.15
       container_name: cabinet-neo4j
       ports:
         - "7474:7474"  # Browser
         - "7687:7687"  # Bolt protocol
       environment:
         - NEO4J_AUTH=neo4j/cabinet123
         - NEO4J_PLUGINS=["apoc"]  # APOC library pentru utils
       volumes:
         - ./neo4j_data:/data
         - ./neo4j_logs:/logs
       restart: unless-stopped
       healthcheck:
         test: ["CMD", "wget", "-q", "--spider", "http://localhost:7474"]
         interval: 30s
         timeout: 10s
         retries: 3
   ```

2. Creează `docs/NEO4J_SETUP.md`:
   - Cum să pornești: `docker-compose -f docker-compose.neo4j.yml up -d`
   - Cum să accesezi Neo4j Browser: http://localhost:7474
   - Credentials: neo4j / cabinet123
   - Cum să oprești/backup/restore

PARTEA 2: Knowledge Graph Schema

3. Creează `agents/core/memory/graph_schema.py` (nou):
   - Definește node labels: Person, Company, Project, Location, Event, Asset
   - Definește relationship types: WORKS_AT, OWNS, LIVES_IN, BUILT, MANAGES, RELATED_TO
   - Definește index-uri pentru performance:
     * CREATE INDEX FOR (p:Person) ON (p.name)
     * CREATE INDEX FOR (c:Company) ON (c.name)

4. Creează `agents/core/memory/knowledge_graph.py` (nou):
   ```python
   class KnowledgeGraph:
       def __init__(self, uri="bolt://localhost:7687", user="neo4j", password="cabinet123"):
           self.driver = GraphDatabase.driver(uri, auth=(user, password))
           self._init_schema()
       
       def _init_schema(self):
           # Creează index-uri și constraints
       
       def add_person(self, name: str, properties: dict):
           # MERGE (p:Person {name: name}) SET p += properties
       
       def add_company(self, name: str, properties: dict):
           # MERGE (c:Company {name: name}) SET c += properties
       
       def add_relationship(self, from_node: str, rel_type: str, to_node: str, properties: dict = None):
           # MATCH (a), (b) WHERE a.name = from_node AND b.name = to_node
           # CREATE (a)-[r:REL_TYPE {properties}]->(b)
       
       def query(self, cypher: str, params: dict = None) -> List[Dict]:
           # Execută query Cypher și returnează results
       
       def close(self):
           self.driver.close()
   ```

PARTEA 3: Entity Extraction & Ingestion

5. Creează `agents/core/memory/entity_extractor.py` (nou):
   - Folosește LLM pentru a extrage entități din conversații
   - Prompt template:
     ```
     Extrage entități din conversația de mai jos.
     Pentru fiecare entitate, returnează:
       - type: Person/Company/Project/Location/Asset
       - name: numele entității
       - properties: dict cu detalii (ex: {role: "CTO", company: "Raiffeisen"})
     
     Conversație:
     {conversation_text}
     ```
   - Output: listă de entități structurate

6. Creează `agents/core/memory/ingestion_pipeline.py` (nou):
   - La fiecare sesiune nouă:
     * Extrage entități cu entity_extractor
     * Adaugă în knowledge graph
     * Detectează relații noi (ex: "Andrei lucrează la Raiffeisen" → WORKS_AT)
     * Actualizează graph-ul
   - Rulează async (nu blochează conversația)

PARTEA 4: Integration cu Memory Manager

7. Actualizează `agents/core/memory/manager.py`:
   - Adaugă `self.graph = KnowledgeGraph()` la inițializare
   - Adaugă metodă `ingest_session(session_id)` → extrage entități și adaugă în graph
   - Adaugă metodă `query_graph(cypher, params)` → query direct
   - La close session, cheamă ingestion_pipeline

8. Actualizează `agents/core/orchestrator.py`:
   - La `memory.add_turn()`, dacă e ultimul turn din sesiune, cheamă `memory.ingest_session()`
   - Adaugă logging: "Ingested 5 entities, 3 relationships from session"

PARTEA 5: Query Helpers

9. Creează `agents/core/memory/graph_queries.py` (nou):
   - Funcții helper pentru query-uri comune:
     * `get_person_details(name)` → detalii despre o persoană
     * `get_companies_for_person(name)` → unde lucrează o persoană
     * `get_projects_for_person(name)` → ce proiecte are
     * `get_all_relationships(entity_name)` → toate relațiile unei entități
     * `find_path(entity1, entity2)` → shortest path între 2 entități

10. Actualizează `agents/core/plugins/` (opțional):
    - Adaugă un plugin `knowledge_graph` care expune query helpers ca skill-uri
    - Skill-uri: `/graph query "MATCH ..."`

PARTEA 6: Testing & Documentation

11. Creează `tests/test_knowledge_graph.py`:
    - Testează KnowledgeGraph (add, query, relationships)
    - Testează entity_extractor (mock LLM)
    - Testează ingestion_pipeline
    - Testează query helpers

12. Creează `docs/KNOWLEDGE_GRAPH.md`:
    - Cum să folosești Neo4j Browser pentru a explora graph-ul
    - Exemple de query-uri Cypher utile
    - Cum să adaugi entități manual
    - Best practices (index-uri, performance)

13. Actualizează `README.md`:
    - Adaugă secțiune "Knowledge Graph (Neo4j)"
    - Link către docs/KNOWLEDGE_GRAPH.md

RESTRICȚII:
- Folosește neo4j Python driver (official)
- Include APOC library pentru utils extra
- Entity extraction trebuie să fie async (nu blochează conversația)
- Knowledge graph e opțional (nu crapa dacă Neo4j unavailable)
- Query-urile trebuie să fie parametrizate (prevention SQL injection-style attacks)

OUTPUT AȘTEPTAT:
- docker-compose.neo4j.yml
- agents/core/memory/graph_schema.py (nou)
- agents/core/memory/knowledge_graph.py (nou)
- agents/core/memory/entity_extractor.py (nou)
- agents/core/memory/ingestion_pipeline.py (nou)
- agents/core/memory/graph_queries.py (nou)
- docs/NEO4J_SETUP.md (nou)
- docs/KNOWLEDGE_GRAPH.md (nou)
- Teste care trec
- Commit message sugestiv

TEST CRITERIA:
- `docker-compose -f docker-compose.neo4j.yml up -d` pornește Neo4j
- Neo4j Browser accesibil la http://localhost:7474
- Entity extraction funcționează (test cu conversație sample)
- Knowledge graph populat cu entități din sesiuni existente
- Query-uri Cypher returnează results corecte
- `python -m pytest tests/test_knowledge_graph.py -v` trece
- Dacă Neo4j oprit, sistemul nu crapa (graceful degradation)
```

---

### 7. Learning Loop Production

**Prioritate:** ⭐⭐⭐⭐⭐ (Critic pentru inteligență pe termen lung)  
**Efort estimat:** 5 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** None (folosește infrastructura existentă)

**Context:**
Learning loop e prezent în cod (`agents/core/learning/loop.py`) dar nu e activat full. Sistemul nu învață din greșeli și nu optimizează routing-ul automat.

**Prompt:**

```
Ești un expert Python cu experiență în machine learning ops și reinforcement learning. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Learning loop: agents/core/learning/loop.py
- Orchestrator: agents/core/orchestrator.py
- Benchmark: agents/core/bench.py
- Agents config: agents/_system/agents.yaml

STARE ACTUALĂ:
- LearningLoop class există dar nu e folosită activ
- Nu se înregistrează interacțiuni pentru analiză
- Nu se optimizează routing pe baza performanței
- Nu se sugerează promovări/demotion de agenți
- BACKLOG.md H3.4: "Learning Loop live"

CE TREBUIE FĂCUT:

PARTEA 1: Interaction Recording

1. Actualizează `agents/core/learning/loop.py`:
   ```python
   class LearningLoop:
       def __init__(self, db_path="memory_logs/learning.db"):
           self.db_path = db_path
           self._init_db()
       
       def _init_db(self):
           # SQLite schema:
           # - interactions (id, timestamp, session_id, agent_id, input, output, latency, success, feedback)
           # - agent_stats (agent_id, total_calls, success_rate, avg_latency, last_30_days_calls)
           # - routing_stats (route, total_calls, success_rate, avg_latency)
           # - optimizations (id, timestamp, type, description, impact)
       
       def record_interaction(self, session_id: str, agent_id: str, input_text: str, 
                             output_text: str, latency: float, route: str, 
                             success: bool, feedback: str = None):
           # Înregistrează interacțiunea în SQLite
       
       def get_agent_stats(self, agent_id: str, days: int = 30) -> Dict:
           # Returnează statistici pentru un agent (success rate, avg latency, call count)
       
       def get_routing_stats(self, days: int = 30) -> Dict:
           # Returnează statistici per route (local vs cloud)
       
       def get_promotion_candidates(self) -> List[Dict]:
           # Găsește agenți bench cu >20 calls în ultima lună și success rate >80%
       
       def get_demotion_candidates(self) -> List[Dict]:
           # Găsește agenți activi cu <5 calls în ultima lună sau success rate <50%
       
       def suggest_optimization(self) -> Optional[Dict]:
           # Analizează patterns și sugerează optimizări
           # Ex: "Route more queries to Claude for research tasks (20% higher success rate)"
   ```

2. Actualizează `agents/core/orchestrator.py`:
   - La `handle_input()`, după ce primești răspunsul:
     ```python
     self.learning.record_interaction(
         session_id=self.session_id,
         agent_id=responder_id,
         input_text=text,
         output_text=synthesized,
         latency=time.monotonic() - start,
         route=route_name,  # de la LLM router
         success=True,  # sau False dacă a fost eroare
         feedback=None  # va fi populat din UI mai târziu
     )
     ```

PARTEA 2: Weekly Analysis Job

3. Creează `agents/core/learning/analyzer.py` (nou):
   ```python
   class LearningAnalyzer:
       def __init__(self, learning_loop: LearningLoop):
           self.loop = learning_loop
       
       def run_weekly_analysis(self) -> Dict:
           # Rulează o dată pe săptămână (cron job)
           # Returnează:
           # - Top 3 agenți după usage
           # - Bottom 3 agenți după usage
           # - Sugestii de promovare (bench → active)
           # - Sugestii de demotion (active → bench)
           # - Routing optimization suggestions
           # - Latency outliers (care agenți sunt prea lenți)
       
       def _analyze_agent_performance(self) -> List[Dict]:
           # Analizează fiecare agent
       
       def _analyze_routing_efficiency(self) -> List[Dict]:
           # Compară local vs cloud performance
       
       def _detect_patterns(self) -> List[Dict]:
           # Detectează patterns (ex: "Vision are success rate mai mare pentru query-uri >500 tokens")
   ```

4. Actualizează `agents/core/heartbeat.py`:
   - Adaugă un heartbeat special "learning_analyzer" care rulează o dată pe săptămână
   - Când rulează, cheamă `LearningAnalyzer.run_weekly_analysis()`
   - Salvează results în `memory_logs/analysis/weekly_YYYY-MM-DD.json`

PARTEA 3: Promotion/Demotion Automation

5. Actualizează `agents/core/agent.py`:
   - Adaugă metodă `check_promotion_eligibility()` → bool
   - Adaugă metodă `check_demotion_eligibility()` → bool
   - Actualizează `should_demote` să folosească learning loop stats (nu doar 5 failures)

6. Actualizează `agents/core/orchestrator.py`:
   - La startup, cheamă `self._check_agent_adjustments()`
   - Verifică dacă vreun agent bench trebuie promovat
   - Verifică dacă vreun agent activ trebuie demovat
   - Log adjustments: "Promoting Bruce from bench to active (25 data queries this month)"

PARTEA 4: Admin UI pentru Learning

7. Actualizează `agents/web/templates/admin.html`:
   - Adaugă o pagină nouă "/admin/learning"
   - Componente React:
     a) `AgentPerformanceTable` — tabel cu toți agenții (calls, success rate, avg latency)
     b) `PromotionSuggestions` — listă de agenți bench care pot fi promovați
     c) `DemotionWarnings` — listă de agenți activi care ar trebui demovați
     d) `OptimizationTips` — sugestii de la analyzer (ex: "Route more to Claude for research")
   - Buton "Run Analysis Now" care cheamă POST /api/learning/analyze

8. Actualizează `agents/web.py`:
   - Adaugă endpoint GET /api/learning/stats → returnează stats pentru UI
   - Adaugă endpoint POST /api/learning/analyze → rulează analysis manual
   - Adaugă endpoint POST /api/learning/promote/:agent → promovează un agent
   - Adaugă endpoint POST /api/learning/demote/:agent → demovează un agent

PARTEA 5: Feedback Collection (Opțional)

9. Actualizează `agents/web/templates/index.html`:
   - Adaugă butoane 👍/👎 lângă fiecare răspuns de la agent
   - Când user dă click, trimite POST /api/feedback cu session_id și feedback type
   - Stochează feedback în learning loop DB

10. Actualizează `agents/core/orchestrator.py`:
    - Adaugă metodă `record_feedback(session_id, feedback_type)`
    - Actualizează interacțiunea cu feedback-ul

PARTEA 6: Testing & Documentation

11. Creează `tests/test_learning_loop.py`:
    - Testează record_interaction()
    - Testează get_agent_stats()
    - Testează get_promotion_candidates()
    - Testează LearningAnalyzer
    - Testează promotion/demotion logic

12. Creează `docs/LEARNING_LOOP.md`:
    - Cum funcționează learning loop
    - Cum să interpretezi analysis results
    - Cum să promovezi/demovezi agenți manual
    - Exemple de optimizări sugerate

13. Actualizează `README.md`:
    - Adaugă secțiune "Learning Loop"
    - Explică cum sistemul devine mai smart over time

RESTRICȚII:
- SQLite pentru learning DB (nu introduce dependențe noi)
- Analysis job trebuie să fie async (nu blochează conversații)
- Promotion/demotion trebuie să fie reversibil (poți schimba back)
- Feedback UI trebuie să fie non-intrusive (nu întrerupe flow-ul)

OUTPUT AȘTEPTAT:
- agents/core/learning/loop.py (actualizat masiv)
- agents/core/learning/analyzer.py (nou)
- agents/core/orchestrator.py (actualizat)
- agents/core/heartbeat.py (actualizat)
- agents/core/agent.py (actualizat)
- agents/web.py (actualizat)
- agents/web/templates/admin.html (actualizat)
- agents/web/templates/index.html (actualizat, opțional)
- docs/LEARNING_LOOP.md (nou)
- Teste care trec
- Commit message sugestiv

TEST CRITERIA:
- Interacțiuni înregistrate în SQLite după fiecare request
- GET /api/learning/stats returnează date corecte
- Weekly analysis job rulează automat (verifică logs)
- Promotion suggestions apar în admin UI
- Click pe "Promote" actualizează agents.yaml și restartă agentul
- `python -m pytest tests/test_learning_loop.py -v` trece
- Feedback 👍/👎 funcționează (dacă implementat)
```

---

### 8. Context Caching Gemini API

**Prioritate:** ⭐⭐⭐  
**Efort estimat:** 2 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Gemini API key

**Context:**
Gemini API oferă 75-90% discount pentru tokeni citiți din context cache. Pentru sesiuni lungi (50+ mesaje), asta înseamnă economii semnificative.

**Prompt:**

```
Ești un expert Python cu experiență în Google Gemini API și context caching. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Gemini backend: agents/core/llm/gemini.py
- Hybrid router: agents/core/llm/hybrid_router.py
- Memory manager: agents/core/memory/manager.py

STARE ACTUALĂ:
- GeminiBackend există și funcționează
- Nu folosește context caching
- Sesiuni lungi (>50 mesaje) costă mult (toți tokeni facturați full price)
- BACKLOG.md H4.11: "Context Caching + Hybrid Routing Metrics"

CE TREBUIE FĂCUT:

PARTEA 1: Gemini Context Cache Implementation

1. Actualizează `agents/core/llm/gemini.py`:
   ```python
   class GeminiBackend(LLMBackend):
       def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
           self.api_key = api_key
           self.model = model
           self._cache = None  # Context cache handle
           self._cache_session_id = None
           self._cache_token_count = 0
       
       async def _get_or_create_cache(self, session_id: str, context_text: str) -> str:
           # Dacă session_id s-a schimbat sau cache nu există:
           #   - Șterge cache vechi (dacă există)
           #   - Creează cache nou cu context_text
           #   - Returnează cache ID
           # Altfel, returnează cache ID existent
       
       async def generate_with_cache(self, prompt: str, system: str, 
                                     session_id: str, context: str,
                                     max_tokens: int, temperature: float) -> str:
           # 1. Obține cache ID pentru session_id
           # 2. Folosește cache în request către Gemini API
           # 3. Returnează response
           # 4. Log cache stats (tokens cached, discount applied)
       
       async def generate(self, model: str, prompt: str, system: str = "", 
                         max_tokens: int = 1024, temperature: float = 0.7,
                         session_id: str = None, context: str = None) -> str:
           # Dacă session_id și context sunt provided:
           #   - Folosește generate_with_cache()
           # Altfel:
           #   - Folosește generate() normal (fără cache)
       
       async def delete_cache(self, session_id: str):
           # Șterge cache pentru session_id
           # Called when session ends
   ```

2. Actualizează `agents/core/orchestrator.py`:
   - La `handle_input()`, dacă route == "cloud" sau "cloud-flash":
     ```python
     response = await backend.generate(
         model=model,
         prompt=prompt,
         system=system_prompt,
         session_id=self.session_id,  # nou
         context=history,  # nou
         max_tokens=max_tokens,
         temperature=temperature,
     )
     ```
   - La session close, cheamă `backend.delete_cache(self.session_id)`

PARTEA 2: Cache Stats & Metrics

3. Actualizează `agents/core/bench.py`:
   - Adaugă metodă `record_cache_stats(session_id, cached_tokens, discount_percent)`
   - Adaugă metodă `get_cache_summary()` → total cached tokens, total savings USD

4. Actualizează `agents/core/llm/gemini.py`:
   - La fiecare request cu cache, log:
     ```
     logger.info(f"Context cache: {cached_tokens} tokens cached, {discount_percent}% discount applied")
     ```

PARTEA 3: Admin UI pentru Cache

5. Actualizează `agents/web/templates/admin.html`:
   - Adaugă o secțiune "Context Cache Stats"
   - Afișează:
     * Total sessions with cache active
     * Total tokens cached (all-time)
     * Estimated savings USD (vs no cache)
     * Cache hit rate (% requests using cache)
   - Grafic: cache usage over time (line chart)

6. Actualizează `agents/web.py`:
   - Adaugă endpoint GET /api/learning/cache-stats → returnează stats pentru UI

PARTEA 4: Testing

7. Creează `tests/test_gemini_cache.py`:
   - Testează _get_or_create_cache() (mock Gemini API)
   - Testează generate_with_cache() (verify cache ID passed to API)
   - Testează delete_cache()
   - Testează cache stats recording
   - Testează că fallback la non-cache funcționează dacă cache unavailable

8. Actualizează `docs/GEMINI_SETUP.md` (sau creează):
   - Adaugă secțiune "Context Caching"
   - Explică cum funcționează (75-90% discount)
   - Cum să verifici că cache e activ (logs, admin UI)
   - Best practices (când să folosești cache: sesiuni >10 mesaje)

PARTEA 5: Optimization Suggestions

9. Actualizează `agents/core/learning/analyzer.py`:
   - Adaugă analiză: "X% din sesiuni ar beneficia de context caching"
   - Sugerează: "Activează cache pentru sesiunile cu >10 mesaje"

RESTRICȚII:
- Folosește official Google Generative AI library (google-generativeai)
- Context cache are cost mic de creare (o singură dată per sesiune)
- Cache expiry: 24 ore (default Gemini)
- Nu folosi cache pentru sesiuni scurte (<5 mesaje) — nu merită costul de creare
- Fallback graceful dacă cache creation eșuează

OUTPUT AȘTEPTAT:
- agents/core/llm/gemini.py (actualizat masiv)
- agents/core/orchestrator.py (actualizat)
- agents/core/bench.py (actualizat)
- agents/web.py (actualizat)
- agents/web/templates/admin.html (actualizat)
- docs/GEMINI_SETUP.md (actualizat sau nou)
- Teste care trec
- Commit message sugestiv

TEST CRITERIA:
- Sesiuni lungi (>10 mesaje) folosesc context cache automat
- Logs arată "Context cache: X tokens cached, Y% discount"
- Admin UI afișează cache stats (tokens, savings)
- Cache deletion la session close funcționează
- `python -m pytest tests/test_gemini_cache.py -v` trece
- Estimated savings calculat corect (tokens cached × price per token × 0.75)
```

---

## Sprint 3 — Platform Maturity

### 9. Advanced Analytics Dashboard

**Prioritate:** ⭐⭐⭐  
**Efort estimat:** 5 zile  
**Model recomandat:** Claude Sonnet 4  
**Dependențe:** Chart.js (CDN), metrics din Sprint 2

**Prompt:**

```
Ești un expert full-stack (Python FastAPI + React vanilla + Chart.js + Data visualization) cu experiență în analytics dashboards. Lucrezi la proiectul "Andrei's Cabinet".

CONTEXT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Metrics: deja implementate în Sprint 1 (Feature 4)
- Learning loop: deja implementat în Sprint 2 (Feature 7)
- Admin panel: agents/web/templates/admin.html

STARE ACTUALĂ:
- Dashboard are metrics de bază (activity feed, latency graph, cost tracker)
- Nu există analytics avansate (heatmaps, trends, correlations)
- Nu există export de date (CSV, JSON)
- Nu există alerts/thresholds

CE TREBUIE FĂCUT:

[Continuă în fișierul separat pentru că prompt-ul e prea lung — vezi `prompts/feature_09_analytics.md`]
```

**Notă:** Pentru feature-urile 9-17, prompt-urile complete sunt prea lungi pentru acest fișier. Le poți genera individual cu:

```
Generează un prompt detaliat pentru implementarea feature-ului X din Cabinet/Jarvis, incluzând:
- Contextul proiectului
- Starea actuală
- Ce trebuie făcut (părțile 1-6)
- Restricții
- Output așteptat
- Test criteria
```

---

## Anexa A: Template Prompt Generic

```
Ești un expert {DOMAIN} cu experiență în {TECH_STACK}. Lucrezi la proiectul "Andrei's Cabinet" — un sistem multi-agent AI cu 15 agenți specializați.

CONTEXT PROIECT:
- Repository: /home/iulian/proiecte/Para/cabinet
- Componenta relevantă: {PATH_TO_COMPONENT}
- Documentație: README.md, docs/{FEATURE}.md

STARE ACTUALĂ:
{DESCRIERE_STARE_ACTUALA}

CE TREBUIE FĂCUT:

PARTEA 1: {TITLE}
1. {TASK_1}
2. {TASK_2}

PARTEA 2: {TITLE}
3. {TASK_3}
4. {TASK_4}

[... continuă până la PARTEA 6 ...]

RESTRICȚII:
- {CONSTRAINT_1}
- {CONSTRAINT_2}
- {CONSTRAINT_3}

OUTPUT AȘTEPTAT:
- Lista fișierelor modificate/create
- Cod complet, gata de commit
- Documentație actualizată
- Commit message sugestiv

TEST CRITERIA:
- {TEST_1}
- {TEST_2}
- {TEST_3}
```

---

## Anexa B: Comenzi Utile pentru Toate Prompt-urile

```bash
# Înainte de a începe implementarea:
git checkout -b feature/{feature-name}

# După implementare:
git add .
git commit -m "{commit-message-from-prompt}"
git push origin feature/{feature-name}

# Pentru testing:
python -m pytest tests/test_{feature}.py -v
python serve.py  # verify server starts
curl http://localhost:8000/status  # verify health
```

---

**Sfârșitul Fișierului de Prompt-uri**

*Generat pe 30 Mai 2026 pentru Andrei's Cabinet v0.2.1*
