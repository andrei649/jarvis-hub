"""The owner connects ChatGPT in a browser on the hub machine."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.responses import JSONResponse
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


def test_chat_selection_refuses_guests_and_uncleared_guards_before_catalog(http, monkeypatch):
    from agents.core import chatgpt_connection as account
    from agents.core.routers import admin

    calls = []

    async def prepare(_model):
        calls.append("prepare")
        return "opaque-generation"

    async def refuse(_changes, **_kwargs):
        calls.append("guard")
        return JSONResponse({"error": "selection_guard", "needs": ["acknowledge_training"]}, status_code=409)

    monkeypatch.setattr(account, "prepare_chat_selection", prepare, raising=False)
    monkeypatch.setattr(admin, "_pair_snapshot", lambda _changes: _async_result((7, "", "")))
    monkeypatch.setattr(admin, "_guard_selection", refuse)
    guest = http.post(BASE + "/select", json={"model": "gpt-synthetic"},
                      headers={"X-User-Token": "synthetic-guest"})
    assert guest.status_code in (401, 403)
    refused = http.post(BASE + "/select", json={"model": "gpt-synthetic"}, headers=ADMIN)
    assert refused.status_code == 409 and refused.json()["error"] == "selection_guard"
    assert calls == ["guard"]


def test_chat_selection_checks_managed_settings_before_catalog_or_guard(http, monkeypatch):
    from agents.core import chatgpt_connection as account
    from agents.core import managed_scope

    calls = []

    async def prepare(_model):
        calls.append("prepare")
        return "opaque-generation"

    def managed(_category, _key, _value):
        calls.append("managed")
        from agents.core.managed_scope import ManagedRefused
        raise ManagedRefused("pinned", names=("llm.compatible_provider",))

    monkeypatch.setattr(account, "prepare_chat_selection", prepare, raising=False)
    monkeypatch.setattr(managed_scope, "check_setting_write", managed)
    refused = http.post(BASE + "/select", json={"model": "gpt-synthetic"}, headers=ADMIN)
    assert refused.status_code == 409
    assert calls == ["managed"]


def test_chat_selection_writes_settings_before_binding_and_redetect(http, monkeypatch):
    from agents.core import chatgpt_connection as account
    from agents.core import managed_scope
    from agents.core.routers import admin, chatgpt_plan

    calls = []
    monkeypatch.setattr(managed_scope, "check_setting_write", lambda *_args: None)

    async def snapshot(changes):
        assert changes == {"llm": {"compatible_provider": "chatgpt-plan", "compatible_model": "gpt-synthetic"}}
        calls.append("snapshot")
        return (11, "", "")

    async def guard(changes, **kwargs):
        assert kwargs["surface"] == "chatgpt-plan"
        assert kwargs["pair_state"] == (11, "", "")
        calls.append("guard")
        return []

    async def prepare(model):
        assert model == "gpt-synthetic"
        calls.append("prepare")
        return "opaque-generation"

    async def write(_fn, category, values, **kwargs):
        assert category == "llm" and values == {"compatible_provider": "chatgpt-plan", "compatible_model": "gpt-synthetic"}
        assert kwargs["expected_pair_revision"] == 11
        calls.append("write")
        return 2, []

    async def audit(_category, _keys, _values):
        calls.append("audit")

    async def required_audit(_preview, _action, *, required):
        assert required is True
        calls.append("required-audit")

    def bind(model, generation):
        assert (model, generation) == ("gpt-synthetic", "opaque-generation")
        calls.append("bind")
        return {"model": model}

    async def detect():
        calls.append("detect")
        return True

    monkeypatch.setattr(admin, "_pair_snapshot", snapshot)
    monkeypatch.setattr(admin, "_guard_selection", guard)
    monkeypatch.setattr(account, "prepare_chat_selection", prepare, raising=False)
    monkeypatch.setattr(admin, "_drain_settings_write", write)
    monkeypatch.setattr(admin, "_audit_settings_change", audit)
    monkeypatch.setattr(chatgpt_plan, "_audit", required_audit)
    monkeypatch.setattr(account, "select_for_chat", bind, raising=False)
    monkeypatch.setattr(chatgpt_plan, "_redetect_router", detect, raising=False)
    selected = http.post(BASE + "/select", json={"model": "gpt-synthetic"}, headers=ADMIN)
    assert selected.status_code == 200 and selected.json() == {"model": "gpt-synthetic"}
    assert calls == ["snapshot", "guard", "prepare", "write", "audit", "required-audit", "bind", "detect"]


def test_chat_selection_refuses_changed_registration_after_settings_write(http, monkeypatch):
    from agents.core import chatgpt_connection as account
    from agents.core import managed_scope
    from agents.core.routers import admin, chatgpt_plan

    calls = []
    monkeypatch.setattr(managed_scope, "check_setting_write", lambda *_args: None)
    monkeypatch.setattr(admin, "_pair_snapshot", lambda _changes: _async_result((11, "", "")))
    monkeypatch.setattr(admin, "_guard_selection", lambda *_args, **_kwargs: _async_result([]))
    monkeypatch.setattr(account, "prepare_chat_selection", lambda _model: _async_result("opaque"), raising=False)
    monkeypatch.setattr(admin, "_drain_settings_write", lambda *_args, **_kwargs: _async_result((2, [])))
    monkeypatch.setattr(admin, "_audit_settings_change", lambda *_args: _async_result(None))
    monkeypatch.setattr(chatgpt_plan, "_audit", lambda *_args, **_kwargs: _async_result(None))

    def changed(_model, _generation):
        calls.append("bind")
        raise account.ConnectionError("connection_changed", 409)

    async def detect():
        calls.append("detect")

    monkeypatch.setattr(account, "select_for_chat", changed, raising=False)
    monkeypatch.setattr(chatgpt_plan, "_redetect_router", detect, raising=False)
    refused = http.post(BASE + "/select", json={"model": "gpt-synthetic"}, headers=ADMIN)
    assert refused.status_code == 409 and refused.json()["error"] == "connection_changed"
    assert calls == ["bind"]


async def _async_result(value):
    return value
