"""Tests for the autonomy task queue + state machine (H6.1)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest
from agents.core.autonomy.queue import TaskQueue, TaskStatus, TaskQueueError, MAX_ATTEMPTS


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield queue
    queue.close()


def test_enqueue_starts_proposed(q):
    tid = q.enqueue("jarvis", "draft_email", "Draft reply", {"to": "x"}, risk_tier=1)
    task = q.get(tid)
    assert task.status == "proposed"
    assert task.agent == "jarvis"
    assert task.payload == {"to": "x"}
    assert task.attempts == 0


def test_happy_path_transitions(q):
    tid = q.enqueue("jarvis", "draft_email", "t")
    q.transition(tid, TaskStatus.APPROVED, decided_by="policy", decision="auto-act")
    assert q.get(tid).status == "approved"
    q.transition(tid, TaskStatus.RUNNING)
    q.transition(tid, TaskStatus.DONE, result={"ok": True})
    task = q.get(tid)
    assert task.status == "done"
    assert task.result == {"ok": True}


def test_illegal_transition_raises(q):
    tid = q.enqueue("jarvis", "draft_email", "t")
    # proposed → done is not allowed
    with pytest.raises(TaskQueueError):
        q.transition(tid, TaskStatus.DONE)


def test_no_reentry_after_terminal(q):
    tid = q.enqueue("jarvis", "draft_email", "t")
    q.transition(tid, TaskStatus.APPROVED)
    q.transition(tid, TaskStatus.RUNNING)
    q.transition(tid, TaskStatus.FAILED)
    with pytest.raises(TaskQueueError):
        q.transition(tid, TaskStatus.APPROVED)


def test_blocked_then_approved(q):
    tid = q.enqueue("jarvis", "delete_file", "t", risk_tier=3)
    q.transition(tid, TaskStatus.BLOCKED)
    q.transition(tid, TaskStatus.APPROVED, decided_by="user", decision="accept")
    assert q.get(tid).status == "approved"
    assert q.get(tid).decided_by == "user"


def test_runnable_excludes_exhausted_attempts(q):
    tid = q.enqueue("jarvis", "draft_email", "t")
    q.transition(tid, TaskStatus.APPROVED)
    for _ in range(MAX_ATTEMPTS):
        q.increment_attempts(tid)
    assert q.runnable() == []


def test_pending_decisions_filter(q):
    a = q.enqueue("jarvis", "delete_file", "a", risk_tier=3)
    b = q.enqueue("jarvis", "delete_file", "b", risk_tier=3)
    q.transition(a, TaskStatus.BLOCKED)
    q.transition(b, TaskStatus.BLOCKED)
    q.mark_pushed(a)
    unpushed = q.pending_decisions(only_unpushed=True)
    assert [t.id for t in unpushed] == [b]
    assert len(q.pending_decisions()) == 2


def test_update_payload(q):
    tid = q.enqueue("jarvis", "draft_email", "t", {"body": "old"})
    q.update_payload(tid, {"body": "new"})
    assert q.get(tid).payload == {"body": "new"}


def test_update_payload_policy_is_atomic_and_preserves_identity(q):
    tid = q.enqueue(
        "steve",
        "delete_database",
        "delete",
        {"target": "old"},
        risk_tier=3,
        autonomy_level="ask",
        origin="inbound",
    )
    q.transition(tid, TaskStatus.BLOCKED)

    task = q.update_payload_policy(
        tid,
        {"target": "new", "kind": "monitor.status"},
        risk_tier=3,
        autonomy_level="ask",
    )

    assert task.payload == {"target": "new", "kind": "monitor.status"}
    assert task.risk_tier == 3
    assert task.autonomy_level == "ask"
    assert task.agent == "steve"
    assert task.kind == "delete_database"
    assert task.origin == "inbound"
    assert task.status == "blocked"


def test_persistence_across_reopen(tmp_path):
    path = str(tmp_path / "autonomy.db")
    q1 = TaskQueue(db_path=path).initialize()
    tid = q1.enqueue("jarvis", "draft_email", "persist me")
    q1.close()
    q2 = TaskQueue(db_path=path).initialize()
    assert q2.get(tid).title == "persist me"
    q2.close()


def test_stats(q):
    q.enqueue("jarvis", "draft_email", "a")
    tid = q.enqueue("jarvis", "draft_email", "b")
    q.transition(tid, TaskStatus.APPROVED)
    stats = q.stats()
    assert stats.get("proposed") == 1
    assert stats.get("approved") == 1
