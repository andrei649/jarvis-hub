# Phase 1 — Resilience Tab in Main HUD

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live Resilience tab to the SystemsPanel in the main HUD (`/`), showing retry metrics and circuit breaker states from a new public endpoint.

**Architecture:** New `GET /api/resilience` endpoint (no admin auth) exposes `get_metrics().get_stats()` + `_circuit_breakers` dict. New `ResilienceTab` component in `systems.js` fetches on mount. `SystemsPanel` updated with `resilience` state + fetch + render.

**Tech Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX)

---

### Task 1: Public resilience endpoint

**Files:**
- Modify: `agents/web.py` (new route after line 1182)
- Test: `tests/test_resilience.py` (new test function)

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_resilience.py (test that endpoint returns expected structure)
def test_resilience_public_endpoint(client):
    resp = client.get("/api/resilience")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    assert "circuit_breakers" in data
```

Run: `python -m pytest tests/test_resilience.py::test_resilience_public_endpoint -v`
Expected: `FAILED` (404 — endpoint not found)

- [ ] **Step 2: Create endpoint in web.py**

Add after line 1182 (before `# ── OAuth endpoints`):

```python
@app.get("/api/resilience")
async def resilience_public():
    """Public resilience metrics and circuit breaker states (no admin auth)."""
    from core.resilience import get_metrics, _circuit_breakers
    metrics = get_metrics().get_stats()
    breakers = {
        key: {
            "state": cb.state,
            "failure_count": cb.failure_count,
            "last_failure_time": cb.last_failure_time,
        }
        for key, cb in _circuit_breakers.items()
    }
    return _nocache_json({"metrics": metrics, "circuit_breakers": breakers})
```

Run: `python -m pytest tests/test_resilience.py::test_resilience_public_endpoint -v`
Expected: `PASSED`

- [ ] **Step 3: Commit**

```bash
git add agents/web.py tests/test_resilience.py
git commit -m "feat: add public /api/resilience endpoint"
```

---

### Task 2: ResilienceTab component

**Files:**
- Modify: `agents/web/static/systems.js` (add ResilienceTab function + export)
- Modify: `agents/web/static/systems.css` (add resilience styles)

- [ ] **Step 1: Write failing test**

```python
# tests/test_resilience.py
@pytest.mark.asyncio
async def test_resilience_tab_render(client):
    """Verify resilience endpoint returns valid data for UI render."""
    resp = client.get("/api/resilience")
    data = resp.json()
    # Circuit breaker entries must have state, failure_count
    for key, cb in data.get("circuit_breakers", {}).items():
        assert "state" in cb
        assert "failure_count" in cb
```

Run: `python -m pytest tests/test_resilience.py::test_resilience_tab_render -v`
Expected: `PASSED` (data structure already correct from Task 1)

- [ ] **Step 2: Add ResilienceTab function to systems.js**

Add to `agents/web/static/systems.js`, after `SecurityBenchTab` function (before `SystemsPanel`):

```javascript
function ResilienceTab({ data }) {
  if (!data) return h('div', { className: 'sys-loading' }, 'Loading resilience data...');

  const metrics = data.metrics || {};
  const breakers = data.circuit_breakers || {};
  const metricKeys = Object.keys(metrics);
  const breakerKeys = Object.keys(breakers);

  return h('div', { className: 'sys-tab-content' },
    metricKeys.length === 0 && breakerKeys.length === 0
      ? h('div', { className: 'sys-empty' }, 'No resilience data recorded yet. Data appears after API calls are made.')
      : null,

    metricKeys.length > 0 && h('div', { className: 'sys-card wide', style: { marginTop: 0 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'RETRY METRICS')
      ),
      h('div', { className: 'sys-resilience-grid' },
        metricKeys.map(key =>
          h('div', { key, className: 'sys-resilience-card' },
            h('div', { className: 'sys-resilience-key' }, key),
            h('div', { className: 'sys-resilience-stats' },
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Success'),
                h('span', { className: 'sys-stat-val accent' }, metrics[key].success)
              ),
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Failure'),
                h('span', { className: 'sys-stat-val warn' }, metrics[key].failure)
              ),
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Avg latency'),
                h('span', { className: 'sys-stat-val mono' }, metrics[key].avg_latency.toFixed(2) + 's')
              ),
              metrics[key].error_types && Object.keys(metrics[key].error_types).length > 0
                ? h('div', { className: 'sys-resilience-errors' },
                    Object.entries(metrics[key].error_types).map(([err, count]) =>
                      h('div', { key: err, className: 'sys-error-row' },
                        h('span', { className: 'sys-error-name' }, err),
                        h('span', { className: 'sys-error-count' }, count)
                      )
                    )
                  )
                : null
            )
          )
        )
      )
    ),

    breakerKeys.length > 0 && h('div', { className: 'sys-card wide', style: { marginTop: 12 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'CIRCUIT BREAKERS')
      ),
      h('div', { className: 'sys-cb-grid' },
        breakerKeys.map(key =>
          h('div', {
            key,
            className: 'sys-cb-row ' + breakers[key].state,
          },
            h('div', { className: 'sys-cb-head' },
              h('span', { className: 'sys-cb-key' }, key),
              h('span', { className: 'sys-cb-state ' + breakers[key].state },
                breakers[key].state.toUpperCase()
              )
            ),
            h('div', { className: 'sys-cb-detail' },
              h('span', {}, 'Failures: ' + breakers[key].failure_count),
              breakers[key].last_failure_time
                ? h('span', { className: 'sys-cb-time' },
                    'Last: ' + new Date(breakers[key].last_failure_time * 1000).toLocaleString()
                  )
                : null
            )
          )
        )
      )
    )
  );
}
```

- [ ] **Step 3: Add resilience CSS styles**

Add to `agents/web/static/systems.css`:

```css
.sys-resilience-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:8px; }
.sys-resilience-card { background:var(--bg-glass); border-radius:6px; padding:10px; }
.sys-resilience-key { font-weight:600; font-size:11px; color:var(--text-secondary); margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px; }
.sys-resilience-stats { display:flex; flex-direction:column; gap:4px; }
.sys-resilience-errors { margin-top:6px; padding-top:6px; border-top:1px solid rgba(255,255,255,.08); }
.sys-error-row { display:flex; justify-content:space-between; font-size:10px; padding:2px 0; }
.sys-error-name { color:var(--text-dim); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; }
.sys-error-count { color:#f87171; font-weight:600; margin-left:8px; }
.sys-cb-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:8px; }
.sys-cb-row { background:var(--bg-glass); border-radius:6px; padding:10px; border-left:3px solid var(--text-dim); }
.sys-cb-row.closed { border-left-color:#4ade80; }
.sys-cb-row.half-open { border-left-color:#facc15; }
.sys-cb-row.open { border-left-color:#f87171; background:rgba(248,113,113,.08); }
.sys-cb-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
.sys-cb-key { font-weight:600; font-size:11px; color:var(--text-secondary); text-transform:uppercase; letter-spacing:.5px; }
.sys-cb-state { font-size:10px; font-weight:700; padding:2px 6px; border-radius:3px; }
.sys-cb-state.closed { background:rgba(74,222,128,.15); color:#4ade80; }
.sys-cb-state.half-open { background:rgba(250,204,21,.15); color:#facc15; }
.sys-cb-state.open { background:rgba(248,113,113,.15); color:#f87171; }
.sys-cb-detail { display:flex; flex-direction:column; gap:2px; font-size:10px; color:var(--text-dim); }
.sys-cb-time { color:var(--text-dim); font-size:9px; }
```

- [ ] **Step 4: Commit**

```bash
git add agents/web/static/systems.js agents/web/static/systems.css
git commit -m "feat: add ResilienceTab component"
```

---

### Task 3: Wire ResilienceTab into SystemsPanel

**Files:**
- Modify: `agents/web/static/systems.js` (TABS array + SystemsPanel component)

- [ ] **Step 1: Add resilience to TABS array**

Update the `TABS` constant:

```javascript
const TABS = [
  { id: 'memory',     label: 'Memory' },
  { id: 'plugins',    label: 'Plugins' },
  { id: 'heartbeats', label: 'Heartbeats' },
  { id: 'learning',   label: 'Learning' },
  { id: 'resilience', label: 'Resilience' },
  { id: 'security',   label: 'Security & Bench' },
];
```

- [ ] **Step 2: Add resilience state + fetch in SystemsPanel**

Add `resilience` state and fetch effect. After `const [heartbeatStatus, setHeartbeatStatus] = useState(null);`:

```javascript
const [resilience, setResilience] = useState(null);
```

After `fetchHeartbeatStatus` callback, add fetch callback:

```javascript
const fetchResilience = useCallback(async () => {
  try {
    const res = await fetch('/api/resilience');
    const data = await res.json();
    setResilience(data);
  } catch (err) {
    console.error('Failed to fetch resilience:', err);
  }
}, []);
```

Add useEffect after heartbeat useEffect:

```javascript
useEffect(() => {
  fetchResilience();
}, [fetchResilience]);
```

Add to handleRefresh callback (after heartbeat branch):

```javascript
if (activeTab === 'resilience') fetchResilience();
```

- [ ] **Step 3: Add resilience tab render in SystemsPanel return**

Add between learning tab and security tab:

```javascript
activeTab === 'resilience' && h(ResilienceTab, { data: resilience }),
```

- [ ] **Step 4: Export ResilienceTab**

Add to the final `Object.assign` line:

```javascript
Object.assign(window, { SystemsPanel, SystemsTabBar, MemoryTab, PluginsTab, HeartbeatsTab, LearningTab, SecurityBenchTab, ResilienceTab });
```

- [ ] **Step 5: Full test run**

Run: `python -m pytest tests/test_resilience.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add agents/web/static/systems.js
git commit -m "feat: wire ResilienceTab into SystemsPanel"
```

---

### Task 4: Verify with server smoke test

- [ ] **Step 1: Start server and verify resilience endpoint**

Run: `python -c "import requests; r=requests.get('http://127.0.0.1:8080/api/resilience'); print(r.status_code, r.json())"`

Expected: 200 + `{"metrics":{},"circuit_breakers":{}}`

- [ ] **Step 2: Full test suite**

Run: `python -m pytest tests/ -q`
Expected: All tests pass (660 passed, 8 skipped)

- [ ] **Step 3: Update BACKLOG.md — mark H5.9 in progress**

Add `🔄` or similar marker to H5.9 row.

```bash
git add BACKLOG.md
git commit -m "chore: start H5.9 resilience tab"
```
