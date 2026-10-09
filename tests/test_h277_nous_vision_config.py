"""Nous vision authority and selection tests; no provider traffic."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from agents.core.llm import vision_nous
from agents.core.llm.nous_auth import NousAuthService
from agents.core.llm.nous_credentials import NousAuthStore
from agents.core.llm.nous_models import Recommendation
from agents.core.llm.vlm import VLMNotConfigured


def _jwt(exp: int) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'HS256'})}.{part({'exp': exp, 'scope': 'inference:invoke'})}.sig"


def _setup(monkeypatch, tmp_path, now, *, profile="default", base="https://inference-api.nousresearch.com/v1"):
    store = NousAuthStore(tmp_path / "nous.sqlite3")
    env = {"JARVIS_ROLE_VISION_PROVIDER": "nous", "JARVIS_ROLE_VISION_PROFILE": profile,
           "JARVIS_NOUS_CLIENT_ID": "nerva-test-client"}
    token = _jwt(now[0] + 3600)
    with store.transaction(profile) as state:
        state.update(access_token=token, refresh_token="grant", scope="inference:invoke",
                     portal_base_url="https://portal.nousresearch.com", client_id="nerva-test-client",
                     inference_base_url=base)
    monkeypatch.setattr(vision_nous, "_auth_service_factory",
                        lambda source: NousAuthService(store, env=source, clock=lambda: now[0]))
    return store, env, token


def test_explicit_opt_in_model_uses_account_only_and_refuses_role_key_or_base(monkeypatch, tmp_path):
    now = [1_800_000_000]
    store, env, token = _setup(monkeypatch, tmp_path, now)
    env["JARVIS_ROLE_VISION_MODEL"] = "anthropic/claude-vision"
    env["JARVIS_NOUS_ANTHROPIC_WIRE"] = "native"
    config = vision_nous.resolve_config(env)
    assert (config.backend, config.api_key, config.base_url, config.model) == (
        "nous", token, "https://inference-api.nousresearch.com/v1", "anthropic/claude-vision")
    assert config.wire_mode == "anthropic_messages"
    assert vision_nous.model_source(env) == "JARVIS_ROLE_VISION_MODEL"
    assert "vision_selection" not in store.read()

    env["JARVIS_ROLE_VISION_KEY"] = "wrong-key"
    with pytest.raises(VLMNotConfigured) as exc:
        vision_nous.resolve_config(env)
    assert exc.value.reason == "vlm_key_conflict"
    env.pop("JARVIS_ROLE_VISION_KEY")
    env["JARVIS_ROLE_VISION_BASE_URL"] = "https://attacker.example/v1"
    with pytest.raises(VLMNotConfigured) as exc:
        vision_nous.resolve_config(env)
    assert exc.value.reason == "vlm_url_invalid"


def test_prepare_persists_selection_for_pure_cross_instance_resolution(monkeypatch, tmp_path):
    now = [1_800_000_000]
    store, env, token = _setup(monkeypatch, tmp_path, now)
    calls = []
    async def recommend(credentials, **kwargs):
        calls.append(credentials)
        kwargs["validate"]()
        return Recommendation("google/gemini-3.6-flash", "nous_fallback")
    monkeypatch.setattr(vision_nous, "recommend_vision", recommend)
    with pytest.raises(VLMNotConfigured) as exc:
        vision_nous.resolve_config(env)
    assert exc.value.reason == "vlm_model_unset"
    prepared = asyncio.run(vision_nous.prepare_config(env))
    assert prepared.model == "google/gemini-3.6-flash" and prepared.api_key == token
    assert len(calls) == 1
    assert store.read()["vision_selection"]["model"] == prepared.model
    assert token not in repr(store.read()["vision_selection"])
    assert vision_nous.resolve_config(env).model == prepared.model
    assert vision_nous.model_source(env) == "nous_recommendation"


def test_rotation_logout_config_and_expiry_revoke_pure_selection(monkeypatch, tmp_path):
    now = [1_800_000_000]
    store, env, _ = _setup(monkeypatch, tmp_path, now)
    async def recommend(_credentials, **_kwargs):
        return Recommendation("google/gemini-3.6-flash", "nous_fallback")
    monkeypatch.setattr(vision_nous, "recommend_vision", recommend)
    asyncio.run(vision_nous.prepare_config(env))

    changed = dict(env, JARVIS_NOUS_ANTHROPIC_WIRE="native")
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(changed)
    with store.transaction() as state:
        state["refresh_token"] = "rotated-grant"
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(env)
    asyncio.run(vision_nous.prepare_config(env))
    with store.transaction() as state:
        state["access_token"] = _jwt(now[0] + 4000)
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(env)
    asyncio.run(vision_nous.prepare_config(env))
    now[0] += 4000
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(env)
    NousAuthService(store, env=env).logout()
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(env)


def test_welcome_host_forces_welcome_model_without_recommendation(monkeypatch, tmp_path):
    now = [1_800_000_000]
    _, env, _ = _setup(monkeypatch, tmp_path, now, base="https://welcome-api.nousresearch.com/v1")
    env["JARVIS_ROLE_VISION_MODEL"] = "anthropic/other"
    def forbidden(*_args, **_kwargs):
        raise AssertionError("recommendation must not run for welcome host")
    monkeypatch.setattr(vision_nous, "recommend_vision", forbidden)
    assert vision_nous.resolve_config(env).model == "nous/welcome"
    assert asyncio.run(vision_nous.prepare_config(env)).model == "nous/welcome"
    assert vision_nous.model_source(env) == "nous_welcome"


def test_newer_preparation_prevents_stale_concurrent_publication(monkeypatch, tmp_path):
    now = [1_800_000_000]
    store, env, _ = _setup(monkeypatch, tmp_path, now)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = [0]
    async def recommend(_credentials, **_kwargs):
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            await release.wait()
            return Recommendation("old-model", "nous_fallback")
        return Recommendation("new-model", "nous_fallback")
    monkeypatch.setattr(vision_nous, "recommend_vision", recommend)

    async def scenario():
        old = asyncio.create_task(vision_nous.prepare_config(env))
        await entered.wait()
        newer = await vision_nous.prepare_config(env)
        release.set()
        with pytest.raises(VLMNotConfigured):
            await old
        return newer

    newest = asyncio.run(scenario())
    assert newest.model == "new-model"
    assert vision_nous.resolve_config(env).model == "new-model"
    assert store.read()["vision_selection"]["model"] == "new-model"


def test_profile_isolation_and_live_config_drift_block_publication(monkeypatch, tmp_path):
    now = [1_800_000_000]
    store, env, _ = _setup(monkeypatch, tmp_path, now)
    env["JARVIS_ROLE_VISION_PROFILE"] = "other"
    with pytest.raises(VLMNotConfigured):
        vision_nous.resolve_config(env)
    with store.transaction("other") as state:
        state.update(access_token=_jwt(now[0] + 3600), refresh_token="other-grant",
                     scope="inference:invoke", portal_base_url="https://portal.nousresearch.com",
                     client_id="nerva-test-client",
                     inference_base_url="https://inference-api.nousresearch.com/v1")
    async def recommend(_credentials, **_kwargs):
        env["JARVIS_NOUS_ANTHROPIC_WIRE"] = "native"
        return Recommendation("google/gemini-3.6-flash", "nous_fallback")
    monkeypatch.setattr(vision_nous, "recommend_vision", recommend)
    with pytest.raises(VLMNotConfigured):
        asyncio.run(vision_nous.prepare_config(env))
    assert "vision_selection" not in store.read("other")
    assert "vision_selection" not in store.read("default")
