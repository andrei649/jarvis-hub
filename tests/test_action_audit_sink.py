"""The autonomy lifecycle must leave a signed, verifiable action record.

Regression context: `AutonomyWorker._audit()` and `RemediationRunner._done()`
both call ``audit.log(event_str, dict)``, but the only sink ever passed in
production was `AuditLogger`, whose `log()` takes a `SecurityEvent` — and the
worker was constructed with no sink at all (`audit=None`), so `_audit()` returned
on its first line. Nothing in the govern → approve → execute path was recorded
anywhere. These tests pin the sink shape, the chain, and the wiring.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import AutonomyWorker, TaskQueue  # noqa: E402
from agents.core.autonomy.audit_sink import ActionAuditSink  # noqa: E402
from agents.core.security.anchor import IntentLog  # noqa: E402


@pytest.fixture()
def sink(tmp_path):
    return ActionAuditSink(IntentLog(path=tmp_path / "intent_log.json",
                                     secret_key="test-key"))


EXECUTED: list[int] = []


async def _executor(task):
    EXECUTED.append(task.id)
    return {"status": "ok"}


def test_sink_maps_the_worker_call_shape_onto_a_signed_record(sink):
    entry = sink.log("autonomy.done", {"task_id": 7, "agent": "steve",
                                       "kind": "email.send", "detail": "executed"})

    assert entry["actor"] == "steve"
    assert entry["action"] == "autonomy.done"
    assert entry["why"] == "executed"
    assert entry["cause"] == "task:7"          # causal link back to the task
    assert entry["metadata"]["kind"] == "email.send"
    assert entry["signature"]                   # HMAC-signed, not just hashed
    assert sink.verify()["ok"] is True


def test_sink_never_raises_into_an_authorized_action():
    class _Exploding:
        def record(self, **_kw):
            raise RuntimeError("disk full")

    sink = ActionAuditSink(_Exploding())
    assert sink.log("autonomy.done", {"task_id": 1}) is None   # swallowed

    # And a missing log is inert rather than fatal — the None case the worker
    # shipped with for its whole life.
    assert ActionAuditSink(None).log("autonomy.done", {"task_id": 1}) is None


def test_sink_coerces_unserializable_payload_values(sink):
    class _Opaque:
        def __repr__(self):
            return "<opaque>"

    entry = sink.log("autonomy.failed", {"task_id": 2, "detail": _Opaque()})
    assert entry["metadata"]["detail"] == "<opaque>"
    assert sink.verify()["ok"] is True          # metadata is hashed, so it must serialize


@pytest.mark.asyncio
async def test_full_cycle_is_recorded_and_the_chain_verifies(tmp_path, sink):
    """govern_enqueue → apply_decision → execute leaves a verifiable trail."""
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, audit=sink, executor=_executor)

    task_id = worker.govern_enqueue(
        agent="steve", kind="demo.action", title="demo",
        payload={"risk_tier": 3},          # irreversible → must be asked, not auto-run
    )
    task = queue.get(task_id)
    assert task.status == "blocked", "an irreversible action must not auto-approve"

    EXECUTED.clear()
    await worker.apply_decision(task_id, "accept", decided_by="owner")
    stats = await worker.tick()

    assert stats["done"] == 1
    assert [task_id] == EXECUTED

    actions = [e["action"] for e in sink._intent_log.list(limit=50)]
    assert "autonomy.decision.accept" in actions, actions
    assert "autonomy.done" in actions, actions

    # Every record carries the decision's provenance and survives verification.
    accept = next(e for e in sink._intent_log.list(limit=50)
                  if e["action"] == "autonomy.decision.accept")
    assert accept["why"] == "by owner"
    assert accept["cause"] == f"task:{task_id}"
    assert sink.verify()["ok"] is True


@pytest.mark.asyncio
async def test_tampering_with_a_record_is_detected(tmp_path, sink):
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, audit=sink, executor=_executor)
    task_id = worker.govern_enqueue(agent="steve", kind="demo.action", title="demo",
                                    payload={"risk_tier": 3})
    await worker.apply_decision(task_id, "accept", decided_by="owner")
    assert sink.verify()["ok"] is True

    # Rewrite who approved it — the point of the chain is that this cannot pass.
    entries = sink._intent_log._entries
    entries[-1]["why"] = "by attacker"
    assert sink.verify()["ok"] is False
