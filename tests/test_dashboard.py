"""HTTP integration tests for GET /dashboard, GET /tasks, and GET /ticker.

Covers the 503 guard when orch is absent, the response structure required by
the React HUD widgets, weather-string parsing, dummy-task fallback, and the
ticker fallback to agent-standby items.
"""
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

_NO_ORCH_CLIENT = TestClient(web.app)  # no lifespan → orch stays None

_WEATHER_REQUIRED_FIELDS = {"city", "temp", "desc", "wind", "humidity", "feels", "updated", "forecast"}
_TASK_REQUIRED_FIELDS = {"id", "owner", "state", "label", "project"}
_TICKER_ITEM_FIELDS = {"agent", "verb", "obj", "pct", "pri"}


class _QueueTask:
    """Small queue-row double with independently controlled raw and JSON state."""

    def __init__(self, data: dict, **raw_fields):
        self._data = data
        for key, value in raw_fields.items():
            setattr(self, key, value)

    def to_dict(self) -> dict:
        return dict(self._data)


def _simple_orch() -> MagicMock:
    m = MagicMock()
    m.agents = {}
    m.observer = None
    m.plugins.get.return_value = None  # no weather / calendar plugin
    m.autonomy_queue.list.return_value = []
    return m


# ---------------------------------------------------------------------------
# GET /dashboard
# ---------------------------------------------------------------------------

def test_dashboard_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.get("/dashboard")
    assert resp.status_code == 503


def test_dashboard_returns_expected_keys(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": time.time()})
    client = TestClient(web.app)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "weather" in data
    assert "calendar" in data
    assert "notifications" in data


def test_dashboard_weather_has_required_fields(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": time.time()})
    client = TestClient(web.app)
    resp = client.get("/dashboard")
    weather = resp.json()["weather"]
    assert _WEATHER_REQUIRED_FIELDS <= set(weather.keys())


def test_dashboard_weather_defaults_when_no_plugin(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": time.time()})
    client = TestClient(web.app)
    weather = client.get("/dashboard").json()["weather"]
    assert weather["temp"] == "—"
    assert weather["desc"] == "Indisponibil"


def test_dashboard_parses_weather_string(monkeypatch):
    raw = "Partly cloudy, +18°C, 65% humidity, 12 km/h wind"
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {
        "weather": raw,
        "news": [],
        "cached_at": time.time(),
    })
    client = TestClient(web.app)
    weather = client.get("/dashboard").json()["weather"]
    assert weather["temp"] == "18"
    assert "65" in weather["humidity"]


def test_dashboard_notifications_is_list(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": time.time()})
    client = TestClient(web.app)
    notifs = client.get("/dashboard").json()["notifications"]
    assert isinstance(notifs, list)


def test_dashboard_calendar_is_list(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": time.time()})
    client = TestClient(web.app)
    cal = client.get("/dashboard").json()["calendar"]
    assert isinstance(cal, list)


def test_dashboard_concurrent_refresh_fetches_weather_once(monkeypatch):
    """BUG-1: concurrent /dashboard refreshes must not double-fetch the weather.

    With a stale cache, several requests racing through the refresh block should
    trigger exactly one upstream weather fetch thanks to the lock + re-check.
    """
    import asyncio

    calls = {"n": 0}

    async def _get_weather(_q):
        calls["n"] += 1
        await asyncio.sleep(0.01)  # widen the race window
        return "Sunny, +20°C"

    weather_plugin = MagicMock()
    weather_plugin.get_weather = _get_weather

    mock = _simple_orch()
    mock.plugins.get.side_effect = lambda name: weather_plugin if name == "weather" else None
    monkeypatch.setattr(web, "orch", mock)
    # Stale cache so the refresh branch is entered.
    monkeypatch.setattr(web, "_dashboard_cache", {"weather": "", "news": [], "cached_at": 0})
    monkeypatch.setattr(web, "_dashboard_lock", asyncio.Lock())

    from agents.core.routers.dashboard import dashboard as _dashboard_handler

    async def _run():
        await asyncio.gather(*(_dashboard_handler() for _ in range(8)))

    asyncio.run(_run())
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------

def test_tasks_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.get("/tasks")
    assert resp.status_code == 503


def test_tasks_returns_tasks_key(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    client = TestClient(web.app)
    data = client.get("/tasks").json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


def test_tasks_empty_queue_returns_empty_list(monkeypatch):
    # H7.7: empty queue returns [] instead of misleading dummy tasks
    monkeypatch.setattr(web, "orch", _simple_orch())
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    assert isinstance(tasks, list)
    assert len(tasks) == 0


def test_tasks_have_required_react_fields(monkeypatch):
    """When real tasks exist, they must include the required React HUD fields."""
    m = _simple_orch()
    real_task = MagicMock()
    real_task.to_dict.return_value = {
        "id": "t-1", "agent_id": "jarvis", "kind": "analysis",
        "title": "Test task", "status": "done", "state": "done",
        "owner": "jarvis", "label": "Test task", "project": "Autonomy",
    }
    m.autonomy_queue.list.return_value = [real_task]
    monkeypatch.setattr(web, "orch", m)
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    for task in tasks:
        assert _TASK_REQUIRED_FIELDS <= set(task.keys()), f"Missing fields in task: {task}"


def test_tasks_real_tasks_have_valid_state(monkeypatch):
    """When real tasks exist, their state field must be a valid state value."""
    m = _simple_orch()
    real_task = MagicMock()
    real_task.to_dict.return_value = {
        "id": "t-2", "agent_id": "friday", "kind": "report",
        "title": "Security scan", "status": "running", "state": "running",
        "owner": "friday", "label": "Security scan", "project": "Security",
    }
    m.autonomy_queue.list.return_value = [real_task]
    monkeypatch.setattr(web, "orch", m)
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    for task in tasks:
        assert task["state"] in ("done", "running", "pending", "failed")


def test_tasks_real_queue_items_are_returned(monkeypatch):
    fake_task = MagicMock()
    fake_task.to_dict.return_value = {
        "id": "real-1", "agent_id": "jarvis", "kind": "analysis",
        "title": "Analyse logs", "status": "done",
    }
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [fake_task]
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    assert any(t["id"] == "real-1" for t in tasks)


def test_tasks_running_view_uses_normalized_state_precedence(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask(
            {"id": "state-wins-running", "state": "  RUNNING ", "status": "done", "owner": "pepper"},
        ),
        _QueueTask(
            {"id": "state-wins-done", "state": "done", "status": "running", "owner": "stark"},
        ),
        _QueueTask(
            {"id": "blank-state-falls-back", "state": "  ", "status": " Running ", "owner": "vision"},
        ),
        _QueueTask(
            {"id": "not-exact", "state": "running-now", "status": "running", "owner": "jarvis"},
        ),
    ]
    monkeypatch.setattr(web, "orch", mock)

    response = TestClient(web.app).get("/tasks", params={"view": "running"})

    assert response.status_code == 200
    data = response.json()
    assert [task["id"] for task in data["tasks"]] == [
        "state-wins-running",
        "blank-state-falls-back",
    ]
    assert data["view"] == "running"
    assert data["source"] == "autonomy_queue"
    assert data["history_included"] is False
    as_of = datetime.fromisoformat(data["as_of"].replace("Z", "+00:00"))
    assert as_of.utcoffset() == UTC.utcoffset(as_of)


def test_tasks_running_view_never_falls_back_to_history(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask({"id": "done", "state": "done", "status": "done"}),
        _QueueTask({"id": "proposed", "status": "proposed"}),
    ]
    monkeypatch.setattr(web, "orch", mock)

    data = TestClient(web.app).get("/tasks?view=running").json()

    assert data["tasks"] == []
    assert data["view"] == "running"
    assert data["history_included"] is False


def test_tasks_history_view_excludes_normalized_running_rows(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask({"id": "running", "status": " RUNNING "}),
        _QueueTask({"id": "done", "state": "done", "status": "running"}),
        _QueueTask({"id": "blocked", "state": "", "status": "blocked"}),
    ]
    monkeypatch.setattr(web, "orch", mock)

    data = TestClient(web.app).get("/tasks?view=history").json()

    assert [task["id"] for task in data["tasks"]] == ["done", "blocked"]
    assert data["view"] == "history"
    assert data["source"] == "autonomy_queue"
    assert data["history_included"] is True


def test_tasks_owner_precedence_includes_legacy_agent_field(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask({"id": "owner", "status": "done", "owner": "pepper", "agent_id": "stark", "agent": "vision"}),
        _QueueTask({"id": "agent-id", "status": "done", "owner": "", "agent_id": "stark", "agent": "vision"}),
        _QueueTask({"id": "agent", "status": "done", "owner": None, "agent_id": "", "agent": "vision"}),
        _QueueTask({"id": "fallback", "status": "done"}),
    ]
    monkeypatch.setattr(web, "orch", mock)

    tasks = TestClient(web.app).get("/tasks?view=history").json()["tasks"]

    assert {task["id"]: task["owner"] for task in tasks} == {
        "owner": "pepper",
        "agent-id": "stark",
        "agent": "vision",
        "fallback": "jarvis",
    }


def test_tasks_legacy_view_keeps_raw_case_sensitive_running_selection(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask({"id": "raw-status", "status": "done"}, status="running"),
        _QueueTask({"id": "raw-state", "state": "done"}, state="running"),
        _QueueTask({"id": "uppercase", "status": "RUNNING"}, status="RUNNING"),
        _QueueTask({"id": "history", "status": "done"}, status="done"),
    ]
    monkeypatch.setattr(web, "orch", mock)

    data = TestClient(web.app).get("/tasks").json()

    assert [task["id"] for task in data["tasks"]] == ["raw-status", "raw-state"]
    assert data["view"] == "legacy"
    assert data["history_included"] is False


def test_tasks_legacy_view_does_not_format_excluded_history(monkeypatch):
    running = _QueueTask({"id": "running", "status": "running"}, status="running")
    excluded_history = MagicMock()
    excluded_history.status = "done"
    excluded_history.state = "done"
    excluded_history.to_dict.side_effect = AssertionError("legacy history row was formatted")
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [running, excluded_history]
    monkeypatch.setattr(web, "orch", mock)

    response = TestClient(web.app).get("/tasks")

    assert response.status_code == 200
    assert [task["id"] for task in response.json()["tasks"]] == ["running"]
    excluded_history.to_dict.assert_not_called()


def test_tasks_legacy_view_keeps_no_running_history_fallback(monkeypatch):
    mock = _simple_orch()
    mock.autonomy_queue.list.return_value = [
        _QueueTask({"id": "uppercase", "status": "RUNNING"}, status="RUNNING"),
        _QueueTask({"id": "history", "status": "done"}, status="done"),
    ]
    monkeypatch.setattr(web, "orch", mock)

    data = TestClient(web.app).get("/tasks").json()

    assert [task["id"] for task in data["tasks"]] == ["uppercase", "history"]
    assert data["view"] == "legacy"
    assert data["source"] == "autonomy_queue"
    assert data["history_included"] is True


def test_tasks_rejects_unknown_view_before_reading_queue(monkeypatch):
    mock = _simple_orch()
    monkeypatch.setattr(web, "orch", mock)

    response = TestClient(web.app).get("/tasks?view=completed")

    assert response.status_code == 422
    mock.autonomy_queue.list.assert_not_called()


def test_tasks_openapi_declares_bounded_view_and_response_metadata():
    operation = web.app.openapi()["paths"]["/tasks"]["get"]
    query = next(parameter for parameter in operation["parameters"] if parameter["name"] == "view")
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert set(query["schema"]["anyOf"][0]["enum"]) == {"running", "history"}
    assert response_schema == {"$ref": "#/components/schemas/TasksResponse"}
    tasks_schema = web.app.openapi()["components"]["schemas"]["TasksResponse"]
    assert {"tasks", "view", "history_included", "as_of"} <= set(tasks_schema["required"])
    assert tasks_schema["properties"]["source"]["default"] == "autonomy_queue"


# ---------------------------------------------------------------------------
# GET /ticker
# ---------------------------------------------------------------------------

def test_ticker_no_orch_returns_503():
    resp = _NO_ORCH_CLIENT.get("/ticker")
    assert resp.status_code == 503


def test_ticker_returns_ticker_key(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    client = TestClient(web.app)
    data = client.get("/ticker").json()
    assert "ticker" in data
    assert isinstance(data["ticker"], list)


def test_ticker_observer_unhealthy_signal_appears(monkeypatch):
    mock = _simple_orch()
    mock.observer = MagicMock()
    mock.observer.status.return_value = {
        "signals": {
            "disk": {"healthy": False, "detail": "Disk 95% full", "agent": "steve", "severity": "CRITICAL"}
        }
    }
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    items = client.get("/ticker").json()["ticker"]
    assert any(it.get("verb") == "WARNING" for it in items)


def test_ticker_healthy_only_signals_use_fallback(monkeypatch):
    mock = _simple_orch()
    mock.observer = MagicMock()
    mock.observer.status.return_value = {"signals": {}}
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    resp = client.get("/ticker")
    assert resp.status_code == 200
