"""OpenRouter vision uses the actual composer and governed HTTP request."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import settings_db
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from tests.test_composer_vision import DESCRIBE, PNG, STATUS


def setting(name, value):
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='llm' AND key=?",
                     (json.dumps(value), name))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def route(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    for name in ("JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_KEY", "OPENROUTER_BASE_URL",
                 "JARVIS_VLM_URL", "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY", "JARVIS_VLM_PRESET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "0")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "image-test")
    monkeypatch.setattr(web, "USER_TOKEN", "image-test")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    state = SimpleNamespace(sent=[], after_gate=None, empty_first=False)

    def respond(request):
        state.sent.append(request)
        content = "" if state.empty_first and len(state.sent) == 1 else "An image."
        return httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content": content}}]})

    def factory(provider, **kwargs):
        client = llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs)

        async def after_gate(request):
            if state.after_gate:
                state.after_gate(request)

        client.event_hooks["request"].append(after_gate)
        return client

    monkeypatch.setattr(vlm, "llm_async_client", factory)
    state.client = TestClient(web.app, headers={"X-User-Token": "image-test"})
    return state


def approved_body(route):
    status = route.client.get(STATUS).json()
    assert status["configured"], status
    assert status["backend"] == "openrouter"
    assert status["reachable"] is None
    assert not route.sent
    assert "synthetic-openrouter-key" not in str(status)
    return {"prompt": "What is shown?", "images": [PNG], "remote_ack": True,
            "expected_destination": status["destination"], "expected_binding": status["binding"]}


@pytest.mark.parametrize("retry", ["0", "1"])
def test_composer_sends_openrouter_controls_and_actual_identity(route, monkeypatch, retry):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    setting("openrouter_only", ["provider-a"])
    setting("openrouter_order", ["provider-a", "provider-b"])
    setting("openrouter_require_parameters", True)
    response = route.client.post(DESCRIBE, json=approved_body(route))
    assert response.status_code == 200, response.text
    assert response.json()["response"] == "An image."
    assert len(route.sent) == 1
    request = route.sent[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer synthetic-openrouter-key"
    payload = json.loads(request.content)
    assert payload["model"] == "vendor/vision"
    assert payload["provider"] == {"only": ["provider-a"], "order": ["provider-a", "provider-b"],
                                   "require_parameters": True, "data_collection": "deny"}
    assert payload["messages"][0]["content"][1]["type"] == "image_url"


def test_openrouter_remote_ack_is_still_required(route):
    body = approved_body(route)
    body["remote_ack"] = False
    assert route.client.post(DESCRIBE, json=body).status_code == 403
    assert not route.sent


@pytest.mark.parametrize("name,value", [
    ("openrouter_data_collection", "allow"), ("openrouter_only", ["new-provider"]),
    ("openrouter_ignore", ["provider-b"]), ("openrouter_sort", "price"),
])
def test_changed_routing_revokes_preview_before_request(route, name, value):
    body = approved_body(route)
    setting(name, value)
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert not route.sent


@pytest.mark.parametrize("retry", ["0", "1"])
@pytest.mark.parametrize("mutation", ["body", "settings", "key"])
def test_last_hook_refuses_mutation_after_egress_gate(route, monkeypatch, retry, mutation):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    body = approved_body(route)

    def mutate(request):
        if mutation == "body":
            payload = json.loads(request.content)
            payload["provider"] = {"data_collection": "allow"}
            request._content = json.dumps(payload).encode()
        elif mutation == "settings":
            setting("openrouter_data_collection", "allow")
        else:
            monkeypatch.setenv("OPENROUTER_API_KEY", "rotated-synthetic-key")

    route.after_gate = mutate
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert not route.sent


def test_openrouter_empty_retry_preserves_body_and_routing(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    route.empty_first = True
    body = approved_body(route)
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 200, response.text
    assert len(route.sent) == 2
    assert route.sent[0].content == route.sent[1].content
    assert json.loads(route.sent[1].content)["provider"] == {"data_collection": "deny"}


@pytest.mark.parametrize("value", [False, 0, {}, ["bad slug"]])
def test_malformed_routing_never_becomes_a_default(route, value):
    setting("openrouter_only", value)
    status = route.client.get(STATUS).json()
    assert status["configured"] is False, status
    assert not route.sent


def test_allowed_collection_is_disclosed_and_needs_training_ack(route):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    status = route.client.get(STATUS).json()
    assert status["data_policy"] == "trains-on-inputs"
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 409, response.text
    assert response.json()["needs"] == ["acknowledge_training"]
    assert not route.sent


def test_free_model_retains_profile_training_guard(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision:free")
    response = route.client.post(DESCRIBE, json=approved_body(route))
    assert response.status_code == 409
    assert response.json()["needs"] == ["acknowledge_training"]
    assert not route.sent


@pytest.mark.parametrize("mutation", ["duplicate", "number"])
def test_provider_wire_controls_preserve_unique_keys_and_types(route, mutation):
    setting("openrouter_require_parameters", True)
    body = approved_body(route)

    def mutate(request):
        if mutation == "duplicate":
            request._content = b'{"provider":{"data_collection":"allow"},' + request.content[1:]
        else:
            payload = json.loads(request.content)
            payload["provider"]["require_parameters"] = 1
            request._content = json.dumps(payload).encode()

    route.after_gate = mutate
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert not route.sent


def test_unreadable_settings_refuse_without_private_diagnostics(route, monkeypatch):
    body = approved_body(route)

    def unavailable(*args):
        raise settings_db.SettingsUnreadable("private database diagnostics")

    monkeypatch.setattr(settings_db, "read_setting", unavailable)
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 503
    assert "private database diagnostics" not in response.text
    assert not route.sent


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["describe", "screen", "telegram"])
async def test_explicit_remote_role_cannot_enable_local_only_consumers(route, monkeypatch, consumer):
    from agents.core.channels.media_reader import InboundImageReader
    from tests.test_h513_interactive_local_vision import invoke

    approved_body(route)
    monkeypatch.setattr(vlm, "VLMBackend", lambda **kw: pytest.fail("remote client constructed"))
    if consumer == "telegram":
        reader = InboundImageReader.from_env()
        assert reader.refusal().reason == "local_vlm_not_proven_local"
    else:
        response = await invoke(consumer)
        assert response.status_code == 503
    assert not route.sent
