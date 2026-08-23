"""Async-seam regressions for HouseActuator — blocking work stays off the loop.

The actuator's device-facing entry points are awaited directly from FastAPI
routes, yet its governed intake (``AutonomyWorker.govern_enqueue`` → sync
sqlite ``TaskQueue.enqueue``), execution-ledger writes, and strong-confirmation
consume were plain sync calls. Every test here asserts thread identity at the
seam: the blocking callable must observe an OS thread id different from the
event loop's, which fails deterministically while the call runs inline.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from agents.core.house.actuation import (
    HOUSE_CONTROL_KIND,
    HOUSE_SECURITY_KIND,
    HouseActuator,
)
from agents.core.house.contracts import HouseEntity, HouseSnapshot
from agents.core.kernel import Decision, Verdict

_LIGHT_PAYLOAD = {
    "version": 1,
    "control": "light",
    "entity_id": "light.kitchen",
    "action": "on",
    "risk_tier": 1,
    "reversible": True,
    "signal_quality": 1.0,
}


class _Kernel:
    def __call__(self, action, capability=None):
        return Decision(Verdict.GRANT, reason="kernel-grant", tier=1)


class _Simulator:
    def __init__(self, *, entity_id="light.kitchen", state="off", now=100.0):
        self.entity_id = entity_id
        self.state = state
        self.now = now
        self.status = "live"
        self.calls = []

    async def snapshot(self):
        entity = HouseEntity(
            entity_id=self.entity_id,
            domain=self.entity_id.split(".", 1)[0],
            name=self.entity_id,
            state=self.state,
            updated_at=self.now,
            attributes=(),
        )
        return HouseSnapshot(
            enabled=True,
            status=self.status,
            observed_at=self.now,
            entities=(entity,),
        )

    async def apply(self, command):
        self.calls.append(dict(command))
        self.state = {
            ("light", "on"): "on",
            ("light", "off"): "off",
            ("security", "lock"): "locked",
        }[(command["control"], command["action"])]
        self.now += 1.0
        return {"ok": True, "transport_status": 200}


class _RecordingLedger:
    """Delegates to the real ledger while noting which thread each op ran on."""

    def __init__(self, inner):
        self._inner = inner
        self.thread_ids = []

    def _note(self):
        self.thread_ids.append(threading.get_ident())

    def lookup(self, task_id, digest):
        self._note()
        return self._inner.lookup(task_id, digest)

    def begin(self, task_id, digest):
        self._note()
        return self._inner.begin(task_id, digest)

    def finish(self, task_id, result):
        self._note()
        self._inner.finish(task_id, result)

    def abort(self, task_id):
        self._note()
        self._inner.abort(task_id)


class _FakeConfirmations:
    def __init__(self):
        self.thread_ids = []

    def mint(self, **_binding):
        self.thread_ids.append(threading.get_ident())
        time.sleep(0.01)
        return {"token": "challenge-token", "status": "challenge_minted"}

    def confirm(self, token, **_binding):
        self.thread_ids.append(threading.get_ident())
        time.sleep(0.01)
        return {"token": token, "status": "confirmed"}

    def consume(self, **_binding):
        self.thread_ids.append(threading.get_ident())
        return True


def _actuator(tmp_path, simulator, *, enqueue=None, confirmations=None, outcomes=None):
    return HouseActuator(
        state_reader=simulator,
        driver=simulator,
        authorizer=_Kernel(),
        enqueue=enqueue,
        outcome_provider=outcomes or (lambda _cap: {"total": 0, "confidence": 0.0}),
        confirmation_store=confirmations,
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: simulator.now,
    )


@pytest.mark.asyncio
async def test_governed_enqueue_runs_off_the_event_loop_thread(tmp_path):
    loop_thread = threading.get_ident()
    observed_threads = []
    enqueued_kwargs = []

    # Stands in for AutonomyWorker.govern_enqueue: same positional/keyword
    # contract, records the OS thread it executed on instead of hitting sqlite.
    def spy_enqueue(agent, kind, title, **kwargs):
        observed_threads.append(threading.get_ident())
        enqueued_kwargs.append({"agent": agent, "kind": kind, "title": title, **kwargs})
        return 41

    actuator = _actuator(tmp_path, _Simulator(), enqueue=spy_enqueue)

    result = await actuator.request_light("light.kitchen", state="on")

    assert result["queued"] is True and result["task_id"] == 41
    assert observed_threads and all(tid != loop_thread for tid in observed_threads)
    assert enqueued_kwargs == [
        {
            "agent": "jarvis",
            "kind": HOUSE_CONTROL_KIND,
            "title": "light on → light.kitchen",
            "payload": _LIGHT_PAYLOAD,
            "risk_tier": 1,
            "autonomy_level": "ask",
            "origin": "generated",
        }
    ]


@pytest.mark.asyncio
async def test_outcome_stats_run_off_the_event_loop_thread(tmp_path):
    loop_thread = threading.get_ident()
    outcome_threads = []

    def blocking_outcomes(_capability):
        outcome_threads.append(threading.get_ident())
        time.sleep(0.01)
        return {"total": 20, "confidence": 0.9}

    actuator = _actuator(
        tmp_path,
        _Simulator(),
        enqueue=lambda *_args, **_kwargs: 42,
        outcomes=blocking_outcomes,
    )

    result = await actuator.request_light("light.kitchen", state="on")

    assert result["queued"] is True and result["task_id"] == 42
    assert result["autonomy_level"] == "act"
    assert outcome_threads and all(thread_id != loop_thread for thread_id in outcome_threads)


@pytest.mark.asyncio
async def test_confirmation_wrappers_run_store_work_off_the_event_loop_thread(tmp_path):
    loop_thread = threading.get_ident()
    confirmations = _FakeConfirmations()
    actuator = _actuator(
        tmp_path,
        _Simulator(entity_id="lock.front_door", state="locked"),
        confirmations=confirmations,
    )
    task = SimpleNamespace(
        id=10,
        kind=HOUSE_SECURITY_KIND,
        payload={
            "version": 1,
            "control": "security",
            "entity_id": "lock.front_door",
            "action": "unlock",
            "risk_tier": 3,
            "reversible": False,
            "signal_quality": 1.0,
        },
    )

    challenge = await actuator.mint_confirmation_async(task)
    confirmed = await actuator.confirm_async(challenge["token"], task)

    assert challenge["status"] == "challenge_minted"
    assert confirmed == {"token": "challenge-token", "status": "confirmed"}
    assert confirmations.thread_ids and all(
        thread_id != loop_thread for thread_id in confirmations.thread_ids
    )


@pytest.mark.asyncio
async def test_execution_ledger_ops_run_off_the_event_loop_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    loop_thread = threading.get_ident()
    actuator = _actuator(tmp_path, _Simulator())
    actuator._ledger = _RecordingLedger(actuator._ledger)
    task = SimpleNamespace(id=7, kind=HOUSE_CONTROL_KIND, payload=dict(_LIGHT_PAYLOAD))

    result = await actuator.execute_task(task)

    assert result["status"] == "verified"
    recorded = actuator._ledger.thread_ids
    assert recorded and all(tid != loop_thread for tid in recorded)


@pytest.mark.asyncio
async def test_strong_confirmation_consume_runs_off_the_event_loop_thread(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    loop_thread = threading.get_ident()
    confirmations = _FakeConfirmations()
    simulator = _Simulator(entity_id="lock.front_door", state="unlocked")
    actuator = _actuator(tmp_path, simulator, confirmations=confirmations)
    task = SimpleNamespace(
        id=9,
        kind=HOUSE_SECURITY_KIND,
        payload={
            "version": 1,
            "control": "security",
            "entity_id": "lock.front_door",
            "action": "lock",
            "risk_tier": 3,
            "reversible": False,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["status"] == "verified"
    assert confirmations.thread_ids
    assert all(tid != loop_thread for tid in confirmations.thread_ids)
