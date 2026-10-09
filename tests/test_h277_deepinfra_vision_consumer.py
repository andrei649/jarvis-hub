"""DeepInfra catalog preparation is wired to actual governed image turns."""

import asyncio
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


@pytest.fixture
def route(monkeypatch, tmp_path):
    from agents.core.llm import vision_deepinfra as catalog

    catalog.clear_cache()
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    for name in ("JARVIS_ROLE_VISION_MODEL", "JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_KEY",
                 "JARVIS_VLM_BACKEND", "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY", "JARVIS_VLM_URL", "DEEPINFRA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "deepinfra")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "synthetic-deepinfra-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "0")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "image-test")
    monkeypatch.setattr(web, "USER_TOKEN", "image-test")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    state = SimpleNamespace(metadata=[], inference=[], model="vendor/vision", catalog_failure=False,
                            after_gate=None, empty_first=False, response=None)

    def respond(request):
        if request.method == "GET":
            state.metadata.append(request)
            if state.catalog_failure:
                return httpx.Response(503, text="private catalog error")
            return httpx.Response(200, json={"data": [
                {"id": "vendor/text", "metadata": {"tags": ["chat"]}},
                {"id": state.model, "metadata": {"tags": ["chat", "vision"]}},
            ]})
        state.inference.append(request)
        if state.response is not None:
            return state.response()
        content = "" if state.empty_first and len(state.inference) == 1 else "A catalog-selected image."
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    def factory(provider, **kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        client = llm_async_client(provider, **kwargs)

        async def after_gate(request):
            if request.method == "POST" and state.after_gate:
                state.after_gate(request)

        client.event_hooks["request"].append(after_gate)
        return client

    monkeypatch.setattr(vlm, "llm_async_client", factory)
    monkeypatch.setattr(catalog, "llm_async_client", factory)
    state.client = TestClient(web.app, headers={"X-User-Token": "image-test"})
    yield state
    catalog.clear_cache()


def approved_body(route):
    status = route.client.get(STATUS).json()
    assert status["configured"], status
    assert status["backend"] == "deepinfra" and status["reachable"] is None
    assert "synthetic-deepinfra-key" not in str(status)
    return {"prompt": "What is shown?", "images": [PNG], "remote_ack": True,
            "expected_destination": status["destination"], "expected_binding": status["binding"]}


def test_status_discovers_model_before_actual_confirmed_inference(route):
    body = approved_body(route)
    assert len(route.metadata) == 1 and not route.inference
    request = route.metadata[0]
    assert str(request.url) == "https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes"
    assert request.headers["Authorization"] == "Bearer synthetic-deepinfra-key"
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "vendor/vision"
    assert len(route.metadata) == 1 and len(route.inference) == 1
    sent = route.inference[0]
    assert str(sent.url) == "https://api.deepinfra.com/v1/openai/chat/completions"
    assert json.loads(sent.content)["model"] == "vendor/vision"
    assert "provider" not in json.loads(sent.content)


def test_explicit_model_bypasses_catalog(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "chosen/vision")
    response = route.client.post(DESCRIBE, json=approved_body(route))
    assert response.status_code == 200
    assert not route.metadata and len(route.inference) == 1
    assert json.loads(route.inference[0].content)["model"] == "chosen/vision"


def test_discovery_does_not_authorize_sending_images(route):
    body = approved_body(route)
    body["remote_ack"] = False
    assert route.client.post(DESCRIBE, json=body).status_code == 403
    assert len(route.metadata) == 1 and not route.inference


def test_explicit_refresh_revises_binding_and_old_request_cannot_send(route):
    body = approved_body(route)
    route.model = "vendor/new-vision"
    refreshed = route.client.get(STATUS, params={"refresh_catalog": "true"}).json()
    assert refreshed["configured"] and refreshed["model"] == route.model
    assert refreshed["binding"] != body["expected_binding"]
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert len(route.metadata) == 2 and not route.inference


def test_failed_refresh_does_not_leave_old_model_authorized(route):
    body = approved_body(route)
    route.catalog_failure = True
    status = route.client.get(STATUS, params={"refresh_catalog": "true"}).json()
    assert status["configured"] is False
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 503
    assert "private catalog error" not in response.text
    assert len(route.metadata) == 2 and not route.inference


def test_post_never_discovers_a_replacement_after_credential_rotation(route, monkeypatch):
    body = approved_body(route)
    monkeypatch.setenv("DEEPINFRA_API_KEY", "rotated-synthetic-key")
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 503
    assert len(route.metadata) == 1 and not route.inference


@pytest.mark.parametrize("retry", ["0", "1"])
@pytest.mark.parametrize("mutation", ["key", "model", "wire"])
def test_late_mutation_refuses_before_inference_transport(route, monkeypatch, retry, mutation):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    body = approved_body(route)

    def mutate(request):
        if mutation == "key":
            monkeypatch.setenv("DEEPINFRA_API_KEY", "rotated-synthetic-key")
        elif mutation == "model":
            monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "other/vision")
        else:
            payload = json.loads(request.content)
            payload["model"] = "other/vision"
            request._content = json.dumps(payload).encode()

    route.after_gate = mutate
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert len(route.metadata) == 1 and not route.inference


def test_empty_retry_keeps_same_selected_model_and_does_not_refetch(route, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    route.empty_first = True
    assert route.client.post(DESCRIBE, json=approved_body(route)).status_code == 200
    assert len(route.metadata) == 1 and len(route.inference) == 2
    assert route.inference[0].content == route.inference[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["describe", "screen", "telegram"])
async def test_catalog_selection_does_not_enable_remote_local_only_consumers(route, consumer):
    from agents.core.channels.media_reader import InboundImageReader
    from tests.test_h513_interactive_local_vision import invoke

    approved_body(route)
    if consumer == "telegram":
        assert InboundImageReader.from_env().refusal().reason == "local_vlm_not_proven_local"
    else:
        assert (await invoke(consumer)).status_code == 503
    assert len(route.metadata) == 1 and not route.inference


@pytest.mark.parametrize("retry", ["0", "1"])
def test_duplicate_model_at_last_hook_cannot_bypass_binding(route, monkeypatch, retry):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    body = approved_body(route)

    def mutate(request):
        request._content = b'{"model":"other/vision",' + request.content[1:]

    route.after_gate = mutate
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert not route.inference


def test_default_no_retry_response_is_bounded(route):
    route.response = lambda: httpx.Response(200, json={"choices": [
        {"message": {"content": "x" * (vlm.MAX_VISION_RESPONSE_BYTES + 1)}}]})
    response = route.client.post(DESCRIBE, json=approved_body(route))
    assert response.status_code == 502
    assert response.json()["reason"] == "vlm_generation_failed"
    assert len(route.inference) == 1


def test_default_no_retry_stream_obeys_total_deadline(route, monkeypatch):
    closed = []

    class SlowResponse(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.1)
            yield b'{"choices":[{"message":{"content":"late answer"}}]}'

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(vlm, "VISION_GENERATION_TIMEOUT", 0.01)
    route.response = lambda: httpx.Response(200, stream=SlowResponse())
    response = route.client.post(DESCRIBE, json=approved_body(route))
    assert response.status_code == 502
    assert len(route.inference) == 1 and closed
