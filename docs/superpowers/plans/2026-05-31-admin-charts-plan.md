# H4.10 Admin Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add latency/usage/success rate charts to the Jarvis Hub admin panel.

**Architecture:** Backend aggregates data from LearningLoop + LatencyBenchmark into a single admin-guarded `/api/admin/stats` endpoint. Frontend renders SVG-based charts (horizontal bars, sparkline, stat cards) via vanilla React `createElement`.

**Tech Stack:** Python 3.12 + FastAPI, vanilla React (createElement, no JSX), SVG inline charts.

---

### Task 1: Backend — `/api/admin/stats` endpoint

**Files:**
- Modify: `agents/web.py` (add endpoint + `import statistics` at top)

- [ ] **Step 1: Add `import statistics` to web.py**

At `agents/web.py`, after `import time` (line 10), add:

```python
import statistics
from collections import defaultdict
from datetime import date, datetime
```

- [ ] **Step 2: Add the endpoint before the OAuth section (before line 976)**

Insert after the `_load_mcp_config()` function (line 974) and before the OAuth section:

```python
# ── Admin Charts endpoint ──────────────────────────────────────

@app.get("/api/admin/stats", dependencies=[Depends(_admin_guard)])
async def admin_stats():
    """Aggregated stats for admin charts: latency, usage, success rate."""
    interactions = getattr(orch.learning, 'interactions', [])
    samples = getattr(orch.bench, 'samples', [])

    total = len(interactions)
    successes = sum(1 for r in interactions if r.success)
    success_rate = successes / total if total else 0.0
    latencies = [r.latency for r in interactions if r.success and r.latency > 0]
    avg_latency = statistics.mean(latencies) if latencies else 0.0

    unique_agents = set(s.agent_id for s in samples) | set(r.agent_id for r in interactions)

    agents_list = []
    for aid in sorted(unique_agents):
        results = orch.bench.get_results(aid, last_n=100) if hasattr(orch.bench, 'get_results') else []
        if results:
            r = results[0]
            agents_list.append({
                "agent_id": aid,
                "samples": r.samples,
                "success_rate": round(r.success_rate, 3),
                "p50_latency": round(r.median_latency, 2),
                "p95_latency": round(r.p95_latency, 2),
                "avg_latency": round(r.mean_latency, 2),
                "model": r.model,
            })
        else:
            agent_records = [x for x in interactions if x.agent_id == aid]
            if agent_records:
                agent_lat = [x.latency for x in agent_records if x.success and x.latency > 0]
                agents_list.append({
                    "agent_id": aid,
                    "samples": len(agent_records),
                    "success_rate": round(sum(1 for x in agent_records if x.success) / len(agent_records), 3),
                    "p50_latency": round(statistics.median(agent_lat), 2) if len(agent_lat) > 1 else round(agent_lat[0], 2) if agent_lat else 0,
                    "p95_latency": 0,
                    "avg_latency": round(statistics.mean(agent_lat), 2) if agent_lat else 0,
                    "model": "",
                })

    daily_map = defaultdict(lambda: {"total": 0, "successful": 0, "failed": 0, "latencies": []})
    for r in interactions:
        d = date.fromtimestamp(r.timestamp).isoformat()
        daily_map[d]["total"] += 1
        if r.success:
            daily_map[d]["successful"] += 1
            if r.latency > 0:
                daily_map[d]["latencies"].append(r.latency)
        else:
            daily_map[d]["failed"] += 1
    daily = []
    for d in sorted(daily_map.keys()):
        entry = daily_map[d]
        daily.append({
            "date": d,
            "total": entry["total"],
            "successful": entry["successful"],
            "failed": entry["failed"],
            "avg_latency": round(statistics.mean(entry["latencies"]), 2) if entry["latencies"] else 0,
        })

    channels = defaultdict(int)
    for r in interactions:
        ch = (r.metadata or {}).get("channel", "unknown")
        channels[ch] += 1

    error_types = {}
    if hasattr(orch.learning, 'get_failure_patterns'):
        for aid in unique_agents:
            patterns = orch.learning.get_failure_patterns(aid)
            for err, count in patterns:
                error_types[err] = error_types.get(err, 0) + count
    error_types_list = sorted(error_types.items(), key=lambda x: -x[1])[:10]

    return _nocache_json({
        "overview": {
            "total_interactions": total,
            "success_rate": round(success_rate, 3),
            "avg_latency": round(avg_latency, 2),
            "agents_tracked": len(unique_agents),
        },
        "agents": agents_list,
        "daily": daily[-30:],
        "channels": dict(channels),
        "error_types": [[k, v] for k, v in error_types_list],
    })
```

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 10`
Expected: 504 passed, 8 skipped (no regressions)

- [ ] **Step 4: Commit**

```bash
git add agents/web.py
git commit -m "feat(admin): add /api/admin/stats endpoint for charts"
```

---

### Task 2: Tests for `/api/admin/stats`

**Files:**
- Create: `tests/test_admin_charts.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for admin charts endpoint."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


def test_stats_endpoint_structure(token_client):
    """GET /api/admin/stats returns expected JSON shape."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "overview" in data
    assert "agents" in data
    assert "daily" in data
    assert "channels" in data
    assert "error_types" in data
    ov = data["overview"]
    for key in ("total_interactions", "success_rate", "avg_latency", "agents_tracked"):
        assert key in ov


def test_stats_agents_has_expected_fields(token_client):
    """Each agent entry has expected fields."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    agents = resp.json().get("agents", [])
    if agents:
        for a in agents:
            for key in ("agent_id", "samples", "success_rate", "avg_latency"):
                assert key in a


def test_stats_daily_sorted_by_date(token_client):
    """Daily entries are sorted chronologically."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    daily = resp.json().get("daily", [])
    dates = [d["date"] for d in daily]
    assert dates == sorted(dates)


def test_stats_channels_is_dict(token_client):
    """Channels field is a dict."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    channels = resp.json().get("channels", {})
    assert isinstance(channels, dict)


def test_stats_error_types_is_list(token_client):
    """Error types is a list of [str, int] pairs."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    errors = resp.json().get("error_types", [])
    assert isinstance(errors, list)
    for item in errors:
        assert isinstance(item, list) and len(item) == 2
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_admin_charts.py -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_charts.py
git commit -m "test(admin): add tests for /api/admin/stats endpoint"
```

---

### Task 3: Frontend — i18n strings for charts

**Files:**
- Modify: `agents/web/static/i18n.js`

- [ ] **Step 1: Add chart translations**

After the `'mcp.disconnect_success':'Deconectat',` line, add:

```javascript
  'cat.charts':      'Charts',

  'desc.charts':     'Statistici utilizare, latență și succes rate pentru toți agenții.',

  'charts.total_int':    'Interacțiuni',
  'charts.success_rate': 'Success Rate',
  'charts.avg_latency':  'Latență medie',
  'charts.agents':       'Agenți monitorizați',
  'charts.no_data':      'Nicio interacțiune înregistrată încă.',
  'charts.success':      'Succes',
  'charts.failed':       'Eșec',
  'charts.latency':      'Latență',
  'charts.agent':        'Agent',
  'charts.calls':        'apeluri',
  'charts.sec':          's',
  'charts.channel':      'Canale',
  'charts.errors':       'Erori frecvente',
  'charts.daily_vol':    'Volum zilnic',
```

- [ ] **Step 2: Verify no syntax errors**

Run: `node --check agents/web/static/i18n.js`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add agents/web/static/i18n.js
git commit -m "i18n(admin): add chart translations"
```

---

### Task 4: Frontend — SVG chart components

**Files:**
- Modify: `agents/web/static/admin.js` (add charts icon, category, description, components, ChartsPage, wiring)

- [ ] **Step 1: Add charts SVG icon**

In the ICONS object (before the closing `};`), add after the `mcp` icon:

```javascript
  charts: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:2,y:12,width:4,height:6,rx:1}),
    h('rect',{x:8,y:7,width:4,height:11,rx:1}),
    h('rect',{x:14,y:2,width:4,height:16,rx:1}),
  ),
```

- [ ] **Step 2: Add charts category**

In `CATEGORIES`, add between `oracle` and `security`:
```javascript
  { id:'charts',   label:_t('cat.charts'),   icon:'charts' },
```

In `CATEGORY_DESC`, add:
```javascript
  charts:    _t('desc.charts'),
```

- [ ] **Step 3: Add SVG chart components + ChartsPage**

After the `MCPPage` component (before `function AdminApp()`), add the chart components:

```javascript
/* ── SVG Chart components ───────────────────────────────────── */

function StatsCard({ label, value, color }) {
  return h('div', {style:{
    background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',
    padding:'16px',flex:1,textAlign:'center',minWidth:120,
  }},
    h('div',{style:{fontSize:28,fontWeight:700,color:color||'var(--accent)'}}, value),
    h('div',{style:{fontSize:11,color:'var(--text-dim)',marginTop:4}}, label),
  );
}

function BarChart({ data, valueKey, labelKey, maxValue, colorFn, unit }) {
  if (!data || !data.length) return null;
  const max = maxValue || Math.max(...data.map(d => d[valueKey]), 0.01);
  const barH = 18;
  const gap = 4;
  const h = data.length * (barH + gap);
  const lw = 80;
  const cw = 260;
  const tw = lw + cw + 70;
  return h('svg',{viewBox:`0 0 ${tw} ${h}`,width:'100%',style:{maxWidth:tw,maxHeight:h}},
    data.map((d,i)=>{
      const y = i * (barH + gap);
      const ratio = Math.min(d[valueKey] / max, 1);
      const bw = Math.max(ratio * cw, 2);
      const c = typeof colorFn === 'function' ? colorFn(ratio) : 'var(--accent)';
      return [
        h('text',{key:`l${i}`,x:0,y:y+barH-4,fontSize:10,fill:'var(--text-secondary)'}, d[labelKey]||''),
        h('rect',{key:`b${i}`,x:lw,y:y,width:bw,height:barH-2,rx:2,fill:c,opacity:0.85}),
        h('text',{key:`v${i}`,x:lw+bw+4,y:y+barH-4,fontSize:9,fill:'var(--text-dim)'}, `${d[valueKey]}${unit||''}`),
      ];
    })
  );
}

function Sparkline({ data, width, height, color }) {
  if (!data || data.length < 2) return h('div',{style:{padding:12,fontSize:11,color:'var(--text-dim)'}},'—');
  const pad = {top:8,right:8,bottom:18,left:8};
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const vals = data.map(d=>d.value);
  const mx = Math.max(...vals,1);
  const mn = Math.min(...vals,0);
  const rng = mx - mn || 1;
  const pts = data.map((d,i)=>{
    const x = pad.left + (i/(data.length-1))*w;
    const y = pad.top + h - ((d.value-mn)/rng)*h;
    return `${x},${y}`;
  }).join(' ');
  const xLabels = data.map((d,i)=>{
    if (data.length>8 && i%Math.ceil(data.length/8)!==0 && i!==data.length-1) return null;
    return h('text',{key:`x${i}`,x:pad.left+(i/(data.length-1))*w,y:height-2,fontSize:8,fill:'var(--text-dim)',textAnchor:'middle'},d.label);
  });
  return h('svg',{viewBox:`0 0 ${width} ${height}`,width:'100%',style:{maxWidth:width,maxHeight:height}},
    h('text',{key:'ymx',x:0,y:pad.top+8,fontSize:9,fill:'var(--text-dim)'}, mx),
    ...xLabels,
    h('polyline',{key:'pl',points:pts,fill:'none',stroke:color||'var(--accent)',strokeWidth:1.5,strokeLinejoin:'round'}),
    h('polygon',{key:'pg',points:pts+` ${pad.left+w},${height-pad.bottom} ${pad.left},${height-pad.bottom}`,fill:color||'var(--accent)',opacity:0.06}),
  );
}

/* ── Charts page ────────────────────────────────────────────── */

function ChartsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/admin/stats').then(r=>r.json()).then(d=>{setData(d);setLoading(false)}).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('admin.loading'));
  if (!data || !data.overview) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('charts.no_data'));

  const ov = data.overview;
  const agents = (data.agents||[]).sort((a,b)=>b.success_rate - a.success_rate);
  const latencyAgents = (data.agents||[]).sort((a,b)=>b.p95_latency - a.p95_latency);
  const daily = (data.daily||[]).slice(-14).map(d=>({label:d.date.slice(5),value:d.total}));
  const channels = Object.entries(data.channels||{});
  const chMax = Math.max(...channels.map(c=>c[1]),1);
  const errors = data.error_types||[];

  const greenYellow = (r) => r > 0.8 ? '#4ade80' : r > 0.5 ? '#facc15' : '#f87171';

  return h('div',null,
    // Overview cards
    h('div',{style:{display:'flex',gap:12,marginBottom:20,flexWrap:'wrap'}},
      h(StatsCard,{label:_t('charts.total_int'),value:ov.total_interactions,color:'var(--accent)'}),
      h(StatsCard,{label:_t('charts.success_rate'),value:(ov.success_rate*100).toFixed(0)+'%',color:greenYellow(ov.success_rate)}),
      h(StatsCard,{label:_t('charts.avg_latency'),value:ov.avg_latency.toFixed(1)+'s',color:'#60a5fa'}),
      h(StatsCard,{label:_t('charts.agents'),value:ov.agents_tracked,color:'#a78bfa'}),
    ),

    // Per-agent success rate
    agents.length > 0 && h('div',{className:'admin-group'},
      h('div',{className:'admin-group-header'}, _t('charts.success')),
      h(BarChart,{data:agents.map(a=>({label:a.agent_id,value:a.success_rate*100})),
        valueKey:'value',labelKey:'label',maxValue:100,unit:'%',
        colorFn:(r)=>r>0.8?'#4ade80':r>0.5?'#facc15':'#f87171'}),
    ),

    // Per-agent latency (p95)
    latencyAgents.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.latency')),
      h(BarChart,{data:latencyAgents.map(a=>({label:a.agent_id,value:a.p95_latency||a.avg_latency})),
        valueKey:'value',labelKey:'label',unit:'s',colorFn:()=>'#60a5fa'}),
    ),

    // Daily volume sparkline
    daily.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.daily_vol')),
      h(Sparkline,{data:daily,width:500,height:80,color:'var(--accent)'}),
    ),

    // Channel breakdown
    channels.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.channel')),
      channels.map(([ch,count],i)=>h('div',{key:i,style:{display:'flex',alignItems:'center',gap:8,padding:'4px 0'}},
        h('span',{style:{width:80,fontSize:11,color:'var(--text-secondary)'}}, ch),
        h('div',{style:{flex:1,height:14,background:'var(--bg-glass)',borderRadius:7,overflow:'hidden'}},
          h('div',{style:{width:`${(count/chMax)*100}%`,height:'100%',background:'var(--accent)',opacity:0.7,borderRadius:7}}),
        ),
        h('span',{style:{fontSize:10,color:'var(--text-dim)',width:40,textAlign:'right'}}, count),
      )),
    ),

    // Error types
    errors.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.errors')),
      errors.map(([err,count],i)=>h('div',{key:i,style:{display:'flex',gap:8,padding:'3px 0',fontSize:11}},
        h('span',{style:{color:'var(--text-secondary)'}}, err),
        h('span',{style:{color:'#f87171',fontWeight:600}}, count),
      )),
    ),
  );
}
```

- [ ] **Step 4: Wire ChartsPage into AdminApp**

In the `AdminApp` function, after `const isMCP = active === 'mcp';`, add:
```javascript
  const isCharts = active === 'charts';
```

In the rendering section, after the `isMCP` branch:
```javascript
            : isCharts
              ? h(ChartsPage)
```

- [ ] **Step 5: Verify JS syntax**

Run: `node --check agents/web/static/admin.js`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add agents/web/static/admin.js
git commit -m "feat(admin): add ChartsPage with SVG bar charts and sparkline"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 10`
Expected: 509 passed, 8 skipped (504 existing + 5 new chart tests)

- [ ] **Step 2: Update BACKLOG.md**

Mark H4.10 as done, update totals in the status table.

- [ ] **Step 3: Final commit**

```bash
git add BACKLOG.md
git commit -m "docs: mark H4.10 Admin Charts complete"
```

---

## Files Changed Summary

| File | Change | Lines |
|------|--------|-------|
| `agents/web.py` | Add `import statistics`, `defaultdict`, `datetime` + `/api/admin/stats` endpoint | ~75 |
| `tests/test_admin_charts.py` | 5 endpoint tests | ~60 |
| `agents/web/static/i18n.js` | Chart translations (~20 strings) | ~20 |
| `agents/web/static/admin.js` | Charts icon, category, desc, 4 components, ChartsPage, wiring | ~200 |
| `BACKLOG.md` | Status update | ~2 |
