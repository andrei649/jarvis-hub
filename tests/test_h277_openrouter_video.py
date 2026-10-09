"""OpenRouter native video stays on an approved, policy-bound ToolRPC lane."""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from agents.core import settings_db
from agents.core.llm import data_handling as dh
from agents.core.llm import video_policy as vp
from agents.core.llm.egress import llm_async_client
from agents.core.llm.model_roles import resolve_video_route
from agents.core.llm.video_routes import VideoRouteConfigError, resolve_video_fallbacks
from tests.test_h277_video_analysis import rig
from tests.test_h513_data_handling import Audit, router


def _setting(name, value):
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='llm' AND key=?",
                     (json.dumps(value), name))
        conn.commit()
    finally:
        conn.close()


def _remote_db(rig, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", rig.tmp / "openrouter-consent.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)


def _grant(target):
    owner_router = router()
    dh.acknowledge(owner_router, target.provider, True, dh.role_target_scope(target), Audit(),
                   target=target.target_id)
    return owner_router


def _explicit(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openrouter")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "vendor/video")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "synthetic-video-key")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")


def test_explicit_openrouter_route_uses_profile_default_base():
    env = {"JARVIS_ROLE_VIDEO_PROVIDER": "openrouter", "JARVIS_ROLE_VIDEO_MODEL": "vendor/video"}
    role = resolve_video_route(env).role
    assert (role.configured, role.provider_id, role.base_url, role.local) == (
        True, "openrouter", "https://openrouter.ai/api/v1", False)


def test_inherited_openrouter_vision_model_override_preserves_endpoint(monkeypatch):
    env = {"JARVIS_ROLE_VISION_PROVIDER": "openrouter",
           "JARVIS_ROLE_VISION_MODEL": "vendor/vision", "OPENROUTER_API_KEY": "synthetic-vision-key",
           "JARVIS_ROLE_VIDEO_MODEL": "vendor/video"}
    route = resolve_video_route(env)
    assert (route.role.configured, route.role.provider_id, route.role.model,
            route.request_url, route.inherited) == (
        True, "openrouter", "vendor/video",
        "https://openrouter.ai/api/v1/chat/completions", True)


def test_openrouter_fallback_requires_own_slot_key():
    env = {"JARVIS_ROLE_VIDEO_FALLBACKS": json.dumps([{
        "provider": "openrouter", "model": "vendor/backup",
        "base_url": "https://openrouter.ai/api/v1"}]),
        "OPENROUTER_API_KEY": "ambient", "JARVIS_ROLE_VIDEO_KEY": "primary",
        "JARVIS_ROLE_VISION_KEY": "vision"}
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(env)
    env["JARVIS_ROLE_VIDEO_FALLBACK_1_KEY"] = "slot-key"
    routes = resolve_video_fallbacks(env)
    assert [(r.provider, r.model, r.api_key) for r in routes] == [
        ("openrouter", "vendor/backup", "slot-key")]


@pytest.mark.asyncio
async def test_signed_openrouter_request_emits_full_video_and_provider_block(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    _setting("openrouter_only", ["provider-a"])
    _setting("openrouter_order", ["provider-a", "provider-b"])
    _setting("openrouter_require_parameters", True)
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A synthetic clip."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    args = {"video_url": str(rig.source), "question": "What happens?", "allow_remote": True}
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": args})
    assert proposal["reason"] == "approval_required", proposal
    assert sent == []
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] == "ok", result
    assert len(sent) == 1
    request = sent[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer synthetic-video-key"
    body = json.loads(request.content)
    assert body["model"] == "vendor/video"
    assert body["stream"] is False
    assert body["provider"] == {"only": ["provider-a"], "order": ["provider-a", "provider-b"],
                                "require_parameters": True, "data_collection": "deny"}
    assert body["messages"][0]["content"][1] == {
        "type": "video_url", "video_url": {"url": "data:video/mp4;base64," +
                                               base64.b64encode(rig.source.read_bytes()).decode("ascii")}}


def test_inherited_vision_key_is_reused_only_for_same_provider_and_physical_url(rig, monkeypatch):
    _remote_db(rig, monkeypatch)
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_BASE_URL", raising=False)
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_KEY", raising=False)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "vendor/video")
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-vision-key")
    identity = vp.describe_video_data_target()
    assert identity is not None
    assert identity.model == "vendor/video"
    assert identity.authorization == "Bearer synthetic-vision-key"
    assert identity.request_url == "https://openrouter.ai/api/v1/chat/completions"
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://proxy.example/api/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openrouter")
    with pytest.raises(vp.VideoPolicyRefused, match="key is unset"):
        vp.describe_video_data_target()


@pytest.mark.parametrize("key", ["", "bad\nInjected: x", "é", "x" * 4097],
                         ids=["missing", "header", "non-ascii", "overlong"])
def test_explicit_openrouter_requires_valid_dedicated_key_without_matching_vision(rig, monkeypatch, key):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", key)
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-key")
    if key:
        with pytest.raises(vp.VideoPolicyRefused, match="invalid video role key"):
            vp.describe_video_data_target()
    else:
        with pytest.raises(vp.VideoPolicyRefused, match="key is unset"):
            vp.describe_video_data_target()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["preference", "key", "model", "url", "remote_grant"])
async def test_approved_openrouter_route_change_refuses_before_dispatch(rig, monkeypatch, change):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    args = {"video_url": str(rig.source), "question": "What happens?", "allow_remote": True}
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": args})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    if change == "preference":
        _setting("openrouter_only", ["new-upstream"])
    elif change == "key":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "rotated-key")
    elif change == "model":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "vendor/other-video")
    elif change == "url":
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://proxy.example/api/v1")
    else:
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "0")
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


def test_local_only_actor_cannot_authorize_openrouter_video(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    with pytest.raises(vp.VideoPolicyRefused, match="local-only agent"):
        vp.authorization_check(target, allow_remote=True, confirm_expensive=False,
                               router=rig.video.router, actor="frigga")
    assert rig.requests == []


@pytest.mark.asyncio
async def test_openrouter_unsupported_video_refuses_without_fallback_or_retry(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "local-fallback",
        "base_url": "http://127.0.0.1:1235/v1"}]))
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.host == "openrouter.ai":
            return httpx.Response(400, json={"error": {"message": "video input is unsupported by this model"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Fallback"}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": True}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] != "ok"
    assert len(sent) == 1
    assert sent[0].url.host == "openrouter.ai"


@pytest.mark.asyncio
async def test_approved_openrouter_fallback_uses_only_slot_key_and_frozen_provider_block(rig, monkeypatch):
    _remote_db(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "openrouter", "model": "vendor/backup-video",
        "base_url": "https://openrouter.ai/api/v1"}]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "synthetic-slot-key")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "wrong-primary-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "wrong-ambient-key")
    _setting("openrouter_data_collection", "deny")
    target = vp.describe_video_data_target("role:video_fallback_1")
    rig.video.router = _grant(target)
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.host == "127.0.0.1":
            return httpx.Response(429, json={"error": {"message": "rate limit exceeded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Backup answer."}}]})

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": True}})
    assert proposal["reason"] == "approval_required", proposal
    assert sent == []
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(proposal["task_id"]).result
    assert result["status"] == "ok", result
    assert result["result"]["chosen_route"] == "role:video_fallback_1"
    assert [request.url.host for request in sent] == ["127.0.0.1", "openrouter.ai"]
    assert sent[1].headers["Authorization"] == "Bearer synthetic-slot-key"
    assert json.loads(sent[1].content)["provider"] == {"data_collection": "deny"}
    assert json.loads(sent[1].content)["messages"][0]["content"][1]["type"] == "video_url"


@pytest.mark.asyncio
async def test_invalid_openrouter_fallback_key_refuses_entire_chain_before_dispatch(rig, monkeypatch):
    _remote_db(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "openrouter", "model": "vendor/backup-video",
        "base_url": "https://openrouter.ai/api/v1"}]))
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-key")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "vision-key")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "primary-key")
    with pytest.raises(vp.VideoPolicyRefused, match="invalid video fallback"):
        rig.video.classifier({"video_url": str(rig.source), "question": "What happens?",
                              "allow_remote": True, "confirm_expensive": False})
    assert rig.requests == []


@pytest.mark.asyncio
async def test_openrouter_provider_preference_mutated_in_request_hook_refuses_physical_send(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    sent = []

    async def mutate(request):
        _setting("openrouter_data_collection", "allow")

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(lambda request: (
            sent.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "Should not arrive"}}]}))),
        event_hooks={"request": [mutate]}, **kw)
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": True}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    assert sent == []
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"


def test_explicit_openrouter_may_reuse_only_exact_matching_guarded_vision_key(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_KEY", raising=False)
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vendor/vision")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-vision-key")
    identity = vp.describe_video_data_target()
    assert identity is not None
    assert identity.authorization == "Bearer synthetic-vision-key"
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "https://proxy.example/api/v1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "proxy-vision-key")
    with pytest.raises(vp.VideoPolicyRefused, match="key is unset"):
        vp.describe_video_data_target()


def test_invalid_openrouter_provider_policy_fails_closed(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    _setting("openrouter_data_collection", "")
    with pytest.raises(vp.VideoPolicyRefused, match="routing policy"):
        vp.describe_video_data_target()


@pytest.mark.asyncio
async def test_openrouter_late_key_revocation_withholds_answer_after_model_send(rig, monkeypatch):
    _explicit(monkeypatch)
    _remote_db(rig, monkeypatch)
    target = vp.describe_video_data_target()
    rig.video.router = _grant(target)
    sent = []

    def factory(backend, **kw):
        client = llm_async_client(backend, transport=httpx.MockTransport(lambda request: (
            sent.append(request) or httpx.Response(200, json={
                "choices": [{"message": {"content": "Too late"}}]}))), **kw)
        close = client._transport.aclose

        async def revoke_on_close():
            monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "rotated-after-send")
            await close()

        client._transport.aclose = revoke_on_close
        return client

    rig.video.model_client_factory = factory
    proposal = await rig.orch.tool_rpc.handle({"tool": "video_analyze", "args": {
        "video_url": str(rig.source), "question": "What happens?", "allow_remote": True}})
    assert proposal["reason"] == "approval_required", proposal
    await rig.worker.apply_decision(proposal["task_id"], "accept", decided_by="andrei")
    await rig.worker.tick()
    assert len(sent) == 1
    assert rig.queue.get(proposal["task_id"]).result["status"] != "ok"
