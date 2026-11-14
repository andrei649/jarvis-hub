"""A restart drain holds new autonomy claims without spending attempts."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.owner_once import OwnerOnceOwner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.restart_runtime import runtime_for
from tests.test_h084_update_kernel import _request, _rig
from tests.test_h487_consent_runtime_integration import (
    _Process,
    ask,
    consent_runtime,
)


@pytest.fixture
def rig(tmp_path):
    queue = TaskQueue(str(tmp_path / "worker.db")).initialize()
    runtime = runtime_for(SimpleNamespace())
    yield queue, runtime
    queue.close()


def approved(queue, title):
    task_id = queue.enqueue("jarvis", "draft_email", title)
    queue.transition(task_id, TaskStatus.APPROVED)
    return task_id


@pytest.mark.asyncio
async def test_closed_gate_holds_ordinary_row_before_claim_and_attempt(rig):
    queue, runtime = rig
    task_id = approved(queue, "first")
    seen = []

    async def execute(task):
        seen.append(task.id)
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=execute, restart_runtime=runtime)
    token = runtime.close_admission()
    assert (await worker.tick(task_id=task_id))["held"] == 1
    assert queue.get(task_id).status == "approved"
    assert queue.get(task_id).attempts == 0
    assert seen == []
    assert runtime.reopen(token)
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert seen == [task_id]


@pytest.mark.asyncio
async def test_signed_enforce_row_is_held_before_mediated_claim(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    runtime = runtime_for(rig.orch)
    rig.worker._restart_runtime = runtime
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        token = runtime.close_admission()
        assert (await rig.worker.tick(task_id=task_id))["held"] == 1
        current = rig.queue.get(task_id)
        assert current.status == "approved" and current.attempts == 0
        assert current.mediation_execution_id is None
        assert runtime.reopen(token)
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_close_during_first_row_holds_later_row_and_counts_until_done(rig):
    queue, runtime = rig
    first, second = approved(queue, "first"), approved(queue, "second")
    entered, release = asyncio.Event(), asyncio.Event()

    async def execute(task):
        if task.id == first:
            entered.set()
            await release.wait()
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=execute, restart_runtime=runtime)
    running = asyncio.create_task(worker.tick(limit=2))
    await asyncio.wait_for(entered.wait(), 2)
    token = runtime.close_admission()
    assert runtime.snapshot()["by_kind"]["worker"] == 1
    release.set()
    summary = await running
    assert summary["done"] == 1 and summary["held"] == 1
    assert queue.get(first).status == "done"
    assert queue.get(second).status == "approved" and queue.get(second).attempts == 0
    assert runtime.snapshot()["by_kind"]["worker"] == 0
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_closed_gate_precedes_private_consent_claim(rig, monkeypatch):
    queue, runtime = rig
    task_id = approved(queue, "consent")
    executor = TaskExecutor(execution_guard=lambda _task: True)
    worker = AutonomyWorker(queue, executor=executor.execute, restart_runtime=runtime)
    monkeypatch.setattr(queue, "consent_task_marker", lambda _id: True)
    calls = []
    monkeypatch.setattr(queue, "claim_consent", lambda *_args, **_kwargs: calls.append(1))
    token = runtime.close_admission()
    assert (await worker.tick(task_id=task_id))["held"] == 1
    assert calls == []
    assert queue.get(task_id).attempts == 0
    assert (await worker._run_consent(queue.get(task_id)))["held"] == 1
    assert calls == []
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_budgeted_handler_child_can_finish_nested_admitted_work(rig):
    queue, runtime = rig
    task_id = approved(queue, "child")
    entered, release = asyncio.Event(), asyncio.Event()
    nested = []

    async def handler(_task):
        entered.set()
        await release.wait()
        lease = runtime.acquire("job", allow_reentrant=True)
        nested.append(lease is not None)
        if lease is not None:
            lease.release()
        return {"status": "ok"}

    executor = TaskExecutor(max_wall_seconds=2, restart_runtime=runtime)
    executor.register("draft_email", handler)
    worker = AutonomyWorker(queue, executor=executor.execute, restart_runtime=runtime)
    running = asyncio.create_task(worker.tick(task_id=task_id))
    await asyncio.wait_for(entered.wait(), 2)
    token = runtime.close_admission()
    release.set()
    assert (await running)["done"] == 1
    assert nested == [True]
    assert runtime.snapshot()["active"] == 0
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_cancelled_child_before_first_step_never_creates_handler(rig):
    _queue, runtime = rig
    parent = runtime.acquire("worker")
    assert parent is not None
    invoked = []

    async def handler():
        invoked.append(True)

    try:
        with parent.bind():
            child = asyncio.create_task(runtime.bind_child_operation(handler))
            child.cancel()
            with pytest.raises(asyncio.CancelledError):
                await child
        assert invoked == []
    finally:
        parent.release()


@pytest.mark.asyncio
async def test_cancelled_worker_releases_lease_and_keeps_running_receipt(rig):
    queue, runtime = rig
    task_id = approved(queue, "cancelled")
    entered = asyncio.Event()

    async def execute(_task):
        entered.set()
        await asyncio.Event().wait()

    worker = AutonomyWorker(queue, executor=execute, restart_runtime=runtime)
    running = asyncio.create_task(worker.tick(task_id=task_id))
    await asyncio.wait_for(entered.wait(), 2)
    assert runtime.snapshot()["by_kind"]["worker"] == 1
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert runtime.snapshot()["by_kind"]["worker"] == 0
    assert queue.get(task_id).status == "running"


@pytest.mark.asyncio
async def test_parallel_child_rows_acquire_separately(rig):
    queue, runtime = rig
    first, second = approved(queue, "first"), approved(queue, "second")
    entered, release = asyncio.Event(), asyncio.Event()
    child_summaries = []

    async def execute(task):
        if task.id == first:
            entered.set()
            await release.wait()
            # This Task copies the first worker row's ContextVar but has no
            # exact binder; it must not claim the second approved row.
            child_summaries.append(await asyncio.create_task(worker.tick(task_id=second)))
        return {"status": "ok"}

    worker = AutonomyWorker(queue, executor=execute, restart_runtime=runtime)
    first_run = asyncio.create_task(worker.tick(task_id=first))
    await asyncio.wait_for(entered.wait(), 2)
    token = runtime.close_admission()
    release.set()
    assert (await first_run)["done"] == 1
    assert child_summaries[0]["held"] == 1
    assert queue.get(second).status == "approved"
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_same_task_live_parent_can_finish_nested_claim(rig):
    queue, runtime = rig
    task_id = approved(queue, "nested")
    worker = AutonomyWorker(
        queue, executor=lambda _task: asyncio.sleep(0, result={"status": "ok"}),
        restart_runtime=runtime,
    )
    parent = runtime.acquire("turn")
    assert parent is not None
    try:
        with parent.bind():
            token = runtime.close_admission()
            assert (await worker.tick(task_id=task_id))["done"] == 1
            assert queue.get(task_id).status == "done"
            assert runtime.snapshot()["by_kind"]["worker"] == 0
    finally:
        parent.release()
    assert runtime.reopen(token)


@pytest.mark.asyncio
async def test_real_consent_proof_runs_with_explicitly_bound_executor_child(
        consent_runtime, monkeypatch):
    source = consent_runtime
    gate = runtime_for(source.orch)
    source.worker._restart_runtime = gate
    source.worker.executor.__self__._restart_runtime = gate
    effects = []

    async def spawn(*args, **_kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = await ask(source)
    offer = source.q.pending_consent_offer(task.id)
    assert offer is not None
    assert await source.worker.apply_consent_decision(
        task.id, offer.revision, choice="session",
        actor=OwnerConsentActor("admin", "admin", lambda: True),
    ) is not None
    token = gate.close_admission()
    assert (await source.worker.tick(task_id=task.id))["held"] == 1
    assert source.q.get(task.id).attempts == 0 and effects == []
    assert gate.reopen(token)
    assert (await source.worker.tick(task_id=task.id))["done"] == 1
    assert source.q.get(task.id).status == "done"
    assert effects == [("git", "reset", "--hard")]
    assert gate.snapshot()["by_kind"]["worker"] == 0


@pytest.mark.asyncio
async def test_accepted_owner_once_remains_unclaimed_during_drain(tmp_path):
    signer = DetachedHMACSigner(
        lambda data: hmac.new(b"restart-owner-once", data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "owner.db"), mediation_signer=signer).initialize()
    runtime = runtime_for(SimpleNamespace())
    turn = open_approval_turn(
        session_id="owner", session_instance="birth",
        principal=Principal(channel="telegram", sender="99", chat="99", admin=True),
        session_is_live=lambda _session, _instance: True,
    )
    bound = bind_approval_turn(turn)
    try:
        with tool_approval_scope("terminal_run"):
            task_id = queue.enqueue(
                "jarvis", "toolrpc.terminal_run", "One command",
                payload={"tool": "terminal_run", "target": "terminal_run",
                         "args": {"target": "dev", "command": "printf hello"}},
                risk_tier=3, autonomy_level="ask",
            )
            queue.transition(task_id, TaskStatus.BLOCKED,
                             decided_by="policy", decision="needs-approval")
        digest = queue.approval_snapshot_digest(queue.get(task_id))
        judgement = SmartApprovalResult("deny", "a" * 64, "b" * 64,
                                        {"model": "fixture"}, 1.0)
        assert queue.store_smart_terminal_judgement(
            task_id, digest, judgement, check=lambda: True)[0]
        offer = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
        assert offer is not None
        generation = "22222222222242228222222222222222"
        assert queue.mark_owner_once_delivered(
            offer, chat_id=99, user_id=99, message_id=17, generation=generation,
            live_check=lambda: True)
        owner = OwnerOnceOwner(turn.principal_key, "telegram", 99, 99, 17, generation)
        claim = queue.decide_owner_once(
            offer, offer.nonce, "once", authenticated_owner=owner, live_check=lambda: True)
        assert claim is not None
        calls = []

        async def execute(task):
            calls.append(task.id)
            return {"status": "ok"}

        worker = AutonomyWorker(queue, executor=execute, restart_runtime=runtime)
        token = runtime.close_admission()
        assert (await worker._run_owner_once(claim, live_check=lambda: True))["held"] == 1
        assert queue.get(task_id).status == "approved"
        assert queue.get(task_id).attempts == 0 and calls == []
        assert runtime.reopen(token)
    finally:
        close_approval_turn(turn, bound)
        queue.close()
