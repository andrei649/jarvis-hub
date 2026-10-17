"""The provider's OAuth redirect is a GET to REDIRECT_URI; the hub must complete the
exchange there (a POST-only callback answered the redirect with 405)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.core.plugins import oauth as plugin
from agents.core.routers import oauth as routes


@pytest.fixture
def client(monkeypatch):
    calls = []

    async def exchange(code, state=""):
        calls.append((code, state))
        return {"access_token": "a", "refresh_token": "r"}

    monkeypatch.setattr(routes, "verify_state", lambda s: "spotify" if s == "good" else None)
    monkeypatch.setattr(routes, "exchange_spotify_code", exchange)
    app = FastAPI()
    app.include_router(routes.router)
    c = TestClient(app)
    c.calls = calls
    return c


def test_the_redirect_uri_is_a_get_route():
    assert plugin.REDIRECT_URI.endswith("/api/oauth/callback")
    methods = {m for r in routes.router.routes if getattr(r, "path", "") == "/api/oauth/callback"
               for m in r.methods}
    assert "GET" in methods and "POST" in methods


def test_provider_redirect_completes_the_exchange(client):
    routes._cached_auth_urls["spotify"] = "https://stale"
    resp = client.get("/api/oauth/callback", params={"code": "c1", "state": "good"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "spotify is connected" in resp.text
    assert client.calls == [("c1", "good")]
    assert "spotify" not in routes._cached_auth_urls


def test_bad_state_or_denied_consent_does_not_exchange(client):
    bad = client.get("/api/oauth/callback", params={"code": "c1", "state": "forged"})
    denied = client.get("/api/oauth/callback", params={"error": "access_denied", "state": "good"})
    assert bad.status_code == 400 and "expired state" in bad.text
    assert denied.status_code == 400 and "not completed" in denied.text
    assert client.calls == []


def test_the_post_callback_still_works(client):
    resp = client.post("/api/oauth/callback", json={"code": "c2", "state": "good"})
    assert resp.json() == {"ok": True, "service": "spotify", "has_refresh": True}
