# Implementation Plan: Gecko + Stark + Cross-cutting

> Sub-skills: subagent-driven-development or manual per task

**Architecture notes:**
- Plugins follow existing pattern: `__init__(**creds)`, async methods, graceful degradation
- Settings DB DEFAULTS use `kind: "text"` for API keys (local-first, SQLite on local machine)
- Mock mode: when no credentials configured, return realistic sample data with `"mock": true` flag

---

### Task 1: Gecko BalanceReaderPlugin

**Files:**
- Create: `agents/core/plugins/balance.py` — BalanceReaderPlugin
- Modify: `agents/core/settings_db.py` — add DEFAULTS for gecko keys
- Modify: `agents/core/orchestrator.py` — register plugin + expose config
- Create: `tests/test_balance.py` — 8+ tests

**Plugin API:**
```python
class BalanceReaderPlugin:
    def __init__(self, ing_client_id="", ing_client_secret="", libra_token="", csv_path=""):
        ...

    async def get_balances(self) -> dict:
        """Returns {source: {account: amount, currency, ...}, ...}"""
        ...

    async def get_summary(self) -> str:
        """Formatted string for agent consumption."""
        ...

    async def get_burn_rate(self, days=30) -> dict:
        """Monthly spend, runway, trends."""
        ...

    def available(self) -> bool:
        """True if any source is configured."""
```

**Settings DEFAULTS additions:**
```python
dict(category="plugins", key="gecko_ing_client_id", value="", label="Gecko - ING Client ID", kind="text", opts=[]),
dict(category="plugins", key="gecko_ing_client_secret", value="", label="Gecko - ING Client Secret", kind="text", opts=[]),
dict(category="plugins", key="gecko_libra_token", value="", label="Gecko - Libra API Token", kind="text", opts=[]),
dict(category="plugins", key="gecko_csv_path", value="", label="Gecko - CSV export path", kind="text", opts=[]),
```

**Mock data** (when unconfigured):
```json
{"ing": [{"account": "RO12INGB1234567890", "balance": 12450.32, "currency": "RON"}],
 "libra": [{"account": "LIBRA123456", "balance": 3200.00, "currency": "RON"}],
 "mock": true}
```

**Orchestrator wiring** — in `load_agents()`:
```python
gecko_ing_id = self.get_setting("plugins.gecko_ing_client_id", "")
gecko_ing_secret = self.get_setting("plugins.gecko_ing_client_secret", "")
gecko_libra = self.get_setting("plugins.gecko_libra_token", "")
gecko_csv = self.get_setting("plugins.gecko_csv_path", "")
self.plugins["balance"] = BalanceReaderPlugin(
    ing_client_id=gecko_ing_id,
    ing_client_secret=gecko_ing_secret,
    libra_token=gecko_libra,
    csv_path=gecko_csv,
)
```

**Tests:**
- `test_init_unconfigured` — no creds → `available()` is False
- `test_get_balances_mock` — mock data returned when unconfigured
- `test_get_summary_mock` — formatted string returned
- `test_get_burn_rate_mock` — burn rate calculated from mock
- `test_available_true` — with creds → returns True
- `test_close` — no error
- `test_get_balances_with_ing_configured` — ING configured → attempts API (mock httpx)
- `test_get_balances_network_error` — API down → graceful fallback

---

### Task 2: Stark AnalyticsPlugin

**Files:**
- Create: `agents/core/plugins/analytics.py` — AnalyticsPlugin
- Modify: `agents/core/settings_db.py` — add DEFAULTS for GA4 service account
- Modify: `agents/core/orchestrator.py` — register plugin
- Create: `tests/test_analytics.py` — 8+ tests

**Plugin API:**
```python
class AnalyticsPlugin:
    def __init__(self, ga4_service_account: str = "", ga4_property_id: str = ""):
        ...

    async def get_kpis(self, days: int = 30) -> dict:
        """Daily active users, page views, sessions, conversion rate."""
        ...

    async def get_summary(self) -> str:
        """Formatted KPI summary for agent."""
        ...

    async def get_campaign_performance(self) -> dict:
        """Campaign metrics: impressions, clicks, spend, ROAS."""
        ...

    def available(self) -> bool:
        """True if GA4 SA is configured."""
```

**Settings DEFAULTS:**
```python
dict(category="plugins", key="stark_ga4_service_account", value="", label="Stark - GA4 Service Account JSON", kind="text", opts=[]),
dict(category="plugins", key="stark_ga4_property_id", value="", label="Stark - GA4 Property ID", kind="text", opts=[]),
```

**Mock data:**
```json
{"daily_users": 1420, "page_views": 8900, "sessions": 5600,
 "conversion_rate": 0.032, "revenue": 45200, "mock": true}
```

**Orchestrator wiring:**
```python
ga4_sa = self.get_setting("plugins.stark_ga4_service_account", "")
ga4_pid = self.get_setting("plugins.stark_ga4_property_id", "")
self.plugins["analytics"] = AnalyticsPlugin(ga4_service_account=ga4_sa, ga4_property_id=ga4_pid)
```

---

### Task 3: Plans per agent

**Files:**
- Modify: `.opencode/plans/` — one file per active agent

Create plan files for all active agents (15+):
- `jarvis_spec.md`, `friday_spec.md`, `pepper_spec.md`, `vision_spec.md`, `frigga_spec.md`,
  `ultron_spec.md`, `hercules_spec.md`, `jerome_spec.md`, `hephaestus_spec.md`,
  `veronica_spec.md`, `steve_spec.md`, `athena_spec.md`, `howard_spec.md`,
  `gecko_spec.md`, `stark_spec.md`, `bruce_spec.md`, `wanda_spec.md`

Each follows template:
```markdown
# Agent: <name>
> Role: ...
> Models: ...

## Skills
- <skill_name> — <purpose> (file: skills/<name>/)

## Tools
- <plugin> — <purpose>

## Memory
- <what this agent stores/retrieves>

## Triggers
- <heartbeat, wake words, etc.>
```

---

### Task 4: Load test

**Files:**
- Create: `tests/test_load.py`

```python
"""Load test: 15 parallel agent requests, verify <30s total."""
import sys, time, asyncio, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from core.agent import Agent
from core.router import IntentRouter

class _FakeBackend:
    async def generate(self, *a, **kw):
        await asyncio.sleep(0.5)
        return "[mock reply]"

class _FakeRouter:
    def select_backend(self, agent_id, prompt):
        return _FakeBackend(), {"backend": "mock"}
    def detect(self):
        pass
    @property
    def backend(self):
        return _FakeBackend()
    @property
    def name(self):
        return "mock"

AGENTS = ["jarvis","friday","pepper","vision","frigga","ultron","hercules",
          "jerome","hephaestus","veronica","steve","athena","howard","gecko","stark"]

@pytest.mark.asyncio
async def test_15_agents_under_30s():
    router = _FakeRouter()
    start = time.time()
    tasks = []
    for aid in AGENTS:
        agent = Agent(aid, {"name": aid.capitalize()}, router)
        agent.guardrails = None
        tasks.append(agent.process("hello", {}))
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start
    assert elapsed < 30, f"Took {elapsed:.2f}s"
    assert all("[mock reply]" in r for r in results)
```
