"""HTTP integration tests for GET /dashboard, GET /tasks, and GET /ticker.

Covers the 503 guard when orch is absent, the response structure required by
the React HUD widgets, weather-string parsing, dummy-task fallback, and the
ticker fallback to agent-standby items.
"""
import sys
import time
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


def test_tasks_empty_queue_returns_dummy_tasks(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    assert len(tasks) == 3


def test_tasks_have_required_react_fields(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
    client = TestClient(web.app)
    tasks = client.get("/tasks").json()["tasks"]
    for task in tasks:
        assert _TASK_REQUIRED_FIELDS <= set(task.keys()), f"Missing fields in task: {task}"


def test_tasks_dummy_have_valid_state(monkeypatch):
    monkeypatch.setattr(web, "orch", _simple_orch())
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
