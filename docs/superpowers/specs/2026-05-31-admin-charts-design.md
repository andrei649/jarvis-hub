# H4.10 — Admin Charts Design

> Spec for latency/usage/success rate charts in the Jarvis Hub admin panel.
> Owner: Andrei · S:8 · Priority: P3 · Dep: H3.1, H3.4

## Architecture

```
Browser (admin.js)                Server (web.py)
┌─────────────────────┐          ┌─────────────────────┐
│  ChartsPage          │  GET    │  /api/admin/stats    │
│  ├─ StatsCard x3     │◄────────┤  (_admin_guard)      │
│  ├─ BarChart x2      │         │                      │
│  ├─ Sparkline        │  JSON   │  orch.learning       │
│  └─ ChannelTable     │────────►│  orch.bench          │
└─────────────────────┘          └─────────────────────┘
```

No external chart libraries. Pure SVG via React `createElement`.

## Backend: `/api/admin/stats`

### Endpoint

```python
@app.get("/api/admin/stats", dependencies=[Depends(_admin_guard)])
async def admin_stats():
```

### Response Shape

```json
{
  "overview": {
    "total_interactions": 2200,
    "success_rate": 0.87,
    "avg_latency": 4.2,
    "agents_tracked": 15
  },
  "agents": [
    {
      "agent_id": "vision",
      "samples": 421,
      "success_rate": 0.92,
      "p50_latency": 3.1,
      "p95_latency": 8.7,
      "avg_latency": 3.8,
      "model": "claude-sonnet-4"
    }
  ],
  "daily": [
    {
      "date": "2026-05-25",
      "total": 42,
      "successful": 38,
      "failed": 4,
      "avg_latency": 3.9
    }
  ],
  "channels": {
    "web": 1800,
    "telegram": 300,
    "voice": 100
  },
  "error_types": [
    ["timeout", 42],
    ["rate_limit", 18]
  ]
}
```

### Aggregation Logic

| Field | Source | Method |
|-------|--------|--------|
| `overview.total_interactions` | `orch.learning.interactions` | `len()` |
| `overview.success_rate` | `orch.learning.interactions` | `sum(success) / total` |
| `overview.avg_latency` | `orch.learning.interactions` | `mean(latency)` of successful |
| `agents[*]` | `orch.bench` | `get_results()` for each unique agent |
| `daily[*]` | `orch.learning.interactions` | Group by `date.fromtimestamp(r.timestamp)`, last 30 days |
| `channels` | `orch.learning.interactions` | Count by `r.metadata.get("channel", "unknown")` |
| `error_types` | `orch.learning` | Aggregate `get_failure_patterns` across all agents |

### Edge Cases

- **No interactions:** Return defaults (zero counts, empty arrays)
- **Single agent:** Still returns agents array with one entry
- **Zero latency samples:** `avg_latency = 0`, skip p95
- **No daily data:** Empty `daily` array
- **Missing channel metadata:** Count as `"unknown"`

## Frontend: ChartsPage

### Category Entry

```javascript
{ id:'charts', label:'Charts', icon:'charts' }
```

SVG icon: simple bar chart (3 vertical bars).

### Layout

Scrolling page (no tabs), top-to-bottom:

1. **3 StatsCards** — total interactions, success rate (colored green/yellow/red), avg latency
2. **Per-agent success rate** — horizontal bar chart, sorted by rate descending
3. **Per-agent latency (p95)** — horizontal bar chart, sorted by p95 ascending
4. **Daily volume sparkline** — SVG polyline, last 14 days, with day labels
5. **Channel breakdown** — simple rows with count + horizontal bar
6. **Error types** — if any errors exist, list with counts

### SVG Chart Components

**StatsCard** — `<div>` with large number + label + unit, no SVG needed.

**BarChart** — reusable horizontal bar component:
```javascript
function BarChart({ data, valueKey, labelKey, color, maxValue, unit }) {
  // data = [{label: "vision", value: 92}, ...]
  // Renders: SVG with <rect> per row, width proportional to value/maxValue
  // Color: interpolate green (high) → yellow (mid) → red (low) based on ratio
}
```

**Sparkline** — timeseries line chart:
```javascript
function Sparkline({ data, width, height }) {
  // data = [{label: "Mon", value: 42}, ...]
  // Renders: <polyline> with normalized points + X/Y axis labels
  // Points: map value to Y, index to X within width/height
}
```

### State Management

```javascript
function ChartsPage({ onToast }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/admin/stats')
      .then(r => r.json())
      .then(d => { setStats(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);
}
```

Auto-refresh on mount only (no polling — these are historical, not live).

### Empty States

- **Loading:** "Se încarcă..." (standard admin pattern)
- **No data:** "No interactions recorded yet" with suggestions
- **Error:** Toast notification, show empty state

## Testing

| Test | What it checks |
|------|---------------|
| `test_stats_endpoint_returns_200` | GET /api/admin/stats returns 200 |
| `test_stats_overview_fields` | All overview keys present |
| `test_stats_agents_list` | Agents array has expected structure |
| `test_stats_daily_grouping` | Daily array sorted by date |
| `test_stats_no_data` | Fresh LearningLoop returns empty defaults |
| `test_stats_page_renders` | ChartsPage mounts without crash |

Test file: `tests/test_admin_charts.py`

## Files Changed

| File | Change |
|------|--------|
| `agents/web.py` | Add `/api/admin/stats` endpoint (~40 lines) |
| `agents/web/static/admin.js` | Add charts icon, category, `ChartsPage` component (~150 lines) |
| `agents/web/static/i18n.js` | Add chart translations (~10 lines) |
| `tests/test_admin_charts.py` | New test file (~60 lines) |

## Non-Goals

- No token usage/cost tracking (not available in data sources)
- No real-time updates (data is historical, refresh on page visit)
- No export/download of chart data
- No interactive chart features (tooltips, zoom)
