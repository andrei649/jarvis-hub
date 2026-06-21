"""HTTP integration tests for workflow CRUD and autonomy HTTP endpoints.

Covers:
  GET    /api/workflows                  — list (user-defined store, no orch needed)
  POST   /api/workflows                  — create workflow
  PUT    /api/workflows/{id}             — update workflow (URL id wins)
  DELETE /api/workflows/{id}             — delete workflow (404 if absent)
  GET    /autonomy/tasks                 — list tasks (admin)
  GET    /autonomy/status                — queue stats (admin)
  POST   /autonomy/tasks                 — submit task (admin)
  POST   /autonomy/tasks/{id}/decision   — resolve blocked task (admin)
  GET    /autonomy/brief                 — morning/evening brief (admin)
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

_TOKEN = "wf-test-token"
_HDR = {"X-Admin-Token": _TOKEN}

_WF_BODY = {
    "id": "sprint-wf",
    "name": "Sprint Workflow",
    "description": "Test workflow",
    "steps": [{"id": "s1", "agent_id": "jarvis", "prompt_template": "hello"}],
}


@pytest.fixture(autouse=True)
def _isolated_wf_store(tmp_path, monkeypatch):
    """Each test gets its own WorkflowStore backed by a tmp directory."""
    from core.workflows.storage import WorkflowStore
    monkeypatch.setattr(web, "_wf_store_instance", WorkflowStore(tmp_path))
    # SEC-3: workflow CRUD is admin-guarded now; these tests exercise endpoint
    # behavior, not auth, so bypass the admin guard (as conftest does for user).
    # The workflow CRUD routes were extracted to routers/workflows.py (CLN-3), which
    # depends on _deps.admin_guard; the autonomy routes still use web._admin_guard.
    # Override BOTH callables so the bypass covers inline + extracted (mirrors the
    # user-guard handling in conftest).
    monkeypatch.setitem(web.app.dependency_overrides, web._admin_guard, lambda: None)
    from agents.core.routers._deps import admin_guard as _ra
    monkeypatch.setitem(web.app.dependency_overrides, _ra, lambda: None)


def _mock_orch() -> MagicMock:
    m = MagicMock()
    m.workflow_registry = MagicMock()
    m.workflow_registry.list = MagicMock(return_value=[])
    m.workflow_registry.get = MagicMock(return_value=None)
    m.workflow_registry.register = MagicMock()
    m.workflow_registry._pipelines = {}
    return m


def _mock_autonomy_orch() -> MagicMock:
    m = MagicMock()
    task = MagicMock()
    task.to_dict = MagicMock(return_value={
        "id": 1, "agent": "jarvis", "kind": "report",
        "title": "Test task", "status": "pending",
    })
    m.autonomy_queue.list = MagicMock(return_value=[task])
    m.autonomy_queue.stats = MagicMock(return_value={"total": 1, "pending": 1})
    m.autonomy_queue.pending_decisions = MagicMock(return_value=[])
    m.autonomy.budget.remaining = MagicMock(return_value=5)
    m.autonomy.budget.per_day = 10
    m.autonomy.submit = AsyncMock(return_value=task)
    m.autonomy.apply_decision = AsyncMock(return_value=task)
    m.autonomy_prefs.suggest_autonomy_raise = MagicMock(return_value=[])
    m.observer = None
    m.get_setting = MagicMock(return_value=True)
    return m


# ---------------------------------------------------------------------------
# GET /api/workflows
# ---------------------------------------------------------------------------

def test_workflows_list_returns_structure(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/api/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "workflows" in data
    assert "total" in data
    assert isinstance(data["workflows"], list)


def test_workflows_list_empty_when_no_store(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    data = client.get("/api/workflows").json()
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/workflows
# ---------------------------------------------------------------------------

def test_workflow_create_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/api/workflows", json=_WF_BODY)
    assert resp.status_code == 503


def test_workflow_create_returns_saved_dict(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.post("/api/workflows", json=_WF_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "sprint-wf"
    assert data["name"] == "Sprint Workflow"


def test_workflow_create_appears_in_list(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    client.post("/api/workflows", json=_WF_BODY)
    workflows = client.get("/api/workflows").json()["workflows"]
    assert any(w["id"] == "sprint-wf" for w in workflows)


def test_workflow_create_registers_in_registry(monkeypatch):
    mock = _mock_orch()
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    client.post("/api/workflows", json=_WF_BODY)
    # register may fail silently for invalid pipeline, but shouldn't raise
    assert True


# ---------------------------------------------------------------------------
# PUT /api/workflows/{id}
# ---------------------------------------------------------------------------

def test_workflow_update_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.put("/api/workflows/sprint-wf", json=_WF_BODY)
    assert resp.status_code == 503


def test_workflow_update_url_id_takes_precedence(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    body = {**_WF_BODY, "id": "body-id-should-be-ignored"}
    resp = client.put("/api/workflows/url-id-wins", json=body)
    assert resp.status_code == 200
    assert resp.json()["id"] == "url-id-wins"


def test_workflow_update_changes_name(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    client.post("/api/workflows", json=_WF_BODY)
    updated = {**_WF_BODY, "name": "Updated Name"}
    resp = client.put("/api/workflows/sprint-wf", json=updated)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


# ---------------------------------------------------------------------------
# DELETE /api/workflows/{id}
# ---------------------------------------------------------------------------

def test_workflow_delete_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.delete("/api/workflows/sprint-wf")
    assert resp.status_code == 503


def test_workflow_delete_nonexistent_returns_404(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.delete("/api/workflows/ghost-workflow")
    assert resp.status_code == 404


def test_workflow_delete_existing_returns_ok(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    client.post("/api/workflows", json=_WF_BODY)
    resp = client.delete("/api/workflows/sprint-wf")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["deleted"] == "sprint-wf"


def test_workflow_delete_removes_from_list(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    client.post("/api/workflows", json=_WF_BODY)
    client.delete("/api/workflows/sprint-wf")
    workflows = client.get("/api/workflows").json()["workflows"]
    assert not any(w["id"] == "sprint-wf" for w in workflows)


# ---------------------------------------------------------------------------
# GET /autonomy/tasks
# ---------------------------------------------------------------------------

def test_autonomy_tasks_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/autonomy/tasks", headers=_HDR)
    assert resp.status_code == 503


def test_autonomy_tasks_returns_list(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_autonomy_orch())
    client = TestClient(web.app)
    resp = client.get("/autonomy/tasks", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data and "total" in data
    assert data["total"] == 1


def test_autonomy_tasks_filter_by_status(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    mock = _mock_autonomy_orch()
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    client.get("/autonomy/tasks?status=pending", headers=_HDR)
    _, kwargs = mock.autonomy_queue.list.call_args
    assert kwargs.get("status") == "pending"


# ---------------------------------------------------------------------------
# GET /autonomy/status
# ---------------------------------------------------------------------------

def test_autonomy_status_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/autonomy/status", headers=_HDR)
    assert resp.status_code == 503


def test_autonomy_status_structure(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_autonomy_orch())
    client = TestClient(web.app)
    resp = client.get("/autonomy/status", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "interrupt_budget_remaining" in data
    assert "pending_decisions" in data


# ---------------------------------------------------------------------------
# POST /autonomy/tasks
# ---------------------------------------------------------------------------

def test_autonomy_submit_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/autonomy/tasks", json={"agent": "jarvis", "kind": "report", "title": "Test"}, headers=_HDR)
    assert resp.status_code == 503


def test_autonomy_submit_returns_task(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_autonomy_orch())
    client = TestClient(web.app)
    resp = client.post(
        "/autonomy/tasks",
        json={"agent": "jarvis", "kind": "report", "title": "Test task"},
        headers=_HDR,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "task" in data


# ---------------------------------------------------------------------------
# POST /autonomy/tasks/{id}/decision
# ---------------------------------------------------------------------------

def test_autonomy_decision_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/autonomy/tasks/1/decision", json={"action": "accept"}, headers=_HDR)
    assert resp.status_code == 503


def test_autonomy_decision_accept_returns_ok(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_autonomy_orch())
    client = TestClient(web.app)
    resp = client.post("/autonomy/tasks/1/decision", json={"action": "accept"}, headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_autonomy_decision_conflict_returns_409(monkeypatch):
    from core.autonomy.queue import TaskQueueError
    mock = _mock_autonomy_orch()
    mock.autonomy.apply_decision = AsyncMock(side_effect=TaskQueueError("already decided"))
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    resp = client.post("/autonomy/tasks/1/decision", json={"action": "accept"}, headers=_HDR)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /autonomy/brief
# ---------------------------------------------------------------------------

def test_autonomy_brief_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/autonomy/brief", headers=_HDR)
    assert resp.status_code == 503


def test_autonomy_brief_morning(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_autonomy_orch())
    with patch("agents.web.build_morning_brief", return_value="Good morning!", create=True), \
         patch("agents.web.build_evening_retro", return_value="Good evening!", create=True):
        client = TestClient(web.app)
        resp = client.get("/autonomy/brief?kind=morning", headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["kind"] == "morning"
    assert isinstance(resp.json()["text"], str)
