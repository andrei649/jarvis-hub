"""Tests for the Always-On headless runtime coordinator's cycle-recorder logic.

Uses a fake orchestrator stand-in (no real Orchestrator boot — that needs a live
LLM backend probe and the full agent roster) to unit-test the read-only snapshot
+ classification + persistence loop in isolation, per the project's own
"Orchestrator instantiation trick" convention (docs/ARCHITECTURE.md §7).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import asyncio

import pytest

from agents.core.autonomy.runtime_coordinator import (
    RuntimeCoordinator,
    _heartbeat_snapshot,
    _night_shift_snapshot,
)
from agents.core.autonomy.runtime_log import read_records
from agents.core.autonomy.runtime_state import RuntimeStateStore


class FakeQueue:
    def __init__(self, stats):
        self._stats = stats

    def stats(self):
        return dict(self._stats)


class FakeHeartbeatScheduler:
    def __init__(self, running=True, jobs=None):
        self._running = running
        self._jobs = jobs or []

    def get_status(self):
        return {"scheduler_running": self._running, "heartbeats": list(self._jobs)}


class FakeOrch:
    def __init__(self, settings=None, queue_stats=None):
        self._settings = settings or {}
        self.autonomy_queue = FakeQueue(queue_stats or {})
        self.heartbeat_scheduler = FakeHeartbeatScheduler()

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)


@pytest.fixture
def coordinator(tmp_path):
    log_path = tmp_path / "runtime.jsonl"
    state_store = RuntimeStateStore(tmp_path / "state.json")
    rc = RuntimeCoordinator(log_path=log_path, state_store=state_store, cycle_floor_seconds=0.01)
    # system.autonomy_tick must also be tiny, else _autonomy_tick_interval()
    # takes max(cycle_floor_seconds, tick_setting) and the 60s default wins.
    rc.orch = FakeOrch(settings={"system.autonomy_tick": 0.01})
    rc.boot_id = 1
    return rc


def test_night_shift_snapshot_reads_settings():
    orch = FakeOrch(settings={"autonomy.night_shift": True, "autonomy.night_start": 23, "autonomy.night_end": 6})
    snap = _night_shift_snapshot(orch)
    assert snap["enabled"] is True
    assert snap["start"] == 23
    assert snap["end"] == 6
    assert isinstance(snap["active"], bool)


def test_night_shift_snapshot_disabled_by_default():
    orch = FakeOrch()
    snap = _night_shift_snapshot(orch)
    assert snap["enabled"] is False
    assert snap["active"] is False


def test_heartbeat_snapshot_reads_scheduler_status():
    orch = FakeOrch()
    orch.heartbeat_scheduler = FakeHeartbeatScheduler(running=True, jobs=[{"agent_id": "jarvis"}])
    snap = _heartbeat_snapshot(orch)
    assert snap == {"scheduler_running": True, "count": 1}


def test_heartbeat_snapshot_never_raises_on_broken_scheduler():
    class BrokenScheduler:
        def get_status(self):
            raise RuntimeError("boom")

    orch = FakeOrch()
    orch.heartbeat_scheduler = BrokenScheduler()
    snap = _heartbeat_snapshot(orch)
    assert snap == {"scheduler_running": False, "count": 0}


def test_snapshot_and_classify_first_cycle_is_clean(coordinator):
    coordinator.orch.autonomy_queue = FakeQueue({"done": 3, "failed": 0})
    stats, worker, status = coordinator._snapshot_and_classify()
    assert status == "clean"
    assert worker == {"done_delta": 3, "failed_delta": 0}


def test_snapshot_and_classify_new_failures_are_degraded(coordinator):
    coordinator.orch.autonomy_queue = FakeQueue({"done": 1, "failed": 1})
    coordinator._snapshot_and_classify()
    coordinator.orch.autonomy_queue = FakeQueue({"done": 2, "failed": 3})
    stats, worker, status = coordinator._snapshot_and_classify()
    assert status == "degraded"
    assert worker == {"done_delta": 1, "failed_delta": 2}


def test_snapshot_and_classify_queue_error_is_error_status(coordinator):
    class BrokenQueue:
        def stats(self):
            raise RuntimeError("db locked")

    coordinator.orch.autonomy_queue = BrokenQueue()
    stats, worker, status = coordinator._snapshot_and_classify()
    assert status == "error"
    assert stats == {}


@pytest.mark.asyncio
async def test_run_cycle_appends_record_and_persists_state(coordinator):
    coordinator.orch.autonomy_queue = FakeQueue({"done": 1, "failed": 0})
    record = await coordinator._run_cycle(1)
    assert record["phase"] == "cycle"
    assert record["cycle"] == 1
    assert record["boot_id"] == 1
    assert record["status"] == "clean"

    logged = read_records(coordinator.log_path)
    assert len(logged) == 1
    assert logged[0]["cycle"] == 1

    state = coordinator.state_store.load()
    assert state["cycle"] == 1
    assert state["last_status"] == "clean"
    assert state["consecutive_clean"] == 1


@pytest.mark.asyncio
async def test_run_cycle_survives_orch_exceptions(coordinator):
    class BrokenQueue:
        def stats(self):
            raise RuntimeError("boom")

    coordinator.orch.autonomy_queue = BrokenQueue()
    record = await coordinator._run_cycle(1)
    assert record["status"] == "error"
    state = coordinator.state_store.load()
    assert state["consecutive_clean"] == 0


@pytest.mark.asyncio
async def test_run_forever_stops_cleanly_and_resumes_cycle_count(coordinator):
    coordinator.orch.autonomy_queue = FakeQueue({"done": 0, "failed": 0})
    task = asyncio.create_task(coordinator.run_forever())
    await asyncio.sleep(0.05)  # a handful of 0.01s-floor cycles
    coordinator.stop()
    await asyncio.wait_for(task, timeout=2)

    records = [r for r in read_records(coordinator.log_path) if r.get("phase") == "cycle"]
    assert len(records) >= 1
    cycles = [r["cycle"] for r in records]
    assert cycles == sorted(cycles)
    assert cycles == list(range(1, len(cycles) + 1))

    # A fresh coordinator against the same state store resumes the counter —
    # this is the "state intact across a restart" contract kill -9 relies on.
    resumed = RuntimeCoordinator(
        log_path=coordinator.log_path, state_store=coordinator.state_store, cycle_floor_seconds=0.01
    )
    resumed.orch = coordinator.orch
    resumed.boot_id = coordinator.boot_id + 1
    state = resumed.state_store.load()
    assert state["cycle"] == cycles[-1]
