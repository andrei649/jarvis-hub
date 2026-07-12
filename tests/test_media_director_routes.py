"""ORIZONT 29 wave 1 — the Media Director HTTP surface (default-off honesty).

Same TestClient-over-web.app pattern as test_feedback_widget.py; guards are
overridden (their behavior is pinned by the auth-matrix gate), and the module
singleton director is replaced per test so nothing persists to agents/data.
"""

import pytest
from fastapi.testclient import TestClient

from agents.core.media_director import (
    DeviceRegistry,
    MediaDevice,
    MediaDirector,
    MediaSession,
    SessionBoard,
)
from agents.core.routers import media_director as media_routes


class _GrantAllDriver:
    def __init__(self):
        self.now_playing = None

    def play(self, device, content):
        self.now_playing = content
        return {"ok": True, "state": "playing"}

    def pause(self, device):
        return {"ok": True, "state": "paused"}

    def resume(self, device):
        return {"ok": True, "state": "playing"}

    def stop(self, device):
        self.now_playing = None
        return {"ok": True, "state": "idle"}

    def status(self, device):
        return {"ok": True, "state": "playing", "content": self.now_playing or {}}


@pytest.fixture
def client(monkeypatch):
    from agents import web
    from agents.core.routers._deps import admin_guard, user_guard

    web.app.dependency_overrides[user_guard] = lambda: None
    web.app.dependency_overrides[admin_guard] = lambda: None
    monkeypatch.setattr(
        media_routes,
        "_director",
        MediaDirector(
            registry=DeviceRegistry(path=None),
            sessions=SessionBoard(path=None),
            drivers={"tv": _GrantAllDriver()},
        ),
    )
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        web.app.dependency_overrides.pop(admin_guard, None)


def test_every_endpoint_is_honestly_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("JARVIS_MEDIA_DIRECTOR", raising=False)
    for method, path, body in (
        ("GET", "/api/media/devices", None),
        ("GET", "/api/media/session", None),
        ("POST", "/api/media/devices", {"id": "x", "name": "X", "kind": "tv"}),
        (
            "POST",
            "/api/media/present",
            {"content": {"type": "url", "value": "https://x"}, "target": "x"},
        ),
        ("POST", "/api/media/restore/x", None),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is False
        assert "JARVIS_MEDIA_DIRECTOR" in payload["hint"]


def test_device_crud_when_enabled(client, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    created = client.post(
        "/api/media/devices",
        json={"id": "tv-1", "name": "Living TV", "kind": "tv", "room": "living"},
    )
    assert created.status_code == 200 and created.json()["device"]["id"] == "tv-1"
    bad = client.post("/api/media/devices", json={"id": "x", "name": "X", "kind": "teleporter"})
    assert bad.status_code == 422

    listed = client.get("/api/media/devices").json()
    assert [d["id"] for d in listed["devices"]] == ["tv-1"]
    assert "no-store" in client.get("/api/media/devices").headers.get("cache-control", "")

    assert client.delete("/api/media/devices/tv-1").status_code == 200
    assert client.delete("/api/media/devices/tv-1").status_code == 404


def test_present_route_goes_through_the_facade_and_reports_disabled_flags(client, monkeypatch):
    """With the media flag on but the unified action API off, the route must
    refuse via the facade — never drive the device unmediated."""
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API", raising=False)
    client.post(
        "/api/media/devices",
        json={"id": "tv-1", "name": "Living TV", "kind": "tv", "room": "living"},
    )
    response = client.post(
        "/api/media/present",
        json={
            "content": {"type": "url", "value": "https://example.local/brief"},
            "target": "tv-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["reason"] == "unified_action_api_disabled"
    # And the driver was never touched: no session was recorded.
    assert client.get("/api/media/session").json()["sessions"] == []


def test_restore_route_reports_honest_no_session(client, monkeypatch):
    from agents.core.kernel import Decision, Verdict

    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: object())
    monkeypatch.setattr(
        "agents.core.kernel.binding.make_action_kernel",
        lambda _orch: lambda action, capability=None: Decision(
            Verdict.GRANT, reason="test", tier=1
        ),
    )
    payload = client.post("/api/media/restore/ghost").json()
    assert payload["enabled"] is True and payload["status"] == "completed"
    assert payload["output"]["ok"] is False
    assert "no session" in payload["output"]["reason"]


def test_restore_route_never_actuates_when_unified_action_api_is_off(client, monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API", raising=False)
    director = media_routes._director
    director.registry.register(MediaDevice(id="tv-1", name="TV", kind="tv"))
    director.sessions.set(
        MediaSession(
            device_id="tv-1",
            content={"type": "url", "value": "https://example.local/current"},
            mode="play",
            privacy="household",
            started_at=1.0,
        )
    )

    payload = client.post("/api/media/restore/tv-1").json()

    assert payload["status"] == "disabled"
    assert payload["reason"] == "unified_action_api_disabled"
    assert director.sessions.get("tv-1") is not None
