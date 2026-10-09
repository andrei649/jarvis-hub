"""DeepInfra's declarative profile and pure H277 role integration."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.llm import model_roles
from agents.core.llm.providers import get_profile
from agents.core.llm.vlm import VLMConfig


def _env(**overrides: str) -> dict[str, str]:
    return {
        "JARVIS_ROLE_VISION_PROVIDER": "deepinfra",
        "JARVIS_ROLE_VISION_MODEL": "acme/vision",
        "DEEPINFRA_API_KEY": "ambient-key",
        **overrides,
    }


def test_profile_claims_reviewed_chat_vision_catalog_and_cloud():
    profile = get_profile("deepinfra")
    assert profile.backend_kind == "openai-compatible"
    assert profile.auth_type == "bearer"
    assert profile.auth_env == "DEEPINFRA_API_KEY"
    assert profile.default_base_url == "https://api.deepinfra.com/v1/openai"
    assert profile.base_url_env == "DEEPINFRA_BASE_URL"
    assert profile.capabilities == frozenset({"chat", "vision", "model-catalog", "cloud"})
    assert profile.fallback_models == ()
    assert profile.data_policy == "unknown"


def test_vision_role_matches_native_config_and_explicit_provenance():
    from agents.core.llm.vision_deepinfra import resolve_config

    env = _env()
    config = resolve_config(env)
    role = model_roles.resolve("vision", env)
    assert role.configured is True
    assert (role.provider_id, role.model, role.base_url, role.local, role.data_policy) == (
        "deepinfra", config.model, config.base_url, config.is_local, "unknown",
    )
    assert role.source == {
        "provider": "JARVIS_ROLE_VISION_PROVIDER",
        "model": "JARVIS_ROLE_VISION_MODEL",
        "base_url": "default",
    }
    assert role.reason == ""


def test_catalog_source_and_provider_base_are_reported_without_discovery(monkeypatch):
    from agents.core.llm import vision_deepinfra

    env = _env(JARVIS_ROLE_VISION_MODEL="", DEEPINFRA_BASE_URL="https://proxy.example/v1",
               JARVIS_ROLE_VISION_KEY="dedicated-key")
    # Role reads must use the pure cached resolver, never prepare the catalog.
    monkeypatch.setattr(vision_deepinfra, "prepare_config", lambda *a, **kw: pytest.fail("I/O"))
    monkeypatch.setattr(vision_deepinfra, "resolve_config",
                        lambda _: VLMConfig("deepinfra", "https://proxy.example/v1",
                                            "served/vision", "dedicated-key", False))
    role = model_roles.resolve("vision", env)
    assert role.model == "served/vision"
    assert role.source == {
        "provider": "JARVIS_ROLE_VISION_PROVIDER",
        "model": "deepinfra_catalog",
        "base_url": "DEEPINFRA_BASE_URL",
    }


def test_role_uses_only_catalog_selection_cached_for_the_current_key(monkeypatch):
    from agents.core.llm import vision_deepinfra

    env = _env(JARVIS_ROLE_VISION_MODEL="")
    vision_deepinfra.clear_cache()

    async def catalog(*_args):
        return "catalog/vision"

    monkeypatch.setattr(vision_deepinfra, "_fetch_catalog", catalog)
    try:
        cold = model_roles.resolve("vision", env)
        assert cold.configured is False and cold.reason == "vlm_model_unset"
        asyncio.run(vision_deepinfra.prepare_config(env))
        warm = model_roles.resolve("vision", env)
        assert warm.configured is True and warm.model == "catalog/vision"
        assert warm.source["model"] == "deepinfra_catalog"
        rotated = model_roles.resolve("vision", {**env, "DEEPINFRA_API_KEY": "new-key"})
        assert rotated.configured is False and rotated.reason == "vlm_model_unset"
    finally:
        vision_deepinfra.clear_cache()


def test_legacy_vision_values_are_ignored_even_when_deepinfra_is_incomplete():
    env = _env(JARVIS_ROLE_VISION_MODEL="", DEEPINFRA_API_KEY="",
               JARVIS_VLM_BACKEND="lmstudio", JARVIS_VLM_URL="http://localhost:1234/v1",
               JARVIS_VLM_MODEL="legacy-vision", JARVIS_VLM_KEY="legacy-key",
               JARVIS_VLM_PRESET="qwen2-vl")
    role = model_roles.resolve("vision", env)
    assert role.configured is False
    assert role.reason in {"vlm_model_unset", "vlm_key_unset", "vlm_catalog_unavailable"}
    assert set(role.ignored) >= {
        "JARVIS_VLM_BACKEND", "JARVIS_VLM_URL", "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY",
        "JARVIS_VLM_PRESET",
    }
    assert role.source["model"] == "deepinfra_catalog"
    assert role.model == ""


def test_role_base_precedes_provider_base_and_data_stays_secret_free():
    env = _env(DEEPINFRA_BASE_URL="https://proxy.example/v1",
               JARVIS_ROLE_VISION_BASE_URL="https://second.example/v1",
               JARVIS_ROLE_VISION_KEY="dedicated-key")
    role = model_roles.resolve("vision", env)
    assert role.configured is True
    assert role.base_url == "https://second.example/v1"
    assert role.source["base_url"] == "JARVIS_ROLE_VISION_BASE_URL"
    assert "DEEPINFRA_BASE_URL" in role.ignored
    assert "dedicated-key" not in repr(role)
    assert "ambient-key" not in repr(model_roles.describe(env))


def test_custom_origin_refusal_is_the_native_resolver_refusal():
    from agents.core.llm.vision_deepinfra import resolve_config
    from agents.core.llm.vlm import VLMNotConfigured

    env = _env(JARVIS_ROLE_VISION_BASE_URL="https://proxy.example/v1")
    with pytest.raises(VLMNotConfigured) as refused:
        resolve_config(env)
    role = model_roles.resolve("vision", env)
    assert role.configured is False
    assert role.reason == refused.value.reason == "vlm_key_unset"
    assert role.source["base_url"] == "JARVIS_ROLE_VISION_BASE_URL"


def test_inherited_video_refuses_deepinfra():
    route = model_roles.resolve_video_route(_env())
    assert route.role.configured is False
    assert route.role.reason == "video_vision_provider_unsupported"
    assert route.request_url == ""
    assert route.inherited is False


def test_deepinfra_does_not_expand_other_role_backend_sets():
    assert "deepinfra" in model_roles.ROLES["vision"].providers
    assert "deepinfra" not in model_roles.ROLES["video"].providers
    assert "deepinfra" not in model_roles.ROLES["approval_judge"].providers
    with pytest.raises(model_roles.RoleConfigError) as refused:
        model_roles.resolve("approval_judge", {
            "JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER": "deepinfra",
            "JARVIS_ROLE_APPROVAL_JUDGE_MODEL": "acme/vision",
        })
    assert refused.value.reason == "role_provider_unsupported"
