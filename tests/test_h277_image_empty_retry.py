"""H277 governed image empty-output recovery on native HTTPX consumers."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import httpx
import pytest

from agents.core import settings_db
from agents.core.cameras import vlm as camera_vlm
from agents.core.channels.media_reader import InboundImageReader
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vision_retry import RETRY_NOTICE
from agents.core.routers import composer_vision, multimodal
from tests.test_h31_camera_pipeline import _event, _frame
from tests.test_h513_camera_policy import grant as camera_grant
from tests.test_h513_camera_policy import native as camera_native
from tests.test_h513_camera_policy import state as camera_state
from tests.test_h513_interactive_local_vision import PNG, invoke, rig
from tests.test_h513_unattended_media_reader import grant as media_grant
from tests.test_h513_unattended_media_reader import state as media_state

NATIVE = vlm.VLMBackend


def reply(content, *, finish="stop"):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish,
                                                   "message": {"content": content}}]})


def install_sequence(monkeypatch, built, responses):
    sent = []

    def handle(request):
        sent.append(request)
        return responses[min(len(sent) - 1, len(responses) - 1)]

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(client=client, **kwargs)
        built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    return sent


@pytest.mark.asyncio
async def test_local_describe_valid_empty_recovers_on_same_prepared_image(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = []

    def handle(request):
        sent.append(request)
        return reply("") if len(sent) == 1 else reply("Recovered image.")

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(client=client, **kwargs)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    body = json.loads(response.body)
    assert response.status_code == 200 and body["response"] == "Recovered image."
    assert body["empty_retries"] == 1
    assert len(sent) == 2 and sent[0].content == sent[1].content
    assert state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_screen_reflex_legacy_wrapper_recovers_only_in_governed_scope(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = install_sequence(monkeypatch, state.built, [reply(""), reply("Recovered screen.")])
    response = await invoke("screen")
    body = json.loads(response.body)
    assert response.status_code == 200 and body["ok"] is True
    assert body["empty_retries"] == 1
    assert len(sent) == 2 and sent[0].content == sent[1].content


@pytest.mark.asyncio
async def test_remote_composer_acknowledged_image_recovers(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    config = vlm.VLMConfig("custom", "https://vision.example/v1", "vision", "synthetic-key", False)
    monkeypatch.setattr(vlm, "resolve_vlm_config", lambda: config)
    public = composer_vision.public_config(config)
    built = []
    sent = install_sequence(monkeypatch, built, [reply(""), reply("Recovered remote image.")])
    body = composer_vision.ComposerVisionBody(
        prompt="What is shown?", images=["data:image/png;base64," + PNG],
        expected_destination=public["destination"], expected_binding=public["binding"],
        remote_ack=True)
    response = await composer_vision.composer_describe(body)
    result = json.loads(response.body)
    assert response.status_code == 200 and result["response"] == "Recovered remote image."
    assert result["empty_retries"] == 1
    assert len(sent) == 2 and sent[0].content == sent[1].content
    assert all(request.headers["Authorization"] == "Bearer synthetic-key" for request in sent)
    assert built[0].client.is_closed


@pytest.mark.asyncio
async def test_unattended_media_reader_recovers_under_role_grant(media_state, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    media_grant(media_state)
    sent = install_sequence(monkeypatch, media_state.built,
                            [reply(""), reply("Recovered private image.")])
    out = await InboundImageReader.from_env()(b"synthetic image")
    assert out.ok and "Recovered private image." in out.text
    assert len(sent) == 2 and sent[0].content == sent[1].content
    assert media_state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_camera_description_recovers_under_role_grant(camera_state, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    camera_grant(camera_state)
    sent = install_sequence(monkeypatch, camera_state.wire.built,
                            [reply(""), reply('{"description":"An anonymous person is visible."}')])
    out = await camera_native(camera_state).describe(_frame(), _event())
    assert out == "An anonymous person is visible."
    assert len(sent) == 2 and sent[0].content == sent[1].content
    assert camera_state.wire.built[0].client.is_closed


@pytest.mark.parametrize(("raw", "expected"), [
    (None, 0), ("", 0), ("   ", 0), ("0", 0), (" 1 ", 1),
])
def test_strict_empty_retry_setting_accepts_only_zero_or_one(raw, expected):
    from agents.core.llm.vision_retry import resolve_vision_empty_retries

    env = {} if raw is None else {"JARVIS_ROLE_VISION_EMPTY_RETRIES": raw}
    assert resolve_vision_empty_retries(env) == expected


@pytest.mark.parametrize("raw", ["2", "01", "+1", "\t1", "1\n", "１", "x" * 17, 1, True])
def test_invalid_empty_retry_setting_is_sanitized(raw):
    from agents.core.llm.vision_retry import VisionRetryConfigError, resolve_vision_empty_retries

    with pytest.raises(VisionRetryConfigError, match="invalid vision empty retry setting") as exc:
        resolve_vision_empty_retries({"JARVIS_ROLE_VISION_EMPTY_RETRIES": raw})
    assert repr(raw) not in str(exc.value)


@pytest.mark.asyncio
async def test_enabled_status_discloses_fixed_notice_and_default_has_no_extras(monkeypatch):
    config = vlm.VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", "vision", "", True)
    monkeypatch.setattr(vlm, "resolve_vlm_config", lambda: config)
    off = vp.describe(config)
    assert "empty_retries" not in off.public() and "retry_notice" not in off.public()
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    on = vp.describe(config)
    assert on.binding != off.binding
    assert on.public()["empty_retries"] == 1
    assert on.public()["retry_notice"] == RETRY_NOTICE
    status = json.loads((await multimodal.vlm_status()).body)
    assert status["empty_retries"] == 1 and status["retry_notice"] == RETRY_NOTICE


@pytest.mark.asyncio
async def test_media_grant_becomes_stale_when_budget_enabled(media_state, monkeypatch):
    media_grant(media_state)
    old = vp.describe_media_data_target()
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    new = vp.describe_media_data_target()
    assert old.binding != new.binding
    assert RETRY_NOTICE in new.note and len(new.note) <= 500
    out = await InboundImageReader.from_env()(b"synthetic image")
    assert not out.ok and media_state.built == []


@pytest.mark.asyncio
async def test_camera_grant_becomes_stale_when_budget_enabled(camera_state, monkeypatch):
    camera_grant(camera_state)
    old = vp.describe_camera_data_target(camera_state.orch)
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    new = vp.describe_camera_data_target(camera_state.orch)
    assert old.binding != new.binding
    assert RETRY_NOTICE in new.note and len(new.note) <= 500
    assert await camera_native(camera_state).describe(_frame(), _event()) is None
    assert camera_state.wire.built == []


@pytest.mark.asyncio
async def test_remote_ack_binding_stales_when_budget_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    config = vlm.VLMConfig("custom", "https://vision.example/v1", "vision", "synthetic-key", False)
    monkeypatch.setattr(vlm, "resolve_vlm_config", lambda: config)
    old = composer_vision.public_config(config)
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    new = composer_vision.public_config(config)
    assert old["binding"] != new["binding"]
    body = composer_vision.ComposerVisionBody(
        prompt="What is shown?", images=["data:image/png;base64," + PNG],
        expected_destination=old["destination"], expected_binding=old["binding"], remote_ack=True)
    response = await composer_vision.composer_describe(body)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_two_valid_empty_responses_keep_existing_sanitized_failure(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = install_sequence(monkeypatch, state.built, [reply(""), reply(" ")])
    response = await invoke("describe")
    body = json.loads(response.body)
    assert response.status_code == 502 and body["reason"] == "vision_inference_failed"
    assert len(sent) == 2 and "response" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [
    reply("", finish="length"),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": "", "reasoning_content": "private thought"}}]}),
    httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": "", "tool_calls": [{"id": "tool"}]}}]}),
    httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": "", "error": {"message": "private"}}}]}),
    httpx.Response(400, json={"error": {"message": "private"}}),
    httpx.Response(200, text="not json"),
    httpx.Response(200, content=b"x" * 512_001),
    reply("<think>private reasoning</think>"),
])
async def test_invalid_or_stripped_blank_never_retries(monkeypatch, first):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = install_sequence(monkeypatch, state.built, [first, reply("Should not be sent")])
    response = await invoke("describe")
    body = json.loads(response.body)
    assert response.status_code == 502 and body["ok"] is False
    assert len(sent) == 1 and "private" not in response.body.decode()


@pytest.mark.asyncio
async def test_first_attempt_body_mutation_cannot_change_retry(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = []

    def handle(request):
        sent.append(request)
        return reply("") if len(sent) == 1 else reply("Stable answer.")

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        original = client.stream

        @asynccontextmanager
        async def mutate_first_body(*args, **kw):
            body = kw["json"]
            async with original(*args, **kw) as response:
                yield response
            if len(sent) == 1:
                body["messages"][-1]["content"][0]["text"] = "mutated after send"

        client.stream = mutate_first_body
        backend = NATIVE(client=client, **kwargs)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    assert response.status_code == 200
    assert len(sent) == 2 and sent[0].content == sent[1].content
    assert b"mutated after send" not in sent[1].content


@pytest.mark.asyncio
async def test_late_request_hook_cannot_mutate_prepared_image_body(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = []

    def handle(request):
        sent.append(request)
        return reply("Should not be sent")

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))

        async def mutate_after_recorder(request):
            body = json.loads(request.content)
            body["messages"][-1]["content"][0]["text"] = "changed after policy check"
            request._content = json.dumps(body).encode()

        client.event_hooks["request"].append(mutate_after_recorder)
        backend = NATIVE(client=client, **kwargs)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    assert response.status_code == 409
    assert sent == []


@pytest.mark.asyncio
async def test_setting_revocation_during_response_cleanup_blocks_retry(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent = []

    def handle(request):
        sent.append(request)
        response = reply("")
        original = response.aclose

        async def close_and_revoke():
            await original()
            monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "0")

        response.aclose = close_and_revoke
        return response

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(client=client, **kwargs)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    assert response.status_code == 409 and len(sent) == 1


@pytest.mark.asyncio
async def test_second_physical_send_inside_one_attempt_is_refused(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    state = rig(monkeypatch)
    sent, built = [], []

    async def handle(request):
        sent.append(request)
        with suppress(Exception):
            await built[0].client.post("/chat/completions", json=json.loads(request.content),
                                       headers=built[0]._headers())
        return reply("")

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(client=client, **kwargs)
        built.append(backend)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    assert response.status_code == 409 and len(sent) == 1


@pytest.mark.asyncio
async def test_inherited_child_cannot_send_after_vision_scope_closes(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    from agents.core.commands import Principal
    from agents.core.llm.data_handling import DataHandlingRefused

    config = vlm.VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", "vision", "", True)
    sent = []
    client = llm_async_client("vlm", base_url=config.base_url, auth=httpx.Auth(), trust_env=False,
                              transport=httpx.MockTransport(
                                  lambda request: sent.append(request) or reply("Too late")))
    backend = NATIVE(config.base_url, client=client, composer_auth=True)
    release = asyncio.Event()

    async def late():
        await release.wait()
        return await backend.generate_vision_checked(config.model, "late", images=[b"fake image"])

    try:
        with vp.composer_request_scope(config, backend, resolve_config=lambda: config,
                                       remote_ack=False, principal=Principal(channel="web")):
            child = asyncio.create_task(late())
        release.set()
        with pytest.raises(DataHandlingRefused):
            await child
        assert sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_parallel_scopes_keep_each_backend_and_model_independent(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    from agents.core.commands import Principal

    entered, release = asyncio.Event(), asyncio.Event()
    first_arrivals = []
    bodies = {"vision-one": [], "vision-two": []}

    async def run(model):
        config = vlm.VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", model, "", True)

        async def handle(request):
            bodies[model].append(json.loads(request.content))
            if len(bodies[model]) == 1:
                first_arrivals.append(model)
                if len(first_arrivals) == 2:
                    entered.set()
                await release.wait()
                return reply("")
            return reply(f"Answer for {model}.")

        client = llm_async_client("vlm", base_url=config.base_url, auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(config.base_url, client=client, composer_auth=True)
        try:
            with vp.composer_request_scope(config, backend, resolve_config=lambda: config,
                                           remote_ack=False, principal=Principal(channel="web")):
                return await backend.generate_vision_checked(model, "what?", images=[b"synthetic"])
        finally:
            await backend.aclose()

    tasks = [asyncio.create_task(run(model)) for model in bodies]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert set(first_arrivals) == set(bodies)
        release.set()
        assert await asyncio.gather(*tasks) == ["Answer for vision-one.", "Answer for vision-two."]
        assert all(len(requests) == 2 and requests[0] == requests[1]
                   and all(body["model"] == model for body in requests)
                   for model, requests in bodies.items())
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_one_generation_deadline_prevents_second_model_send(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    monkeypatch.setattr(vlm, "VISION_GENERATION_TIMEOUT", 0.02)
    state = rig(monkeypatch)
    sent = []

    async def handle(request):
        sent.append(request)
        await asyncio.sleep(0.2)
        return reply("")

    def factory(**kwargs):
        client = llm_async_client("vlm", base_url=kwargs["base_url"], auth=httpx.Auth(),
                                  trust_env=False, transport=httpx.MockTransport(handle))
        backend = NATIVE(client=client, **kwargs)
        state.built.append(backend)
        return backend

    monkeypatch.setattr(vlm, "VLMBackend", factory)
    response = await invoke("describe")
    assert response.status_code == 502 and len(sent) <= 1
    assert state.built[0].client.is_closed
