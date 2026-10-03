"""A signed owner reply runs only through the private one-use worker scope."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import replace

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    tool_approval_scope,
)
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.owner_once import OwnerOnceOwner
from agents.core.autonomy.owner_once_execution import owner_once_current, owner_once_dispatch
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge


@pytest.fixture
def accepted(tmp_path):
    signer = DetachedHMACSigner(
        lambda data: hmac.new(b"owner-once-worker", data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "owner-worker.db"), mediation_signer=signer).initialize()
    turn = open_approval_turn(
        session_id="owner", session_instance="birth",
        principal=Principal(channel="telegram", sender="99", chat="99", admin=True),
        session_is_live=lambda _session, _instance: True,
    )
    token = bind_approval_turn(turn)
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
    denied = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
    assert queue.store_smart_terminal_judgement(task_id, digest, denied,
                                                check=lambda: True)[0]
    offer = queue.offer_owner_once(task_id, digest, turn=turn, live_check=lambda: True)
    assert offer is not None
    generation = "22222222222242228222222222222222"
    assert queue.mark_owner_once_delivered(
        offer, chat_id=99, user_id=99, message_id=17, generation=generation,
        live_check=lambda: True,
    )
    owner = OwnerOnceOwner(turn.principal_key, "telegram", 99, 99, 17, generation)
    claim = queue.decide_owner_once(offer, offer.nonce, "once",
                                    authenticated_owner=owner, live_check=lambda: True)
    assert claim is not None
    yield queue, task_id, claim, offer
    close_approval_turn(turn, token)
    queue.close()


@pytest.mark.asyncio
async def test_generic_off_mode_and_named_tick_cannot_use_owner_reply(accepted):
    queue, task_id, claim, _offer = accepted
    seen = []

    async def executor(task):
        seen.append(task.id)
        assert worker.execution_allowed(task) is False
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(queue, executor=executor)
    assert worker.execution_allowed(queue.get(task_id)) is False
    assert owner_once_current(task_id) is False
    assert owner_once_dispatch(task_id) is False
    assert (await worker.tick(task_id=task_id))["ran"] == 0
    assert seen == [] and queue.get(task_id).status == "approved"
    assert claim.task_id == task_id
    running = queue.claim_owner_once(task_id, claim, execution_id="manual-claim",
                                     live_check=lambda: True)
    assert running is not None
    assert not worker.execution_allowed(running)
    assert not worker.execution_allowed(replace(running, decided_by="policy"))


@pytest.mark.asyncio
async def test_legacy_null_decision_remains_runnable_beside_owner_approval(accepted):
    queue, owner_id, _claim, _offer = accepted
    seen = []

    async def executor(task):
        seen.append(task.id)
        return {"status": "ok"}

    task_id = queue.enqueue("jarvis", "draft_email", "Ordinary task", {"to": "x"})
    queue.transition(task_id, TaskStatus.APPROVED)
    worker = AutonomyWorker(queue, executor=executor)
    assert [task.id for task in queue.runnable(task_id=task_id)] == [task_id]
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert seen == [task_id] and queue.get(owner_id).status == "approved"


@pytest.mark.asyncio
async def test_private_owner_once_dispatches_once_and_signs_done(accepted):
    queue, task_id, claim, _offer = accepted
    calls = []
    copied = []
    children = []
    release_child = asyncio.Event()

    async def executor(task):
        assert worker.execution_allowed(task)
        assert owner_once_current(task.id)
        assert owner_once_dispatch(task.id)
        assert not owner_once_dispatch(task.id)
        async def copied_context():
            await release_child.wait()
            copied.append((owner_once_current(task.id), owner_once_dispatch(task.id)))

        children.append(asyncio.create_task(copied_context()))
        calls.append(task.id)
        return {"status": "ok", "result": {"ok": True, "stdout": "hello"}}

    worker = AutonomyWorker(queue, executor=executor)
    result = await worker._run_owner_once(claim, live_check=lambda: True)
    assert result["done"] == 1 and calls == [task_id]
    assert queue.get(task_id).status == "done"
    assert queue.get(task_id).attempts == 1
    assert queue.verify_owner_once_terminal_result(task_id)
    assert not owner_once_current(task_id)
    assert not owner_once_dispatch(task_id)
    release_child.set()
    await children[0]
    assert copied == [(False, False)]
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["ran"] == 0


@pytest.mark.asyncio
async def test_owner_once_halt_and_failure_never_retry(accepted):
    queue, task_id, claim, _offer = accepted
    halted = [True]

    class Stop:
        def is_halted(self, _scope=None):
            return halted[0]

    calls = []

    async def executor(task):
        calls.append(task.id)
        raise RuntimeError("executor failed")

    worker = AutonomyWorker(queue, executor=executor, kill_switch=Stop())
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["ran"] == 0
    assert queue.get(task_id).status == "approved" and calls == []
    halted[0] = False
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["failed"] == 1
    assert calls == [task_id] and queue.get(task_id).status == "failed"
    assert queue.get(task_id).attempts == 1
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["ran"] == 0


@pytest.mark.asyncio
async def test_hold_revocation_and_copied_claim_never_start(accepted):
    queue, task_id, claim, offer = accepted
    called = []

    async def executor(task):
        called.append(task.id)
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(queue, executor=executor)
    queue.mediation_mode = "hold"
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["ran"] == 0
    queue.mediation_mode = "off"
    assert (await worker._run_owner_once(replace(claim), live_check=lambda: True))["ran"] == 0
    assert queue.revoke_owner_once(offer)
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["ran"] == 0
    assert called == [] and queue.get(task_id).status == "rejected"


@pytest.mark.asyncio
async def test_success_shape_without_physical_dispatch_is_not_done(accepted):
    queue, task_id, claim, _offer = accepted

    async def executor(task):
        assert worker.execution_allowed(task)
        assert owner_once_current(task.id)
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(queue, executor=executor)
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["failed"] == 1
    assert queue.get(task_id).status == "failed"
    assert queue.get(task_id).attempts == 1
    assert not queue.verify_owner_once_terminal_result(task_id)


@pytest.mark.asyncio
async def test_halt_after_claim_revokes_physical_dispatch(accepted):
    queue, task_id, claim, _offer = accepted
    halted = [False]

    class Stop:
        def is_halted(self, _scope=None):
            return halted[0]

    async def executor(task):
        assert worker.execution_allowed(task)
        halted[0] = True
        assert not owner_once_current(task.id)
        assert not owner_once_dispatch(task.id)
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(queue, executor=executor, kill_switch=Stop())
    assert (await worker._run_owner_once(claim, live_check=lambda: True))["failed"] == 1
    assert queue.get(task_id).status == "failed"
    assert not queue.verify_owner_once_terminal_result(task_id)


@pytest.mark.asyncio
async def test_cancellation_resistant_executor_cannot_dispatch_late(accepted):
    queue, task_id, claim, _offer = accepted
    entered = asyncio.Event()
    release = asyncio.Event()
    physical = []

    async def executor(task):
        assert worker.execution_allowed(task)
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        if owner_once_dispatch(task.id):
            physical.append(task.id)
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(queue, executor=executor)
    running = asyncio.create_task(worker._run_owner_once(claim, live_check=lambda: True))
    await entered.wait()
    running.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert physical == []
    assert not owner_once_current(task_id)
    assert not queue.verify_owner_once_terminal_result(task_id)


@pytest.mark.asyncio
async def test_enforced_owner_run_consumes_b7_permit_and_records_governed_event(
        tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(
        lambda data: hmac.new(b"enforced-owner-worker", data, hashlib.sha256).hexdigest()
    )
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(
        str(tmp_path / "enforced-owner-worker.db"), mediation_mode="enforce",
        mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_classifier=lambda _kind: True, mediation_scope="global",
    ).initialize()
    calls = []

    async def executor(task):
        assert owner_once_current(task.id)
        assert not owner_once_dispatch(task.id)
        assert worker.execution_allowed(task)
        assert not worker.execution_allowed(task)
        assert owner_once_dispatch(task.id)
        calls.append(task.id)
        return {"status": "ok", "result": {"ok": True}}

    worker = AutonomyWorker(
        queue, executor=executor, mediation_signer=signer,
        kernel=MediationKernelBridge(lambda _action: Decision(
            Verdict.QUEUE, tier=3, reason="owner review")),
    )
    turn = open_approval_turn(
        session_id="owner", session_instance="birth",
        principal=Principal(channel="telegram", sender="99", chat="99", admin=True),
        session_is_live=lambda _session, _instance: True,
    )
    token = bind_approval_turn(turn)
    try:
        with tool_approval_scope("terminal_run"):
            task = await worker.submit(
                "jarvis", "toolrpc.terminal_run", "One command",
                {"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": "printf hello"}},
                attention_mode="none",
            )
        assert task.status == "blocked"
        digest = queue.approval_snapshot_digest(queue.get(task.id))
        denied = SmartApprovalResult("deny", "a" * 64, "b" * 64, {"model": "fixture"}, 1.0)
        assert queue.store_smart_terminal_judgement(
            task.id, digest, denied, check=lambda: True,
        )[0]
        offer = queue.offer_owner_once(task.id, digest, turn=turn, live_check=lambda: True)
        assert offer is not None
        generation = "22222222222242228222222222222222"
        assert queue.mark_owner_once_delivered(
            offer, chat_id=99, user_id=99, message_id=17, generation=generation,
            live_check=lambda: True,
        )
        claim = queue.decide_owner_once(
            offer, offer.nonce, "once",
            authenticated_owner=OwnerOnceOwner(turn.principal_key, "telegram", 99, 99, 17,
                                               generation),
            live_check=lambda: True,
        )
        assert claim is not None
        assert (await worker._run_owner_once(claim, live_check=lambda: True))["done"] == 1
        assert calls == [task.id]
        assert queue.verified_mediation_stats()["governed"] == 1
        assert queue.verify_owner_once_terminal_result(task.id)
    finally:
        close_approval_turn(turn, token)
        queue.close()
