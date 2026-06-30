"""0.34 wiring — AutonomyCoordinator drains the durable workflow pending-queue.

The drain *mechanics* (run/complete, retry-with-backoff until the cap, dead) are
covered by tests/test_workflow_pending_queue.py. This proves the coordinator wires
that machinery correctly: opt-in via JARVIS_WORKFLOW_PERSIST (byte-identical when
unset), resolves pipeline ids through the live registry, caches the queue, and a
drain hiccup never breaks the autonomy tick.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.autonomy_coordinator as acmod  # noqa: E402
from agents.core.autonomy_coordinator import AutonomyCoordinator  # noqa: E402
from agents.core.workflows.pending_queue import WorkflowPendingQueue  # noqa: E402


class _FakeEngine:
    def __init__(self):
        self.calls = []

    async def drain_pending(self, queue, resolve, *, now=None):
        self.calls.append((queue, resolve, now))
        return {"ran": 0, "done": 0, "retried": 0, "dead": 0, "skipped": 0}


class _FakeRegistry:
    def get(self, pipeline_id):
        return None


class _Orch:
    def __init__(self, engine=None, registry=None):
        self.workflow_engine = engine
        self.workflow_registry = registry


@pytest.mark.asyncio
async def test_noop_when_flag_unset(monkeypatch):
    monkeypatch.delenv("JARVIS_WORKFLOW_PERSIST", raising=False)
    eng = _FakeEngine()
    c = AutonomyCoordinator(_Orch(eng, _FakeRegistry()))
    await c._drain_workflow_pending()
    assert eng.calls == []            # engine untouched → tick byte-identical
    assert c._pending_queue is None   # no queue even constructed


@pytest.mark.asyncio
async def test_drains_when_flag_set_and_caches_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "1")
    made = WorkflowPendingQueue(tmp_path / "pending.json")
    monkeypatch.setattr(acmod, "WorkflowPendingQueue", lambda: made)
    eng, reg = _FakeEngine(), _FakeRegistry()
    c = AutonomyCoordinator(_Orch(eng, reg))

    await c._drain_workflow_pending()
    assert len(eng.calls) == 1
    queue, resolve, _ = eng.calls[0]
    assert queue is made              # the durable queue
    assert resolve == reg.get         # resolves pipeline ids via the live registry

    await c._drain_workflow_pending()  # second tick reuses the cached queue
    assert eng.calls[1][0] is made


@pytest.mark.asyncio
async def test_noop_when_engine_absent(monkeypatch):
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "1")
    c = AutonomyCoordinator(_Orch(engine=None, registry=_FakeRegistry()))
    await c._drain_workflow_pending()  # engine None → no crash, no queue built
    assert c._pending_queue is None


@pytest.mark.asyncio
async def test_drain_hiccup_is_swallowed(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "1")
    monkeypatch.setattr(acmod, "WorkflowPendingQueue",
                        lambda: WorkflowPendingQueue(tmp_path / "pending.json"))

    class _BoomEngine:
        async def drain_pending(self, *a, **k):
            raise RuntimeError("drain blew up")

    c = AutonomyCoordinator(_Orch(_BoomEngine(), _FakeRegistry()))
    await c._drain_workflow_pending()  # must not raise — a drain hiccup is contained
