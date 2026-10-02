"""Auto vision route selection with synthetic authority and no live provider I/O."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agents.core.llm import vision_deepinfra, vision_nous, vision_openrouter
from agents.core.llm.vlm import VLMConfig, VLMNotConfigured


def _env(**updates):
    return {"JARVIS_ROLE_VISION_PROVIDER": "auto", **updates}


def _config(backend: str, model: str = "example/vision") -> VLMConfig:
    return VLMConfig(backend, "https://example.test/v1", model, "scoped-key", False)


def test_pure_resolution_uses_openrouter_free_fallback_and_does_not_prepare(monkeypatch):
    from agents.core.llm import vision_auto

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: {"data_collection": "deny"})
    monkeypatch.setattr(vision_nous, "prepare_config",
                        lambda *a, **kw: pytest.fail("pure resolution prepared Nous"))
    monkeypatch.setattr(vision_deepinfra, "prepare_config",
                        lambda *a, **kw: pytest.fail("pure resolution prepared DeepInfra"))
    config = vision_auto.resolve_config(_env(OPENROUTER_API_KEY="canonical-key"))
    assert (config.backend, config.model, config.api_key, config.route_source) == (
        "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free",
        "canonical-key", "auto:openrouter")


def test_explicit_base_is_authoritative_and_requires_model_and_scoped_key(monkeypatch):
    from agents.core.llm import vision_auto

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: pytest.fail("explicit endpoint fell through"))
    env = _env(JARVIS_ROLE_VISION_BASE_URL="https://owner.example/v1",
               JARVIS_ROLE_VISION_MODEL="owner/vision",
               JARVIS_ROLE_VISION_KEY="owner-key", OPENROUTER_API_KEY="ambient-key")
    config = vision_auto.resolve_config(env)
    assert (config.backend, config.base_url, config.model, config.api_key,
            config.route_source) == (
                "custom", "https://owner.example/v1", "owner/vision", "owner-key",
                "auto:override")
    env.pop("JARVIS_ROLE_VISION_KEY")
    with pytest.raises(VLMNotConfigured) as exc:
        vision_auto.resolve_config(env)
    assert exc.value.reason == "vlm_key_unset"
    env["JARVIS_ROLE_VISION_KEY"] = "owner-key"
    env.pop("JARVIS_ROLE_VISION_MODEL")
    with pytest.raises(VLMNotConfigured) as exc:
        vision_auto.resolve_config(env)
    assert exc.value.reason == "vlm_model_unset"


def test_explicit_base_keeps_legacy_key_on_its_original_origin():
    from agents.core.llm import vision_auto

    env = _env(JARVIS_ROLE_VISION_BASE_URL="https://owner.example/v1/vision",
               JARVIS_ROLE_VISION_MODEL="owner/vision",
               JARVIS_VLM_URL="https://owner.example/legacy",
               JARVIS_VLM_KEY="legacy-owner-key")
    assert vision_auto.resolve_config(env).api_key == "legacy-owner-key"
    env["JARVIS_ROLE_VISION_BASE_URL"] = "https://other.example/v1"
    with pytest.raises(VLMNotConfigured) as exc:
        vision_auto.resolve_config(env)
    assert exc.value.reason == "vlm_key_unset"


@pytest.mark.asyncio
async def test_prepare_skips_unavailable_providers_in_order(monkeypatch):
    from agents.core.llm import vision_auto

    seen = []

    def openrouter(view):
        seen.append(("openrouter", view.get("JARVIS_ROLE_VISION_PROVIDER"),
                     view.get("JARVIS_ROLE_VISION_KEY")))
        raise VLMNotConfigured("vlm_key_unset")

    async def nous(view, *, force_refresh):
        seen.append(("nous", view.get("JARVIS_ROLE_VISION_PROVIDER"),
                     view.get("JARVIS_ROLE_VISION_KEY")))
        raise VLMNotConfigured("vlm_model_unset")

    async def deepinfra(view, *, force_refresh):
        seen.append(("deepinfra", view.get("JARVIS_ROLE_VISION_PROVIDER"),
                     view.get("JARVIS_ROLE_VISION_KEY")))
        return _config("deepinfra")

    monkeypatch.setattr(vision_openrouter, "resolve_config", openrouter)
    monkeypatch.setattr(vision_nous, "prepare_config", nous)
    monkeypatch.setattr(vision_deepinfra, "prepare_config", deepinfra)
    monkeypatch.setattr(vision_deepinfra, "resolve_config", lambda view: _config("deepinfra"))
    config = await vision_auto.prepare_config(_env(JARVIS_ROLE_VISION_KEY="role-only"))
    assert (config.backend, config.route_source) == ("deepinfra", "auto:deepinfra")
    assert seen[:3] == [("openrouter", "openrouter", ""), ("nous", "nous", ""),
                        ("deepinfra", "deepinfra", "")]


def test_malformed_provider_policy_refuses_without_fallback(monkeypatch):
    from agents.core.llm import vision_auto

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: (_ for _ in ()).throw(ValueError("openrouter_routing_invalid")))
    monkeypatch.setattr(vision_nous, "resolve_config",
                        lambda env: pytest.fail("malformed policy fell through"))
    with pytest.raises(VLMNotConfigured) as exc:
        vision_auto.resolve_config(_env(OPENROUTER_API_KEY="canonical-key"))
    assert exc.value.reason == "openrouter_routing_invalid"


@pytest.mark.asyncio
async def test_preparation_refuses_when_earlier_candidate_gains_credentials(monkeypatch):
    from agents.core.llm import vision_auto

    started = asyncio.Event()
    resume = asyncio.Event()

    async def nous(view, *, force_refresh):
        started.set()
        await resume.wait()
        return _config("nous")

    monkeypatch.setattr(vision_nous, "prepare_config", nous)
    monkeypatch.setattr(vision_nous, "resolve_config", lambda view: _config("nous"))
    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: {"data_collection": "deny"})
    env = _env()
    task = asyncio.create_task(vision_auto.prepare_config(env))
    await started.wait()
    env["OPENROUTER_API_KEY"] = "new-canonical-key"
    resume.set()
    with pytest.raises(VLMNotConfigured) as exc:
        await task
    assert exc.value.reason == "vlm_selection_changed"


def test_main_candidate_requires_an_explicit_selected_config(monkeypatch):
    from agents.core.llm import vision_auto

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: {"data_collection": "deny"})
    env = _env(OPENROUTER_API_KEY="canonical-key")
    assert vision_auto.resolve_config(env).route_source == "auto:openrouter"
    selected = _config("custom", "main/vision")
    config = vision_auto.resolve_config(env, main_config=selected)
    assert (config.backend, config.model, config.route_source) == (
        "custom", "main/vision", "auto:main")


def test_explicit_role_model_overrides_selected_main_model(monkeypatch):
    from agents.core.llm import vision_auto

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: pytest.fail("main route fell through"))
    config = vision_auto.resolve_config(
        _env(JARVIS_ROLE_VISION_MODEL="owner/vision"),
        main_config=_config("custom", "main/text"),
    )
    assert (config.model, config.route_source) == ("owner/vision", "auto:main")


@pytest.mark.asyncio
async def test_preparation_rechecks_higher_priority_account_state(monkeypatch):
    from agents.core.llm import vision_auto

    started = asyncio.Event()
    resume = asyncio.Event()
    state = {"nous_available": False}

    async def no_nous(view, *, force_refresh):
        raise VLMNotConfigured("vlm_model_unset")

    def current_nous(view):
        if state["nous_available"]:
            return _config("nous")
        raise VLMNotConfigured("vlm_model_unset")

    async def deepinfra(view, *, force_refresh):
        started.set()
        await resume.wait()
        return _config("deepinfra")

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: {"data_collection": "deny"})
    monkeypatch.setattr(vision_nous, "prepare_config", no_nous)
    monkeypatch.setattr(vision_nous, "resolve_config", current_nous)
    monkeypatch.setattr(vision_deepinfra, "prepare_config", deepinfra)
    monkeypatch.setattr(vision_deepinfra, "resolve_config", lambda view: _config("deepinfra"))
    task = asyncio.create_task(vision_auto.prepare_config(_env()))
    await started.wait()
    state["nous_available"] = True
    resume.set()
    with pytest.raises(VLMNotConfigured) as exc:
        await task
    assert exc.value.reason == "vlm_selection_changed"


@pytest.mark.asyncio
async def test_auto_prepares_deepinfra_through_scoped_catalog_transport(monkeypatch):
    from agents.core.llm import vision_auto

    def no_nous(view, **kwargs):
        raise VLMNotConfigured("vlm_key_unset")

    requests = []

    def catalog(request):
        requests.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"data": [
            {"id": "org/vision", "metadata": {"tags": ["chat", "vision"]}},
        ]})

    monkeypatch.setattr(vision_openrouter, "current_provider_block",
                        lambda: {"data_collection": "deny"})
    monkeypatch.setattr(vision_nous, "prepare_config", no_nous)
    monkeypatch.setattr(vision_nous, "resolve_config", no_nous)
    monkeypatch.setattr(vision_deepinfra, "_metadata_transport_factory",
                        lambda: httpx.MockTransport(catalog))
    vision_deepinfra.clear_cache()
    try:
        config = await vision_auto.prepare_config(_env(DEEPINFRA_API_KEY="deepinfra-scoped-key"))
        assert (config.backend, config.model, config.route_source) == (
            "deepinfra", "org/vision", "auto:deepinfra")
        assert requests == [(
            "https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes",
            "Bearer deepinfra-scoped-key",
        )]
    finally:
        vision_deepinfra.clear_cache()
