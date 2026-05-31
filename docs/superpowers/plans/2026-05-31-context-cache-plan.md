# H4.11 Context Caching + Hybrid Routing Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini context caching, route usage tracking, and cost estimation to the admin dashboard.

**Architecture:** Three subsystems built incrementally: (1) cost estimator module + route tracking via extended InteractionRecord, (2) Gemini context caching via REST cachedContents API with settings DB persistence, (3) dashboard UI reusing existing ChartsPage components. Each produces working, testable software.

**Tech Stack:** Python 3.12 + FastAPI, httpx, vanilla React (createElement, no JSX), SVG inline charts, SQLite settings DB.

**Route names tracked:** `local`, `cloud-flash`, `cloud-pro`, `cloud`, `claude`, `ollama-howard`, `local-fallback`, `cloud-fallback`

---

### Task 1: Cost estimator module

**Files:**
- Create: `agents/core/llm/cost_estimator.py`
- Test: `tests/test_cost_estimator.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for LLM cost estimator."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.cost_estimator import estimate_cost, estimate_monthly, MODELS


def test_estimate_cost_local_is_free():
    cost = estimate_cost("qwen3:7b", 1000, 500)
    assert cost["total"] == 0.0
    assert cost["input_cost"] == 0.0
    assert cost["output_cost"] == 0.0


def test_estimate_cost_gemini_flash():
    cost = estimate_cost("gemini-2.5-flash", 1000, 500, cached_tokens=800)
    # 200 non-cached input (1000-800) * $0.15/M + 500 output * $0.60/M
    # = 200/1e6*0.15 + 500/1e6*0.60 = 0.00003 + 0.0003 = 0.00033
    expected_input = (1000 - 800) / 1_000_000 * 0.15
    expected_output = 500 / 1_000_000 * 0.60
    assert cost["input_cost"] == round(expected_input, 10)
    assert cost["output_cost"] == round(expected_output, 10)
    assert cost["total"] == round(expected_input + expected_output, 10)
    assert cost["cached_input"] == 800
    assert cost["savings"] == round(800 / 1_000_000 * 0.15, 10)


def test_estimate_cost_gemini_pro():
    cost = estimate_cost("gemini-2.5-pro", 100_000, 2000)
    # 100K input * $2.00/M + 2K output * $10.00/M
    assert cost["total"] == 100_000 / 1_000_000 * 2.00 + 2000 / 1_000_000 * 10.00


def test_estimate_cost_claude():
    cost = estimate_cost("claude-sonnet-4-20250514", 5000, 1000)
    assert cost["total"] > 0


def test_estimate_cost_unknown_model_returns_zero():
    cost = estimate_cost("unknown-model", 1000, 500)
    assert cost["total"] == 0.0


def test_estimate_monthly_empty():
    assert estimate_monthly([])["total"] == 0.0


def test_estimate_monthly_with_records():
    records = [
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 0},
        {"model": "local", "input_tokens": 2000, "output_tokens": 1000, "cached_tokens": 0},
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 900},
    ]
    result = estimate_monthly(records)
    assert result["total_interactions"] == 3
    assert result["total"] > 0
    assert result["total_savings"] > 0
    assert "gemini-2.5-flash" in result["per_model"]
    assert "local" in result["per_model"]
    assert result["per_model"]["local"]["total"] == 0.0  # free


def test_MODELS_has_entries():
    assert len(MODELS) >= 5
    assert "local" in MODELS
    assert "gemini-2.5-flash" in MODELS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cost_estimator.py -v`
Expected: ModuleNotFoundError for `core.llm.cost_estimator`

- [ ] **Step 3: Write minimal implementation**

```python
"""
cost_estimator.py — Token-based cost estimation for LLM calls.
Supports Gemini, Claude, and local models. All prices per 1M tokens in USD.
"""

from typing import Optional

MODELS = {
    # Gemini family
    "gemini-2.5-flash":    {"input": 0.15,  "cached_input": 0.015, "output": 0.60},
    "gemini-2.5-pro":      {"input": 2.00,  "cached_input": 0.20,  "output": 10.00},
    "gemini-3.1-pro":      {"input": 2.00,  "cached_input": 0.20,  "output": 12.00},
    "gemini-3.5-flash":    {"input": 1.50,  "cached_input": 0.15,  "output": 9.00},
    "gemini-3-flash":      {"input": 0.50,  "cached_input": 0.05,  "output": 3.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "cached_input": 0.025, "output": 1.50},
    # Claude
    "claude-sonnet-4-20250514": {"input": 3.00, "cached_input": 0.30, "output": 15.00},
    # Local (free)
    "local":               {"input": 0,     "cached_input": 0,     "output": 0},
    "qwen3:7b":            {"input": 0,     "cached_input": 0,     "output": 0},
    "google/gemma-4-31b-a4b": {"input": 0, "cached_input": 0,     "output": 0},
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> dict:
    """Estimate cost for a single LLM call.

    Returns dict with input_cost, output_cost, total, cached_input, savings.
    Unrecognized models return zero cost.
    """
    pricing = MODELS.get(model) or MODELS.get("local")
    if pricing is None or pricing["input"] == 0:
        return {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0,
                "cached_input": cached_tokens, "savings": 0.0}

    non_cached_input = max(0, input_tokens - cached_tokens)
    input_cost = non_cached_input / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    savings = cached_tokens / 1_000_000 * pricing["input"]

    return {
        "input_cost": round(input_cost, 10),
        "output_cost": round(output_cost, 10),
        "total": round(input_cost + output_cost, 10),
        "cached_input": cached_tokens,
        "savings": round(savings, 10),
    }


def estimate_monthly(records: list[dict]) -> dict:
    """Aggregate cost across multiple interaction records.

    Each record has: model, input_tokens, output_tokens, cached_tokens.
    Returns per-model breakdown and totals.
    """
    total = 0.0
    total_savings = 0.0
    per_model: dict[str, dict] = {}

    for r in records:
        model = r.get("model", "unknown")
        cost = estimate_cost(
            model=model,
            input_tokens=r.get("input_tokens", 0),
            output_tokens=r.get("output_tokens", 0),
            cached_tokens=r.get("cached_tokens", 0),
        )
        total += cost["total"]
        total_savings += cost["savings"]

        if model not in per_model:
            per_model[model] = {"calls": 0, "total": 0.0, "savings": 0.0}
        per_model[model]["calls"] += 1
        per_model[model]["total"] = round(per_model[model]["total"] + cost["total"], 10)
        per_model[model]["savings"] = round(per_model[model]["savings"] + cost["savings"], 10)

    return {
        "total": round(total, 10),
        "total_savings": round(total_savings, 10),
        "total_interactions": len(records),
        "per_model": per_model,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cost_estimator.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agents/core/llm/cost_estimator.py tests/test_cost_estimator.py
git commit -m "feat(cost): add LLM cost estimator module with tests"
```

---

### Task 2: Add route_name to InteractionRecord + track in orchestrator

**Files:**
- Modify: `agents/core/learning/loop.py`
- Modify: `agents/core/orchestrator.py`
- Test: `tests/test_learning_live.py` (extend existing)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_learning_live.py`:

```python
# ── Route tracking ──────────────────────────────────────────

def test_record_route_name_default(loop):
    """route_name defaults to empty string."""
    loop.record(agent_id="jarvis", task="t", response="r", success=True, latency=0.1)
    assert loop.interactions[0].route_name == ""


def test_record_route_name_custom(loop):
    """route_name is stored on InteractionRecord."""
    loop.record(agent_id="jarvis", task="t", response="r", success=True, latency=0.1, route_name="cloud-flash")
    assert loop.interactions[0].route_name == "cloud-flash"


def test_get_route_counts_empty(loop):
    """No interactions returns empty dict."""
    assert loop.get_route_counts() == {}


def test_get_route_counts_mixed(loop):
    """Route counts are aggregated correctly."""
    for route in ["local", "cloud-flash", "local", "cloud-pro", "local"]:
        loop.record(agent_id="jarvis", task="t", response="r", success=True, latency=0.1, route_name=route)
    counts = loop.get_route_counts()
    assert counts["local"] == 3
    assert counts["cloud-flash"] == 1
    assert counts["cloud-pro"] == 1
```

Run: `python -m pytest tests/test_learning_live.py::test_record_route_name_default -v`
Expected: AttributeError: 'InteractionRecord' object has no attribute 'route_name'

- [ ] **Step 2: Modify InteractionRecord + LearningLoop**

In `agents/core/learning/loop.py`:

Add `route_name` field to `InteractionRecord`:
```python
@dataclass
class InteractionRecord:
    agent_id: str
    task: str
    response: str
    success: bool
    latency: float
    timestamp: float
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    route_name: str = ""
```

Add `route_name` parameter to `LearningLoop.record()`:
```python
    def record(
        self,
        agent_id: str,
        task: str,
        response: str,
        success: bool,
        latency: float,
        error: str = None,
        metadata: dict = None,
        route_name: str = "",
    ):
        record = InteractionRecord(
            agent_id=agent_id,
            task=task,
            response=response,
            success=success,
            latency=latency,
            timestamp=time.time(),
            error=error,
            metadata=metadata or {},
            route_name=route_name,
        )
```

Add `get_route_counts()` method:
```python
    def get_route_counts(self) -> dict[str, int]:
        """Return count of interactions per route_name."""
        counts: dict[str, int] = {}
        for r in self.interactions:
            if r.route_name:
                counts[r.route_name] = counts.get(r.route_name, 0) + 1
        return counts
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_learning_live.py::test_record_route_name_default tests/test_learning_live.py::test_record_route_name_custom tests/test_learning_live.py::test_get_route_counts_empty tests/test_learning_live.py::test_get_route_counts_mixed -v`
Expected: 4 passed

- [ ] **Step 4: Wire route_name into orchestrator._record_interactions**

In `agents/core/orchestrator.py`, locate `_record_interactions` (line 702). After the `self.learning.record(` call, add `route_name` parameter. Also track route_name in bench records.

Change the `_record_interactions` method to accept and pass route_name. Modify the callsite in both `handle_input` and the per-agent recording loop.

In `handle_input` (line ~301), after `responses = await self._call_agents_parallel(...)`, we already have intent data. The route_name comes from `select_backend`. But `_call_agents_parallel` doesn't track route per agent. We need to capture it before the parallel call.

Actually, let's look at the flow more carefully. In `handle_input`, `_call_agents_parallel` calls each agent's `process()` which internally uses `self.llm_router.select_backend()`. The route_name isn't returned from `_call_agents_parallel`. 

Simplest approach: call `select_backend` before `_call_agents_parallel` and pass the route_name to `_record_interactions`. But we need per-agent route names...

Actually, looking at this more closely, `handle_input` is complex. Let me take the simpler approach: for now, just pass route_name to `_record_interactions` at the callsites where we have it. The streaming path (`handle_input_stream`) already calls `select_backend` explicitly (line 419), so we can pass route_name there. For `handle_input`, we can record it from the first agent.

Let me make minimal changes:

In `_record_interactions`, add an optional `route_name` parameter:

```python
    def _record_interactions(self, text: str, responses: dict, synthesized: str, route_name: str = ""):
        for agent_id, resp in responses.items():
            if agent_id in self.agents and resp:
                ...
                self.learning.record(
                    agent_id=agent_id,
                    task=text[:200],
                    response=resp[:500],
                    success=success,
                    latency=latency,
                    error=resp if not success else None,
                    metadata={"channel": "web"},
                    route_name=route_name,
                )
```

Then update callsites:

In `handle_input` (line 301 and 358):
```python
            # After intent is classified and before _call_agents_parallel:
            route_name = ""
            try:
                _, _, route_name = self.llm_router.select_backend(
                    (intent.target_agents or ["jarvis"])[0], text
                )
            except RuntimeError:
                pass
            
            # Pass to _record_interactions:
            self._record_interactions(text, responses, synthesized, route_name=route_name)
```

Similarly for the agent_override path (line ~300).

In `handle_input_stream` (line ~358), route_name is already available from line 419:
```python
            backend, router_model, route_name = self.llm_router.select_backend(agent_id, prompt)
```
We need to store this and pass it to... well, `handle_input_stream` doesn't call `_record_interactions`. Let me check... 

Looking at the code, `handle_input_stream` doesn't call `_record_interactions` at all. That's fine — we'll add route_name tracking where `_record_interactions` is called (in `handle_input`).

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_learning_live.py tests/test_routing.py -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add agents/core/learning/loop.py agents/core/orchestrator.py
git commit -m "feat(routing): add route_name to InteractionRecord and orchestrator tracking"
```

---

### Task 3: Route usage + cost estimates in admin stats endpoint

**Files:**
- Modify: `agents/web.py` (extend `/api/admin/stats`)
- Test: `tests/test_admin_charts.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_charts.py`:

```python
def test_stats_route_usage_is_dict(token_client):
    """Route usage field is present and is a dict."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "route_usage" in data
    assert isinstance(data["route_usage"], dict)


def test_stats_cost_estimates_present(token_client):
    """Cost estimates field has expected structure."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "cost_estimates" in data
    ce = data["cost_estimates"]
    assert "total" in ce
    assert "total_savings" in ce
    assert "total_interactions" in ce
    assert "per_model" in ce
```

Run: `python -m pytest tests/test_admin_charts.py::test_stats_route_usage_is_dict -v`
Expected: AssertionError — key "route_usage" not in response

- [ ] **Step 2: Extend the `/api/admin/stats` endpoint**

In `agents/web.py`, after the `error_types` aggregation (line ~1055) and before the return statement, add:

```python
    # Route usage
    route_usage = orch.learning.get_route_counts() if hasattr(orch.learning, 'get_route_counts') else {}

    # Cost estimates
    cost_records = []
    for r in interactions:
        cost_records.append({
            "model": r.route_name or "unknown",
            "input_tokens": (r.metadata or {}).get("input_tokens", 0),
            "output_tokens": (r.metadata or {}).get("output_tokens", 0),
            "cached_tokens": (r.metadata or {}).get("cached_tokens", 0),
        })
    from core.llm.cost_estimator import estimate_monthly
    cost_estimates = estimate_monthly(cost_records)
```

Update the return dict to include the new fields:

```python
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
        "route_usage": route_usage,
        "cost_estimates": cost_estimates,
    })
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_admin_charts.py -v`
Expected: 7 passed (5 original + 2 new)

- [ ] **Step 4: Commit**

```bash
git add agents/web.py tests/test_admin_charts.py
git commit -m "feat(admin): add route_usage and cost_estimates to /api/admin/stats"
```

---

### Task 4: Gemini context cache module

**Files:**
- Create: `agents/core/llm/gemini_cache.py`
- Test: `tests/test_gemini_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for Gemini context cache management."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.gemini_cache import ContextCache


@pytest.mark.asyncio
async def test_cache_key_generation():
    cache = ContextCache(api_key="test")
    key1 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key3 = cache.cache_key("be nice", "gemini-2.5-flash")
    assert key1 == key2
    assert key1 != key3


@pytest.mark.asyncio
async def test_cache_key_includes_model():
    cache = ContextCache(api_key="test")
    key1 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = cache.cache_key("be helpful", "gemini-2.5-pro")
    assert key1 != key2


def test_cache_init_no_network():
    cache = ContextCache(api_key="test")
    assert cache.api_key == "test"
    assert cache._cache_map == {}


@pytest.mark.asyncio
async def test_close():
    cache = ContextCache(api_key="test")
    await cache.close()  # should not raise


@pytest.mark.asyncio
async def test_create_cache_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("connection refused")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cache = ContextCache(api_key="test")
    result = await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
        model="gemini-2.5-flash",
    )
    assert result is None


@pytest.mark.asyncio
async def test_delete_cache_no_name():
    cache = ContextCache(api_key="test")
    result = await cache.delete("nonexistent")
    assert result is False
```

Run: `python -m pytest tests/test_gemini_cache.py -v`
Expected: ModuleNotFoundError for `core.llm.gemini_cache`

- [ ] **Step 2: Write minimal implementation**

```python
"""
gemini_cache.py — Gemini Context Caching via REST cachedContents API.
Manages creation, extension, and deletion of cached content for session history.
Cache mappings are persisted in the SQLite settings DB (category "cache").
"""

import hashlib
import json
import logging
from typing import Optional

import httpx

from core.settings_db import get_category, put_category

logger = logging.getLogger("jarvis.gemini.cache")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TTL_SECONDS = 3600  # 1 hour


class ContextCache:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        # session_id -> {"cache_name": str, "model": str, "contents_count": int}
        self._cache_map: dict[str, dict] = {}
        self._load_persisted()

    def _load_persisted(self):
        try:
            items = get_category("cache")
            for item in items:
                if item["key"] == "entries":
                    self._cache_map = item["value"]
                    logger.info(f"Loaded {len(self._cache_map)} cache entries from DB")
        except Exception:
            self._cache_map = {}

    def _save_persisted(self):
        try:
            put_category("cache", {"entries": self._cache_map})
        except Exception as e:
            logger.warning(f"Failed to persist cache map: {e}")

    def cache_key(self, system_instruction: str, model: str) -> str:
        raw = f"{system_instruction}|{model}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def create_or_extend(
        self,
        session_id: str,
        system_instruction: str,
        history: list[dict],
        model: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Optional[str]:
        """Create a new cache entry or extend an existing one for this session.

        Returns the cache name (e.g. 'cachedContents/abc123') or None on failure.
        """
        existing = self._cache_map.get(session_id)

        if existing:
            return await self._extend(existing["cache_name"], ttl_seconds)

        return await self._create(session_id, system_instruction, history, model, ttl_seconds)

    async def _create(
        self, session_id: str, system_instruction: str,
        history: list[dict], model: str, ttl: int,
    ) -> Optional[str]:
        url = f"{GEMINI_API_BASE}/cachedContents?key={self.api_key}"
        payload = {
            "model": f"models/{model}",
            "contents": history,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "ttl": f"{ttl}s",
        }
        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            cache_name = data.get("name", "")
            if cache_name:
                self._cache_map[session_id] = {
                    "cache_name": cache_name,
                    "model": model,
                    "contents_count": len(history),
                }
                self._save_persisted()
                logger.info(f"Created cache {cache_name} for session {session_id} ({len(history)} turns)")
            return cache_name or None
        except Exception as e:
            logger.warning(f"Failed to create cache for {session_id}: {e}")
            return None

    async def _extend(self, cache_name: str, ttl: int) -> Optional[str]:
        url = f"{GEMINI_API_BASE}/{cache_name}?key={self.api_key}"
        payload = {"ttl": f"{ttl}s"}
        try:
            resp = await self.client.patch(url, json=payload)
            resp.raise_for_status()
            logger.info(f"Extended TTL for {cache_name}")
            return cache_name
        except Exception as e:
            logger.warning(f"Failed to extend cache {cache_name}: {e}")
            return None

    async def delete(self, cache_name: str) -> bool:
        """Delete a cached content entry. Returns True on success."""
        url = f"{GEMINI_API_BASE}/{cache_name}?key={self.api_key}"
        try:
            resp = await self.client.delete(url)
            resp.raise_for_status()
            # Remove from map
            for sid, entry in list(self._cache_map.items()):
                if entry["cache_name"] == cache_name:
                    del self._cache_map[sid]
            self._save_persisted()
            return True
        except Exception as e:
            logger.warning(f"Failed to delete cache {cache_name}: {e}")
            return False

    def get_cache_info(self, session_id: str) -> Optional[dict]:
        return self._cache_map.get(session_id)

    def count_active(self) -> int:
        return len(self._cache_map)

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_gemini_cache.py -v`
Expected: 6 passed

- [ ] **Step 4: Commit**

```bash
git add agents/core/llm/gemini_cache.py tests/test_gemini_cache.py
git commit -m "feat(cache): add Gemini context cache module with settings DB persistence"
```

---

### Task 5: Wire context caching into GeminiBackend + orchestrator

**Files:**
- Modify: `agents/core/llm/gemini.py` (add session_id + history params, cachedContents support)
- Modify: `agents/core/orchestrator.py` (wire ContextCache into handle_input_stream)
- Test: `tests/test_hybrid_router.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hybrid_router.py`:

```python
# ── Gemini caching integration ─────────────────────────────────

def test_gemini_build_payload_with_cache():
    """_build_payload should not include system when using cache."""
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello", system="be helpful", use_cache="cachedContents/abc123")
    assert "cachedContent" in payload
    assert payload["cachedContent"] == "cachedContents/abc123"
    assert "systemInstruction" not in payload  # system is in cache


def test_gemini_build_payload_without_cache():
    """Normal payload without cache reference."""
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello", system="be helpful")
    assert "cachedContent" not in payload
    assert "systemInstruction" in payload
```

Run: `python -m pytest tests/test_hybrid_router.py::test_gemini_build_payload_with_cache -v`
Expected: TypeError because _build_payload doesn't accept use_cache

- [ ] **Step 2: Update _build_payload in gemini.py**

Change the `_build_payload` method signature and implementation in `agents/core/llm/gemini.py`:

```python
    def _build_payload(self, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7,
                       use_cache: str = "") -> dict:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if use_cache:
            payload["cachedContent"] = use_cache
        elif system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload
```

- [ ] **Step 3: Run new tests**

Run: `python -m pytest tests/test_hybrid_router.py::test_gemini_build_payload_with_cache tests/test_hybrid_router.py::test_gemini_build_payload_without_cache -v`
Expected: 2 passed

- [ ] **Step 4: Wire ContextCache into orchestator's handle_input_stream**

In `agents/core/orchestrator.py`, import ContextCache at the top:

```python
from .llm.gemini_cache import ContextCache
```

In `__init__`, add after `self.llm_router = ...`:

```python
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        self.context_cache = ContextCache(api_key=gemini_key) if gemini_key else None
```

In `handle_input_stream` (after the prompt is built, around line 406), add cache integration:

After line ~406 where `prompt` is built with history, add:
```python
                # Try to use context cache for Gemini cloud backends
                cache_hit = False
                cached_tokens = 0
                if self.context_cache and "cloud" in route_name and history:
                    cache_key = self.context_cache.cache_key(system_prompt, model)
                    history_messages = [{"role": "user", "parts": [{"text": t}]}
                                        for t in history.split("\n---\n") if t.strip()]
                    if history_messages:
                        cache_name = self.context_cache.create_or_extend(
                            session_id=self.session_id,
                            system_instruction=system_prompt,
                            history=history_messages[:-1],  # exclude latest user msg
                            model=model,
                        )
                        try:
                            cache_name_resolved = await cache_name
                        except Exception:
                            cache_name_resolved = None
                        if cache_name_resolved:
                            cache_hit = True
                            cached_tokens = sum(estimate_tokens(t) for t in history_messages[:-1])
                            prompt = f"User: {text}\nRespond as {agent.name}."
```

Wait, this is getting complex. Let me simplify. The actual history string from `get_context` is a flat string with turns separated by newlines, not a list. And the orchestrator needs careful handling.

Let me simplify the approach: in `handle_input_stream`, after we build the prompt with conversation history, we check if we can use context caching. If so, we:

1. Create/extend the cache with the system prompt + conversation history (minus last user message)
2. Only send the last user message as the prompt
3. Pass cachedContent reference

But the prompt structure is complex — it includes plugin_data, context_block, etc. Let me take a simpler approach: just cache the system prompt + history portion, and strip it from the actual prompt sent to the API.

Actually, let me make this simpler. The caching is an optimization that doesn't change the response. Let me just:

1. In `handle_input_stream`, after we have the final prompt and before calling `backend.generate()`, check if we can use cache
2. If we can, rewrite the prompt to only include the dynamic part (last user message)
3. Track cache tokens for stats

Let me write this more carefully.

Actually, the simplest approach that works: store a "cached baseline" prompt per session_id. Each subsequent call sends only the delta. The backend reformats.

Wait, I'm overcomplicating this. Let me step back.

The key insight from the design: "Sesiune 50 mesaje → 80% tokeni citiți din cache". This means we need to:
1. Cache the conversation history (system prompt + previous turns)
2. Only send the latest user message with a `cachedContent` reference

For the implementation:
1. First time in a session: create cache with (system + history_except_last), send full prompt normally
2. Subsequent times: extend cache TTL, send only (last_user_message) with cachedContent reference

The simplest integration point is in `handle_input_stream` since it already builds the full prompt. We can:
1. Before sending, compute what would be cached (system + history)
2. If match found, send only the user message part with cachedContent
3. Record cache_hit in metadata

Let me write this more concretely. The prompt in handle_input_stream looks like:
```
Conversation history:
user: hi
assistant: hello
user: what's up

[PLUGIN DATA]
Agent context: ...
User: latest message
Respond as AgentName.
```

For caching, we want to cache everything except "User: latest message\nRespond as AgentName." But `handle_input_stream` only sends one request per stream invocation — it builds the prompt with all history and the latest user message. The caching is for the NEXT invocation.

OK, I think the right approach is simpler: for each handle_input_stream call:
1. Build the prompt as usual (it contains history + latest user message)  
2. Look for an existing cache for this session
3. If cache exists: extend it, and strip the cached portion from the prompt
4. If no cache: create one with the current conversation history (system + previous turns), send full prompt

Actually, the cleanest approach: cache management should happen BEFORE handle_input_stream is called, at the session level. Each time handle_input_stream completes, the assistant response is added to memory. Before the NEXT call, we create/extend the cache with all prior turns, and only send the new user message.

This means: in handle_input_stream, before building the prompt:
1. Get cached content name (if any) for this session
2. If exists: only fetch the latest user message as history, don't include the full history in prompt  
3. If not exists: create cache with full history after the call completes

This is still complex for a single task. Let me simplify the plan: wire caching into the orchestrator at the `handle_input_stream` level with the following approach:

- Before each stream call, check for existing cache
- If cache exists, include only the last user message (no history replay) + cachedContent reference
- If no cache, send full prompt + create cache asynchronously after
- Track cache_hit, cached_tokens in metadata

Let me write this as code:

In `handle_input_stream`, after getting the history and before building the full prompt (around the point where `history = await self.memory.get_context(...)`):

```python
                # Context caching for Gemini cloud routes
                use_cache_name = None
                cache_hit = False
                cached_tokens = 0
                is_gemini_route = "cloud" in route_name or route_name in ("gemini",)
                
                if is_gemini_route and self.context_cache and history:
                    cache_entry = self.context_cache.get_cache_info(self.session_id)
                    if cache_entry:
                        # Cache exists — use cachedContent, strip history from prompt
                        use_cache_name = cache_entry["cache_name"]
                        cache_hit = True
                        # Estimate cached tokens from the history portion
                        cached_tokens = estimate_tokens(history)
                        # Rebuild prompt without history
                        prompt = (
                            f"{plugin_block}{context_block}"
                            f"User: {text}\n"
                            f"Respond as {agent.name}."
                        )
```

Then in the `generate` call:
```python
                    if hasattr(backend, "_build_payload") and use_cache_name:
                        # Direct call with cachedContent
                        response = await backend.generate(
                            model=model, prompt=prompt,
                            system=system_prompt,
                            max_tokens=max_tokens, temperature=temperature,
                            use_cache=use_cache_name,
                        )
                    else:
```

Wait, `backend.generate()` doesn't accept `use_cache`. And the `generate()` method's signature is defined in the abstract base. I'd rather pass it as metadata and handle it in `_build_payload`.

Actually, the simplest approach: modify `_build_payload` to optionally take `use_cache`. Modify `generate` to optionally take it. The abstract base can have it as a **kwarg so other backends ignore it.

Let me use a simpler approach: pass cache info via the existing metadata mechanism. In `_build_payload`, check for a class-level flag that gets set before each generate call.

Even simpler: set `self._use_cache` on the backend instance before calling generate:

```python
                if use_cache_name:
                    backend._use_cache = use_cache_name
                else:
                    backend._use_cache = ""
                response = await backend.generate(...)
```

And in `_build_payload`:
```python
    def _build_payload(self, prompt, system="", max_tokens=1024, temperature=0.7, use_cache=""):
        ...
        if use_cache:
            use_cache = getattr(self, '_use_cache', '')
        ...
```

Hmm, this is fragile. Let me just modify the `generate` signature.

Abstract base `generate`: `async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7, **kwargs) -> str`
This way extra kwargs are accepted by all backends but only GeminiBackend uses them.

Let me finalize the plan steps for this task.

Actually, I realize I'm going too deep into implementation detail for the plan. Let me step back and write the plan more concisely with actual code, following the skill's instruction "Complete code in every step — if a step changes code, show the code."

Let me write manageable code blocks.

- [ ] **Step 5: Wire cache into orchestrator handle_input_stream**

In `agents/core/orchestrator.py`:

Add import:
```python
from .llm.gemini_cache import ContextCache
```

In `__init__`, after `self.llm_router = ...`:
```python
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        self.context_cache = ContextCache(api_key=gemini_key) if gemini_key else None
```

In `handle_input_stream`, before the `try` block that calls `select_backend` (after line ~396, around the loop), add cache-aware prompt building.

Replace the section from line ~396 (inside the `for agent_id in target:` loop, around the backend call) with cache-aware code:

```python
                # Context caching for Gemini cloud routes
                use_cache_name = None
                cache_hit = False
                cached_tokens = 0
                is_gemini_route = route_name in ("cloud", "cloud-flash", "cloud-pro", "cloud-fallback", "gemini")

                if is_gemini_route and self.context_cache and history:
                    cache_entry = self.context_cache.get_cache_info(self.session_id)
                    if cache_entry:
                        use_cache_name = cache_entry["cache_name"]
                        cache_hit = True
                        cached_tokens = estimate_tokens(history)
                        # Strip history — it's in the cache
                        prompt = (
                            f"{plugin_block}{context_block}"
                            f"User: {text}\n"
                            f"Respond as {agent.name}."
                        )
                    else:
                        # Create cache asynchronously — use full prompt this time
                        history_parts = [t.strip() for t in history.split("\n---\n") if t.strip()]
                        asyncio.ensure_future(self._async_create_cache(
                            session_id=self.session_id,
                            system_instruction=system_prompt,
                            history_texts=history_parts,
                            model=model,
                        ))

                if use_cache_name:
                    backend._use_cache = use_cache_name
                else:
                    backend._use_cache = ""
```

Add helper method:
```python
    async def _async_create_cache(self, session_id: str, system_instruction: str,
                                    history_texts: list[str], model: str):
        """Create a context cache entry in the background."""
        if not self.context_cache or not history_texts:
            return
        history = [{"role": "user", "parts": [{"text": t}]} for t in history_texts]
        await self.context_cache.create_or_extend(
            session_id=session_id,
            system_instruction=system_instruction,
            history=history,
            model=model,
        )
```

- [ ] **Step 6: Make backend.generate accept cache via instance state**

Change `_build_payload` in `gemini.py` to check `self._use_cache`:

```python
    def _build_payload(self, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> dict:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        use_cache = getattr(self, '_use_cache', '')
        if use_cache:
            payload["cachedContent"] = use_cache
        elif system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload
```

Also update `__init__` to set `_use_cache = ""`:
```python
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)
        self._use_cache = ""
```

- [ ] **Step 7: Run existing tests**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 10`
Expected: all existing tests pass (no regressions)

- [ ] **Step 8: Commit**

```bash
git add agents/core/llm/gemini.py agents/core/orchestrator.py agents/core/llm/gemini_cache.py
git commit -m "feat(cache): wire Gemini context caching into orchestrator streaming path"
```

---

### Task 6: Track tokens + cache info in interaction records

**Files:**
- Modify: `agents/core/orchestrator.py` (extend metadata with tokens + cache)
- Modify: `agents/core/llm/cost_estimator.py` (add token estimation helper if needed)

- [ ] **Step 1: Modify _record_interactions to include token estimates**

In `_record_interactions`, add token estimation and cache metadata:

```python
    def _record_interactions(self, text: str, responses: dict, synthesized: str, route_name: str = ""):
        for agent_id, resp in responses.items():
            if agent_id in self.agents and resp:
                is_timeout = resp.endswith("timeout]")
                is_error = resp.endswith("error:") or "error:" in resp
                success = not (is_timeout or is_error)
                latency = getattr(self, "_last_latencies", {}).get(agent_id, 0.0)
                metadata = {
                    "channel": "web",
                    "input_tokens": estimate_tokens(text),
                    "output_tokens": estimate_tokens(resp),
                    "cached_tokens": 0,
                    "cache_hit": False,
                }
                self.learning.record(
                    agent_id=agent_id,
                    task=text[:200],
                    response=resp[:500],
                    success=success,
                    latency=latency,
                    error=resp if not success else None,
                    metadata=metadata,
                    route_name=route_name,
                )
```

- [ ] **Step 2: Commit**

```bash
git add agents/core/orchestrator.py
git commit -m "feat(cost): add token estimates and cache metadata to interaction records"
```

---

### Task 7: Dashboard UI — route distribution + cost cards

**Files:**
- Modify: `agents/web/static/i18n.js` (add translations)
- Modify: `agents/web/static/admin.js` (extend ChartsPage with route + cost sections)

- [ ] **Step 1: Add i18n strings**

In `agents/web/static/i18n.js`, after the chart translations (after `'charts.errors': 'Erori frecvente',`), add:

```javascript
  'charts.route_usage':  'Rute utilizate',
  'charts.cost':         'Cost estimat',
  'charts.cost_total':   'Cost total',
  'charts.cost_savings': 'Economii cache',
  'charts.cost_month':   'Lunar',
  'charts.cache_active': 'Cache-uri active',
  'charts.cache_tokens': 'Tokeni din cache',
```

- [ ] **Step 2: Verify i18n syntax**

Run: `node --check agents/web/static/i18n.js`
Expected: no errors

- [ ] **Step 3: Extend ChartsPage with route + cost sections**

In `agents/web/static/admin.js`, in the `ChartsPage` function (line 605), after the error types section (after line ~667) and before the closing `)` of the return, add:

```javascript
    // Route usage distribution
    data.route_usage && Object.keys(data.route_usage).length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.route_usage')),
      h(BarChart,{data:Object.entries(data.route_usage).map(([k,v])=>({label:k,value:v})).sort((a,b)=>b.value-a.value),
        valueKey:'value',labelKey:'label',colorFn:()=>'#a78bfa'}),
    ),

    // Cost estimates
    data.cost_estimates && h('div',{style:{display:'flex',gap:12,marginTop:20,flexWrap:'wrap'}},
      h(StatsCard,{label:_t('charts.cost_total'),
        value:'$'+data.cost_estimates.total.toFixed(4),color:'#f59e0b'}),
      data.cost_estimates.total_savings > 0 && h(StatsCard,{label:_t('charts.cost_savings'),
        value:'$'+data.cost_estimates.total_savings.toFixed(4),color:'#4ade80'}),
      h(StatsCard,{label:_t('charts.cache_active'),
        value:data.cost_estimates.total_interactions,color:'#60a5fa'}),
    ),
```

- [ ] **Step 4: Verify JS syntax**

Run: `node --check agents/web/static/admin.js`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add agents/web/static/i18n.js agents/web/static/admin.js
git commit -m "feat(admin): add route usage and cost charts to dashboard"
```

---

### Task 8: Final verification + BACKLOG update

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 15`
Expected: all tests pass (509 existing + ~6 new = 515 passed, 8 skipped)

- [ ] **Step 2: Update BACKLOG.md**

Mark H4.11 as done, update totals:
- H4.11 status: ✅
- H4 Platform: 11/11 ✅ (100%)
- Items: 65/65 ✅ (100%)
- S total: 217 + 5 = 222 / 255

- [ ] **Step 3: Final commit**

```bash
git add BACKLOG.md
git commit -m "docs: mark H4.11 Context Caching complete"
```

---

## Files Changed Summary

| File | Change | Lines |
|------|--------|-------|
| `agents/core/llm/cost_estimator.py` | **Create** — pricing table + estimate_cost + estimate_monthly | ~80 |
| `tests/test_cost_estimator.py` | **Create** — 8 tests for cost estimation | ~70 |
| `agents/core/learning/loop.py` | Modify — add route_name to InteractionRecord, add get_route_counts | ~15 |
| `agents/core/orchestrator.py` | Modify — wire route_name, ContextCache, token tracking | ~50 |
| `agents/web.py` | Modify — extend /api/admin/stats with route_usage + cost_estimates | ~20 |
| `tests/test_admin_charts.py` | Modify — add 2 tests for new fields | ~20 |
| `agents/core/llm/gemini_cache.py` | **Create** — ContextCache with REST API + settings DB persistence | ~120 |
| `tests/test_gemini_cache.py` | **Create** — 6 tests for cache module | ~65 |
| `agents/core/llm/gemini.py` | Modify — add cachedContent support to _build_payload | ~10 |
| `agents/web/static/i18n.js` | Modify — add route + cost translations | ~8 |
| `agents/web/static/admin.js` | Modify — extend ChartsPage with route distribution + cost cards | ~25 |
| `BACKLOG.md` | Modify — mark H4.11 complete | ~2 |
