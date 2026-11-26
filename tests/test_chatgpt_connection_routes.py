"""The owner connects ChatGPT in a browser on the hub machine."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from agents import web

BASE = "/api/admin/chatgpt-plan"
CALLBACK = "/api/oauth/chatgpt/callback"
LOCAL = "http://127.0.0.1:46783"
ADMIN = {"X-Admin-Token": "synthetic-plan-owner"}


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_admin_configured", lambda: True)
    monkeypatch.setattr(web, "_admin_credential_ok", lambda token: token == ADMIN["X-Admin-Token"])
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setenv("JARVIS_USER_TOKEN", "synthetic-guest")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "profile"))
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    return TestClient(web.app, base_url=LOCAL, client=("127.0.0.1", 41022))


def test_only_owner_can_connect_list_or_forget_an_account(http):
    for method, path in (("GET", ""), ("POST", "/connect"), ("GET", "/models"), ("POST", "/disconnect")):
        response = http.request(method, BASE + path, headers={"X-User-Token": "synthetic-guest"})
        assert response.status_code in (401, 403), (path, response.status_code)
    assert http.post(BASE + "/connect", json={}, headers={**ADMIN, "Origin": "https://example.invalid"}).status_code == 403
    assert http.post(BASE + "/connect", content="{}", headers=ADMIN).status_code == 415
    assert http.post(BASE + "/connect", json={}, headers={**ADMIN, "host": "testserver"}).status_code in (400, 403)


def test_owner_browser_receives_only_the_public_link_and_owns_the_return(http, monkeypatch):
    from agents.core import chatgpt_connection as service

    started = http.post(BASE + "/connect", headers=ADMIN, json={})
    assert started.status_code == 200, started.text
    assert set(started.json()) == {"url"}
    url = urlsplit(started.json()["url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "auth.openai.com", "/api/accounts/authorize")
    query = parse_qs(url.query)
    assert query["redirect_uri"] == [LOCAL + CALLBACK]
    assert "code_verifier" not in query
    cookie = started.headers["set-cookie"]
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower() and ("path=" + CALLBACK) in cookie.lower()
    assert "no-store" in started.headers["cache-control"]
    state = query["state"][0]
    # Invalid or unbound redirects must neither consume the legitimate offer nor exchange a code.
    other = TestClient(web.app, base_url=LOCAL, client=("127.0.0.1", 41024))
    denied = other.get(CALLBACK, params={"state": state, "code": "SYNTHETIC_CODE"})
    assert denied.status_code == 403
    assert "SYNTHETIC_CODE" not in denied.text and state not in denied.text
    assert "no-store" in denied.headers["cache-control"]
    assert denied.headers["referrer-policy"] == "no-referrer"
    assert http.get(BASE, headers=ADMIN).json() == {"connected": False}

    async def record_return(got_state, binding, *, code, client_id, error):
        assert got_state == state and binding and binding in cookie
        assert code == "SYNTHETIC_CODE" and client_id == "oaiapp_fixture" and error is None

    monkeypatch.setattr(service, "complete", record_return)
    accepted = http.get(CALLBACK, params={"state": state, "code": "SYNTHETIC_CODE", "client_id": "oaiapp_fixture"})
    assert accepted.status_code == 200 and "ChatGPT" in accepted.text
    assert "SYNTHETIC_CODE" not in accepted.text and "max-age=0" in accepted.headers["set-cookie"].lower()
    assert http.post(BASE + "/disconnect", headers=ADMIN, json={}).status_code == 200
