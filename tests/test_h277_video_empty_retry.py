"""H277 signed video consumer retry for structurally valid empty responses."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core.llm import data_handling as dh
from agents.core.llm.egress import llm_async_client
from agents.core.llm.video_native import VideoNativeEmpty, VideoNativeRefused, gemini_video_answer
from agents.core.video_analysis import VideoHTTPClient
from tests.test_h277_video_analysis import rig
from tests.test_h277_video_gemini import _grant, _local_gemini
from tests.test_h277_video_provider_chain import approved_run, local_fallback


def compatible(text, *, finish="stop"):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": finish, "message": {"content": text}}]})


def gemini(text):
    return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                                      "content": {"parts": [{"text": text}]}}]})


@pytest.mark.parametrize(("raw", "expected"), [
    (None, 0), ("", 0), ("   ", 0), ("0", 0), (" 1 ", 1),
])
def test_empty_budget_accepts_only_canonical_small_values(raw, expected):
    from agents.core.llm.video_retry import resolve_video_empty_retry_count

    env = {} if raw is None else {"JARVIS_ROLE_VIDEO_EMPTY_RETRIES": raw}
    assert resolve_video_empty_retry_count(env) == expected


@pytest.mark.parametrize("raw", ["2", "01", "+1", "\t1", "1\n", "１", "x" * 17, 1, True])
def test_empty_budget_invalid_values_are_sanitized(raw):
    from agents.core.llm.video_retry import (
        VideoEmptyRetryConfigError,
        resolve_video_empty_retry_count,
    )

    with pytest.raises(VideoEmptyRetryConfigError, match="invalid video empty retry setting") as exc:
        resolve_video_empty_retry_count({"JARVIS_ROLE_VIDEO_EMPTY_RETRIES": raw})
    assert repr(raw) not in str(exc.value)


@pytest.mark.parametrize("parts", [
    [{"text": " "}], [{"text": "reasoning", "thought": True}],
    [{"text": "", "thought": True}, {"text": "\n"}],
])
def test_gemini_valid_empty_is_typed_only_after_native_checks(parts):
    with pytest.raises(VideoNativeEmpty):
        gemini_video_answer({"candidates": [{"finishReason": "STOP", "content": {"parts": parts}}]})


@pytest.mark.parametrize("payload", [
    {"candidates": []},
    {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": ""}]}}]},
    {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"functionCall": {"name": "tool"}, "thought": True}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"inline_data": {"data": "AA=="}}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "", "thought": 1}]}}]},
    {"candidates": [{"finishReason": "STOP", "error": {"message": "private"}, "content": {"parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"error": {"message": "private"}, "parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "", "error": {"message": "private"}}]}}]},
])
def test_gemini_invalid_empty_never_gets_typed_recovery(payload):
    with pytest.raises(VideoNativeRefused) as exc:
        gemini_video_answer(payload)
    assert type(exc.value) is VideoNativeRefused


@pytest.mark.asyncio
async def test_signed_compatible_primary_empty_restarts_full_consumer(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent, clients = [], []

    def respond(request):
        sent.append(request)
        return compatible("  ") if len(sent) == 1 else compatible("Recovered.")

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Recovered."
    assert result["result"]["attempts"] == [{
        "target_id": "role:video_analysis", "category": "empty_output",
        "consumer_call": 1, "attempt": 1}]
    assert result["result"]["chosen_call"] == 2
    assert result["result"]["chosen_attempt"] == 1
    assert len(sent) == len(clients) == 2
    assert all(client.is_closed for client in clients)
    assert sent[0].content == sent[1].content and sent[0].url == sent[1].url


@pytest.mark.asyncio
async def test_signed_gemini_primary_empty_restarts_with_same_native_wire(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        return gemini(" ") if len(sent) == 1 else gemini("Recovered Gemini.")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Recovered Gemini."
    assert result["result"]["chosen_call"] == 2
    assert [request.url.port for request in sent] == [8420, 8420]
    assert sent[0].content == sent[1].content
    assert all(request.headers.get("x-goog-api-key") == "synthetic-gemini-key" for request in sent)


@pytest.mark.asyncio
async def test_empty_fallback_restarts_from_primary(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    local_fallback(monkeypatch)
    sent = []

    def respond(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(429)
        return compatible("") if len(sent) == 2 else compatible("Primary recovered.")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in sent] == [1234, 1235, 1234]
    assert result["result"]["chosen_route"] == "role:video_analysis"
    assert result["result"]["chosen_call"] == 2
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "rate_limit", "consumer_call": 1, "attempt": 1},
        {"target_id": "role:video_fallback_1", "category": "empty_output", "consumer_call": 1, "attempt": 1},
    ]


@pytest.mark.asyncio
async def test_second_empty_is_terminal_and_never_starts_third_call(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def respond(request):
        sent.append(request)
        return compatible("")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 2
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "empty_output", "consumer_call": 1, "attempt": 1},
        {"target_id": "role:video_analysis", "category": "empty_output", "consumer_call": 2, "attempt": 1},
    ]
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_primary_transient_budget_is_fresh_in_each_consumer_call(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    sent, clients = [], []

    def respond(request):
        sent.append(request)
        if len(sent) in (1, 3):
            raise httpx.ConnectError("synthetic private transport error", request=request)
        return compatible("") if len(sent) == 2 else compatible("Recovered after both budgets.")

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Recovered after both budgets."
    assert result["result"]["chosen_call"] == 2
    assert result["result"]["chosen_attempt"] == 2
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "connection", "consumer_call": 1, "attempt": 1},
        {"target_id": "role:video_analysis", "category": "empty_output", "consumer_call": 1, "attempt": 2},
        {"target_id": "role:video_analysis", "category": "connection", "consumer_call": 2, "attempt": 1},
    ]
    assert len(sent) == len(clients) == 4
    assert all(client.is_closed for client in clients)
    assert len({request.content for request in sent}) == 1


@pytest.mark.asyncio
async def test_enabled_first_call_success_reports_provenance(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"] == {
        "ok": True, "analysis": "A synthetic clip.", "attempts": [],
        "chosen_route": "role:video_analysis", "chosen_provider": "lm-studio",
        "chosen_model": "local-video", "chosen_call": 1, "chosen_attempt": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", [
    {"message": {"content": ""}},
    {"finish_reason": "length", "message": {"content": ""}},
    {"finish_reason": "tool_calls", "message": {"content": ""}},
    {"finish_reason": "stop", "message": {"content": "", "tool_calls": [{"id": "tool"}]}},
    {"finish_reason": "stop", "message": {"content": "", "refusal": "private denial"}},
    {"finish_reason": "stop", "message": {"content": "", "reasoning_content": "private reasoning"}},
    {"finish_reason": "stop", "message": {"content": "", "reasoning_content": []}},
    {"finish_reason": "stop", "message": {"content": "", "reasoning": {}}},
    {"finish_reason": "stop", "message": {"content": "", "refusal": False}},
    {"finish_reason": "stop", "message": {"content": "", "tool_calls": False}},
    {"finish_reason": "stop", "message": {"content": "", "function_call": False}},
    {"finish_reason": "stop", "error": {"message": "private"}, "message": {"content": ""}},
    {"finish_reason": "stop", "message": {"content": "", "error": {"message": "private"}}},
    {"finish_reason": "stop", "message": {"content": []}},
    {"finish_reason": "stop", "message": {}},
])
async def test_compatible_invalid_or_nonempty_reasoning_never_restarts(rig, monkeypatch, choice):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [choice]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"candidates": [{"finishReason": "STOP", "error": {"message": "private"},
                     "content": {"parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {
        "error": {"message": "private"}, "parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": "", "error": {"message": "private"}}]}}]},
])
async def test_gemini_nested_error_envelope_never_restarts(rig, monkeypatch, payload):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    sent = []

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(
            lambda request: sent.append(request) or httpx.Response(200, json=payload)), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_successful_206_empty_is_eligible(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def respond(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(206, json={"choices": [{"finish_reason": "stop",
                                                          "message": {"content": None}}]})
        return compatible("Recovered.")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_setting_flip_after_signed_approval_refuses_before_model_send(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    args = {"video_url": str(rig.source), "question": "What happens?"}
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": args})
    assert proposal["reason"] == "approval_required", proposal
    approved_class = rig.queue.get(proposal["task_id"]).payload["class"]
    assert "full-chain empty restart" in rig.queue.get(proposal["task_id"]).payload["notice"].lower()
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "0")
    assert rig.video.classifier(rig.video.preflight(args))["class"] != approved_class
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_setting_flip_on_first_client_close_blocks_restart(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(
            lambda request: sent.append(request) or compatible("")), **kw)
        old_close = client._transport.aclose

        async def flip_on_close():
            monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "0")
            await old_close()

        client._transport.aclose = flip_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1


def test_long_notice_describes_both_budgets_and_stays_bounded(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    fallbacks = []
    for slot in range(1, 5):
        fallbacks.append({"provider": "lm-studio", "model": f"model-{slot}-" + "x" * 220,
                          "base_url": f"http://127.0.0.1:{1234 + slot}/v1"})
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps(fallbacks))
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    notice = rig.video.classifier(args)["notice"]
    assert len(notice) <= 200
    assert "full-chain empty restart once" in notice
    assert "primary transient retry once" in notice
    assert "1L:" in notice and "5L:" in notice


def test_classifier_notice_uses_same_captured_policy_as_signed_class(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    original = rig.video._binding
    expected = rig.video.classifier(args)["class"]

    def flip_after_binding(*a, **kw):
        bound = original(*a, **kw)
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "0")
        return bound

    monkeypatch.setattr(rig.video, "_binding", flip_after_binding)
    labels = rig.video.classifier(args)
    assert labels["class"] == expected
    assert "full-chain empty restart once" in labels["notice"]


@pytest.mark.asyncio
async def test_url_source_is_fetched_once_across_consumer_retry(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    gets, posts = [], []

    def fetch(request):
        gets.append(request)
        return httpx.Response(200, content=b"one prepared synthetic clip")

    rig.video.source_client_factory = lambda plugin, **kw: VideoHTTPClient(
        plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
        transport_factory=lambda target: httpx.MockTransport(fetch), **kw)

    def respond(request):
        posts.append(request)
        return compatible("") if len(posts) == 1 else compatible("From prepared source.")

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
    assert result["result"]["chosen_call"] == 2


@pytest.mark.asyncio
async def test_consent_revocation_on_cleanup_blocks_empty_restart(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    _local_gemini(monkeypatch)
    owner_router, target, audit = _grant(rig, monkeypatch)
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(
            lambda request: sent.append(request) or gemini("")), **kw)
        old_close = client._transport.aclose

        async def revoke_on_close():
            dh.acknowledge(owner_router, target.provider, False, dh.role_target_scope(target),
                           audit, target=target.target_id)
            await old_close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_kernel_revocation_on_cleanup_blocks_empty_restart(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(
            lambda request: sent.append(request) or compatible("")), **kw)
        old_close = client._transport.aclose

        async def revoke_on_close():
            rig.video.kernel_check = lambda _args, _task: "synthetic denial"
            await old_close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_five_route_chain_never_exceeds_two_full_calls(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "lm-studio", "model": f"fallback-{slot}",
         "base_url": f"http://127.0.0.1:{1234 + slot}/v1"}
        for slot in range(1, 5)
    ]))
    sent, clients = [], []

    def respond(request):
        sent.append(request)
        if request.url.port == 1234:
            raise httpx.ConnectError("private transient", request=request)
        return compatible("") if request.url.port == 1238 else httpx.Response(429)

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [1234, 1234, 1235, 1236, 1237, 1238] * 2
    assert len(clients) == 12 and all(client.is_closed for client in clients)
    assert len(result["result"]["attempts"]) == 12
    assert [entry["consumer_call"] for entry in result["result"]["attempts"]] == [1] * 6 + [2] * 6


@pytest.mark.asyncio
async def test_one_total_deadline_prevents_late_empty_restart(rig, monkeypatch):
    from agents.core import video_analysis as video

    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    monkeypatch.setattr(video, "VIDEO_EXECUTION_TIMEOUT", 0.02)
    sent = []

    async def respond(request):
        sent.append(request)
        await asyncio.sleep(0.2)
        return compatible("")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert len(sent) <= 1


@pytest.mark.asyncio
async def test_cancellation_closes_client_without_empty_restart(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
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
        old_close = client._transport.aclose

        async def observe_close():
            closed.append(True)
            await old_close()

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
