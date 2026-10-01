"""Native video consumer: signed worker, scoped sources, consent and wire guards."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kernel.binding import make_action_kernel
from agents.core.llm.egress import llm_async_client
from agents.core.tool_rpc import ToolRPCValidationError
from agents.core.video_analysis import VideoAnalysisTool, _read_scoped, _source
from tests.test_task_mediation_evidence import _head_anchor, _signer


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "local-video")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "http://127.0.0.1:1234")
    path = tmp_path / "queue.db"
    queue = TaskQueue(str(path), mediation_mode="enforce", mediation_signer=_signer(),
                      mediation_head_anchor=_head_anchor(path), mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=None, budget_ledger=None, loop_detector=None,
                           permission_gate=None, llm_router=None)
    worker.bind_mediation(make_action_kernel(orch), _signer())
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
    worker.executor = executor.execute
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"tiny synthetic video fixture")
    requests = []

    def model(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"][1]["type"] == "video_url"
        return httpx.Response(200, json={"choices": [{"message": {"content": "A synthetic clip."}}]})

    video = orch.tool_rpc._tools["video_analyze"]["handler"].__self__
    video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(model), **kw)
    try:
        yield SimpleNamespace(tmp=tmp_path, queue=queue, worker=worker, orch=orch,
                              coordinator=coordinator, video=video, source=source, requests=requests)
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_registered_signed_worker_path_sends_native_video_only_after_approval(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    task = rig.queue.get(proposal["task_id"])
    assert task.status == "blocked" and task.kind == "tool.rpc"
    assert task.mediation_receipt is not None
    assert rig.requests == []
    early = await rig.coordinator._approved_image_tool_rpc_execute(task)
    assert early["status"] == "failed"
    await rig.worker.apply_decision(task.id, "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(task.id).result
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "A synthetic clip."
    assert len(rig.requests) == 1
    assert rig.requests[0].url.path == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_role_change_after_approval_refuses_before_model_request(rig, monkeypatch):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "different-video-model")
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


def test_workspace_source_is_descriptor_scoped_and_rejects_symlink_swap(rig):
    from agents.core.file_tools import FileScope
    scope = FileScope.from_env()
    kind, path, _ = _source(str(rig.source), scope)
    assert kind == "file" and _read_scoped(path, scope) == b"tiny synthetic video fixture"
    rig.source.unlink()
    rig.source.symlink_to("/etc/passwd")
    with pytest.raises(ToolRPCValidationError):
        _source(str(rig.source), scope)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/clip.mp4", "http://user:pass@video.example/clip.mp4",
    "https://video.example/clip.mp4?token=secret", "file:///etc/passwd",
])
def test_unsafe_video_urls_refused_at_intake(rig, url):
    with pytest.raises(ToolRPCValidationError):
        rig.video.preflight({"video_url": url, "question": "What?"})


@pytest.mark.asyncio
async def test_public_url_uses_pinned_client_and_rejects_private_redirect(rig):
    from agents.core.video_analysis import VideoHTTPClient, _read_url

    seen, checks = [], []

    def transport(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.mp4"})

    def factory(plugin, **kw):
        return VideoHTTPClient(plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
                               transport_factory=lambda target: httpx.MockTransport(transport), **kw)

    with pytest.raises(ToolRPCValidationError):
        await _read_url("https://video.example/clip.mp4", lambda: checks.append(1),
                        client_factory=factory)
    assert len(seen) == 1 and len(checks) >= 2
    assert seen[0].headers["Host"] == "video.example"


@pytest.mark.asyncio
async def test_public_url_refuses_stream_byte_overflow(rig, monkeypatch):
    from agents.core import video_analysis as video

    monkeypatch.setattr(video, "MAX_VIDEO_BYTES", 5)
    seen = []

    def factory(plugin, **kw):
        return video.VideoHTTPClient(plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
                                     transport_factory=lambda target: httpx.MockTransport(
                                         lambda request: (seen.append(request) or httpx.Response(200, content=b"123456"))),
                                     **kw)

    with pytest.raises(video.VideoPolicyRefused, match="too large"):
        await video._read_url("https://video.example/clip.mp4", lambda: None, client_factory=factory)
    assert len(seen) == 1


def test_remote_video_needs_independent_config_bound_role_consent(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import data_handling as dh
    from agents.core.llm import video_policy
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-video-consent-key")
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "remote-video")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    target = video_policy.describe_video_data_target()
    assert target is not None and target.local is False
    with pytest.raises(dh.DataHandlingRefused):
        video_policy.authorization_check(target, allow_remote=True, confirm_expensive=False)
    dh.acknowledge(router(), target.provider, True, dh.role_target_scope(target), Audit(),
                   target=dh.VIDEO_TARGET)
    video_policy.authorization_check(target, allow_remote=True, confirm_expensive=False)
    with pytest.raises(video_policy.VideoPolicyRefused, match="explicit approval"):
        video_policy.authorization_check(target, allow_remote=False, confirm_expensive=False)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "new-synthetic-key")
    with pytest.raises(video_policy.VideoPolicyRefused, match="configuration changed"):
        video_policy.authorization_check(target, allow_remote=True, confirm_expensive=False)


@pytest.mark.asyncio
async def test_actual_file_bytes_must_match_the_approved_snapshot(rig, monkeypatch):
    from agents.core import video_analysis as video

    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    original = video._read_scoped
    calls = []

    def swapped(path, scope):
        calls.append(1)
        return b"unapproved swapped bytes" if len(calls) == 3 else original(path, scope)

    monkeypatch.setattr(video, "_read_scoped", swapped)
    await rig.worker.tick()
    assert len(calls) >= 3
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_revocation_during_model_client_cleanup_withholds_answer(rig, monkeypatch):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    original_factory = rig.video.model_client_factory

    def factory(*args, **kwargs):
        client = original_factory(*args, **kwargs)
        close = client._transport.aclose

        async def revoke_on_close():
            monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "revoked-model")
            await close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    await rig.worker.tick()
    assert len(rig.requests) == 1
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_physical_model_guard_rejects_extra_unapproved_message(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def mutate(request):
        body = json.loads(request.content)
        body["messages"].append({"role": "user", "content": "Extra unapproved instruction"})
        request._content = json.dumps(body).encode()

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "Changed prompt succeeded"}}]}))),
        event_hooks={"request": [mutate]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_server_owned_class_and_dispatcher_refuse_other_canonical_payloads(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    task = rig.queue.get(proposal["task_id"])
    assert task.payload["tool"] == task.payload["target"] == "video_analyze"
    assert task.payload["class"].startswith("video.")
    assert task.payload["class"] == rig.video.classifier(task.payload["args"])["class"]
    wrong = SimpleNamespace(kind="tool.rpc", payload={"tool": "echo", "target": "echo", "args": {}},
                            id=task.id, agent=task.agent)
    denied = await rig.coordinator._approved_image_tool_rpc_execute(wrong)
    assert denied == {"status": "failed", "reason": "image_task_required"}
    await rig.worker.apply_decision(task.id, "accept", decided_by="andrei")
    rig.orch.tool_rpc._tools["video_analyze"]["classifier"] = lambda args: {"class": "video." + "0" * 56}
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task.id).result["reason"] == "approval_class_mismatch"


@pytest.mark.asyncio
async def test_role_revoked_at_physical_source_get_blocks_model(rig, monkeypatch):
    from agents.core.video_analysis import VideoHTTPClient

    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": "https://video.example/clip.mp4", "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    sent = []

    def factory(plugin, **kw):
        client = VideoHTTPClient(plugin, resolver=lambda host, mode: (["8.8.8.8"], None),
                                 transport_factory=lambda target: httpx.MockTransport(
                                     lambda request: (sent.append(request) or httpx.Response(200, content=b"clip"))),
                                 **kw)
        pinned = client._pinned_client

        def revoke_before_send(target):
            physical = pinned(target)

            async def revoke(_request):
                monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "revoked-model")

            physical.event_hooks["request"].insert(0, revoke)
            return physical

        client._pinned_client = revoke_before_send
        return client

    rig.video.source_client_factory = factory
    await rig.worker.tick()
    assert sent == [] and rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.parametrize("posture", ["strict_local", "cloud_fallback_never", "safe_mode", "local_only_agent"])
def test_remote_role_cannot_override_shared_privacy_posture(tmp_path, monkeypatch, posture):
    from agents.core import safe_mode, settings_db
    from agents.core.llm import data_handling as dh
    from agents.core.llm import video_policy
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-video-consent-key")
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "remote-video")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    target = video_policy.describe_video_data_target()
    dh.acknowledge(router(), target.provider, True, dh.role_target_scope(target), Audit(),
                   target=dh.VIDEO_TARGET)
    if posture == "strict_local":
        monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    elif posture == "cloud_fallback_never":
        monkeypatch.setattr(safe_mode, "get_value", lambda *args: "never")
    elif posture == "safe_mode":
        monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    actor = "ultron" if posture == "local_only_agent" else "jarvis"
    with pytest.raises(video_policy.VideoPolicyRefused):
        video_policy.authorization_check(target, allow_remote=True,
                                         confirm_expensive=False, actor=actor)


@pytest.mark.asyncio
async def test_role_use_is_recorded_only_when_physical_model_send_begins(rig):
    from agents.core.llm import data_handling as dh

    observed_router = SimpleNamespace(_data_handling_role_used={})
    rig.video.router = observed_router
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert observed_router._data_handling_role_used == {}
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    assert observed_router._data_handling_role_used == {}
    await rig.worker.tick()
    assert rig.queue.get(proposal["task_id"]).result["status"] == "ok"
    used = observed_router._data_handling_role_used[dh.VIDEO_TARGET]
    assert isinstance(used["at"], float) and len(used["scope"]) == 64


@pytest.mark.asyncio
async def test_revocation_at_physical_model_hook_blocks_transport(rig, monkeypatch):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def revoke(_request):
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "revoked-model")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "should not send"}}]}))),
        event_hooks={"request": [revoke]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_adapter_cannot_mutate_expected_body_before_physical_send(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    original_factory = rig.video.model_client_factory

    def factory(*args, **kwargs):
        client = original_factory(*args, **kwargs)
        stream = client.stream

        def mutate(*stream_args, **stream_kwargs):
            stream_kwargs["json"]["messages"].append({"role": "user", "content": "Unapproved extra"})
            return stream(*stream_args, **stream_kwargs)

        client.stream = mutate
        return client

    rig.video.model_client_factory = factory
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_accepted_unsigned_canonical_video_row_cannot_run_with_mediation_off(rig):
    queue = TaskQueue(str(rig.tmp / "unsigned.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=None, budget_ledger=None, loop_detector=None,
                           permission_gate=None, llm_router=None)
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=None)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
    worker.executor = executor.execute
    args = {"video_url": str(rig.source), "question": "What happens?",
            "allow_remote": False, "confirm_expensive": False}
    video = orch.tool_rpc._tools["video_analyze"]["handler"].__self__
    cls = video.classifier(args)["class"]
    proposed = await orch.tool_rpc.handle({"tool": "video_analyze", "args": args})
    assert proposed["reason"] == "signed_video_mediation_required"
    assert queue.list() == []
    sent = []
    video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            sent.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "unsigned send"}}]}))), **kw)
    task_id = queue.enqueue("jarvis", "tool.rpc", "Unsigned video row", payload={
        "tool": "video_analyze", "target": "video_analyze", "args": args, "class": cls},
        risk_tier=3, autonomy_level="ask")
    queue.transition(task_id, TaskStatus.BLOCKED)
    try:
        await worker.apply_decision(task_id, "accept", decided_by="andrei")
        await worker.tick()
        assert sent == []
        assert queue.get(task_id).result["status"] != "ok"
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_signed_row_cannot_run_after_mediation_mode_changes_to_off(rig):
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    rig.queue.mediation_mode = "off"
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_model_response_stream_is_bounded(rig, monkeypatch):
    from agents.core import video_analysis as video

    monkeypatch.setattr(video, "MAX_MODEL_RESPONSE_BYTES", 5)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    assert len(rig.requests) == 1
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"
