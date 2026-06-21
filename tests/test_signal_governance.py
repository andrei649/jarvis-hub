"""Tests for the Signal Layer → approvals governance bridge.

Verifies it is OFF by default, only queues actionable recommendations, queues
them as preview-only (BLOCKED, awaiting human) and never as approved/running.
"""

import pytest

from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.signal_governance import SignalGovernanceBridge


@pytest.fixture
def queue(tmp_path):
    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield q
    q.close()


RECS = [
    {"type": "monitor", "label": "Monitor watched airports again within 24h.", "requiresApproval": True},
    {"type": "review", "label": "Review cyber exposure before action.", "requiresApproval": True},
    {"type": "monitor", "label": "Continue monitoring. No action.", "requiresApproval": False},
]


def test_disabled_by_default_queues_nothing(queue):
    bridge = SignalGovernanceBridge(queue)  # enabled defaults to False
    out = bridge.submit_recommendations(RECS)
    assert out["status"] == "disabled"
    assert out["queued"] == 0
    assert queue.list() == []


def test_from_env_off_unless_flag_set(queue):
    assert SignalGovernanceBridge.from_env(queue, env={}).enabled is False
    assert SignalGovernanceBridge.from_env(queue, env={"JARVIS_SIGNAL_GOVERNANCE": "0"}).enabled is False
    assert SignalGovernanceBridge.from_env(queue, env={"JARVIS_SIGNAL_GOVERNANCE": "true"}).enabled is True


def test_enabled_queues_only_actionable_as_blocked(queue):
    audited = []
    bridge = SignalGovernanceBridge(queue, enabled=True, audit=lambda e, d: audited.append((e, d)))
    out = bridge.submit_recommendations(RECS, context={"scope": "world"})

    assert out["status"] == "ok"
    assert out["queued"] == 2          # two requiresApproval items
    assert out["skipped"] == 1         # the advisory one
    assert len(out["task_ids"]) == 2

    # Every queued task is BLOCKED (awaiting human) — never approved/running/done.
    for tid in out["task_ids"]:
        task = queue.get(tid)
        assert task.status == TaskStatus.BLOCKED.value
        assert task.kind == "signal_recommendation"
        assert task.payload["preview_only"] is True
        assert task.payload["context"]["scope"] == "world"

    # They show up as pending human decisions.
    pending = queue.pending_decisions()
    assert len(pending) == 2

    # Nothing was approved/run.
    assert queue.list(status="approved") == []
    assert queue.list(status="running") == []

    # Audit fired once per queued item.
    assert sum(1 for e, _ in audited if e == "signal_governance.queued") == 2


def test_submit_from_brief_extracts_recommendations(queue):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    brief = {"scope": "world", "title": "Global Intelligence Brief", "recommendations": RECS}
    out = bridge.submit_from_brief(brief)
    assert out["queued"] == 2
    # Context carried the brief scope/title through to the queued task.
    task = queue.get(out["task_ids"][0])
    assert task.payload["context"]["title"] == "Global Intelligence Brief"


def test_empty_or_missing_recommendations_are_safe(queue):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    assert bridge.submit_recommendations([])["queued"] == 0
    assert bridge.submit_from_brief(None)["queued"] == 0
    assert bridge.submit_from_brief({})["queued"] == 0
