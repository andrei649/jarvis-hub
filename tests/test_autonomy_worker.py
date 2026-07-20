"""Tests for the autonomy worker: submit/gate/tick/decision (H6.1+H6.2+H6.3)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield queue
    queue.close()


def make_worker(q, executor=None, notifier=None, budget=None):
    return AutonomyWorker(q, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                          executor=executor, notifier=notifier,
                          budget=budget or InterruptBudget(per_day=4))


@pytest.mark.asyncio
async def test_reversible_auto_approved(q):
    w = make_worker(q)
    task = await w.submit("jarvis", "draft_email", "Draft a reply")
    assert task.status == "approved"
    assert task.decided_by == "policy"


@pytest.mark.asyncio
async def test_irreversible_blocks_and_pushes(q):
    pushed = []

    async def notifier(task):
        pushed.append(task.id)
        return True

    w = make_worker(q, notifier=notifier)
    task = await w.submit("jarvis", "delete_file", "Delete old logs")
    assert task.status == "blocked"
    assert pushed == [task.id]
    assert q.get(task.id).pushed == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_holds_without_push(q):
    pushed = []

    async def notifier(task):
        pushed.append(task.id)
        return True

    w = make_worker(q, notifier=notifier, budget=InterruptBudget(per_day=2))
    for i in range(4):
        await w.submit("jarvis", "delete_file", f"del {i}")
    # only 2 pushed; the rest held (blocked, unpushed) for daily review
    assert len(pushed) == 2
    held = q.pending_decisions(only_unpushed=True)
    assert len(held) == 2


@pytest.mark.asyncio
async def test_tick_executes_and_completes(q):
    async def executor(task):
        return {"ok": True, "title": task.title}

    w = make_worker(q, executor=executor)
    task = await w.submit("jarvis", "research_market", "Research CEE")
    summary = await w.tick()
    assert summary["done"] == 1
    assert q.get(task.id).status == "done"
    assert q.get(task.id).result["ok"] is True


@pytest.mark.asyncio
async def test_tick_retries_then_fails(q):
    calls = {"n": 0}

    async def flaky(task):
        calls["n"] += 1
        raise RuntimeError("boom")

    w = make_worker(q, executor=flaky)
    task = await w.submit("jarvis", "research_market", "Research")
    # 3 ticks → 3 attempts → failed
    await w.tick(); await w.tick(); await w.tick()
    assert q.get(task.id).status == "failed"
    assert calls["n"] == 3
    # no further runs
    await w.tick()
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_no_executor_is_noop_success(q):
    w = make_worker(q)
    task = await w.submit("jarvis", "research_market", "Research")
    await w.tick()
    assert q.get(task.id).status == "done"
    assert q.get(task.id).result["status"] == "noop"


@pytest.mark.asyncio
async def test_apply_decision_accept_then_run(q):
    async def executor(task):
        return {"ok": True}

    w = make_worker(q, executor=executor)
    task = await w.submit("jarvis", "delete_file", "Delete")
    assert task.status == "blocked"
    await w.apply_decision(task.id, "accept", decided_by="andrei")
    await w.tick()
    assert q.get(task.id).status == "done"


@pytest.mark.asyncio
async def test_apply_decision_reject(q):
    w = make_worker(q)
    task = await w.submit("jarvis", "delete_file", "Delete")
    await w.apply_decision(task.id, "reject", decided_by="andrei")
    assert q.get(task.id).status == "rejected"


@pytest.mark.asyncio
async def test_apply_decision_edit_updates_payload(q):
    # Editing execution bytes cannot lower the durable server-owned tier. The
    # original delete identity remains authoritative, so the task stays blocked.
    w = make_worker(q)
    task = await w.submit("jarvis", "delete_file", "Delete", payload={"path": "/old"})
    assert q.get(task.id).status == "blocked"
    await w.apply_decision(
        task.id, "edit", decided_by="andrei",
        payload={"path": "/new", "risk_tier": "read_only"},
    )
    t = q.get(task.id)
    assert t.status == "blocked"
    assert t.risk_tier == 3
    assert t.autonomy_level == "ask"
    assert t.payload == {"path": "/new", "risk_tier": "read_only"}


@pytest.mark.asyncio
async def test_edit_to_irreversible_stays_blocked(q):
    """BUG-11: editing a blocked task toward an irreversible payload (without
    raising any amount) must re-gate the full payload and stay BLOCKED — the old
    amount-only check would have auto-approved it under the original decision.
    Also asserts the edited payload is still persisted, and the card re-pushed."""
    pushed = []

    async def notifier(task):
        pushed.append(task.id)
        return True

    w = make_worker(q, notifier=notifier)
    task = await w.submit("jarvis", "delete_file", "Delete logs", payload={"path": "/logs"})
    assert q.get(task.id).status == "blocked"
    pushed.clear()  # ignore the submit-time push; assert on the re-push below
    # Edit toward an explicitly irreversible action with no amount change.
    await w.apply_decision(
        task.id, "edit", decided_by="andrei",
        payload={"path": "/etc", "risk_tier": "irreversible"},
    )
    t = q.get(task.id)
    assert t.status == "blocked"                    # re-gated → still needs approval
    assert t.payload == {"path": "/etc", "risk_tier": "irreversible"}
    assert pushed == [task.id]                       # fresh decision card re-pushed


@pytest.mark.asyncio
async def test_edit_over_cap_reblocks(q):
    """BUG-11: editing a blocked task past the per-action cap re-blocks instead of
    silently approving under the original lower-risk decision."""
    w = make_worker(q)  # cap_per_action=50
    task = await w.submit("jarvis", "delete_file", "Delete", payload={"path": "/old"})
    assert q.get(task.id).status == "blocked"
    await w.apply_decision(task.id, "edit", decided_by="andrei", payload={"amount": 300})
    assert q.get(task.id).status == "blocked"          # escalated spend → re-blocked
    task2 = await w.submit("jarvis", "delete_file", "Delete2", payload={"path": "/o2"})
    await w.apply_decision(task2.id, "edit", decided_by="andrei", payload={"amount": 10})
    assert q.get(task2.id).status == "blocked"         # durable delete tier cannot be lowered


@pytest.mark.asyncio
async def test_money_within_cap_auto_acts(q):
    async def executor(task):
        return {"paid": task.payload.get("amount")}

    w = make_worker(q, executor=executor)
    task = await w.submit("gecko", "pay_invoice", "Pay small bill", payload={"amount": 20})
    assert task.status == "approved"
    await w.tick()
    assert q.get(task.id).status == "done"


def test_interrupt_budget_rollover():
    b = InterruptBudget(per_day=2)
    assert b.consume() and b.consume()
    assert not b.consume()
    # force a new day
    import datetime
    b._day = datetime.date(2000, 1, 1)
    assert b.remaining() == 2
