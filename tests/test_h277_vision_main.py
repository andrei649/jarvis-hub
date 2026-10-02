"""Selected-turn vision authority comes from the selected backend instance."""

from types import SimpleNamespace

import pytest

from agents.core.llm.base import LMStudioBackend
from agents.core.llm.job_selection import scoped_backend, selection_scope
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.vlm import VLMNotConfigured
from agents.core.llm.vision_main import selected_main_config


def _local(base="http://127.0.0.1:1234"):
    # Construct only the selected route state; never open a transport.
    backend = object.__new__(LMStudioBackend)
    backend.base_url = base
    return backend


def _compatible(profile="openrouter", base="https://openrouter.ai/api/v1", key="selected-key"):
    return OpenRouterBackend(
        api_key=key, base_url=base, client=object(), profile=DEFAULT_REGISTRY.get(profile)
    )


def _reason(backend, model="vendor/vision", route="cloud-compatible"):
    with pytest.raises(VLMNotConfigured) as refused:
        selected_main_config(backend, model, route)
    return refused.value.reason


def test_selected_lmstudio_uses_its_loopback_origin_and_exact_model():
    config = selected_main_config(_local("http://localhost:2345/private"), "local/vision", "local-deep")
    assert (config.backend, config.base_url, config.model, config.api_key,
            config.is_local, config.route_source) == (
                "lmstudio", "http://localhost:2345/v1", "local/vision", "", True, "auto:main")


def test_selected_compatible_uses_its_own_endpoint_key_and_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-other-key")
    backend = _compatible("openai-compatible", "https://owner.example/v1", "owner-key")
    config = selected_main_config(backend, "owner/vision", "cloud-compatible")
    assert (config.backend, config.base_url, config.model, config.api_key,
            config.is_local, config.route_source) == (
                "custom", "https://owner.example/v1", "owner/vision", "owner-key", False,
                "auto:main")


def test_selected_openrouter_keeps_key_scoped_to_selected_proxy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "canonical-key")
    backend = _compatible(base="https://proxy.example/api/v1", key="proxy-key")
    config = selected_main_config(backend, "proxy/vision", "cloud-compatible")
    assert (config.backend, config.base_url, config.api_key, config.model) == (
        "openrouter", "https://proxy.example/api/v1", "proxy-key", "proxy/vision")


def test_ambient_key_cannot_fill_missing_selected_proxy_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "canonical-key")
    assert _reason(_compatible(base="https://proxy.example/api/v1", key="")) == "vlm_key_unset"


@pytest.mark.parametrize("profile", ["openai-compatible", "openrouter"])
def test_compatible_loopback_proxy_refuses_until_locality_can_be_represented(profile):
    backend = _compatible(profile, "http://127.0.0.1:8899/v1", "proxy-key")
    assert _reason(backend) == "vlm_proxy_locality_unproven"


def test_conversion_never_calls_transport_or_provider_policy(monkeypatch):
    from agents.core.llm import vision_openrouter

    def unexpected(*_args, **_kwargs):
        pytest.fail("selected-main conversion attempted I/O or policy lookup")

    monkeypatch.setattr(vision_openrouter, "current_provider_block", unexpected)
    monkeypatch.setattr("httpx.AsyncClient.post", unexpected)
    config = selected_main_config(_compatible(), "vendor/vision", "cloud-compatible")
    assert config.route_source == "auto:main"


def test_remote_lmstudio_and_mismatched_route_refuse():
    assert _reason(_local("https://remote.example"), route="local") == "vlm_locality_invalid"
    assert _reason(_local(), route="cloud-compatible") == "vlm_route_invalid"
    assert _reason(_compatible(), route="local") == "vlm_route_invalid"


def test_selected_lmstudio_requires_a_valid_base():
    assert _reason(_local(""), route="local") == "vlm_url_invalid"


def test_compatible_backend_with_other_profile_refuses_explicitly():
    backend = _compatible()
    backend.profile = SimpleNamespace(id="xai")
    assert _reason(backend) == "vlm_profile_unsupported"


@pytest.mark.parametrize("backend", [object(), SimpleNamespace(base_url="https://example.test")])
def test_native_or_unknown_backends_have_no_chat_completions_vision_wire(backend):
    assert selected_main_config(backend, "vision", "cloud") is None


@pytest.mark.parametrize("model,reason", [
    ("", "vlm_model_unset"),
    ("bad\nmodel", "vlm_model_invalid"),
    ("x" * 513, "vlm_model_invalid"),
])
def test_selected_model_must_be_bounded_and_safe(model, reason):
    assert _reason(_compatible(), model=model) == reason


@pytest.mark.parametrize("base", [
    "", "http://remote.example/v1", "https://user:pass@proxy.example/v1",
    "https://proxy.example/v1?token=x", "https://proxy.example:bad/v1",
])
def test_selected_compatible_endpoint_must_be_safe(base):
    assert _reason(_compatible(base=base)) == "vlm_url_invalid"


@pytest.mark.parametrize("key,reason", [
    ("", "vlm_key_unset"),
    ("bad\r\nHeader: injected", "vlm_key_invalid"),
    ("x" * 4097, "vlm_key_invalid"),
])
def test_selected_key_must_be_present_and_header_safe(key, reason):
    assert _reason(_compatible(key=key)) == reason


def test_scoped_job_selection_refuses_explicitly_even_while_live():
    with selection_scope({"model": "job/vision"}):
        wrapped = scoped_backend(_local(), "job/vision")
        assert _reason(wrapped, model="job/vision", route="local") == "vlm_scoped_backend_unsupported"
    assert _reason(wrapped, model="job/vision", route="local") == "vlm_scoped_backend_unsupported"
