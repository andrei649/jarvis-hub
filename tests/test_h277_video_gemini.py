"""Signed native Gemini video requests retain route, consent and wire authority."""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from agents.core import settings_db
from agents.core.llm import data_handling as dh
from agents.core.llm import model_roles, video_native
from agents.core.llm import video_policy as vp
from agents.core.llm.egress import llm_async_client
from agents.core.llm.video_routes import VideoRouteConfigError, resolve_video_fallbacks
from agents.core.video_analysis import VideoHTTPClient
from tests.test_h277_video_analysis import rig
from tests.test_h513_data_handling import Audit, router


def _local_gemini(monkeypatch, *, key="synthetic-gemini-key"):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "gemini")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "models/gemini-2.5-flash")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "http://127.0.0.1:8420/v1beta")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", key)


async def _approved(rig, *, source=None, allow_remote=False):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(source or rig.source), "question": "What happens?",
        "allow_remote": allow_remote}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    return rig.queue.get(proposal["task_id"]).result


def _grant(rig, monkeypatch, target_id=dh.VIDEO_TARGET, *, initialize=True):
    if initialize:
        monkeypatch.setattr(settings_db, "DB_PATH", rig.tmp / "gemini-consent.db")
        monkeypatch.setattr(settings_db, "_initialized", False)
        settings_db.init_db(force=True)
    target = vp.describe_video_data_target(target_id)
    owner_router, audit = router(), Audit()
    dh.acknowledge(owner_router, target.provider, True, dh.role_target_scope(target), audit,
                   target=target.target_id)
    return owner_router, target, audit


def _gemini_fallback(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "gemini", "model": "gemini-2.5-flash",
        "base_url": "http://127.0.0.1:8420/v1beta"}]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "fallback-key")


def test_explicit_gemini_uses_video_only_default_and_own_key(monkeypatch):
    env = {"JARVIS_ROLE_VIDEO_PROVIDER": "gemini", "JARVIS_ROLE_VIDEO_MODEL": "gemini-2.5-flash",
           "GEMINI_API_KEY": "global-key", "JARVIS_ROLE_VISION_PROVIDER": "bogus",
           "JARVIS_ROLE_VIDEO_KEY": "video-key"}
    route = model_roles.resolve_video_route(env)
    assert route.role.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert route.role.provider_id == "gemini" and route.inherited is False
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "gemini")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "global-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "bogus")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "video-key")
    target = vp.describe_video_data_target()
    assert target.request_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert target.authorization == "video-key"
    assert target.request_headers == {"x-goog-api-key": "video-key"}
    assert "video-key" not in repr(target)


@pytest.mark.parametrize("bad_model,bad_base", [
    ("../escape", "http://127.0.0.1:8420/v1beta"),
    ("gemini-2.5-flash", "https://api.openai.com/v1"),
    ("gemini-2.5-flash", "https://user@model.example/v1beta"),
    ("gemini-2.5-flash", "http://model.example/v1beta"),
])
def test_native_fallback_rejects_incompatible_model_or_base(bad_model, bad_base):
    env = {"JARVIS_ROLE_VIDEO_FALLBACKS": json.dumps([{
        "provider": "gemini", "model": bad_model, "base_url": bad_base}])}
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(env)


def test_primary_gemini_never_borrows_global_or_vision_key_even_when_keyless(monkeypatch):
    _local_gemini(monkeypatch, key="")
    monkeypatch.setenv("GEMINI_API_KEY", "global-secret")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "vision-secret")
    monkeypatch.setenv("JARVIS_VLM_KEY", "legacy-secret")
    target = vp.describe_video_data_target()
    assert target.authorization == ""
    assert target.request_headers == {}
    assert all(secret not in repr(target) for secret in ("global-secret", "vision-secret", "legacy-secret"))


@pytest.mark.parametrize("key", ["x" * 4097, "\nsecret", "secret\r", "key" + " " * 4094])
def test_primary_gemini_rejects_invalid_raw_dedicated_key(monkeypatch, key):
    _local_gemini(monkeypatch, key=key)
    with pytest.raises(vp.VideoPolicyRefused):
        vp.describe_video_data_target()


@pytest.mark.asyncio
async def test_signed_gemini_sends_exact_inline_video_and_only_scoped_header(rig, monkeypatch):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": "Native answer."}]}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Native answer."
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert request.headers.get("x-goog-api-key") == "synthetic-gemini-key"
    assert request.headers.get("Authorization") is None
    body = json.loads(request.content)
    assert body["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "video/mp4"
    assert base64.b64decode(body["contents"][0]["parts"][1]["inline_data"]["data"]) == rig.source.read_bytes()
    assert "messages" not in body


@pytest.mark.asyncio
async def test_compatible_rate_limit_reaches_only_approved_gemini_fallback(rig, monkeypatch):
    _gemini_fallback(monkeypatch)
    _grant(rig, monkeypatch, "role:video_fallback_1")
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.port == 1234:
            return httpx.Response(429)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": "Native fallback."}]}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig)
    assert result["status"] == "ok", result
    assert result["result"]["chosen_provider"] == "gemini"
    assert result["result"]["analysis"] == "Native fallback."
    assert [request.url.port for request in requests] == [1234, 8420]
    assert requests[1].headers.get("x-goog-api-key") == "fallback-key"
    assert requests[1].headers.get("Authorization") is None


@pytest.mark.asyncio
async def test_gemini_rate_limit_reaches_only_approved_compatible_fallback(rig, monkeypatch):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "backup", "base_url": "http://127.0.0.1:1235/v1"}]))
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.port == 8420:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Compatible fallback."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig)
    assert result["status"] == "ok", result
    assert result["result"]["chosen_provider"] == "lm-studio"
    assert result["result"]["analysis"] == "Compatible fallback."
    assert [request.url.port for request in requests] == [8420, 1235]
    assert requests[0].headers.get("x-goog-api-key") == "synthetic-gemini-key"
    assert requests[1].headers.get("x-goog-api-key") is None


@pytest.mark.asyncio
async def test_gemini_fallback_needs_its_own_consent(rig, monkeypatch):
    _local_gemini(monkeypatch)
    _gemini_fallback(monkeypatch)
    _grant(rig, monkeypatch)
    assert dh.role_target_scope(vp.describe_video_data_target()) != dh.role_target_scope(
        vp.describe_video_data_target("role:video_fallback_1"))
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    with pytest.raises(dh.DataHandlingRefused):
        rig.video.classifier(args)
    _grant(rig, monkeypatch, "role:video_fallback_1", initialize=False)
    assert rig.video.classifier(args)["class"].startswith("video.")


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [
    {"candidates": []},
    {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "secret", "thought": True}]}}]},
])
async def test_native_empty_blocked_or_thought_only_never_discloses_or_falls_back(rig, monkeypatch, malformed):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "backup", "base_url": "http://127.0.0.1:1235/v1"}]))
    requests = []
    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(200, json=malformed))), **kw)
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert "secret" not in json.dumps(result)
    assert [request.url.port for request in requests] == [8420]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["authorization", "extra-key", "duplicate-key", "size"])
async def test_native_final_hook_refuses_wrong_credentials_or_physical_size(rig, monkeypatch, mutation):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    requests = []

    async def mutate(request):
        if mutation == "authorization":
            request.headers["Authorization"] = "Bearer wrong"
        elif mutation == "extra-key":
            request.headers["x-goog-api-key"] = "wrong"
        elif mutation == "duplicate-key":
            request.headers = httpx.Headers(list(request.headers.multi_items()) +
                                           [("x-goog-api-key", "second")])
        else:
            request._content = request.content + b" " * 1000

    if mutation == "size":
        monkeypatch.setattr(vp, "GEMINI_VIDEO_MAX_REQUEST_BYTES", 800, raising=False)

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(200))), **kw)
        client.event_hooks["request"].append(mutate)
        return client

    rig.video.model_client_factory = factory
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert requests == []


@pytest.mark.asyncio
async def test_mixed_chain_native_size_refuses_before_compatible_send(rig, monkeypatch):
    _gemini_fallback(monkeypatch)
    _grant(rig, monkeypatch, "role:video_fallback_1")
    monkeypatch.setattr(video_native, "GEMINI_VIDEO_MAX_REQUEST_BYTES", 100)
    clients = []
    rig.video.model_client_factory = lambda backend, **kw: (clients.append(backend) or llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kw))
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert clients == []


def test_mixed_chain_rejects_matroska_before_intake(rig, monkeypatch):
    _gemini_fallback(monkeypatch)
    source = rig.tmp / "clip.mkv"
    source.write_bytes(b"synthetic")
    args = rig.video.preflight({"video_url": str(source), "question": "What?"})
    with pytest.raises(vp.VideoPolicyRefused, match="format"):
        rig.video.classifier(args)


@pytest.mark.asyncio
async def test_gemini_key_rotation_after_approval_refuses_before_transport(rig, monkeypatch):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "rotated-key")
    await rig.worker.tick()
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"
    assert rig.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("filename", "mime"), [
    ("clip.mov", "video/quicktime"), ("clip.avi", "video/avi"),
])
async def test_native_source_url_is_fetched_once_before_fallback(rig, monkeypatch, filename, mime):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "backup", "base_url": "http://127.0.0.1:1235/v1"}]))
    gets, posts = [], []

    def fetch(request):
        gets.append(request)
        return httpx.Response(200, content=b"url video bytes")

    rig.video.source_client_factory = lambda plugin, **kw: VideoHTTPClient(
        plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
        transport_factory=lambda target: httpx.MockTransport(fetch), **kw)

    def respond(request):
        posts.append(request)
        if request.url.port == 8420:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Backup."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig, source=f"https://video.example/{filename}")
    assert result["status"] == "ok", result
    assert len(gets) == 1 and len(posts) == 2
    native = json.loads(posts[0].content)["contents"][0]["parts"][1]["inline_data"]
    assert native["mime_type"] == mime
    assert base64.b64decode(native["data"]) == b"url video bytes"
    compatible_url = json.loads(posts[1].content)["messages"][0]["content"][1]["video_url"]["url"]
    assert compatible_url.startswith(f"data:{mime};base64,")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["key", "consent"])
async def test_native_close_time_authority_change_stops_before_fallback(rig, monkeypatch, change):
    _local_gemini(monkeypatch)
    owner_router, target, audit = _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "backup", "base_url": "http://127.0.0.1:1235/v1"}]))
    requests = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or (httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": "Withhold."}]}}]})
                if change == "consent" else httpx.Response(429)))), **kw)
        if backend == "gemini":
            original_close = client._transport.aclose

            async def rotate_on_close():
                if change == "key":
                    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "rotated")
                else:
                    dh.acknowledge(owner_router, target.provider, False, dh.role_target_scope(target),
                                   audit, target=target.target_id)
                await original_close()

            client._transport.aclose = rotate_on_close
        return client

    rig.video.model_client_factory = factory
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [8420]
    assert "Withhold." not in json.dumps(result)


@pytest.mark.asyncio
async def test_compatible_final_hook_refuses_added_gemini_header(rig):
    requests = []

    async def inject(request):
        request.headers["x-goog-api-key"] = "unapproved"

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(200))), **kw)
        client.event_hooks["request"].append(inject)
        return client

    rig.video.model_client_factory = factory
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert requests == []


def test_three_provider_compact_legend_names_gemini_within_limit(rig, monkeypatch):
    _gemini_fallback(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "gemini", "model": "g" * 180, "base_url": "http://127.0.0.1:8420/v1beta"},
        {"provider": "lm-studio", "model": "l" * 180, "base_url": "http://127.0.0.1:1235/v1"},
        {"provider": "openai-compatible", "model": "o" * 180, "base_url": "http://127.0.0.1:1236/v1"},
        {"provider": "lm-studio", "model": "z" * 180, "base_url": "http://127.0.0.1:1237/v1"}]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "")
    # The local Gemini candidate still needs its own persisted role consent.
    _grant(rig, monkeypatch, "role:video_fallback_1")
    _grant(rig, monkeypatch, "role:video_fallback_3", initialize=False)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    notice = rig.video.classifier(args)["notice"]
    assert len(notice) <= 200
    assert "Gemini" in notice
    assert "oc=OpenAI-compatible" in notice
    assert all(f"{slot}L:" in notice for slot in range(1, 6))
