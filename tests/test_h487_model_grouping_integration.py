"""Real generic RPC intake groups cards, never durable decisions or executions."""

import asyncio
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.tool_rpc import ToolRPCServer


@pytest.fixture
def rig(tmp_path):
    path = str(tmp_path / "tasks.db")
    queue = TaskQueue(path).initialize()
    pushed, executed = [], []

    class Broker:
        async def dispatch(self, _id, _category, callback):
            await callback()
            return {"status": "delivered"}

    async def notify(task):
        pushed.append(task.id)
        return True

    worker = AutonomyWorker(queue, notifier=notify, delivery_broker=Broker())
    server = ToolRPCServer(enqueue=worker.govern_enqueue)

    async def send(args):
        executed.append(args)
        return {"ok": True}

    server.register_tool("send_mail", send, gated=True)
    worker.executor = server.execute
    value = SimpleNamespace(
        q=queue,
        path=path,
        worker=worker,
        server=server,
        send=send,
        pushed=pushed,
        executed=executed,
    )
    yield value
    queue.close()


async def ask(
    rig, *, actor="jarvis", args=None, principal=None, session="s", instance="i", live=True
):
    context = open_approval_turn(
        session_id=session,
        session_instance=instance,
        principal=principal or Principal(channel="web", admin=True),
        session_is_live=lambda sid, inst: live and sid == session and inst == instance,
    )
    token = bind_approval_turn(context)
    try:
        result = await rig.server.handle(
            {"tool": "send_mail", "args": args or {"to": "alice"}}, actor=actor
        )
        assert result["reason"] == "approval_required"
        return rig.q.get(result["task_id"])
    finally:
        close_approval_turn(context, token)


async def settle(rig):
    while rig.worker._bg_tasks:
        await asyncio.gather(*tuple(rig.worker._bg_tasks))


@pytest.mark.asyncio
async def test_actual_rpc_two_asks_one_card_two_tasks_and_one_execution(rig):
    first, second = await ask(rig), await ask(rig)
    await settle(rig)
    assert first.id != second.id
    assert rig.q.get(first.id).status == rig.q.get(second.id).status == "blocked"
    (group,) = rig.q.pending_groups()
    assert group["member_ids"] == [first.id, second.id]
    assert rig.pushed == [first.id] and rig.executed == []
    await rig.worker.apply_decision(first.id, "accept", decided_by="owner")
    assert rig.q.get(second.id).status == "blocked"
    await rig.worker.tick()
    await rig.worker.tick()
    assert rig.q.get(first.id).status == "done"
    assert rig.q.get(second.id).status == "blocked"
    assert rig.executed == [{"to": "alice"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "difference",
    ["actor", "principal", "session", "instance", "registration", "policy", "taint", "args"],
)
async def test_real_intake_identity_boundaries_never_merge(rig, difference):
    await ask(rig)
    kwargs = {}
    if difference == "actor":
        kwargs["actor"] = "pepper"
    elif difference == "principal":
        kwargs["principal"] = Principal(channel="telegram", admin=True, sender="alice", chat="room")
    elif difference == "session":
        kwargs["session"] = "other-session"
    elif difference == "instance":
        kwargs["instance"] = "recreated-instance"
    elif difference == "registration":
        rig.server.register_tool("send_mail", rig.send, gated=True)
    elif difference == "policy":
        rig.worker.policy = AutonomyPolicy(cap_per_action=7, daily_ceiling=19)
    elif difference == "args":
        kwargs["args"] = {"to": "bob"}
    origin = bind_action_origin("inbound" if difference == "taint" else "generated")
    try:
        await ask(rig, **kwargs)
    finally:
        reset_action_origin(origin)
    await settle(rig)
    assert rig.q.pending_groups() == []
    assert len(rig.q.pending_decisions()) == 2
    assert len(rig.pushed) == 2


@pytest.mark.asyncio
async def test_closed_copied_turn_and_raw_coordinator_style_intake_cannot_borrow_proof(rig):
    await ask(rig)
    context = open_approval_turn(
        session_id="s",
        session_instance="i",
        principal=Principal(channel="web", admin=True),
        session_is_live=lambda *_: True,
    )
    token = bind_approval_turn(context)
    copied = copy_context()
    close_approval_turn(context, token)
    task = asyncio.create_task(
        rig.server.handle({"tool": "send_mail", "args": {"to": "alice"}}), context=copied
    )
    assert (await task)["reason"] == "approval_required"
    rig.worker.govern_enqueue(
        "jarvis",
        "toolrpc.send_mail",
        "Tool 'send_mail' via RPC",
        payload={"tool": "send_mail", "args": {"to": "alice"}, "target": "send_mail"},
    )
    await settle(rig)
    assert rig.q.pending_groups() == []
    assert len(rig.pushed) == 3 and len(rig.q.pending_decisions()) == 3


@pytest.mark.asyncio
async def test_specialized_intake_opts_out_even_with_live_turn(rig):
    await ask(rig)

    def intake(actor, args):
        return rig.worker.govern_enqueue(
            actor,
            "toolrpc.send_mail",
            "Tool 'send_mail' via RPC",
            payload={"tool": "send_mail", "args": args, "target": "send_mail"},
        )

    rig.server.register_tool(
        "send_mail", rig.send, gated=True, trusted_execution=True, gated_intake=intake
    )
    await ask(rig)
    await settle(rig)
    assert rig.q.pending_groups() == []
    assert len(rig.pushed) == 2


@pytest.mark.asyncio
async def test_group_restart_promotion_and_stale_rejection_do_not_touch_neighbor(rig):
    first, second = await ask(rig), await ask(rig)
    await settle(rig)
    (original,) = rig.q.pending_groups()
    reopened = TaskQueue(rig.path).initialize()
    try:
        assert reopened.pending_groups() == [original]
    finally:
        reopened.close()
    await rig.worker.apply_decision(first.id, "reject", decided_by="owner")
    assert rig.q.pending_group(second.id) is None  # singleton card has no group projection
    assert rig.q.pending_group_leader(original["id"]).id == second.id
    assert rig.pushed == [first.id, second.id]
    result = await rig.worker.reject_group(
        original["id"], snapshot=original["snapshot"], member_ids=original["member_ids"]
    )
    assert result is None and rig.q.get(second.id).status == "blocked"
    # A freshly registered process cannot append to persisted prior-epoch groups.
    fresh = ToolRPCServer(enqueue=rig.worker.govern_enqueue)
    fresh.register_tool("send_mail", rig.send, gated=True)
    rig.server = fresh
    third = await ask(rig)
    await settle(rig)
    assert rig.q.pending_group(third.id) is None
    assert rig.q.pending_group(second.id) is None
    assert rig.q.pending_groups() == []


@pytest.mark.asyncio
async def test_expired_group_snapshot_conflicts_and_promotes_live_follower(rig, monkeypatch):
    deadline = datetime.now(UTC) + timedelta(seconds=30)
    enqueue = rig.q.enqueue
    calls = []

    def owner_deadline(*args, **kwargs):
        # Existing public authoring metadata seam: only first task gets an opt-in deadline.
        kwargs["approval_deadline_at"] = deadline.isoformat() if not calls else None
        calls.append(True)
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(rig.q, "enqueue", owner_deadline)
    first, second = await ask(rig), await ask(rig)
    await settle(rig)
    (group,) = rig.q.pending_groups()
    await rig.worker.approval_housekeeping(now=deadline + timedelta(seconds=1))
    result = await rig.worker.reject_group(
        group["id"], snapshot=group["snapshot"], member_ids=group["member_ids"]
    )
    assert result is None
    assert rig.q.get(first.id).status == "expired"
    assert rig.q.get(second.id).status == "blocked"
    assert rig.q.pending_group_leader(group["id"]).id == second.id
    assert rig.pushed == [first.id, second.id]
    assert rig.executed == []


@pytest.mark.asyncio
async def test_actual_mediated_rpc_receipts_are_independent(rig, tmp_path, monkeypatch):
    from agents.core.kernel import Decision, Verdict
    from agents.core.kernel.binding import MediationKernelBridge
    from tests.test_task_mediation_evidence import NOW_MS, _head_anchor, _signer

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    path = tmp_path / "mediated.db"
    queue = TaskQueue(
        str(path),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(path),
        mediation_scope="global",
        mediation_policy_revision="model-integration",
        mediation_clock_ms=lambda: NOW_MS,
        mediation_classifier=lambda _: True,
    ).initialize()
    try:
        worker = AutonomyWorker(
            queue,
            kernel=MediationKernelBridge(
                lambda _: Decision(Verdict.QUEUE, reason="owner approval required", tier=2)
            ),
            mediation_signer=_signer(),
            mediation_clock_ms=lambda: NOW_MS,
        )
        server = ToolRPCServer(enqueue=worker.govern_enqueue)
        server.register_tool("send_mail", rig.send, gated=True)
        bound = SimpleNamespace(q=queue, server=server)
        first, second = await ask(bound), await ask(bound)
        assert first.mediation_receipt and second.mediation_receipt
        assert first.mediation_receipt["receipt_id"] != second.mediation_receipt["receipt_id"]
        (group,) = queue.pending_groups()
        assert group["member_ids"] == [first.id, second.id]
        assert queue.verified_mediation_stats()["valid"] is True
        await worker.apply_decision(first.id, "accept", decided_by="owner")
        assert queue.get(second.id).status == "blocked"
        assert queue.get(second.id).mediation_receipt == second.mediation_receipt
        while worker._bg_tasks:
            await asyncio.gather(*tuple(worker._bg_tasks))
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_nonlive_session_never_mints_grouping_provenance(rig):
    await ask(rig)
    await ask(rig, live=False)
    await settle(rig)
    assert rig.q.pending_groups() == []
    assert len(rig.pushed) == 2 and len(rig.q.pending_decisions()) == 2
