"""Explicit OpenRouter vision resolution and provider-routing safety."""

import pytest

from agents.core.llm import model_roles, vision_openrouter
from agents.core.llm.vlm import VLMNotConfigured


def _env(**overrides):
    return {
        "JARVIS_ROLE_VISION_PROVIDER": "openrouter",
        "JARVIS_ROLE_VISION_MODEL": "vendor/vision-model",
        "OPENROUTER_API_KEY": "ambient-openrouter-key",
        **overrides,
    }


def test_explicit_openrouter_uses_canonical_base_and_ambient_key_only_there():
    config = vision_openrouter.resolve_config(_env())
    assert (config.backend, config.base_url, config.model, config.api_key, config.is_local) == (
        "openrouter", "https://openrouter.ai/api/v1", "vendor/vision-model",
        "ambient-openrouter-key", False,
    )
    role = model_roles.resolve("vision", _env())
    assert (role.provider_id, role.model, role.base_url, role.local) == (
        "openrouter", config.model, config.base_url, False,
    )
    assert role.source["base_url"] == "default"
    assert role.data_policy == "unknown"


def test_role_base_with_canonical_default_port_can_use_ambient_key():
    config = vision_openrouter.resolve_config(_env(
        JARVIS_ROLE_VISION_BASE_URL="https://openrouter.ai:443/api/v1"))
    assert config.api_key == "ambient-openrouter-key"


def test_foreign_origin_needs_dedicated_role_key():
    env = _env(JARVIS_ROLE_VISION_BASE_URL="https://proxy.example/api/v1")
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config(env)
    assert refused.value.reason == "vlm_key_unset"
    config = vision_openrouter.resolve_config({**env, "JARVIS_ROLE_VISION_KEY": "dedicated"})
    assert config.api_key == "dedicated"
    assert config.base_url == "https://proxy.example/api/v1"


def test_legacy_and_other_provider_keys_never_cross_into_openrouter():
    env = _env(OPENROUTER_API_KEY="", JARVIS_VLM_KEY="legacy",
               OPENAI_API_KEY="other", JARVIS_VLM_MODEL="legacy-model")
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config(env)
    assert refused.value.reason == "vlm_key_unset"
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config({**env, "JARVIS_ROLE_VISION_MODEL": ""})
    assert refused.value.reason == "vlm_model_unset"


def test_ambient_credentials_alone_do_not_select_a_vision_route():
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config({"OPENROUTER_API_KEY": "ambient",
                                          "JARVIS_ROLE_VISION_MODEL": "vendor/vision-model"})
    assert refused.value.reason == "vlm_disabled"


@pytest.mark.parametrize("name,value,reason", [
    ("JARVIS_ROLE_VISION_MODEL", "vision\nmodel", "vlm_model_invalid"),
    ("JARVIS_ROLE_VISION_MODEL", "a" * 513, "vlm_model_invalid"),
    ("JARVIS_ROLE_VISION_KEY", "key\r\nX-Header: injected", "vlm_key_invalid"),
])
def test_model_and_key_fields_are_bounded_and_header_safe(name, value, reason):
    env = _env(OPENROUTER_API_KEY="", JARVIS_ROLE_VISION_KEY="dedicated")
    env[name] = value
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config(env)
    assert refused.value.reason == reason
    assert value not in str(refused.value)


@pytest.mark.parametrize("base", [
    "http://remote.example/v1", "https://user:pass@proxy.example/v1",
    "https://proxy.example/v1?secret=x", "https://proxy.example/v1#part",
    "ftp://proxy.example/v1", "https://proxy.example:bad/v1",
    "https://proxy.example/v1\nX-Injected: yes",
])
def test_invalid_endpoint_refuses_without_echoing_its_value(base):
    with pytest.raises(VLMNotConfigured) as refused:
        vision_openrouter.resolve_config(_env(JARVIS_ROLE_VISION_BASE_URL=base,
                                               JARVIS_ROLE_VISION_KEY="dedicated"))
    assert refused.value.reason == "vlm_url_invalid"
    assert base not in str(refused.value)


def test_loopback_http_is_allowed_only_with_dedicated_key():
    env = _env(JARVIS_ROLE_VISION_BASE_URL="http://127.0.0.1:8888/v1",
               JARVIS_ROLE_VISION_KEY="dedicated")
    config = vision_openrouter.resolve_config(env)
    assert config.is_local is True and config.api_key == "dedicated"


def test_inherited_video_refuses_openrouter_with_specific_reason():
    route = model_roles.resolve_video_route(_env())
    assert route.role.configured is False
    assert route.role.reason == "video_vision_provider_unsupported"
    assert route.request_url == "" and route.inherited is False


def test_provider_block_defaults_to_data_collection_deny(monkeypatch):
    monkeypatch.setattr("agents.core.settings_db.read_setting", lambda category, key: (False, None))
    assert vision_openrouter.current_provider_block() == {"data_collection": "deny"}


def test_provider_block_preserves_all_valid_live_settings(monkeypatch):
    values = {"openrouter_sort": "latency", "openrouter_only": ["DeepInfra"],
              "openrouter_ignore": ["bad"], "openrouter_order": ["deepinfra"],
              "openrouter_require_parameters": True, "openrouter_data_collection": "deny"}
    monkeypatch.setattr("agents.core.settings_db.read_setting",
                        lambda category, key: (True, values[key]))
    assert vision_openrouter.current_provider_block() == {
        "sort": "latency", "only": ["deepinfra"], "ignore": ["bad"],
        "order": ["deepinfra"], "require_parameters": True,
        "data_collection": "deny",
    }


@pytest.mark.parametrize("key,value", [
    ("openrouter_data_collection", ""), ("openrouter_data_collection", None),
    ("openrouter_only", ""), ("openrouter_only", False),
    ("openrouter_require_parameters", 0),
])
def test_malformed_falsey_routing_settings_fail_closed(monkeypatch, key, value):
    monkeypatch.setattr("agents.core.settings_db.read_setting",
                        lambda category, name: (True, value) if name == key else (False, None))
    with pytest.raises(ValueError, match="openrouter_routing_invalid"):
        vision_openrouter.current_provider_block()


def test_unreadable_routing_settings_fail_closed_without_leaking_detail(monkeypatch):
    def unreadable(category, key):
        raise RuntimeError("secret database path /private/config")

    monkeypatch.setattr("agents.core.settings_db.read_setting", unreadable)
    with pytest.raises(ValueError) as refused:
        vision_openrouter.current_provider_block()
    assert str(refused.value) == "openrouter_routing_unavailable"
