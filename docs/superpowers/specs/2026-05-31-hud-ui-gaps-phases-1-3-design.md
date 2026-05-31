# HUD UI Gaps — Phase 1–3 Design

> **Scope:** 3 faze care transformă taburile mock ale SystemsPanel și widgeturile principale din HUD în componente live, conectate la endpoint-uri reale.
> **Driver:** Andrei observă că resilience + alte feature-uri backend nu au reprezentare în interfața principală (`/`), doar în admin (`/admin`).

---

## Phase 1 — Resilience Tab in SystemsPanel

### Problemă
Resilience metrics (`@resilient_call`, `CircuitBreaker`, `ResilienceMetrics`) există doar în admin UI (`/admin`). Main HUD le ignoră complet.

### Soluție
1. **Endpoint public** `GET /api/resilience` (fără admin guard) care expune:
   - `metrics`: același dict ca `get_metrics().get_stats()`
   - `circuit_breakers`: stări curente per key
2. **ResilienceTab** componentă nouă în `systems.js`:
   - Retry metrics: success/failure/avg_latency per agent+backend
   - Circuit breakers: listă cu stare (closed/half-open/open), failure_count, last_failure_time
   - Culori: verde (closed), galben (half-open), roșu (open)
3. **TAB nou** `{ id: 'resilience', label: 'Resilience' }` în `TABS` din `systems.js`
4. **State + fetch** în `SystemsPanel` (asemănător cu `heartbeatStatus`, dar pentru resilience)

### Fișiere modificate
- `agents/web.py` — noul endpoint `/api/resilience`
- `agents/web/static/systems.js` — ResilienceTab + TABS update + SystemsPanel wiring
- `agents/web/static/systems.css` — stiluri pentru resilience cards
- `tests/test_resilience.py` — test pentru endpoint

---

## Phase 2 — Live Data Wiring

### Problemă
4 din 5 taburi ale SystemsPanel folosesc mock-uri statice din `data.js` în loc de date live:
- MemoryTab ← `MEMORY_STATS`
- PluginsTab ← `PLUGINS`
- LearningTab ← `LEARNING`
- SecurityBenchTab ← `SECURITY` + `BENCH`

### Soluție
4 endpoint-uri publice noi + wiring în `SystemsPanel`:

### 2a. Memory → live
- Endpoint `GET /api/memory/stats`: sessions (total/active/current), vectors (stored/dimension/backend), knowledge_graph (entities/relations/last_seed), agent_contexts (per-agent key count)
- Sursă: `orch.memory`, `orch.checkpoints`, `orch.learning`
- Wiring: `SystemsPanel` fetch-uiește la mount, la fel ca heartbeatStatus

### 2b. Plugins → live
- Endpoint `GET /api/plugins`: listă plugin-uri cu id, name, enabled, network_access, data_scope, allowed_domains, agents_served
- Sursă: `orch.plugins` dict + metadata din plugin instances
- Wiring: `PluginsTab` primește live data instead of static `PLUGINS`

### 2c. Learning → live
- Endpoint `GET /api/learning/stats`: interactions_total, success_rate, prompt_optimizations, promotion_candidates, demotion_warnings
- Sursă: `orch.learning` module
- Wiring: `LearningTab` primește live data instead of static `LEARNING`

### 2d. Security + Bench → live
- Endpoint `GET /api/security/stats`: guardrails (mode/redact_count/block_count), scanners (secret+ PII patterns/findings), ssrf (enabled/blocked_requests/max_redirects)
- Endpoint `GET /api/bench/stats`: latency (p50/p95/p99), throughput (rpm/avg_tokens), by_agent
- Wiring: `SecurityBenchTab` primește live data; `MEMORY_STATS`, `PLUGINS`, `LEARNING`, `SECURITY`, `BENCH` din `data.js` devin neutilizate (se păstrează ca fallback)

### Fișiere modificate
- `agents/web.py` — 6 endpoint-uri noi + 1 endpoint updated (`/security/status` există deja)
- `agents/web/static/systems.js` — toate taburile trec la fetch live
- `agents/web/static/data.js` — se păstrează mock-urile ca fallback
- `tests/test_systems_api.py` — teste pentru noile endpoint-uri

---

## Phase 3 — Missing Widgets

### Problemă
Widgeturi care există ca componentă dar nu sunt populate:
- **SituationTicker** (`/`): `ticker` state rămâne `[]` — `loadJarvisData()` nu consumă `/ticker`
- **CognitionPanel**: `COGNITION_SCORING`, `ROUTING_DECISION`, `ORCHESTRATION_TRACE` sunt mock-uri statice
- **HeartbeatFeed** (`/`): `notifications` vine gol din `/dashboard`
- **Lipsă totală**: OAuth status, Oracle status, Tasks în UI

### Soluție
**3a. Ticker live:** Adăugăm call la `/ticker` în `loadJarvisData()` (în `data.js`), populăm state `ticker`.

**3b. CognitionPanel live:** Endpoint `GET /api/cognition/status`: scoring, routing_decision, orchestration_trace. Wiring în `app.js`.

**3c. HeartbeatFeed populator:** Endpoint `/dashboard` returnează deja `notifications: []`. Trebuie populat din `orch.heartbeat.get_recent_events()`.

**3d. OAuth tab nou** în SystemsPanel:
- Endpoint `GET /api/oauth/status` — deja există
- Tab afișează provideri: google (calendar+gmail), spotify — conectat/neconectat, token expiry

**3e. Oracle tab nou** în SystemsPanel:
- Endpoint `GET /api/oracle/status` — deja există
- Tab afișează workflow-uri, ultima execuție, conflicte

**3f. Tasks widget** în right panel (lângă CalendarCard):
- Consumă `GET /tasks` (deja există, dar returnează `[]`)
- Populat cu task-uri din autonomy queue (`/autonomy/tasks`)

### Fișiere modificate
- `agents/web.py` — endpoint-uri noi + `/dashboard` update
- `agents/web/static/data.js` — `loadJarvisData()` consumă `/ticker`, `/tasks`
- `agents/web/static/app.js` — state ticker wiring, noi widget-uri
- `agents/web/static/systems.js` — OAuthTab, OracleTab
- `agents/web/static/systems.css` — stiluri pentru taburi noi

---

## Arhitectură Generală

```
loadJarvisData()          SystemsPanel (mount)
     │                          │
     ├─ /api/agents             ├─ /api/resilience (P1)
     ├─ /status                 ├─ /api/memory/stats (P2a)
     ├─ /dashboard              ├─ /api/plugins (P2b)
     ├─ /tasks                  ├─ /api/learning/stats (P2c)
     ├─ /ticker (P3a)           ├─ /api/security/stats (P2d)
     └─ /api/cognition (P3b)   ├─ /api/bench/stats (P2d)
                                ├─ /api/oauth/status (P3d)
                                └─ /api/oracle/status (P3e)
```

Fiecare endpoint public expune date agregate din modulele corespunzătoare (orch.memory, orch.plugins, orch.learning, orch.security, orch.bench, etc.). Fallback: mock-urile din `data.js` rămân ca plasă de siguranță când serverul e pornit dar modulele nu-s inițializate.

---

## Testing
- Fiecare endpoint nou: test `client.get(...)` + assert response fields
- Fiecare tab component: test că se inițializează cu fallback data când endpoint e down
- Overall: `python -m pytest tests/ -v` — nimic nu trebuie să se rupă
