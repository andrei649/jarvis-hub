"""GET /api/worldview/status — the HUD World-tab bridge route.

Reuses the chat-agent WorldViewPlugin's own status() (see test_worldview_plugin.py
for its unit coverage); this file only covers the route-level wiring: no
orchestrator, no plugin, and the happy path — always a structured, honest
response, never a fabricated "connected".
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import worldview as worldview_router


def test_open_no_guard():
    # No admin/user dependency override needed — this is a non-sensitive meter,
    # same tier as /api/analytics/locality and /api/metrics/capabilities.
    resp = TestClient(web.app).get("/api/worldview/status")
    assert resp.status_code == 200


def test_no_orchestrator_reports_not_connected(monkeypatch):
    monkeypatch.setattr(worldview_router, "get_orch", lambda: None)
    resp = TestClient(web.app).get("/api/worldview/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "api_url": None}
    assert "no-store" in resp.headers.get("cache-control", "")


def test_plugin_not_registered_reports_not_connected(monkeypatch):
    orch = SimpleNamespace(plugins={})
    monkeypatch.setattr(worldview_router, "get_orch", lambda: orch)
    resp = TestClient(web.app).get("/api/worldview/status")
    assert resp.json() == {"connected": False, "api_url": None}


def test_delegates_to_plugin_status(monkeypatch):
    class _FakePlugin:
        async def status(self):
            return {"connected": True, "api_url": "http://localhost:4000", "service": "worldview-api"}

    orch = SimpleNamespace(plugins={"worldview": _FakePlugin()})
    monkeypatch.setattr(worldview_router, "get_orch", lambda: orch)
    resp = TestClient(web.app).get("/api/worldview/status")
    assert resp.json() == {
        "connected": True,
        "api_url": "http://localhost:4000",
        "service": "worldview-api",
    }
