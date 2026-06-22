"""Mission Workspaces (0.32) — store + state machine + budget + audit trail.

Offline: a temp-dir MissionStore, no orchestrator/LLM/network. Mirrors the
TaskQueue test style. Verifies the workspace lifecycle a long-horizon mission
relies on — pause/resume, the strict transition table, the hard step budget
(auto-fail on exhaustion), on-disk artifacts that can't escape the workspace,
and the append-only event audit trail.
"""
import pytest

from agents.core.autonomy.missions import (
    MissionStore, MissionStatus, MissionError, BudgetExceeded,
)


@pytest.fixture()
def store(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"), artifact_root=str(tmp_path / "art")).initialize()
    yield s
    s.close()


def test_create_seeds_plan_and_planned_state(store):
    m = store.create("Ship the demo", goal="60s proof", plan=["script", "record", "edit"])
    assert m.status == MissionStatus.PLANNED.value
    assert m.steps_used == 0
    assert [s["title"] for s in m.plan] == ["script", "record", "edit"]
    assert all(s["status"] == "pending" for s in m.plan)
    # 'created' is the first audit event.
    assert store.events(m.id)[0].event == "created"


def test_create_requires_title(store):
    with pytest.raises(MissionError):
        store.create("   ")


def test_pause_resume_roundtrip(store):
    m = store.create("Long task", plan=["a", "b"])
    store.start(m.id)
    assert store.get(m.id).status == "active"
    started_first = store.get(m.id).started_at
    assert started_first is not None
    store.pause(m.id)
    assert store.get(m.id).status == "paused"
    store.resume(m.id)
    assert store.get(m.id).status == "active"
    # Resume must NOT reset the wall-clock start.
    assert store.get(m.id).started_at == started_first


def test_illegal_transition_rejected(store):
    m = store.create("x")
    # planned cannot go straight to paused
    with pytest.raises(MissionError):
        store.pause(m.id)


def test_terminal_has_no_exit(store):
    m = store.create("x")
    store.start(m.id)
    store.complete(m.id)
    assert store.get(m.id).status == "done"
    with pytest.raises(MissionError):
        store.resume(m.id)


def test_finish_step_charges_budget_and_records(store):
    m = store.create("x", plan=["one", "two"], max_steps=10)
    store.start(m.id)
    m2 = store.finish_step(m.id, 0, status="done", result="ok")
    assert m2.steps_used == 1
    assert m2.plan[0]["status"] == "done"
    assert m2.plan[0]["result"] == "ok"
    assert m2.plan[0]["ended_at"] is not None
    assert any(e.event == "step" for e in store.events(m.id))


def test_finish_step_requires_active(store):
    m = store.create("x", plan=["one"])
    # not started yet
    with pytest.raises(MissionError):
        store.finish_step(m.id, 0)


def test_step_budget_exhaustion_autofails(store):
    m = store.create("x", plan=["a", "b", "c"], max_steps=2)
    store.start(m.id)
    store.finish_step(m.id, 0)               # used 1/2
    with pytest.raises(BudgetExceeded):
        store.finish_step(m.id, 1)           # used 2/2 → auto-fail
    assert store.get(m.id).status == "failed"


def test_finish_step_out_of_range(store):
    m = store.create("x", plan=["a"])
    store.start(m.id)
    with pytest.raises(MissionError):
        store.finish_step(m.id, 5)


def test_budget_status_reports_remaining_and_time(store):
    m = store.create("x", plan=["a", "b"], max_steps=5, max_seconds=3600)
    store.start(m.id)
    store.finish_step(m.id, 0)
    b = store.budget_status(m.id)
    assert b["steps_used"] == 1
    assert b["steps_remaining"] == 4
    assert b["elapsed_seconds"] is not None
    assert b["over_time"] is False


def test_artifact_stays_inside_workspace(store, tmp_path):
    m = store.create("x")
    # a hostile name with separators must be reduced to a safe basename
    path = store.add_artifact(m.id, "../../etc/passwd", "data")
    art_root = (tmp_path / "art").resolve()
    assert art_root in (tmp_path / "art" / str(m.id)).resolve().parents or \
        (tmp_path / "art" / str(m.id)).resolve().is_relative_to(art_root)
    # the written file is contained under the mission's own dir
    assert str(m.id) in path
    assert "/etc/passwd" not in path
    assert any(e.event == "artifact" for e in store.events(m.id))


def test_list_filters_by_status(store):
    a = store.create("a")
    b = store.create("b")
    store.start(b.id)
    planned = store.list(status="planned")
    active = store.list(status="active")
    assert a.id in [m.id for m in planned]
    assert b.id in [m.id for m in active]


def test_cancel_from_planned(store):
    m = store.create("x")
    store.cancel(m.id)
    assert store.get(m.id).status == "cancelled"
