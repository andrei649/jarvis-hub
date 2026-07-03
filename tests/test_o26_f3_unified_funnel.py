"""
test_o26_f3_unified_funnel.py — ORIZONT 26 P0.7 (finding F3): golden loops #2 & #4.

Before this fix, broker-originated tasks (social/writeback/call/node/tool-rpc)
enqueued straight to `TaskQueue.enqueue` as status='proposed': the risk policy
(AUTO/ASK/OFF dial + money caps) never ran, `pending_decisions()` (the Telegram
+ HUD decision inbox) filtered status='blocked' only so they never surfaced,
and — with the kernel off, the default — an engaged kill-switch did NOT stop an
approved broker task from executing.

Loop #2: propose → inbox → approve → execute → audit trail, end-to-end.
Loop #4: the kill-switch halts the executor seam, kernel-independently.
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.policy import ASK, AutonomyPolicy  # noqa: E402
from agents.core.autonomy.queue import TaskQueue, TaskStatus  # noqa: E402
from agents.core.autonomy.worker import AutonomyWorker  # noqa: E402
from agents.core.security.capability import KillSwitch  # noqa: E402
from agents.core.social import SocialBroker  # noqa: E402


def _worker(tmp_path, kill_switch=None) -> AutonomyWorker:
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()

    async def executor(task):
        return {"ok": True, "echo": task.kind}

    return AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor,
                          kill_switch=kill_switch)


# ── golden loop #2: propose → inbox → approve → execute ─────────────────────

def test_broker_proposal_reaches_the_decision_inbox(tmp_path):
    w = _worker(tmp_path)
    broker = SocialBroker(enqueue=w.govern_enqueue)
    result = broker.request("x", "post", {"text": "hello world"})
    assert result["ok"] and result["queued"]

    pending = w.queue.pending_decisions()
    assert any(t.id == result["task_id"] for t in pending), (
        "F3 regression: a broker proposal is invisible to the decision inbox"
    )
    task = w.queue.get(result["task_id"])
    assert task.status == TaskStatus.BLOCKED.value, (
        "an always-ask broker task must land BLOCKED (needs a human), "
        f"got {task.status!r}"
    )


def test_broker_proposal_runs_the_risk_policy(tmp_path):
    """The policy's tier can only tighten the broker's request, never weaken it."""
    w = _worker(tmp_path)
    broker = SocialBroker(enqueue=w.govern_enqueue)
    result = broker.request("x", "dm", {"recipient": "mara", "text": "ping"})
    task = w.queue.get(result["task_id"])
    # social.* is an external write: the policy classifies it EXTERNAL (>=2)
    # and the broker asked for ask — the effective outcome must still be ask.
    assert task.autonomy_level == ASK
    assert task.risk_tier >= 2


def test_governed_ask_beats_a_weaker_policy_outcome(tmp_path):
    """A broker's always-ask survives even if the policy would auto-approve."""
    w = _worker(tmp_path)
    # 'monitor' kinds are READ_ONLY → policy says ACT; the caller says ask.
    task_id = w.govern_enqueue("stark", "monitor.check", "watch a thing",
                               payload={}, risk_tier=0, autonomy_level=ASK)
    task = w.queue.get(task_id)
    assert task.status == TaskStatus.BLOCKED.value, (
        "the stricter (ask) level must win over the policy's auto-approve"
    )


def test_approved_broker_task_executes_and_audits(tmp_path):
    w = _worker(tmp_path)
    broker = SocialBroker(enqueue=w.govern_enqueue)
    result = broker.request("x", "post", {"text": "ship it"})
    w.queue.transition(result["task_id"], TaskStatus.APPROVED,
                       decided_by="owner", decision="accept")
    summary = asyncio.run(w.tick())
    assert summary["done"] == 1
    task = w.queue.get(result["task_id"])
    assert task.status == TaskStatus.DONE.value


def test_plain_proposed_tasks_also_surface(tmp_path):
    """Direct queue submissions awaiting a decision are in the inbox too."""
    w = _worker(tmp_path)
    task_id = w.queue.enqueue(agent="pepper", kind="create_task",
                              title="raw proposed", payload={})
    assert any(t.id == task_id for t in w.queue.pending_decisions())


def test_morning_brief_sees_broker_proposals(tmp_path):
    from agents.core.autonomy.digest import build_morning_brief

    w = _worker(tmp_path)
    broker = SocialBroker(enqueue=w.govern_enqueue)
    broker.request("x", "post", {"text": "brief me"})
    brief = build_morning_brief(w.queue)
    assert "post" in brief.lower() or "decision" in brief.lower() or "x" in brief.lower()


def test_govern_enqueue_works_without_an_event_loop(tmp_path):
    """Sync broker context (no running loop): the card waits in the inbox."""
    w = _worker(tmp_path)
    task_id = w.govern_enqueue("veronica", "social.x.post", "no loop",
                               payload={"text": "hi"})
    assert any(t.id == task_id for t in w.queue.pending_decisions())


# ── golden loop #4: the kill-switch stops the executor seam ─────────────────

def test_kill_switch_halts_approved_tasks_kernel_independently(tmp_path):
    ks = KillSwitch(path=tmp_path / "kill.json")
    w = _worker(tmp_path, kill_switch=ks)
    broker = SocialBroker(enqueue=w.govern_enqueue)
    result = broker.request("x", "post", {"text": "should not run while halted"})
    w.queue.transition(result["task_id"], TaskStatus.APPROVED,
                       decided_by="owner", decision="accept")

    ks.engage(reason="test halt")
    summary = asyncio.run(w.tick())
    assert summary.get("halted") is True and summary["ran"] == 0, (
        "F3 regression: an engaged kill-switch did not stop the executor seam"
    )
    task = w.queue.get(result["task_id"])
    assert task.status == TaskStatus.APPROVED.value, (
        "held tasks must stay APPROVED (nothing lost) while halted"
    )

    ks.disengage()
    summary = asyncio.run(w.tick())
    assert summary["done"] == 1, "disengage must let the held task run"
    assert w.queue.get(result["task_id"]).status == TaskStatus.DONE.value


def test_kill_switch_failure_never_blocks_the_tick(tmp_path):
    class BrokenSwitch:
        def is_halted(self):
            raise RuntimeError("store unreadable")

    w = _worker(tmp_path, kill_switch=BrokenSwitch())
    w.queue.enqueue(agent="pepper", kind="noop", title="x", payload={})
    summary = asyncio.run(w.tick())
    assert "halted" not in summary or not summary["halted"]
