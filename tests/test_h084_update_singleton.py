"""One executable hub.update card per shared autonomy database."""

from __future__ import annotations

import multiprocessing

import pytest

from agents.core.autonomy.queue import TaskQueue, TaskStatus
from tests.test_h084_update_kernel import _request, _rig


def _race_insert(db_path, ready, start, outcome):
    """Each spawned interpreter opens its own SQLite connection."""
    from agents.core.autonomy.queue import TaskQueue

    queue = TaskQueue(db_path).initialize()
    ready.put(True)
    if not start.wait(10):
        outcome.put("timeout")
        return
    try:
        queue.enqueue("owner", "hub.update", "Update", {"target": "different-plan"})
        outcome.put("inserted")
    except Exception as exc:
        outcome.put(type(exc).__name__)
    finally:
        queue.close()


def test_two_spawned_processes_share_one_sqlite_singleton(tmp_path):
    path = str(tmp_path / "queue.db")
    seed = TaskQueue(path).initialize()
    seed.close()
    mp = multiprocessing.get_context("spawn")
    ready, start, outcome = mp.Queue(), mp.Event(), mp.Queue()
    processes = [mp.Process(target=_race_insert, args=(path, ready, start, outcome))
                 for _ in range(2)]
    for process in processes:
        process.start()
    try:
        assert ready.get(timeout=15) and ready.get(timeout=15)
        start.set()
        results = sorted((outcome.get(timeout=15), outcome.get(timeout=15)))
        assert results == ["HubUpdateActive", "inserted"]
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        check = TaskQueue(path).initialize()
        try:
            assert len(check.list(kind="hub.update")) == 1
        finally:
            check.close()
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(5)


@pytest.mark.parametrize("status", [
    "proposed", "blocked", "approved", "running", "deferred", "unknown",
])
def test_active_or_unknown_status_blocks_legacy_enqueue(tmp_path, status):
    queue = TaskQueue(str(tmp_path / "queue.db")).initialize()
    try:
        first = queue.enqueue("owner", "hub.update", "First", {"target": "A"})
        if status == "blocked":
            queue.transition(first, TaskStatus.BLOCKED)
        elif status in {"approved", "running"}:
            queue.transition(first, TaskStatus.APPROVED)
            if status == "running":
                queue.transition(first, TaskStatus.RUNNING)
        elif status == "deferred":
            queue.transition(first, TaskStatus.DEFERRED)
        elif status == "unknown":
            queue._conn.execute("UPDATE tasks SET status='unrecognized' WHERE id=?", (first,))
            queue._conn.commit()
        from agents.core.autonomy.queue import HubUpdateActive

        with pytest.raises(HubUpdateActive):
            queue.enqueue("owner", "hub.update", "Different", {"target": "B"})
        assert queue.enqueue("owner", "hub.update_rollback", "Rollback", {}) > first
        assert len(queue.list(kind="hub.update")) == 1
    finally:
        queue.close()


@pytest.mark.parametrize("status", ["rejected", "done", "failed", "quarantined", "expired"])
def test_terminal_status_allows_a_new_distinct_update_card(tmp_path, status):
    queue = TaskQueue(str(tmp_path / "queue.db")).initialize()
    try:
        first = queue.enqueue("owner", "hub.update", "First", {"target": "A"})
        if status == "rejected":
            queue.transition(first, TaskStatus.REJECTED)
        elif status in {"done", "failed"}:
            queue.transition(first, TaskStatus.APPROVED)
            queue.transition(first, TaskStatus.RUNNING)
            queue.transition(first, TaskStatus(status))
        else:
            # Quarantine/expiry use private guards; fixture only proves the
            # singleton's terminal predicate, not those guards' authority.
            queue._conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, first))
            queue._conn.commit()
        second = queue.enqueue("owner", "hub.update", "Second", {"target": "B"})
        assert second != first and len(queue.list(kind="hub.update")) == 2
    finally:
        queue.close()


def test_signed_enforce_rejection_has_no_second_task_or_mediation_event(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        first = _request(rig)["pending"]
        task = rig.queue.get(first)
        before = rig.queue._conn.execute(
            "SELECT COUNT(*) FROM task_mediation_events").fetchone()[0]
        from agents.core.autonomy.queue import HubUpdateActive

        with pytest.raises(HubUpdateActive):
            rig.worker.govern_enqueue(
                agent=task.agent, kind="hub.update", title=task.title, payload=task.payload,
                risk_tier=3, autonomy_level="ask", origin="manual",
            )
        assert len(rig.queue.list(kind="hub.update")) == 1
        assert rig.queue._conn.execute(
            "SELECT COUNT(*) FROM task_mediation_events").fetchone()[0] == before
        rig.queue.transition(first, TaskStatus.REJECTED)
        second = _request(rig)["pending"]
        assert second != first
    finally:
        rig.queue.close()
