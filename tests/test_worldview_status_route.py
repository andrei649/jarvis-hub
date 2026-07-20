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


# ── /overview — liveness + recon read data in one call ──────────────

def test_overview_no_orchestrator_reports_not_connected(monkeypatch):
    monkeypatch.setattr(worldview_router, "get_orch", lambda: None)
    resp = TestClient(web.app).get("/api/worldview/overview")
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "api_url": None, "recon": None}


def test_overview_down_backend_never_fabricates_recon(monkeypatch):
    class _DownPlugin:
        async def status(self):
            return {"connected": False, "api_url": "http://localhost:4000"}

        async def recon_overview(self):  # pragma: no cover — must NOT be reached
            raise AssertionError("recon_overview must not be called when not connected")

    orch = SimpleNamespace(plugins={"worldview": _DownPlugin()})
    monkeypatch.setattr(worldview_router, "get_orch", lambda: orch)
    resp = TestClient(web.app).get("/api/worldview/overview")
    assert resp.json() == {
        "connected": False,
        "api_url": "http://localhost:4000",
        "recon": None,
    }


def test_overview_connected_passes_recon_through(monkeypatch):
    recon = {
        "status": "ok",
        "upcoming_windows": [{"norad_id": 40115, "aoi_id": "hormuz"}],
        "due_alerts": [{"norad_id": 40115, "aoi_id": "hormuz"}],
        "api_url": "http://localhost:4000",
    }

    class _UpPlugin:
        async def status(self):
            return {"connected": True, "api_url": "http://localhost:4000", "service": "worldview-api"}

        async def recon_overview(self):
            return recon

    orch = SimpleNamespace(plugins={"worldview": _UpPlugin()})
    monkeypatch.setattr(worldview_router, "get_orch", lambda: orch)
    body = TestClient(web.app).get("/api/worldview/overview").json()
    assert body["connected"] is True
    assert body["recon"] == recon


def test_overview_connected_but_recon_unavailable_is_honest(monkeypatch):
    class _PartialPlugin:
        async def status(self):
            return {"connected": True, "api_url": "http://localhost:4000", "service": "worldview-api"}

        async def recon_overview(self):
            return {"status": "unavailable", "error": "recon"}

    orch = SimpleNamespace(plugins={"worldview": _PartialPlugin()})
    monkeypatch.setattr(worldview_router, "get_orch", lambda: orch)
    body = TestClient(web.app).get("/api/worldview/overview").json()
    assert body["connected"] is True
    assert body["recon"] == {"status": "unavailable", "error": "recon"}
