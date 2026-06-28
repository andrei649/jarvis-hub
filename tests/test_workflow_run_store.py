"""0.34 — workflow run-history persistence (opt-in, default-off)."""

import pytest

from agents.core.workflows.engine import WorkflowEngine
from agents.core.workflows.run_store import WorkflowRunStore


def _store(tmp_path, **kw):
    return WorkflowRunStore(tmp_path / "runs.json", **kw)


# ── store mechanics ───────────────────────────────────────────────────────────
def test_record_then_list_most_recent_first(tmp_path):
    s = _store(tmp_path)
    s.record({"pipeline_id": "a", "ts": 1})
    s.record({"pipeline_id": "b", "ts": 2})
    assert [r["pipeline_id"] for r in s.list()] == ["b", "a"]
    assert [r["pipeline_id"] for r in s.all()] == ["a", "b"]     # chronological for seeding


def test_cap_prunes_oldest(tmp_path):
    s = _store(tmp_path, max_keep=3)
    for i in range(5):
        s.record({"pipeline_id": str(i), "ts": i})
    assert [r["pipeline_id"] for r in s.all()] == ["2", "3", "4"]   # oldest two dropped


def test_missing_and_corrupt_files_degrade_to_empty(tmp_path):
    s = _store(tmp_path)
    assert s.all() == [] and s.list() == []                      # no file yet
    (tmp_path / "runs.json").write_text("not json{", encoding="utf-8")
    assert s.all() == []                                         # corrupt → empty, not a crash
    s.record({"pipeline_id": "x"})                               # and still writable afterwards
    assert [r["pipeline_id"] for r in s.all()] == ["x"]


# ── engine wiring ─────────────────────────────────────────────────────────────
def test_engine_persists_runs_when_store_attached(tmp_path):
    s = _store(tmp_path)
    eng = WorkflowEngine(object(), run_store=s)        # __init__ only stashes the orch ref
    eng._stash_run({"pipeline_id": "p1", "ts": 1})
    assert [r["pipeline_id"] for r in eng.recent()] == ["p1"]    # in-memory ring
    assert [r["pipeline_id"] for r in s.list()] == ["p1"]        # …and durable on disk


def test_engine_seeds_recent_runs_from_store_on_init(tmp_path):
    s = _store(tmp_path)
    s.record({"pipeline_id": "old1", "ts": 1})
    s.record({"pipeline_id": "old2", "ts": 2})
    eng = WorkflowEngine(object(), run_store=s)
    assert [r["pipeline_id"] for r in eng.recent()] == ["old2", "old1"]   # survives "restart"


def test_default_is_no_persistence(monkeypatch):
    monkeypatch.delenv("JARVIS_WORKFLOW_PERSIST", raising=False)
    eng = WorkflowEngine(object())
    assert eng._run_store is None                                # default off — nothing written


def test_env_opt_in_attaches_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "1")
    # point the default store at a tmp file so the test writes nowhere real
    import agents.core.workflows.run_store as rs
    monkeypatch.setattr(rs, "_DEFAULT_FILE", tmp_path / "runs.json")
    eng = WorkflowEngine(object())
    assert isinstance(eng._run_store, WorkflowRunStore)


@pytest.mark.parametrize("val", ["0", "", "no", "off"])
def test_env_falsey_stays_off(tmp_path, monkeypatch, val):
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", val)
    assert WorkflowEngine(object())._run_store is None
