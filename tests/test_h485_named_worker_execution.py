"""Named worker selection uses the existing governed claim and execution path."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import threading
from types import SimpleNamespace

import pytest

from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.queue import MAX_ATTEMPTS, TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge


@pytest.fixture
def queue(tmp_path):
    secret = b"h485-named-signed"
    signer = DetachedHMACSigner(lambda raw: hmac.new(secret, raw, hashlib.sha256).hexdigest())
    value = TaskQueue(str(tmp_path / "named-worker.db"), mediation_signer=signer).initialize()
    yield value
    value.close()


def approved(queue, *, agent="jarvis", tier=1, title="approved"):
    task_id = queue.enqueue(agent, "draft_email", title, risk_tier=tier)
    queue.transition(task_id, TaskStatus.APPROVED, decided_by="policy", decision="auto-act")
    return task_id


@pytest.mark.asyncio
async def test_named_tick_executes_only_selected_approved_task(queue):
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok", "task_id": task.id}

    worker = AutonomyWorker(queue, executor=executor)
    older = approved(queue, title="older")
    selected = approved(queue, title="selected")
    summary = await worker.tick(limit=1, task_id=selected)
    assert summary["ran"] == summary["done"] == 1
    assert seen == [selected]
    assert queue.get(selected).status == "done"
    assert queue.get(selected).result == {"status": "ok", "task_id": selected}
    assert queue.get(older).status == "approved"
    assert queue.get(older).attempts == 0
    assert [task.id for task in queue.runnable(task_id=older)] == [older]


@pytest.mark.asyncio
async def test_selector_keeps_status_retry_and_tier_predicates(queue):
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=executor)
    high = approved(queue, tier=3, title="high")
    exhausted = approved(queue, title="exhausted")
    for _ in range(MAX_ATTEMPTS):
        queue.increment_attempts(exhausted)
    blocked = queue.enqueue("jarvis", "draft_email", "blocked", risk_tier=1)
    queue.transition(blocked, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    for task_id in (high, exhausted, blocked):
        assert queue.runnable(task_id=task_id, max_tier=1) == []
        assert (await worker.tick(task_id=task_id, max_tier=1))["ran"] == 0
    assert seen == []
    assert [task.id for task in queue.runnable(task_id=high)] == [high]
    assert (await worker.tick(task_id=high, max_tier=3))["done"] == 1
    assert seen == [high]
    assert queue.get(exhausted).status == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", [True, False, 0, -1, "1", 1.0])
async def test_invalid_selector_raises_before_housekeeping(queue, monkeypatch, selector):
    worker = AutonomyWorker(queue)
    touched = []

    async def housekeeping(*_args, **_kwargs):
        touched.append(True)

    monkeypatch.setattr(worker, "approval_housekeeping", housekeeping)
    with pytest.raises(ValueError, match="task_id"):
        queue.runnable(task_id=selector)
    with pytest.raises(ValueError, match="task_id"):
        await worker.tick(task_id=selector)
    assert touched == []


@pytest.mark.asyncio
async def test_named_tick_respects_global_and_agent_halt(queue):
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=executor)
    task_id = approved(queue, agent="jarvis")
    halted = {None}
    worker._kill_switch = SimpleNamespace(is_halted=lambda scope=None: scope in halted)
    assert (await worker.tick(task_id=task_id))["halted"] is True
    assert queue.get(task_id).status == "approved"
    halted.clear()
    halted.add("jarvis")
    summary = await worker.tick(task_id=task_id)
    assert summary["held"] == 1 and summary["ran"] == 0
    assert queue.get(task_id).status == "approved" and seen == []
    halted.clear()
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert seen == [task_id]


@pytest.mark.asyncio
async def test_named_smart_terminal_executes_only_selected_signed_approval(queue):
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=executor)

    def signed(command):
        task_id = queue.enqueue(
            "jarvis", "toolrpc.terminal_run", "Run terminal command",
            payload={"tool": "terminal_run", "target": "terminal_run",
                     "args": {"target": "dev", "command": command}},
            risk_tier=3, autonomy_level="ask",
        )
        queue.transition(task_id, TaskStatus.BLOCKED,
                         decided_by="policy", decision="needs-approval")
        digest = queue.approval_snapshot_digest(queue.get(task_id))
        result = SmartApprovalResult(
            "approve", "a" * 64, "b" * 64, {"model": "fixture"}, 1_000_000.0,
        )
        assert queue.store_smart_terminal_judgement(
            task_id, digest, result, check=lambda: True,
        )[0]["decision"] == "approve"
        return task_id

    older = signed("printf older")
    selected = signed("printf selected")
    assert queue.get(older).status == queue.get(selected).status == "approved"
    assert queue.verify_smart_terminal_approval(selected, check=lambda _receipt: True)
    summary = await worker.tick(task_id=selected, limit=1)
    assert summary["ran"] == summary["done"] == 1
    assert seen == [selected]
    assert queue.get(selected).status == "done"
    assert queue.get(older).status == "approved"
    assert queue.get(older).attempts == 0


@pytest.mark.asyncio
async def test_named_tick_preserves_enforced_mediation_receipt_and_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    secret = b"h485-named-mediation"
    signer = DetachedHMACSigner(lambda raw: hmac.new(secret, raw, hashlib.sha256).hexdigest())
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(
        str(tmp_path / "mediated-named.db"), mediation_mode="enforce", mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_classifier=lambda _kind: True, mediation_scope="global",
    ).initialize()
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok"}

    worker = AutonomyWorker(
        queue, kernel=MediationKernelBridge(lambda _action: Decision(
            Verdict.QUEUE, tier=3, reason="owner review")),
        mediation_signer=signer, executor=executor,
    )
    try:
        older = await worker.submit("jarvis", "filesystem.write", "Older", {"path": "older"},
                                    attention_mode="none")
        selected = await worker.submit("jarvis", "filesystem.write", "Selected", {"path": "selected"},
                                       attention_mode="none")
        await worker.apply_decision(older.id, "accept")
        await worker.apply_decision(selected.id, "accept")
        queue.mediation_mode = "hold"
        try:
            assert (await worker.tick(task_id=selected.id))["ran"] == 0
            assert queue.get(selected.id).status == "approved" and seen == []
        finally:
            queue.mediation_mode = "enforce"
        assert (await worker.tick(task_id=selected.id))["done"] == 1
        assert seen == [selected.id]
        assert queue.get(selected.id).status == "done"
        assert queue.get(older.id).status == "approved"
        assert queue.verified_mediation_stats()["valid"] is True
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_two_sqlite_connections_racing_named_claim_execute_once(tmp_path, monkeypatch):
    db_path = str(tmp_path / "racing-named.db")
    first = TaskQueue(db_path).initialize()
    second = TaskQueue(db_path).initialize()
    seen = []
    seen_lock = threading.Lock()
    barrier = threading.Barrier(2)

    async def executor(task):
        with seen_lock:
            seen.append(task.id)
        await asyncio.sleep(0)
        return {"status": "ok"}

    try:
        task_id = approved(first)
        original_first = first.runnable
        original_second = second.runnable

        def synchronized(original):
            def read(*args, **kwargs):
                tasks = original(*args, **kwargs)
                barrier.wait(timeout=3)
                return tasks

            return read

        monkeypatch.setattr(first, "runnable", synchronized(original_first))
        monkeypatch.setattr(second, "runnable", synchronized(original_second))
        workers = [AutonomyWorker(first, executor=executor), AutonomyWorker(second, executor=executor)]

        def run(worker):
            return asyncio.run(worker.tick(task_id=task_id))

        summaries = await asyncio.gather(*(asyncio.to_thread(run, worker) for worker in workers))
        assert sorted(summary["ran"] for summary in summaries) == [0, 1]
        assert seen == [task_id]
        assert first.get(task_id).status == second.get(task_id).status == "done"
        assert first.get(task_id).attempts == 1
    finally:
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_named_claim_does_not_swallow_unrelated_queue_failure(queue, monkeypatch):
    worker = AutonomyWorker(queue)
    task_id = approved(queue)
    original = queue.transition

    def fail_claim(item_id, status, **kwargs):
        if item_id == task_id and status is TaskStatus.RUNNING:
            raise TaskQueueError("durable store failed")
        return original(item_id, status, **kwargs)

    monkeypatch.setattr(queue, "transition", fail_claim)
    with pytest.raises(TaskQueueError, match="durable store failed"):
        await worker.tick(task_id=task_id)
    assert queue.get(task_id).status == "approved"
