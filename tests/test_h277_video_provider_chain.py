"""Signed video approval binds every configured native destination."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

from agents.core import safe_mode, settings_db
from agents.core.file_tools import FileScope
from agents.core.llm import data_handling as dh
from agents.core.llm import video_policy as vp
from agents.core.llm.egress import llm_async_client
from agents.core.video_analysis import VideoHTTPClient
from tests.test_h277_video_analysis import rig


def local_fallback(monkeypatch, *, model="backup-video", port=1235):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": model,
        "base_url": f"http://127.0.0.1:{port}/v1",
    }]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "synthetic-backup-key")


def remote_fallback(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "openai-compatible", "model": "remote-video",
        "base_url": "https://remote.example/private/native/v1",
    }]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "synthetic-remote-secret")


def grant_remote(rig, monkeypatch):
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setattr(settings_db, "DB_PATH", rig.tmp / "remote-consent.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    target = vp.describe_video_data_target("role:video_fallback_1")
    owner_router, audit = router(), Audit()
    dh.acknowledge(owner_router, target.provider, True, dh.role_target_scope(target),
                   audit, target=target.target_id)
    return owner_router, target, audit


async def approved_run(rig, *, allow_remote=False):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": allow_remote}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    return rig.queue.get(proposal["task_id"]).result


@pytest.mark.asyncio
async def test_signed_primary_rate_limit_uses_only_approved_local_fallback(rig, monkeypatch):
    local_fallback(monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.port == 1234:
            return httpx.Response(429, json={"error": {"message": "rate limit exceeded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Backup answer."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Backup answer."
    assert result["result"]["chosen_route"] == "role:video_fallback_1"
    assert result["result"]["chosen_provider"] == "lm-studio"
    assert result["result"]["chosen_model"] == "backup-video"
    assert [request.url.port for request in requests] == [1234, 1235]
    assert [json.loads(request.content)["model"] for request in requests] == ["local-video", "backup-video"]
    assert requests[0].headers.get("Authorization") is None
    assert requests[1].headers.get("Authorization") == "Bearer synthetic-backup-key"


@pytest.mark.asyncio
async def test_primary_success_with_chain_never_sends_to_backup(rig, monkeypatch):
    local_fallback(monkeypatch)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "A synthetic clip."
    assert len(rig.requests) == 1
    assert rig.requests[0].url.port == 1234


@pytest.mark.asyncio
async def test_primary_client_cannot_mutate_prepared_messages_for_backup(rig, monkeypatch):
    local_fallback(monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        return (httpx.Response(429) if request.url.port == 1234 else
                httpx.Response(200, json={"choices": [{"message": {"content": "Backup answer."}}]}))

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(respond), **kw)
        if not requests:
            original_stream = client.stream
            original_close = client._transport.aclose
            captured = {}

            def stream(*args, **kwargs):
                captured["body"] = kwargs["json"]
                return original_stream(*args, **kwargs)

            async def mutate_on_close():
                captured["body"]["messages"][0]["content"][0]["text"] = "Changed after approval"
                await original_close()

            client.stream = stream
            client._transport.aclose = mutate_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in requests] == [1234, 1235]
    first_text = json.loads(requests[0].content)["messages"][0]["content"][0]["text"]
    second_text = json.loads(requests[1].content)["messages"][0]["content"][0]["text"]
    assert second_text == first_text


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["approved_task", "execution_check"])
async def test_initial_trust_lookup_error_is_sanitized(rig, broken):
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    if broken == "execution_check":
        proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
            "video_url": str(rig.source), "question": "What happens?"}})
        task = rig.queue.get(proposal["task_id"])
        rig.video.approved_task = lambda: task

    def fail(*_args):
        raise TimeoutError("synthetic store timeout")

    setattr(rig.video, broken, fail)
    assert await rig.video.execute(args) == {"ok": False, "reason": "video_analysis_refused"}
    assert rig.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "key", "order"])
async def test_signed_chain_change_after_approval_refuses_before_any_model_send(rig, monkeypatch, change):
    local_fallback(monkeypatch)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    if change == "model":
        local_fallback(monkeypatch, model="rotated-video")
    elif change == "key":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "rotated-synthetic-key")
    else:
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
            {"provider": "lm-studio", "model": "other-video", "base_url": "http://127.0.0.1:1236/v1"},
            {"provider": "lm-studio", "model": "backup-video", "base_url": "http://127.0.0.1:1235/v1"},
        ]))
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_source_disappearing_after_full_chain_approval_sends_nowhere(rig, monkeypatch):
    local_fallback(monkeypatch)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    rig.source.unlink()
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


def test_unchained_class_remains_exact_old_primary_binding(rig):
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    source_key = [str(rig.source), hashlib.sha256(rig.source.read_bytes()).hexdigest()]
    identity = vp.describe_video_data_target()
    roots = tuple(map(str, FileScope.from_env().roots))
    frozen_v1 = json.dumps([identity.binding, {**args, "video_url": source_key}, roots],
                           sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(vp._scope_key(), b"H277:video-approval:v1\0" + frozen_v1,
                      hashlib.sha256).hexdigest()
    expected = "video." + digest[:56]
    assert rig.video.classifier(args)["class"] == expected
    assert rig.video.classifier(args)["notice"] == "Analyze video on local lm-studio/local-video"
    primary_scope_wire = json.dumps([
        "role:video_analysis", "lm-studio", "local-video", "dedicated",
        identity.policy, identity.binding,
    ], sort_keys=True, separators=(",", ":")).encode()
    expected_scope = hmac.new(dh._scope_key(), b"H513:role-target:v1\0" + primary_scope_wire,
                              hashlib.sha256).hexdigest()
    assert dh.role_target_scope(identity) == expected_scope


@pytest.mark.asyncio
async def test_unchained_success_result_keeps_exact_old_shape(rig):
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert result["result"] == {"ok": True, "analysis": "A synthetic clip."}


def test_remote_candidate_needs_per_lane_consent_before_proposal_and_notice_hides_path(rig, monkeypatch):
    remote_fallback(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?",
                                "allow_remote": True})
    with pytest.raises(dh.DataHandlingRefused):
        rig.video.classifier(args)
    grant_remote(rig, monkeypatch)
    notice = rig.video.classifier(args)["notice"]
    assert "lm-studio/local-video" in notice
    assert "openai-compatible/remote-video" in notice
    assert "https://remote.example" in notice
    assert "/private/native" not in notice
    assert "synthetic-remote-secret" not in notice


@pytest.mark.parametrize("restriction", [
    "allow_remote", "role_opt_in", "strict_local", "safe_mode", "local_only",
])
def test_remote_candidate_restrictions_refuse_entire_proposal(rig, monkeypatch, restriction):
    remote_fallback(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    grant_remote(rig, monkeypatch)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?",
                                "allow_remote": restriction != "allow_remote"})
    if restriction == "role_opt_in":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "0")
    elif restriction == "strict_local":
        monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    elif restriction == "safe_mode":
        monkeypatch.setattr(safe_mode, "enabled", lambda: True)
    with pytest.raises(vp.VideoPolicyRefused):
        if restriction == "local_only":
            rig.video.intake("frigga", args)
        else:
            rig.video.classifier(args)
    assert rig.requests == []


@pytest.mark.asyncio
async def test_five_lane_notice_fits_signed_classifier_and_names_each_origin(rig, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "lm-studio", "model": "synthetic-long-model-" + "x" * 180 + str(slot),
         "base_url": f"http://127.0.0.1:{1234 + slot}/private/native/v1"}
        for slot in range(1, 5)
    ]))
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    labels = rig.video.classifier(args)
    assert len(labels["notice"]) <= 200
    assert all(f"{slot}L:" in labels["notice"] for slot in range(1, 6))
    assert "/private/native" not in labels["notice"]
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    assert rig.requests == []


@pytest.mark.asyncio
async def test_long_remote_origins_and_models_still_fit_five_lane_signed_notice(rig, monkeypatch):
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "openai-compatible", "model": "remote-synthetic-" + "m" * 180 + str(slot),
         "base_url": "https://" + (chr(96 + slot) * 50 + ".") * 3 + "example/private/native/v1"}
        for slot in range(1, 5)
    ]))
    monkeypatch.setattr(settings_db, "DB_PATH", rig.tmp / "long-remote-consent.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    owner_router, audit = router(), Audit()
    for identity in vp.describe_video_route_set()[1:]:
        dh.acknowledge(owner_router, identity.provider, True, dh.role_target_scope(identity),
                       audit, target=identity.target_id)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?",
                                "allow_remote": True})
    labels = rig.video.classifier(args)
    assert len(labels["notice"]) <= 200
    assert all(f"{slot}R:" in labels["notice"] for slot in range(2, 6))
    assert "/private/native" not in labels["notice"]
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": True}})
    assert proposal["reason"] == "approval_required", proposal
    assert rig.requests == []


def test_compact_notice_sanitizes_embedded_model_control_character(rig, monkeypatch):
    local_fallback(monkeypatch, model="ab\nlong-synthetic-model-" + "x" * 180)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    notice = rig.video.classifier(args)["notice"]
    assert len(notice) <= 200
    assert "\n" not in notice


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "content"), [
    (400, b'{"error":{"message":"invalid request"}}'),
    (403, b'{"error":{"message":"permission denied"}}'),
    (404, b'{"error":{"message":"model not found"}}'),
    (503, b'{"error":{"message":"quota exceeded"}}'),
    (200, b"not JSON"),
    (200, b'{"choices":[]}'),
    (200, b'{"choices":[{"message":{"content":""}}]}'),
])
async def test_noneligible_status_or_answer_never_switches_routes(rig, monkeypatch, status, content):
    local_fallback(monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=content)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]


@pytest.mark.asyncio
async def test_exhausted_chain_sends_once_per_lane_and_reports_fixed_categories(rig, monkeypatch):
    local_fallback(monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "too many requests"}})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "rate_limit"},
        {"target_id": "role:video_fallback_1", "category": "rate_limit"},
    ]
    assert "too many requests" not in json.dumps(result)


@pytest.mark.asyncio
async def test_oversized_failed_body_stops_before_fallback(rig, monkeypatch):
    local_fallback(monkeypatch)
    requests = []
    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(429, content=b"x" * 512001))), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]
    assert "xxxx" not in json.dumps(result)


@pytest.mark.asyncio
async def test_chain_reads_public_source_once_and_reuses_identical_media(rig, monkeypatch):
    local_fallback(monkeypatch)
    source_requests, model_requests = [], []

    def source_response(request):
        source_requests.append(request)
        return httpx.Response(200, content=b"one synthetic source")

    rig.video.source_client_factory = lambda plugin, **kw: VideoHTTPClient(
        plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
        transport_factory=lambda target: httpx.MockTransport(source_response), **kw)

    def model_response(request):
        model_requests.append(request)
        if request.url.port == 1234:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Source answer."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(model_response), **kw)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": "https://video.example/clip.mp4", "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] == "ok", result
    assert len(source_requests) == 1
    assert [request.url.port for request in model_requests] == [1234, 1235]
    payloads = [json.loads(request.content) for request in model_requests]
    assert payloads[0]["messages"] == payloads[1]["messages"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    dh.DataHandlingRefused("synthetic store refusal"),
    httpx.ConnectError("synthetic guard connection lookalike"),
])
async def test_actual_use_guard_error_never_becomes_fallback(rig, monkeypatch, failure):
    from agents.core import video_analysis as video

    local_fallback(monkeypatch)

    def fail_actual_use(router, identity, *, actual_use):
        assert actual_use is True
        raise failure

    monkeypatch.setattr(video, "authorize_role_target", fail_actual_use)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert rig.requests == []
    assert "synthetic" not in json.dumps(result)


@pytest.mark.asyncio
async def test_request_hook_connect_error_before_transport_never_switches(rig, monkeypatch):
    local_fallback(monkeypatch)

    async def fail_hook(request):
        raise httpx.ConnectError("hook-owned failure", request=request)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200))),
        event_hooks={"request": [fail_hook]}, **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert rig.requests == []


@pytest.mark.asyncio
async def test_post_guard_request_hook_connect_error_never_switches(rig, monkeypatch):
    local_fallback(monkeypatch)
    clients = []

    async def fail_after_guard(request):
        raise httpx.ConnectError("post-guard hook failure", request=request)

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200))), **kw)
        clients.append(client)
        client.event_hooks["request"].append(fail_after_guard)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert rig.requests == []
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_post_guard_hook_request_mutation_is_refused_before_transport(rig, monkeypatch):
    local_fallback(monkeypatch)
    clients = []

    async def mutate_after_guard(request):
        request.headers["Authorization"] = "Bearer unapproved"

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200))), **kw)
        clients.append(client)
        client.event_hooks["request"].append(mutate_after_guard)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert rig.requests == []
    assert len(clients) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ConnectError("response hook"),
                                          httpx.ReadTimeout("response hook")])
async def test_response_hook_httpx_error_never_switches(rig, monkeypatch, failure):
    local_fallback(monkeypatch)
    clients, requests = [], []

    async def fail_hook(_response):
        raise failure

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "primary"}}]}))),
            event_hooks={"response": [fail_hook]}, **kw)
        clients.append(client)
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_transport_read_error_after_dispatch_can_use_approved_fallback(rig, monkeypatch):
    local_fallback(monkeypatch)
    requests = []

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            raise httpx.ReadError("wire read failed")

    def respond(request):
        requests.append(request)
        if request.url.port == 1234:
            return httpx.Response(200, stream=BrokenStream())
        return httpx.Response(200, json={"choices": [{"message": {"content": "Recovered."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in requests] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "connection"}]


@pytest.mark.asyncio
async def test_successful_physical_request_records_actual_use_once(rig, monkeypatch):
    from agents.core import video_analysis as video

    seen = []
    original = video.authorize_role_target

    def record(router, identity, *, actual_use):
        seen.append((identity.target_id, actual_use))
        return original(router, identity, actual_use=actual_use)

    monkeypatch.setattr(video, "authorize_role_target", record)
    result = await approved_run(rig)
    assert result["status"] == "ok"
    assert seen == [("role:video_analysis", True)]


@pytest.mark.asyncio
async def test_fresh_request_retry_inside_one_lane_is_refused_before_second_send(rig, monkeypatch):
    from agents.core import video_analysis as video

    local_fallback(monkeypatch)
    requests, actual_uses = [], []
    original = video.authorize_role_target

    def record(router, identity, *, actual_use):
        actual_uses.append(identity.target_id)
        return original(router, identity, actual_use=actual_use)

    monkeypatch.setattr(video, "authorize_role_target", record)

    class FreshRetry(httpx.Auth):
        def auth_flow(self, request):
            response = yield request
            if response.status_code == 401:
                retry = httpx.Request(request.method, request.url, headers=request.headers,
                                      content=request.content)
                yield retry

    def respond(request):
        requests.append(request)
        if request.url.port == 1234 and len(requests) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"choices": [{"message": {"content": "retry"}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, auth=FreshRetry(), transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]
    assert actual_uses == ["role:video_analysis"]


@pytest.mark.asyncio
async def test_total_deadline_includes_synchronous_source_materialization(rig, monkeypatch):
    from agents.core import video_analysis as video

    local_fallback(monkeypatch)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    monkeypatch.setattr(video, "VIDEO_EXECUTION_TIMEOUT", 0.25)
    original = video._read_scoped
    calls = []

    def slow_materialization(path, scope):
        calls.append(1)
        if len(calls) == 2:
            time.sleep(0.5)
        return original(path, scope)

    monkeypatch.setattr(video, "_read_scoped", slow_materialization)
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] != "ok"
    assert len(calls) >= 2
    assert rig.requests == []


@pytest.mark.asyncio
async def test_total_deadline_starts_before_initial_approval_lookup(rig, monkeypatch):
    from agents.core import video_analysis as video

    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    approved = rig.queue.get(proposal["task_id"])
    rig.video.approved_task = lambda: approved

    checks = []

    def slow_approval(_task):
        checks.append(1)
        if len(checks) == 1:
            time.sleep(0.2)
        return True

    rig.video.execution_check = slow_approval
    rig.video.kernel_check = lambda _args, _task: None
    monkeypatch.setattr(video, "VIDEO_EXECUTION_TIMEOUT", 0.1)
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    result = await rig.video.execute(args)
    assert result == {"ok": False, "reason": "video_analysis_refused"}
    assert len(checks) == 1
    assert rig.requests == []


@pytest.mark.asyncio
async def test_total_deadline_includes_client_cleanup_before_next_lane(rig, monkeypatch):
    from agents.core import video_analysis as video

    local_fallback(monkeypatch)
    monkeypatch.setattr(video, "VIDEO_EXECUTION_TIMEOUT", 0.25)
    clients, requests, closed = [], [], []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(429))), **kw)
        clients.append(client)
        original_close = client._transport.aclose

        async def slow_close():
            try:
                await asyncio.sleep(0.5)
            finally:
                closed.append(True)
                await original_close()

        client._transport.aclose = slow_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]
    assert len(clients) == len(closed) == 1


@pytest.mark.asyncio
async def test_external_cancellation_closes_client_without_next_lane(rig, monkeypatch):
    local_fallback(monkeypatch)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    approved = rig.queue.get(proposal["task_id"])
    rig.video.approved_task = lambda: approved
    rig.video.execution_check = lambda _task: True
    rig.video.kernel_check = lambda _args, _task: None
    started = asyncio.Event()
    clients, requests, closed = [], [], []

    async def wait_forever(request):
        requests.append(request)
        started.set()
        await asyncio.Event().wait()

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(wait_forever), **kw)
        clients.append(client)
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
    assert [request.url.port for request in requests] == [1234]
    assert len(clients) == len(closed) == 1


@pytest.mark.asyncio
async def test_kernel_timeout_after_primary_physical_send_never_switches(rig, monkeypatch):
    local_fallback(monkeypatch)

    def kernel_check(_args, _task):
        if rig.requests:
            raise TimeoutError("synthetic kernel timeout")
        return None

    rig.video.kernel_check = kernel_check
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in rig.requests] == [1234]
    assert "synthetic kernel" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["key", "model", "order"])
async def test_close_time_chain_change_stops_before_next_lane(rig, monkeypatch, change):
    local_fallback(monkeypatch)
    if change == "order":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
            {"provider": "lm-studio", "model": "backup-video", "base_url": "http://127.0.0.1:1235/v1"},
            {"provider": "lm-studio", "model": "second-video", "base_url": "http://127.0.0.1:1236/v1"},
        ]))
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "synthetic-second-key")
    requests, clients = [], []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(429))), **kw)
        clients.append(client)
        if not requests:
            original_close = client._transport.aclose

            async def rotate_on_close():
                if change == "key":
                    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "rotated-after-send")
                elif change == "model":
                    local_fallback(monkeypatch, model="rotated-after-send")
                else:
                    rows = json.loads(os.environ["JARVIS_ROLE_VIDEO_FALLBACKS"])
                    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps(list(reversed(rows))))
                await original_close()

            client._transport.aclose = rotate_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_close_time_remote_consent_revocation_stops_before_next_lane(rig, monkeypatch):
    remote_fallback(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    owner_router, target, audit = grant_remote(rig, monkeypatch)
    requests = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(429))), **kw)
        if not requests:
            original_close = client._transport.aclose

            async def revoke_on_close():
                dh.acknowledge(owner_router, target.provider, False,
                               dh.role_target_scope(target), audit, target=target.target_id)
                await original_close()

            client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    result = await approved_run(rig, allow_remote=True)
    assert result["status"] != "ok"
    assert [request.url.port for request in requests] == [1234]


@pytest.mark.asyncio
async def test_attempt_owned_timeout_may_switch_but_hook_timeout_may_not(rig, monkeypatch):
    from agents.core import video_analysis as video

    local_fallback(monkeypatch)
    monkeypatch.setattr(video, "VIDEO_MODEL_ATTEMPT_TIMEOUT", 0.02)
    requests = []

    async def respond(request):
        requests.append(request)
        if request.url.port == 1234:
            await asyncio.sleep(0.2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Timed backup."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await approved_run(rig)
    assert result["status"] == "ok", result
    assert [request.url.port for request in requests] == [1234, 1235]
    assert result["result"]["attempts"] == [
        {"target_id": "role:video_analysis", "category": "timeout"}]


@pytest.mark.asyncio
async def test_hook_owned_timeout_error_refuses_without_second_lane(rig, monkeypatch):
    local_fallback(monkeypatch)

    async def fail_hook(_request):
        raise TimeoutError("synthetic hook timeout")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200))),
        event_hooks={"request": [fail_hook]}, **kw)
    result = await approved_run(rig)
    assert result["status"] != "ok"
    assert rig.requests == []
