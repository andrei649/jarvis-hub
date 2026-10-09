"""Auto vision selection must govern an actual image send through the composer."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import settings_db
from agents.core.llm import model_roles, nous_auth, selection_guards, vision_deepinfra, vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.nous_credentials import NousAuthStore
from agents.core.secrets import SecretStore
from tests.test_composer_vision import DESCRIBE, PNG, STATUS
from tests.test_h277_nous_auth import _jwt
from tests.test_h277_nous_credentials import KEY


@pytest.fixture
def route(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    for name in ("JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_KEY",
                 "JARVIS_ROLE_VISION_MODEL", "JARVIS_VLM_URL", "JARVIS_VLM_MODEL",
                 "JARVIS_VLM_KEY", "OPENROUTER_API_KEY", "DEEPINFRA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "auto")
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "0")
    monkeypatch.setenv("JARVIS_NOUS_CLIENT_ID", "nerva-auto-test-client")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "image-test")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "image-admin")
    monkeypatch.setattr(web, "USER_TOKEN", "image-test")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    store = NousAuthStore(tmp_path / "nous.sqlite3", cipher=SecretStore(tmp_path / "cipher", key=KEY))
    monkeypatch.setattr(nous_auth, "NousAuthStore", lambda: store)
    state = SimpleNamespace(client=None, requests=[], audit_events=[], store=store)

    class Audit:
        def log(self, event):
            state.audit_events.append(event)

    monkeypatch.setattr(selection_guards, "_orch", lambda: SimpleNamespace(audit=Audit()))

    def respond(request):
        state.requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": "An image."}}]})

    def factory(provider, **kwargs):
        return llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(vlm, "llm_async_client", factory)
    state.client = TestClient(web.app, headers={"X-User-Token": "image-test",
                                               "X-Admin-Token": "image-admin"})
    state.user_client = TestClient(web.app, headers={"X-User-Token": "image-test"})
    return state


def approved(status):
    return {"prompt": "Describe this", "images": [PNG], "remote_ack": True,
            "expected_destination": status["destination"], "expected_binding": status["binding"]}


def test_auto_openrouter_prepares_and_sends_with_free_model_and_policy(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    status = route.client.get(STATUS).json()
    assert status["configured"], status
    assert (status["backend"], status["selection_source"], status["model"]) == (
        "openrouter", "auto:openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")
    assert status["destination"] == "https://openrouter.ai/api/v1"
    assert "synthetic-openrouter-key" not in str(status)
    assert not route.requests
    body = approved(status)
    if any(item["needs"] == "acknowledge_training" for item in status.get("selection_requirements", [])):
        body["acknowledge_training"] = True
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 200, response.text
    assert len(route.requests) == 1
    sent = route.requests[0]
    assert str(sent.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer synthetic-openrouter-key"
    payload = json.loads(sent.content)
    assert payload["model"] == status["model"]
    assert payload["provider"]["data_collection"] == "deny"
    assert [event.action_taken for event in route.audit_events] == ["model_training_consent"]


def test_auto_prefers_prepared_nous_when_openrouter_unavailable(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "anthropic/claude-sonnet-4-6")
    with route.store.transaction() as account:
        account.update(access_token=_jwt(int(time.time()) + 3600), refresh_token="test-grant",
                       scope="inference:invoke", portal_base_url="https://portal.nousresearch.com",
                       client_id="nerva-auto-test-client")
    status = route.client.get(STATUS).json()
    assert status["configured"], status
    assert (status["backend"], status["selection_source"]) == ("nous", "auto:nous")
    response = route.client.post(DESCRIBE, json=approved(status))
    assert response.status_code == 200, response.text
    assert len(route.requests) == 1
    assert str(route.requests[0].url) == "https://inference-api.nousresearch.com/v1/chat/completions"


def test_auto_status_prepares_deepinfra_catalog_before_review(route, monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "synthetic-deepinfra-key")
    catalog_requests = []

    def catalog(request):
        catalog_requests.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"data": [
            {"id": "org/vision", "metadata": {"tags": ["chat", "vision"]}},
        ]})

    monkeypatch.setattr(vision_deepinfra, "_metadata_transport_factory",
                        lambda: httpx.MockTransport(catalog))
    vision_deepinfra.clear_cache()
    try:
        status = route.client.get(STATUS).json()
        assert status["configured"], status
        assert (status["backend"], status["model"], status["selection_source"]) == (
            "deepinfra", "org/vision", "auto:deepinfra")
        assert catalog_requests == [(
            "https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes",
            "Bearer synthetic-deepinfra-key",
        )]
        response = route.client.post(DESCRIBE, json=approved(status))
        assert response.status_code == 200, response.text
        assert len(route.requests) == 1
        assert str(route.requests[0].url) == "https://api.deepinfra.com/v1/openai/chat/completions"
        assert len(catalog_requests) == 1
    finally:
        vision_deepinfra.clear_cache()


def test_auto_switch_after_key_revocation_requires_fresh_review(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "synthetic-deepinfra-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision")
    status = route.client.get(STATUS).json()
    assert status["backend"] == "openrouter"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    response = route.client.post(DESCRIBE, json=approved(status))
    assert response.status_code == 409, response.text
    assert not route.requests
    refreshed = route.client.get(STATUS).json()
    assert refreshed["configured"] and refreshed["backend"] == "deepinfra"
    assert refreshed["selection_source"] == "auto:deepinfra"
    assert refreshed["binding"] != status["binding"]


def test_auto_never_sends_without_remote_confirmation(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    status = route.client.get(STATUS).json()
    body = approved(status)
    body["remote_ack"] = False
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 403
    assert not route.requests


def test_role_listing_agrees_with_prepared_auto_route_without_discovery(route, monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "synthetic-deepinfra-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision")
    status = route.client.get(STATUS).json()
    assert status["backend"] == "deepinfra"
    role = model_roles.resolve("vision")
    assert role.configured and role.provider_id == "deepinfra"
    assert role.model == "vendor/vision" and role.source["provider"] == "JARVIS_ROLE_VISION_PROVIDER"
    assert not route.requests


def test_auto_never_becomes_an_inherited_video_route(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    assert route.client.get(STATUS).json()["configured"]
    video = model_roles.resolve_video_route()
    assert not video.role.configured
    assert video.role.reason == "video_vision_provider_unsupported"
    assert not route.requests


def test_prepared_image_review_binds_prompt_session_and_destination(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": "session-a",
    })
    assert preview.status_code == 200, preview.text
    status = preview.json()
    assert status["configured"] and status["review_token"]
    assert not route.requests

    body = {**approved(status), "review_token": status["review_token"],
            "agent": "jarvis", "session_id": "session-a"}
    changed = route.client.post("/api/vlm/composer/describe-prepared",
                                json={**body, "prompt": "What is behind it?"})
    assert changed.status_code == 409
    assert changed.json()["reason"] == "vlm_destination_changed"
    assert not route.requests
    replay = route.client.post("/api/vlm/composer/describe-prepared", json=body)
    assert replay.status_code == 409
    assert not route.requests


def test_prepared_image_review_sends_once_then_replay_refuses(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": "session-a",
    })
    assert preview.status_code == 200, preview.text
    status = preview.json()
    body = {**approved(status), "review_token": status["review_token"],
            "agent": "jarvis", "session_id": "session-a"}
    if any(item["needs"] == "acknowledge_training" for item in status.get("selection_requirements", [])):
        body["acknowledge_training"] = True
    first = route.client.post("/api/vlm/composer/describe-prepared", json=body)
    assert first.status_code == 200, first.text
    assert len(route.requests) == 1
    second = route.client.post("/api/vlm/composer/describe-prepared", json=body)
    assert second.status_code == 409
    assert len(route.requests) == 1


def test_prepared_image_review_refuses_key_rotation_before_egress(route, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": "session-a",
    })
    assert preview.status_code == 200, preview.text
    status = preview.json()
    monkeypatch.setenv("OPENROUTER_API_KEY", "rotated-openrouter-key")
    body = {**approved(status), "review_token": status["review_token"],
            "agent": "jarvis", "session_id": "session-a"}
    response = route.client.post("/api/vlm/composer/describe-prepared", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["reason"] == "vlm_destination_changed"
    assert not route.requests
