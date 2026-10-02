"""Signed native video retry stays on the approved primary route."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core.llm import data_handling as dh
from agents.core.llm.egress import llm_async_client
from agents.core.video_analysis import VideoHTTPClient
from tests.test_h277_video_analysis import rig
from tests.test_h277_video_gemini import _grant, _local_gemini
from tests.test_h277_video_provider_chain import approved_run, local_fallback


@pytest.mark.parametrize(("raw", "expected"), [
    (None, 0), ("", 0), ("   ", 0), ("0", 0), (" 1 ", 1),
])
def test_retry_setting_accepts_only_the_fixed_small_budget(raw, expected):
    from agents.core.llm.video_retry import resolve_video_retry_count

    env = {} if raw is None else {"JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES": raw}
    assert resolve_video_retry_count(env) == expected


@pytest.mark.parametrize("raw", ["2", "01", "+1", "\t1", "1\n", "１", "x" * 17, 1, True])
def test_retry_setting_refuses_ambiguous_values(raw):
    from agents.core.llm.video_retry import VideoRetryConfigError, resolve_video_retry_count

    with pytest.raises(VideoRetryConfigError) as exc:
        resolve_video_retry_count({"JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES": raw})
    assert str(exc.value) == "invalid video retry setting"
    assert repr(raw) not in str(exc.value)


@pytest.mark.parametrize(("status", "expected"), [
    (408, True), (500, True), (599, True), (429, False), (400, False),
    (600, False), (True, False), (500.0, False), ("500", False),
])
def test_only_exact_transient_http_statuses_qualify(status, expected):
    from agents.core.llm.video_retry import native_retryable_status

    assert native_retryable_status(status) is expected


@pytest.mark.asyncio
async def test_primary_connection_retries_once_then_uses_existing_fallback(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.port == 1234:
            raise httpx.ConnectError("private synthetic failure", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Recovered backup."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in sent] == [1234, 1234, 1235]
    assert result["result"]["analysis"] == "Recovered backup."
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "connection", "attempt": 1},
        {"target_id": "role:video_analysis", "category": "connection", "attempt": 2},
    ]
    assert result["result"]["chosen_route"] == "role:video_fallback_1"
    assert result["result"]["chosen_attempt"] == 1
    assert "private synthetic failure" not in json.dumps(result)


@pytest.mark.asyncio
async def test_primary_http_503_retries_once_without_provider_fallback(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(503, text="private provider body")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [1234, 1234]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "transient_http", "attempt": 1},
        {"target_id": "role:video_analysis", "category": "transient_http", "attempt": 2},
    ]
    assert "private provider body" not in json.dumps(result)


@pytest.mark.asyncio
async def test_primary_once_success_has_provenance_and_fresh_client(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    clients = []
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            raise httpx.RemoteProtocolError("private stream reset", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Recovered primary."}}]})

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Recovered primary."
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "connection", "attempt": 1}]
    assert result["result"]["chosen_route"] == "role:video_analysis"
    assert result["result"]["chosen_attempt"] == 2
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert clients[0].is_closed and clients[1].is_closed
    assert bodies[0] == bodies[1]


@pytest.mark.asyncio
async def test_enabled_policy_change_invalidates_signed_pending_task(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    args = {"video_url": str(rig.source), "question": "What happens?"}
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": args})
    assert proposal["reason"] == "approval_required", proposal
    approved_class = rig.queue.get(proposal["task_id"]).payload["class"]
    assert "retry" in rig.queue.get(proposal["task_id"]).payload["notice"].lower()
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "0")
    assert rig.video.classifier(rig.video.preflight(args))["class"] != approved_class
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_timeout_and_rate_limit_bypass_primary_retry(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.port == 1234:
            return httpx.Response(429, json={"error": {"message": "too many requests"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Backup."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in sent] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "rate_limit", "attempt": 1}]


@pytest.mark.asyncio
async def test_default_zero_still_refuses_generic_http_without_retry(rig, monkeypatch):
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", raising=False)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(503, text="internal")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1
    assert "attempts" not in result["result"]


@pytest.mark.asyncio
async def test_default_zero_chain_generic_http_keeps_legacy_refusal_shape(rig, monkeypatch):
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", raising=False)
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(503, text="private provider body")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [1234]
    assert result["result"] == {"ok": False, "reason": "video_analysis_refused"}


@pytest.mark.asyncio
async def test_gemini_primary_http_408_retries_same_native_wire(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(408, text="private response")
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": "Gemini recovered."}]}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Gemini recovered."
    assert result["result"]["chosen_attempt"] == 2
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "transient_http", "attempt": 1}]
    assert len(sent) == 2
    assert sent[0].url == sent[1].url
    assert all(request.headers.get("x-goog-api-key") == "synthetic-gemini-key" for request in sent)
    assert json.loads(sent[0].content) == json.loads(sent[1].content)
    assert "private response" not in json.dumps(result)


@pytest.mark.asyncio
async def test_fallback_connection_never_gets_second_send(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.port == 1234:
            return httpx.Response(429)
        raise httpx.ConnectError("private backup failure", request=request)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "rate_limit", "attempt": 1},
        {"target_id": "role:video_fallback_1", "category": "connection", "attempt": 1},
    ]


@pytest.mark.asyncio
async def test_close_time_policy_drift_blocks_second_primary_send(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            sent.append(request) or httpx.Response(503))), **kw)
        original_close = client._transport.aclose

        async def change_on_close():
            monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "0")
            await original_close()

        client._transport.aclose = change_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_close_time_consent_revocation_blocks_second_primary_send(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    _local_gemini(monkeypatch)
    owner_router, target, audit = _grant(rig, monkeypatch)
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            sent.append(request) or httpx.Response(503))), **kw)
        original_close = client._transport.aclose

        async def revoke_on_close():
            dh.acknowledge(owner_router, target.provider, False, dh.role_target_scope(target),
                           audit, target=target.target_id)
            await original_close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_enabled_url_source_is_fetched_once_across_primary_retry(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    gets, posts = [], []

    def fetch(request):
        gets.append(request)
        return httpx.Response(200, content=b"one prepared video")

    rig.video.source_client_factory = lambda plugin, **kw: VideoHTTPClient(
        plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
        transport_factory=lambda target: httpx.MockTransport(fetch), **kw)

    def respond(request):
        posts.append(request)
        if len(posts) == 1:
            raise httpx.ConnectError("synthetic", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "From URL."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    source = "https://video.example/clip.mp4"
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": source, "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] == "ok", result
    assert len(gets) == 1 and len(posts) == 2
    assert posts[0].content == posts[1].content


@pytest.mark.asyncio
async def test_invalid_retry_setting_refuses_proposal_before_send(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "2")
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] != "approval_required"
    assert rig.requests == []


@pytest.mark.asyncio
async def test_owned_attempt_timeout_goes_directly_to_fallback(rig, monkeypatch):
    from agents.core import video_analysis as video

    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    monkeypatch.setattr(video, "VIDEO_MODEL_ATTEMPT_TIMEOUT", 0.02)
    local_fallback(monkeypatch)
    sent = []

    async def respond(request):
        sent.append(request)
        if request.url.port == 1234:
            await asyncio.sleep(0.2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Backup."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in sent] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "timeout", "attempt": 1}]


@pytest.mark.asyncio
async def test_retry_uses_fresh_mutable_body_after_first_close(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    sent = []
    captured = {}

    def respond(request):
        sent.append(request)
        if len(sent) == 1:
            raise httpx.ConnectError("synthetic", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Fresh."}}]})

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        if not sent:
            original_stream = client.stream
            original_close = client._transport.aclose

            def stream(*args, **kwargs):
                captured["body"] = kwargs["json"]
                return original_stream(*args, **kwargs)

            async def mutate_on_close():
                captured["body"]["messages"][0]["content"][0]["text"] = "changed after send"
                await original_close()

            client.stream = stream
            client._transport.aclose = mutate_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert len(sent) == 2
    first = json.loads(sent[0].content)["messages"][0]["content"][0]["text"]
    second = json.loads(sent[1].content)["messages"][0]["content"][0]["text"]
    assert first == second
    assert captured["body"]["messages"][0]["content"][0]["text"] == "changed after send"


@pytest.mark.asyncio
async def test_total_deadline_stops_retry_after_first_send(rig, monkeypatch):
    from agents.core import video_analysis as video

    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    monkeypatch.setattr(video, "VIDEO_EXECUTION_TIMEOUT", 0.02)
    sent = []

    async def respond(request):
        sent.append(request)
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Too late."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) <= 1


def test_enabled_five_lane_notice_names_each_candidate_within_limit(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "lm-studio", "model": "synthetic-long-model-" + "x" * 180 + str(slot),
         "base_url": f"http://127.0.0.1:{1234 + slot}/private/native/v1"}
        for slot in range(1, 5)
    ]))
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    notice = rig.video.classifier(args)["notice"]
    assert len(notice) <= 200
    assert "primary retry once" in notice
    assert all(f"{slot}L:" in notice for slot in range(1, 6))
    assert "lm=LM Studio" in notice
    assert "/private/native" not in notice


def test_enabled_five_lane_mixed_notice_names_gemini_and_compatible(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "openai-compatible", "model": "compatible-" + "x" * 170,
         "base_url": "http://127.0.0.1:1235/v1"},
        {"provider": "gemini", "model": "gemini-2.5-flash",
         "base_url": "http://127.0.0.1:8420/v1beta"},
        {"provider": "lm-studio", "model": "local-" + "x" * 180,
         "base_url": "http://127.0.0.1:1237/v1"},
        {"provider": "openai-compatible", "model": "compatible-" + "y" * 170,
         "base_url": "http://127.0.0.1:1238/v1"},
    ]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "synthetic-gemini-key")
    _grant(rig, monkeypatch, "role:video_fallback_1")
    _grant(rig, monkeypatch, "role:video_fallback_2", initialize=False)
    _grant(rig, monkeypatch, "role:video_fallback_4", initialize=False)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    notice = rig.video.classifier(args)["notice"]
    assert len(notice) <= 200
    assert "primary retry once" in notice
    assert "oc=OpenAI-compatible" in notice
    assert "g=Gemini" in notice
    assert all(f"{slot}L:" in notice for slot in range(1, 6))


@pytest.mark.asyncio
async def test_external_cancellation_closes_first_client_without_retry(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    approved = rig.queue.get(proposal["task_id"])
    rig.video.approved_task = lambda: approved
    rig.video.execution_check = lambda _task: True
    rig.video.kernel_check = lambda _args, _task: None
    started = asyncio.Event()
    sent, closed = [], []

    async def wait_forever(request):
        sent.append(request)
        started.set()
        await asyncio.Event().wait()

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(wait_forever), **kw)
        original_close = client._transport.aclose

        async def observe_close():
            closed.append(True)
            await original_close()

        client._transport.aclose = observe_close
        return client

    rig.video.model_client_factory = factory
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    execution = asyncio.create_task(rig.video.execute(args))
    await asyncio.wait_for(started.wait(), 1)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert len(sent) == len(closed) == 1


@pytest.mark.asyncio
async def test_enabled_auth_flow_cannot_turn_one_attempt_into_two_sends(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    class FreshRetry(httpx.Auth):
        def auth_flow(self, request):
            response = yield request
            if response.status_code == 401:
                yield httpx.Request(request.method, request.url, headers=request.headers,
                                    content=request.content)

    def respond(request):
        sent.append(request)
        return httpx.Response(401)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, auth=FreshRetry(), transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [1234]


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_kind", ["request", "response"])
async def test_enabled_hook_transport_lookalike_never_becomes_retry(rig, monkeypatch, hook_kind):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    local_fallback(monkeypatch)
    sent, clients = [], []

    async def fail_hook(_message):
        raise httpx.ConnectError("hook-owned synthetic failure")

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Withhold."}}]})

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond),
                                  event_hooks={hook_kind: [fail_hook]}, **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == (0 if hook_kind == "request" else 1)
    assert len(clients) == 1
    assert "Withhold." not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"candidates": []},
    {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "private", "thought": True}]}}]},
])
async def test_enabled_empty_or_blocked_success_never_retries(rig, monkeypatch, payload):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json=payload)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [8420]
    assert "private" not in json.dumps(result)
