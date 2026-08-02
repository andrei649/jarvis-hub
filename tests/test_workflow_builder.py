"""Tests for H9.1 — Visual Workflow Builder.

Covers:
  - Pipeline from_dict / to_dict round-trip.
  - from_dict raises ValueError on cyclic DAGs.
  - WorkflowStore CRUD on a tmp path.
  - HTTP endpoints via FastAPI TestClient.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.workflows.pipeline import Pipeline, WorkflowStep
from agents.core.workflows.storage import WorkflowStore
from agents.core.workflows.registry import WorkflowRegistry


# ── Pipeline serialisation ─────────────────────────────────────────────────────

def test_workflowstep_from_dict_round_trip():
    original = WorkflowStep(
        id="s1", agent_id="gecko", prompt_template="{_input} foo",
        depends_on=["prev"],
    )
    d = original.to_dict()
    restored = WorkflowStep.from_dict(d)
    assert restored.id == original.id
    assert restored.agent_id == original.agent_id
    assert restored.prompt_template == original.prompt_template
    assert restored.depends_on == original.depends_on


def test_workflowstep_from_dict_tolerates_missing_depends_on():
    d = {"id": "x", "agent_id": "jarvis", "prompt_template": "hi"}
    step = WorkflowStep.from_dict(d)
    assert step.depends_on == []


def test_pipeline_from_dict_round_trip():
    original = Pipeline(
        id="my_pipe",
        name="My Pipeline",
        description="A test pipeline",
        steps=[
            WorkflowStep("a", "gecko", "{_input}"),
            WorkflowStep("b", "veronica", "{a}", depends_on=["a"]),
        ],
    )
    d = original.to_dict()
    restored = Pipeline.from_dict(d)
    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.description == original.description
    assert len(restored.steps) == 2
    assert restored.steps[0].id == "a"
    assert restored.steps[1].depends_on == ["a"]


def test_pipeline_from_dict_missing_optional_fields():
    # name and description are optional.
    d = {
        "id": "min_pipe",
        "steps": [{"id": "s", "agent_id": "jarvis", "prompt_template": "hello"}],
    }
    p = Pipeline.from_dict(d)
    assert p.id == "min_pipe"
    assert p.name == "min_pipe"  # falls back to id
    assert p.description == ""


def test_pipeline_from_dict_raises_on_cycle():
    d = {
        "id": "cyclic",
        "name": "Cyclic",
        "description": "",
        "steps": [
            {"id": "a", "agent_id": "ag1", "prompt_template": "x", "depends_on": ["b"]},
            {"id": "b", "agent_id": "ag2", "prompt_template": "y", "depends_on": ["a"]},
        ],
    }
    with pytest.raises(ValueError, match="[Cc]ycle"):
        Pipeline.from_dict(d)


def test_pipeline_from_dict_raises_on_unresolved_dep():
    d = {
        "id": "broken",
        "name": "Broken",
        "description": "",
        "steps": [
            {"id": "a", "agent_id": "ag1", "prompt_template": "x", "depends_on": ["ghost"]},
        ],
    }
    with pytest.raises(ValueError):
        Pipeline.from_dict(d)


def test_pipeline_to_dict_from_dict_parallel():
    """Fan-in topology: two parallel branches + merge step."""
    original = Pipeline(
        id="fan",
        name="Fan",
        description="",
        steps=[
            WorkflowStep("left", "ag1", "{_input}"),
            WorkflowStep("right", "ag2", "{_input}"),
            WorkflowStep("merge", "ag3", "{left}+{right}", depends_on=["left", "right"]),
        ],
    )
    restored = Pipeline.from_dict(original.to_dict())
    batches = restored.execution_batches()
    assert len(batches) == 2
    first_ids = {s.id for s in batches[0]}
    assert first_ids == {"left", "right"}
    assert batches[1][0].id == "merge"


# ── WorkflowStore CRUD ─────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return WorkflowStore(path=tmp_path / "wf_test")


_VALID_PIPE = {
    "id": "test_pipe",
    "name": "Test Pipe",
    "description": "For testing",
    "steps": [
        {"id": "step1", "agent_id": "jarvis", "prompt_template": "{_input}", "depends_on": []},
    ],
}


def test_store_save_and_get(store):
    saved = store.save(_VALID_PIPE)
    assert saved["id"] == "test_pipe"
    assert "_saved_at" in saved

    got = store.get("test_pipe")
    assert got is not None
    assert got["id"] == "test_pipe"


def test_store_list(store):
    store.save(_VALID_PIPE)
    items = store.list()
    assert any(i["id"] == "test_pipe" for i in items)


def test_store_update(store):
    store.save(_VALID_PIPE)
    updated = dict(_VALID_PIPE, name="Updated Name")
    store.save(updated)
    got = store.get("test_pipe")
    assert got["name"] == "Updated Name"


def test_store_delete(store):
    store.save(_VALID_PIPE)
    assert store.get("test_pipe") is not None
    result = store.delete("test_pipe")
    assert result is True
    assert store.get("test_pipe") is None


def test_store_delete_nonexistent(store):
    assert store.delete("ghost_pipe") is False


def test_store_save_rejects_cyclic_dag(store):
    bad = {
        "id": "bad",
        "name": "Bad",
        "description": "",
        "steps": [
            {"id": "a", "agent_id": "ag1", "prompt_template": "x", "depends_on": ["b"]},
            {"id": "b", "agent_id": "ag2", "prompt_template": "y", "depends_on": ["a"]},
        ],
    }
    with pytest.raises(ValueError):
        store.save(bad)


def test_store_list_empty(store):
    items = store.list()
    assert items == []


def test_store_atomic_write_leaves_no_tmp(store, tmp_path):
    store.save(_VALID_PIPE)
    tmp_files = list((tmp_path / "wf_test").glob("*.tmp"))
    assert tmp_files == []


# ── HTTP endpoint tests ────────────────────────────────────────────────────────

def _make_mock_orch():
    """Create a minimal mock orchestrator with workflow_registry."""
    mock_orch = MagicMock()
    mock_orch.workflow_registry = WorkflowRegistry()
    return mock_orch


@pytest.fixture
def wf_client(tmp_path):
    """TestClient with injected mock orch and isolated WorkflowStore."""
    import agents.web as web
    from agents.core.workflows.storage import WorkflowStore as WFStore

    # Inject mock orch.
    old_orch = web.orch
    web.orch = _make_mock_orch()

    # Inject isolated store so tests don't touch real disk.
    old_store = web._wf_store_instance
    web._wf_store_instance = WFStore(path=tmp_path / "ep_wf")

    # NOTE: do NOT use `with TestClient(...)` here — the context-manager form runs
    # the app lifespan, whose shutdown joins background threads and can hang under
    # full-suite ordering (global orch leak). These endpoints only need the
    # injected mock orch + store, so a plain client (no lifespan) is correct.
    # SEC-3: workflow CRUD is admin-guarded; bypass the guard for endpoint-behavior tests.
    # CRUD/run routes were extracted to routers/workflows.py (CLN-3) → they depend on
    # _deps.admin_guard, so override BOTH callables (mirrors conftest's user-guard handling).
    from agents.core.routers._deps import admin_guard as _ra
    web.app.dependency_overrides[web._admin_guard] = lambda: None
    web.app.dependency_overrides[_ra] = lambda: None
    c = TestClient(web.app)
    try:
        yield c
    finally:
        web.app.dependency_overrides.pop(web._admin_guard, None)
        web.app.dependency_overrides.pop(_ra, None)
        web.orch = old_orch
        web._wf_store_instance = old_store


_EP_PIPE = {
    "id": "ep_test",
    "name": "Endpoint Test Pipe",
    "description": "Created by test",
    "steps": [
        {"id": "s1", "agent_id": "jarvis", "prompt_template": "{_input}", "depends_on": []},
    ],
}


def test_endpoint_create_workflow(wf_client):
    r = wf_client.post("/api/workflows", json=_EP_PIPE)
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "ep_test"
    assert "_saved_at" in d


def test_endpoint_list_includes_new_workflow(wf_client):
    wf_client.post("/api/workflows", json=_EP_PIPE)
    r = wf_client.get("/api/workflows")
    assert r.status_code == 200
    ids = [w["id"] for w in r.json()["workflows"]]
    assert "ep_test" in ids
    # Built-ins from registry should also appear.
    assert "finance_report" in ids


def test_endpoint_list_builtin_workflows(wf_client):
    """GET /api/workflows returns built-in pipelines even with no user workflows."""
    r = wf_client.get("/api/workflows")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 3
    ids = [w["id"] for w in d["workflows"]]
    assert "finance_report" in ids


def test_endpoint_update_workflow(wf_client):
    wf_client.post("/api/workflows", json=_EP_PIPE)
    updated = dict(_EP_PIPE, name="Updated via PUT")
    r = wf_client.put("/api/workflows/ep_test", json=updated)
    assert r.status_code == 200
    assert r.json()["name"] == "Updated via PUT"


def test_endpoint_delete_workflow(wf_client):
    wf_client.post("/api/workflows", json=_EP_PIPE)
    r = wf_client.delete("/api/workflows/ep_test")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Should be gone from the list.
    r2 = wf_client.get("/api/workflows")
    ids = [w["id"] for w in r2.json()["workflows"]]
    assert "ep_test" not in ids


def test_endpoint_delete_nonexistent_returns_404(wf_client):
    r = wf_client.delete("/api/workflows/no_such_pipe")
    assert r.status_code == 404


def test_endpoint_create_invalid_dag_returns_422(wf_client):
    bad = {
        "id": "bad_dag",
        "name": "Bad DAG",
        "description": "",
        "steps": [
            {"id": "a", "agent_id": "ag1", "prompt_template": "x", "depends_on": ["b"]},
            {"id": "b", "agent_id": "ag2", "prompt_template": "y", "depends_on": ["a"]},
        ],
    }
    r = wf_client.post("/api/workflows", json=bad)
    assert r.status_code == 422


def test_endpoint_run_workflow_registry(wf_client):
    """POST /api/workflows/run resolves from the registry (built-in)."""
    import agents.web as web

    # Ensure workflow_engine is set on mock orch.
    async def _fake_run(pipeline, initial_input):
        return {"_ok": True, "_elapsed": 0.1, "_errors": [], "s1": "fake result"}

    web.orch.workflow_engine = MagicMock()
    web.orch.workflow_engine.run = _fake_run

    # Save a pipeline first so it's registered.
    wf_client.post("/api/workflows", json=_EP_PIPE)

    r = wf_client.post(
        "/api/workflows/run",
        json={"pipeline_id": "ep_test", "input": "hello"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True


def test_endpoint_delete_shadow_keeps_builtin(wf_client):
    """WFL-036: deleting a user pipeline saved under a built-in id must restore
    the built-in in the live registry, not pop it until restart."""
    import agents.web as web

    shadow = dict(_EP_PIPE, id="finance_report", name="Shadow")
    assert wf_client.post("/api/workflows", json=shadow).status_code == 200
    r = wf_client.delete("/api/workflows/finance_report")
    assert r.status_code == 200 and r.json()["ok"] is True

    ids = [w["id"] for w in wf_client.get("/api/workflows").json()["workflows"]]
    assert "finance_report" in ids, "the built-in must survive the shadow's deletion"
    restored = web.orch.workflow_registry.get("finance_report")
    assert restored is not None and restored.name != "Shadow"
    assert len(restored.steps) >= 3, (
        "the registry entry must be the pristine BUILT-IN, not the 1-step shadow"
    )
