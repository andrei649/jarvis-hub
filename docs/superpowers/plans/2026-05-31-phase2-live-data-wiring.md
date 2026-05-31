# Phase 2 — Live Data Wiring (H5.10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static mock data (MEMORY_STATS, PLUGINS, LEARNING, SECURITY, BENCH) in 5 SystemsPanel tabs with live API endpoints. Same pattern as the resilience/heartbeat tabs.

**Architecture:** 4 new/fixed endpoints in web.py → SystemsPanel fetches on mount → data flows to tab components. Props memory/plugins/learning/security/bench removed from SystemsPanel and App.js.

**Tech Stack:** Python 3.12 + FastAPI + vanilla React (createElement)

---

### Task 1: Fix `/api/learning/stats` endpoint

**Files:**
- Modify: `agents/web.py` (fix broken learning stats endpoint)
- Test: `tests/test_learning_api.py`

**Context:** Current endpoint at line ~1399 references `orch.learning_loop` (wrong attr) and nonexistent methods. Replace with working code using `orch.learning.get_stats()` etc.

- [ ] **Step 1: Read the current broken endpoint**

Read `C:\Users\andre\cabinet\agents\web.py` around line 1395-1420.

- [ ] **Step 2: Write failing test**

Add to a new test file or appropriate existing test:

```python
def test_learning_stats_endpoint():
    from fastapi.testclient import TestClient
    from agents import web
    client = TestClient(web.app)
    resp = client.get("/api/learning/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_interactions" in data or "interactions_total" in data
```

- [ ] **Step 3: Implement the fix**

Replace the broken endpoint body with:
```python
@app.get("/api/learning/stats")
async def learning_stats():
    """Live learning stats for SystemsPanel."""
    if not orch or not hasattr(orch, 'learning') or not orch.learning:
        return _nocache_json({"interactions_total": 0, "success_rate": 0, "prompt_optimizations": [], "promotion_candidates": [], "demotion_warnings": []})
    try:
        stats = orch.learning.get_stats()
        agents = list(stats.get("agents_tracked", stats.get("active_ids", [])))
        optimizations = []
        for aid in agents:
            opt = orch.learning.optimize_prompt(aid)
            if opt:
                optimizations.append({"agent": aid, "before": "", "after": opt, "improvement": ""})
        promotions = orch.learning.suggest_promotions(agents) if hasattr(orch.learning, 'suggest_promotions') else []
        promos = [{"agent": p.get("bench_agent", p.get("agent", "")), "triggers": p.get("count", 0), "threshold": p.get("threshold", 0)} for p in promotions]
        total = stats.get("total_interactions", 0)
        successful = stats.get("successful", 0)
        rate = successful / total if total > 0 else 0
        return _nocache_json({
            "interactions_total": total,
            "success_rate": round(rate, 3),
            "prompt_optimizations": optimizations,
            "promotion_candidates": promos,
            "demotion_warnings": [],
        })
    except Exception:
        return _nocache_json({"interactions_total": 0, "success_rate": 0, "prompt_optimizations": [], "promotion_candidates": [], "demotion_warnings": []})
```

- [ ] **Step 4: Verify tests pass**

Run: `python -m pytest tests/test_learning_api.py -v` or the test you created

- [ ] **Step 5: Commit**

```bash
git add agents/web.py tests/test_learning_api.py
git commit -m "fix: repair /api/learning/stats endpoint"
```

---

### Task 2: Create `/api/memory/stats` endpoint

**Files:**
- Modify: `agents/web.py` (add memory stats endpoint)
- Test: `tests/test_memory_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_memory_stats_endpoint():
    from fastapi.testclient import TestClient
    from agents import web
    client = TestClient(web.app)
    resp = client.get("/api/memory/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert "vectors" in data
```

- [ ] **Step 2: Create endpoint in web.py**

Add before the existing `/memory` route or near other public endpoints:
```python
@app.get("/api/memory/stats")
async def memory_stats():
    """Live memory stats for SystemsPanel."""
    if not orch or not hasattr(orch, 'memory') or not orch.memory:
        return _nocache_json({"sessions": {"total": 0, "current": "", "active": 0}, "vectors": {"stored": 0, "dimension": 0, "backend": ""}, "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""}, "agent_contexts": {}})
    try:
        sess = orch.memory.get_session_stats()
        contexts = {}
        if hasattr(orch.memory, 'agent_contexts'):
            for aid, ctx in orch.memory.agent_contexts.items():
                contexts[aid] = len(ctx) if isinstance(ctx, dict) else (len(ctx) if hasattr(ctx, '__len__') else 0)
        kg_entities = 0
        kg_relations = 0
        if hasattr(orch.memory, 'graph') and orch.memory.graph:
            try:
                kg_entities = len(orch.memory.graph.entities) if hasattr(orch.memory.graph, 'entities') else 0
                kg_relations = len(orch.memory.graph.relations) if hasattr(orch.memory.graph, 'relations') else 0
            except Exception:
                pass
        return _nocache_json({
            "sessions": {"total": sess.get("sessions", 0), "current": sess.get("current_session", ""), "active": sess.get("active", 0)},
            "vectors": {"stored": sess.get("vectors", 0), "dimension": 768 if sess.get("vectors", 0) > 0 else 0, "backend": "qdrant" if sess.get("vectors", 0) > 0 else ""},
            "knowledge_graph": {"entities": kg_entities, "relations": kg_relations, "last_seed": ""},
            "agent_contexts": contexts,
        })
    except Exception:
        return fallback
```

- [ ] **Step 3: Verify tests pass**

- [ ] **Step 4: Commit**

```bash
git add agents/web.py tests/test_memory_api.py
git commit -m "feat: add /api/memory/stats endpoint"
```

---

### Task 3: Wire Memory tab to live endpoint

**Files:**
- Modify: `agents/web/static/systems.js` (add memoryData state + fetch + remove memory prop)
- Modify: `agents/web/static/app.js` (remove memory from SystemsPanel props)

- [ ] **Step 1: Add memoryData state + fetch in SystemsPanel**

Add after resilience state:
```javascript
const [memoryData, setMemoryData] = useState(null);
```

Add after fetchResilience:
```javascript
const fetchMemory = useCallback(async () => {
  try {
    const res = await fetch('/api/memory/stats');
    setMemoryData(await res.json());
  } catch (err) { console.error('Failed to fetch memory:', err); }
}, []);
```

Add after resilience useEffect:
```javascript
useEffect(() => { fetchMemory(); }, [fetchMemory]);
```

Add to handleRefresh:
```javascript
if (activeTab === 'memory') fetchMemory();
```

Update render:
```javascript
activeTab === 'memory' && h(MemoryTab, { data: memoryData, onRefresh: handleRefresh }),
```

- [ ] **Step 2: Remove memory from SystemsPanel props**

Change destructuring from:
```javascript
function SystemsPanel({ memory, plugins, learning, security, bench, agents, onRefresh, onPluginToggle }) {
```
to:
```javascript
function SystemsPanel({ agents, onRefresh, onPluginToggle }) {
```

- [ ] **Step 3: Update App.js**

Change from:
```javascript
h(SystemsPanel, {
  memory: MEMORY_STATS,
  plugins: PLUGINS,
  learning: LEARNING,
  security: SECURITY,
  bench: BENCH,
  agents: agents,
  onRefresh: function (tab) { console.log('refresh systems tab:', tab); },
  onPluginToggle: function (id) { console.log('toggle plugin:', id); },
}),
```
to:
```javascript
h(SystemsPanel, {
  agents: agents,
  onRefresh: function (tab) { console.log('refresh systems tab:', tab); },
  onPluginToggle: function (id) { console.log('toggle plugin:', id); },
}),
```

- [ ] **Step 4: Commit**

```bash
git add agents/web/static/systems.js agents/web/static/app.js
git commit -m "feat: wire Memory tab to live /api/memory/stats"
```

---

### Task 4: Wire Plugins tab to live endpoint

Same pattern as Task 3 but for plugins.

**Files:**
- Modify: `agents/web.py` (add `/api/plugins` endpoint if not already at public path)
- Modify: `agents/web/static/systems.js`
- Modify: `agents/web/static/app.js` (already done in Task 3)
- Test: appropriate test file

- [ ] **Step 1: Check if `/api/plugins` endpoint exists**

It does at line ~1364 in web.py, verify it's working.

- [ ] **Step 2: Add pluginsData state + fetch in SystemsPanel**

```javascript
const [pluginsData, setPluginsData] = useState(null);

const fetchPlugins = useCallback(async () => {
  try {
    const res = await fetch('/api/plugins');
    setPluginsData(await res.json());
  } catch (err) { console.error('Failed to fetch plugins:', err); }
}, []);

useEffect(() => { fetchPlugins(); }, [fetchPlugins]);

// In handleRefresh:
if (activeTab === 'plugins') fetchPlugins();

// In render:
activeTab === 'plugins' && h(PluginsTab, { data: pluginsData, onToggle: onPluginToggle, onRefresh: handleRefresh }),
```

- [ ] **Step 3: Commit**

```bash
git add agents/web/static/systems.js
git commit -m "feat: wire Plugins tab to live /api/plugins"
```

---

### Task 5: Wire Learning tab to live endpoint

**Files:**
- Modify: `agents/web/static/systems.js`

Same pattern as Task 3:
- learningData state + fetchLearning callback + useEffect + handleRefresh branch + render update

- [ ] **Step 1: Implement in systems.js**

```javascript
const [learningData, setLearningData] = useState(null);

const fetchLearning = useCallback(async () => {
  try {
    const res = await fetch('/api/learning/stats');
    setLearningData(await res.json());
  } catch (err) { console.error('Failed to fetch learning:', err); }
}, []);

useEffect(() => { fetchLearning(); }, [fetchLearning]);

// In handleRefresh:
if (activeTab === 'learning') fetchLearning();

// In render:
activeTab === 'learning' && h(LearningTab, { data: learningData, onRefresh: handleRefresh }),
```

- [ ] **Step 2: Commit**

```bash
git add agents/web/static/systems.js
git commit -m "feat: wire Learning tab to live /api/learning/stats"
```

---

### Task 6: Wire Security & Bench tab to live endpoints

**Files:**
- Modify: `agents/web/static/systems.js` (add securityData + benchData state + fetch)
- Modify: `agents/web/static/app.js` (already done)

- [ ] **Step 1: Add securityData + benchData state + fetch in SystemsPanel**

```javascript
const [securityData, setSecurityData] = useState(null);
const [benchData, setBenchData] = useState(null);

const fetchSecurity = useCallback(async () => {
  try {
    const res = await fetch('/security/status');
    setSecurityData(await res.json());
  } catch (err) { console.error('Failed to fetch security:', err); }
}, []);

const fetchBench = useCallback(async () => {
  try {
    const res = await fetch('/api/bench/stats');
    setBenchData(await res.json());
  } catch (err) { console.error('Failed to fetch bench:', err); }
}, []);

useEffect(() => { fetchSecurity(); }, [fetchSecurity]);
useEffect(() => { fetchBench(); }, [fetchBench]);

// In handleRefresh:
if (activeTab === 'security') { fetchSecurity(); fetchBench(); }

// In render:
activeTab === 'security' && h(SecurityBenchTab, { security: securityData, bench: benchData, onRefresh: handleRefresh }),
```

- [ ] **Step 2: Commit**

```bash
git add agents/web/static/systems.js
git commit -m "feat: wire Security & Bench tabs to live endpoints"
```

---

### Task 7: Update handleRefresh dependencies

- [ ] **Step 1: Fix deps array**

After adding all new callbacks, update handleRefresh useCallback deps:
```javascript
const handleRefresh = useCallback(() => {
  if (onRefresh) onRefresh(activeTab);
  if (activeTab === 'heartbeats') fetchHeartbeatStatus();
  if (activeTab === 'resilience') fetchResilience();
  if (activeTab === 'memory') fetchMemory();
  if (activeTab === 'plugins') fetchPlugins();
  if (activeTab === 'learning') fetchLearning();
  if (activeTab === 'security') { fetchSecurity(); fetchBench(); }
}, [activeTab, onRefresh, fetchHeartbeatStatus, fetchResilience, fetchMemory, fetchPlugins, fetchLearning, fetchSecurity, fetchBench]);
```

- [ ] **Step 2: Full test run**

Run: `python -m pytest tests/test_resilience.py tests/test_resilience_integration.py -v`

- [ ] **Step 3: Commit**

```bash
git add agents/web/static/systems.js
git commit -m "fix: update handleRefresh dependencies"
```

---

### Task 8: Verify

- [ ] **Step 1: Start server and smoke test endpoints**

Run each:
```bash
curl http://127.0.0.1:8001/api/memory/stats
curl http://127.0.0.1:8001/api/plugins
curl http://127.0.0.1:8001/api/learning/stats
curl http://127.0.0.1:8001/api/bench/stats
curl http://127.0.0.1:8001/security/status
```

All should return 200.

- [ ] **Step 2: Update BACKLOG.md**

Mark H5.10 as done.

- [ ] **Step 3: Commit**

```bash
git add BACKLOG.md
git commit -m "chore: mark H5.10 complete"
```
