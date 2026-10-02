"""Video inherits only an unambiguous, effective vision route."""
from __future__ import annotations

import json

import httpx
import pytest

from agents.core.llm import model_roles, video_policy
from agents.core.llm.egress import llm_async_client
from tests.test_h277_video_analysis import rig

VISION_NAMES = (
    "JARVIS_ROLE_VISION_PROVIDER", "JARVIS_ROLE_VISION_MODEL",
    "JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_KEY",
    "JARVIS_VLM_BACKEND", "JARVIS_VLM_MODEL", "JARVIS_VLM_URL", "JARVIS_VLM_KEY",
    "JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
    "JARVIS_ROLE_VIDEO_BASE_URL", "JARVIS_ROLE_VIDEO_KEY",
)


@pytest.fixture(autouse=True)
def clean_roles(monkeypatch):
    for name in VISION_NAMES:
        monkeypatch.delenv(name, raising=False)


def local_vision(monkeypatch, *, model="vision-model", base="http://127.0.0.1:1234/v1",
                 key="vision-secret"):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", model)
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", base)
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", key)


def test_video_inherits_resolved_vision_route_and_uses_video_model_override(monkeypatch):
    from agents.core.llm.data_handling import role_target_scope

    local_vision(monkeypatch)
    role = model_roles.resolve("video")
    assert (role.provider_id, role.model, role.base_url) == (
        "lm-studio", "vision-model", "http://127.0.0.1:1234/v1")
    assert role.source["model"] == "JARVIS_ROLE_VISION_MODEL"
    identity = video_policy.describe_video_data_target()
    assert identity.request_url == "http://127.0.0.1:1234/v1/chat/completions"
    assert identity.authorization == "Bearer vision-secret"
    assert "vision-secret" not in repr(identity)
    assert "vision-secret" not in repr(model_roles.describe())
    old_scope = role_target_scope(identity)
    old_class = video_policy.class_binding(identity, {"question": "synthetic"}, ("/tmp",))
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "rotated-secret")
    changed = video_policy.describe_video_data_target()
    assert role_target_scope(changed) != old_scope
    assert video_policy.class_binding(changed, {"question": "synthetic"}, ("/tmp",)) != old_class
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "video-override")
    assert model_roles.resolve("video").model == "video-override"
    assert video_policy.describe_video_data_target().model == "video-override"


@pytest.mark.parametrize("value", ["", "auto", " AUTO "])
def test_auto_or_blank_video_model_inherits_vision_model(monkeypatch, value):
    local_vision(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", value)
    assert model_roles.resolve("video").model == "vision-model"


def test_explicit_video_route_never_borrows_foreign_provider_or_model(monkeypatch):
    local_vision(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openai-compatible")
    assert not model_roles.resolve("video").configured
    assert video_policy.describe_video_data_target() is None
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "video-model")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "http://127.0.0.1:1234/v1")
    identity = video_policy.describe_video_data_target()
    assert (identity.provider, identity.model, identity.authorization) == (
        "openai-compatible", "video-model", "")


def test_exact_native_endpoint_and_provider_required_to_borrow_vision_key(monkeypatch):
    local_vision(monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "video-model")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "http://127.0.0.1:1234")
    assert video_policy.describe_video_data_target().authorization == "Bearer vision-secret"
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "http://127.0.0.1:1234/other")
    assert video_policy.describe_video_data_target().authorization == ""
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "video-secret")
    assert video_policy.describe_video_data_target().authorization == "Bearer video-secret"


def test_invalid_configured_vision_does_not_select_another_video_destination(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "video-model")
    role = model_roles.resolve("video")
    assert not role.configured
    assert video_policy.describe_video_data_target() is None


def test_inherited_nonstandard_native_path_and_guarded_legacy_key(monkeypatch):
    monkeypatch.setenv("JARVIS_VLM_BACKEND", "custom")
    monkeypatch.setenv("JARVIS_VLM_URL", "http://127.0.0.1:8000/legacy/v1")
    monkeypatch.setenv("JARVIS_VLM_KEY", "legacy-secret")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "http://127.0.0.1:8000/native/v1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vision-model")
    identity = video_policy.describe_video_data_target()
    assert identity.request_url == "http://127.0.0.1:8000/native/v1/chat/completions"
    assert identity.authorization == "Bearer legacy-secret"  # vision's existing same-origin guard
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "http://127.0.0.1:8001/native/v1")
    assert video_policy.describe_video_data_target().authorization == ""


def test_no_configured_vision_retains_explicit_video_model_and_auto_is_unset(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "video-only")
    assert model_roles.resolve("video").model == "video-only"
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "auto")
    assert model_roles.resolve("video").configured is False


def test_invalid_vision_native_destination_is_not_listed_as_usable(monkeypatch):
    local_vision(monkeypatch, base="http://user:pass@127.0.0.1:1234/v1")
    # The model can resolve it, but video cannot safely inherit userinfo.
    with pytest.raises(video_policy.VideoPolicyRefused):
        video_policy.describe_video_data_target()
    row = next(r for r in model_roles.describe() if r["role"] == "video")
    assert row["configured"] is False and row["error"] is True


def test_inherited_remote_route_needs_video_consent_and_privacy_controls(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import data_handling as dh
    from tests.test_h513_data_handling import Audit, router

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-video-fallback-consent")
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "remote-video")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "https://vision.example/v1")
    identity = video_policy.describe_video_data_target()
    assert identity.local is False
    with pytest.raises(video_policy.VideoPolicyRefused, match="explicit approval"):
        video_policy.authorization_check(identity, allow_remote=False, confirm_expensive=False)
    with pytest.raises(dh.DataHandlingRefused):
        video_policy.authorization_check(identity, allow_remote=True, confirm_expensive=False)
    dh.acknowledge(router(), identity.provider, True, dh.role_target_scope(identity), Audit(),
                   target=dh.VIDEO_TARGET)
    video_policy.authorization_check(identity, allow_remote=True, confirm_expensive=False)
    monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    with pytest.raises(video_policy.VideoPolicyRefused, match="strict-local"):
        video_policy.authorization_check(identity, allow_remote=True, confirm_expensive=False)


@pytest.mark.asyncio
async def test_signed_toolrpc_worker_uses_inherited_route(rig, monkeypatch):
    local_vision(monkeypatch)
    for name in ("JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
                 "JARVIS_ROLE_VIDEO_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] == "ok", result
    assert len(rig.requests) == 1
    assert rig.requests[0].headers["Authorization"] == "Bearer vision-secret"
    assert str(rig.requests[0].url) == "http://127.0.0.1:1234/v1/chat/completions"
    assert json.loads(rig.requests[0].content)["model"] == "vision-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,value", [
    ("JARVIS_ROLE_VISION_KEY", "changed-secret"),
    ("JARVIS_ROLE_VISION_MODEL", "changed-model"),
    ("JARVIS_ROLE_VISION_BASE_URL", "http://127.0.0.1:1235/v1"),
    ("JARVIS_ROLE_VISION_PROVIDER", "openai-compatible"),
])
async def test_inherited_route_change_after_approval_blocks_physical_request(
        rig, monkeypatch, name, value):
    from agents.core import video_analysis

    local_vision(monkeypatch)
    for video_name in ("JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
                       "JARVIS_ROLE_VIDEO_BASE_URL"):
        monkeypatch.delenv(video_name, raising=False)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    reads = []
    original = video_analysis._read_scoped
    monkeypatch.setattr(video_analysis, "_read_scoped", lambda *args: (reads.append(1) or original(*args)))
    monkeypatch.setenv(name, value)
    await rig.worker.tick()
    # The worker may hash the already scoped local file while recomputing the
    # signed class; it never makes a source HTTP or model request on stale config.
    assert reads == ([] if name == "JARVIS_ROLE_VISION_PROVIDER" else [1])
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_inherited_key_change_during_client_cleanup_withholds_answer(rig, monkeypatch):
    local_vision(monkeypatch)
    for name in ("JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
                 "JARVIS_ROLE_VIDEO_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    original_factory = rig.video.model_client_factory

    def factory(*args, **kwargs):
        client = original_factory(*args, **kwargs)
        close = client._transport.aclose

        async def revoke_on_close():
            monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "revoked-secret")
            await close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    await rig.worker.tick()
    assert len(rig.requests) == 1
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_inherited_key_change_at_physical_model_hook_blocks_transport(rig, monkeypatch):
    local_vision(monkeypatch)
    for name in ("JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
                 "JARVIS_ROLE_VIDEO_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")

    async def revoke(_request):
        monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "changed-secret")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "should not send"}}]}))),
        event_hooks={"request": [revoke]}, **kw)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


@pytest.mark.asyncio
async def test_model_failure_does_not_retry_with_another_provider(rig, monkeypatch):
    local_vision(monkeypatch)
    for name in ("JARVIS_ROLE_VIDEO_PROVIDER", "JARVIS_ROLE_VIDEO_MODEL",
                 "JARVIS_ROLE_VIDEO_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            rig.requests.append(request) or httpx.Response(503))), **kw)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?"}})
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    assert len(rig.requests) == 1
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"
