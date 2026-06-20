"""Tests for the concurrent live-plugin fan-out (plugin_gatherer).

Covers the H7-style perf fix: eligible plugins run together under a bounded
semaphore with a per-plugin deadline, instead of one serial ``await`` each. A
slow/failing plugin must not stall or fail the turn, and the result order must
stay deterministic so the prompt block is stable.
"""

import asyncio
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.plugin_gatherer as pg
from agents.core.plugin_gatherer import gather_plugin_data
from agents.core.router import Intent


class _Gate:
    """Permission gate that allows every call."""
    def check_call(self, plugin, agent):
        return True


class _Orch:
    def __init__(self, plugins):
        self.plugins = plugins
        self.permission_gate = _Gate()


def _make_plugin(method_name, *, delay=0.0, fail=False, ret=None):
    """A fake plugin exposing one async *method_name* that sleeps then returns
    (or raises). Used to stand in for weather/news/worldview/etc."""
    async def _call(*args, **kwargs):
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise RuntimeError("boom")
        return ret

    plugin = type("FakePlugin", (), {})()
    setattr(plugin, method_name, _call)
    return plugin


def _intent():
    return Intent(target_agents=["jarvis"], is_general=False,
                  context={"keywords_found": []})


async def test_plugins_run_concurrently_not_serially():
    delay = 0.25
    orch = _Orch({
        "weather": _make_plugin("get_weather", delay=delay, ret="W"),
        "news": _make_plugin("summarize", delay=delay, ret="N"),
    })
    t0 = time.perf_counter()
    data = await gather_plugin_data(orch, "weather and news please", _intent())
    elapsed = time.perf_counter() - t0

    assert data == {"weather": "W", "news": "N"}        # both ran
    assert list(data.keys()) == ["weather", "news"]      # order preserved
    # Serial would be ~2*delay (0.5s); concurrent is ~delay (0.25s).
    assert elapsed < 2 * delay - 0.05, f"fan-out looks serial: {elapsed:.3f}s"


async def test_failing_plugin_is_isolated():
    orch = _Orch({
        "weather": _make_plugin("get_weather", fail=True),
        "news": _make_plugin("summarize", ret="N"),
    })
    data = await gather_plugin_data(orch, "weather and news", _intent())

    assert "weather" not in data        # failure omitted, not raised
    assert data == {"news": "N"}         # sibling still collected


async def test_slow_plugin_times_out_without_stalling(monkeypatch):
    monkeypatch.setattr(pg, "PLUGIN_TIMEOUT_S", 0.05)
    orch = _Orch({
        "weather": _make_plugin("get_weather", delay=0.5, ret="W"),  # exceeds deadline
        "news": _make_plugin("summarize", ret="N"),
    })
    t0 = time.perf_counter()
    data = await gather_plugin_data(orch, "weather and news", _intent())
    elapsed = time.perf_counter() - t0

    assert data == {"news": "N"}                 # slow one dropped on timeout
    assert elapsed < 0.4, "timeout did not bound the slow plugin"


async def test_no_eligible_plugins_returns_empty():
    orch = _Orch({"weather": _make_plugin("get_weather", ret="W")})
    # No plugin keyword in the text → nothing eligible.
    data = await gather_plugin_data(orch, "just saying hello", _intent())
    assert data == {}
