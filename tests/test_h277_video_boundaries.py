"""H277 physical video request and scoped-source boundary regressions."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.file_tools import FileScope
from agents.core.llm.egress import llm_async_client
from agents.core.llm.video_policy import VideoPolicyRefused
from agents.core.tool_rpc import ToolRPCValidationError
from agents.core.video_analysis import VideoHTTPClient, _read_scoped, _read_url, _source
from tests.test_h277_video_analysis import rig


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite", ["url", "method", "authorization", "cookie"])
async def test_signed_worker_refuses_changed_physical_model_request(rig, rewrite):
    """Adapter event hooks can rewrite the final wire request after approval."""
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def alter(request):
        if rewrite == "url":
            request.url = httpx.URL("http://127.0.0.1:1234/v1/other")
        elif rewrite == "method":
            request.method = "GET"
        elif rewrite == "authorization":
            request.headers["Authorization"] = "Bearer altered-synthetic-key"
        else:
            request.headers["Cookie"] = "synthetic=1"

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "should not send"}}]}))),
        event_hooks={"request": [alter]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_signed_worker_refuses_transport_substitution_after_initial_proof(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    sent = []

    class OpaqueTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            sent.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": "unsafe"}}]})

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(
            lambda request: httpx.Response(500)), **kw)

        async def swap(_request):
            # Initial scope proof saw the direct MockTransport; the physical
            # request proof must notice this later route replacement.
            client._transport = OpaqueTransport()

        client.event_hooks["request"].insert(0, swap)
        return client

    rig.video.model_client_factory = factory
    await rig.worker.tick()
    assert sent == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


def test_scoped_video_read_refuses_symlink_swapped_after_resolution(rig):
    scope = FileScope.from_env()
    kind, resolved, _ = _source(str(rig.source), scope)
    assert kind == "file" and resolved == rig.source
    outside = rig.tmp.parent / (rig.tmp.name + "-synthetic-outside.mp4")
    outside.write_bytes(b"synthetic outside bytes")
    rig.source.unlink()
    rig.source.symlink_to(outside)
    try:
        with pytest.raises((OSError, VideoPolicyRefused)):
            _read_scoped(resolved, scope)
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_http_video_stream_without_content_length_is_byte_bounded(rig, monkeypatch):
    from agents.core import video_analysis

    monkeypatch.setattr(video_analysis, "MAX_VIDEO_BYTES", 5)
    seen = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123"
            yield b"456"

    def factory(plugin, **kw):
        return VideoHTTPClient(plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
                               transport_factory=lambda target: httpx.MockTransport(
                                   lambda request: (seen.append(request) or
                                                    httpx.Response(200, stream=Chunks()))), **kw)

    with pytest.raises(VideoPolicyRefused, match="too large"):
        await _read_url("https://video.example/clip.mp4", lambda: None, client_factory=factory)
    assert len(seen) == 1


def test_scoped_file_read_requests_at_most_cap_plus_one_byte(rig, monkeypatch):
    from agents.core import video_analysis

    monkeypatch.setattr(video_analysis, "MAX_VIDEO_BYTES", 5)
    rig.source.write_bytes(b"1234")
    real_fdopen = video_analysis.os.fdopen
    requested = []

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            requested.append(size)
            return self.stream.read(size)

    monkeypatch.setattr(video_analysis.os, "fdopen", lambda *args, **kw: ObservedStream(
        real_fdopen(*args, **kw)))
    assert _read_scoped(rig.source, FileScope.from_env()) == b"1234"
    assert len(requested) == 1 and 0 <= requested[0] <= 6


@pytest.mark.asyncio
async def test_signed_worker_kernel_denial_after_acceptance_blocks_model(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    calls = []

    def deny_video_execution(args, task):
        calls.append((args["question"], task.id))
        return "synthetic kernel denial"

    rig.video.kernel_check = deny_video_execution
    await rig.worker.tick()
    assert rig.requests == []
    assert calls and calls[0][1] == proposal["task_id"]
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_handler_rejects_canonical_kind_with_wrong_video_target(rig):
    args = rig.video.preflight({"video_url": str(rig.source), "question": "What happens?"})
    task = SimpleNamespace(kind="tool.rpc", id=1, agent="jarvis", payload={
        "tool": "video_analyze", "target": "other_tool", "args": args,
        "class": rig.video.classifier(args)["class"],
    })
    rig.video.approved_task = lambda: task
    rig.video.execution_check = lambda presented: presented is task
    rig.video.kernel_check = lambda args, presented: None
    result = await rig.video.execute(args)
    assert result["ok"] is False
    assert rig.requests == []


def test_remote_call_still_needs_per_call_approval_after_video_role_consent(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import data_handling as dh
    from agents.core.llm import video_policy
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-video-boundary-consent")
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "remote-video")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    target = video_policy.describe_video_data_target()
    dh.acknowledge(router(), target.provider, True, dh.role_target_scope(target), Audit(),
                   target=dh.VIDEO_TARGET)
    # Independent role consent is present, so it cannot mask a missing call flag.
    video_policy.authorization_check(target, allow_remote=True, confirm_expensive=False)
    with pytest.raises(video_policy.VideoPolicyRefused, match="explicit approval"):
        video_policy.authorization_check(target, allow_remote=False, confirm_expensive=False)


@pytest.mark.asyncio
async def test_redirect_validation_prevents_private_second_physical_get(rig):
    seen = []

    def transport(request):
        seen.append((str(request.url), request.headers.get("Host", "")))
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private.mp4"})
        return httpx.Response(200, content=b"forbidden synthetic second GET")

    def factory(plugin, **kw):
        return VideoHTTPClient(plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
                               transport_factory=lambda target: httpx.MockTransport(transport), **kw)

    with pytest.raises(ToolRPCValidationError):
        await _read_url("https://video.example/clip.mp4", lambda: None, client_factory=factory)
    assert len(seen) == 1
    assert seen[0][1] == "video.example"


@pytest.mark.asyncio
async def test_durable_receipt_revoked_at_physical_model_hook_blocks_send(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def revoke_receipt(_request):
        with rig.queue._lock:
            row = rig.queue._conn.execute(
                "SELECT mediation_receipt FROM tasks WHERE id=?", (proposal["task_id"],)).fetchone()
            receipt = json.loads(row[0])
            receipt["signature"] = "invalid-synthetic-signature"
            rig.queue._conn.execute("UPDATE tasks SET mediation_receipt=? WHERE id=?",
                                    (json.dumps(receipt), proposal["task_id"]))
            rig.queue._conn.commit()

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "should not send"}}]}))),
        event_hooks={"request": [revoke_receipt]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_persisted_media_tuple_swap_after_permit_blocks_video_send(rig):
    """A post-permit image-shaped row cannot authorize the presented video task."""
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def swap_persisted_payload(_request):
        image_payload = {"tool": "image_generate", "target": "image_generate",
                         "args": {"prompt": "synthetic image request"}}
        with rig.queue._lock:
            rig.queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?",
                                    (json.dumps(image_payload), proposal["task_id"]))
            rig.queue._conn.commit()

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "should not send"}}]}))),
        event_hooks={"request": [swap_persisted_payload]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_video_intake_requires_enforce_mode_even_when_hold_classifies_tool_rpc(rig):
    rig.queue.mediation_mode = "hold"
    assert rig.queue.classify_mediation("tool.rpc") is True
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "signed_video_mediation_required"
    assert rig.queue.list() == []
    assert rig.requests == []
