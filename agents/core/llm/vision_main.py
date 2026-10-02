"""Convert a selected conversation backend to its scoped vision authority.

This is a pure adapter for a prepared turn. The caller must pass the backend,
model and route returned by ``HybridRouter.select_backend`` for that same turn.
It never reads ambient configuration or constructs a transport.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .anthropic import ANTHROPIC_API_BASE, ClaudeBackend
from .base import LMStudioBackend, OllamaBackend
from .gemini import GEMINI_API_BASE, GeminiBackend
from .job_selection import _ScopedBackend
from .openrouter import OpenRouterBackend
from .responses import ENDPOINT as RESPONSES_ENDPOINT
from .responses import MODELS as RESPONSES_MODELS
from .responses import ResponsesBackend
from .vision_openrouter import _validated_base
from .vision_xai_wire import XAI_ENDPOINT
from .vlm import VLMConfig, VLMNotConfigured
from .xai import XAIBackend


def _model(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VLMNotConfigured("vlm_model_unset")
    if len(value) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise VLMNotConfigured("vlm_model_invalid")
    return value.strip()


def _base(value: object) -> tuple[str, bool]:
    if not isinstance(value, str):
        raise VLMNotConfigured("vlm_url_invalid")
    try:
        base, local, _origin = _validated_base(value)
    except ValueError:
        raise VLMNotConfigured("vlm_url_invalid") from None
    return base, local


def selected_main_config(backend: object, model: str, route: str) -> VLMConfig | None:
    """Use only the selected backend's own endpoint, profile and credential.

    Native backends without a reviewed image wire return ``None``.
    A scoped job wrapper is refused because its lifetime cannot safely be
    carried into a later image request by this synchronous adapter.
    """
    if isinstance(backend, _ScopedBackend):
        raise VLMNotConfigured("vlm_scoped_backend_unsupported")
    if type(backend) is XAIBackend:
        from .providers import DEFAULT_REGISTRY

        if route != "cloud-compatible":
            raise VLMNotConfigured("vlm_xai_route_unsupported")
        selected_model = _model(model)
        profile = DEFAULT_REGISTRY.get("xai")
        if selected_model not in profile.fallback_models:
            raise VLMNotConfigured("vlm_model_unsupported")
        key = backend.api_key
        if (not isinstance(key, str) or not key or len(key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in key)
                or backend.endpoint != XAI_ENDPOINT
                or getattr(backend.profile, "id", None) != "xai"):
            raise VLMNotConfigured("vlm_xai_authority_invalid")
        level, reason = backend.profile.clamp_reasoning_effort(
            selected_model, backend.reasoning_effort,
        )
        if reason == "below-minimum":
            raise VLMNotConfigured("vlm_reasoning_unavailable")
        return VLMConfig(
            backend="xai", base_url=XAI_ENDPOINT.removesuffix("/responses"),
            model=selected_model, api_key=key, is_local=False, wire_mode="xai_responses",
            reasoning_effort=level or "", route_source="auto:main",
        )
    # xAI subclasses ResponsesBackend but has a different model, response
    # envelope and data policy. It can still use the existing dedicated fallback.
    if type(backend) is ResponsesBackend:
        if route != "cloud-compatible":
            raise VLMNotConfigured("vlm_responses_route_unsupported")
        selected_model = _model(model)
        if selected_model not in RESPONSES_MODELS:
            raise VLMNotConfigured("vlm_model_unsupported")
        key = backend.api_key
        if (not isinstance(key, str) or not key or len(key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in key)
                or backend.endpoint != RESPONSES_ENDPOINT
                or backend.retention not in {"in_memory", "24h"}):
            raise VLMNotConfigured("vlm_responses_authority_invalid")
        return VLMConfig(
            backend="openai-responses", base_url=RESPONSES_ENDPOINT.removesuffix("/responses"),
            model=selected_model, api_key=key, is_local=False, wire_mode="responses",
            prompt_cache_retention=backend.retention, route_source="auto:main",
        )
    if isinstance(backend, ClaudeBackend):
        if route != "claude":
            raise VLMNotConfigured("vlm_route_invalid")
        selected_model = _model(model)
        key = backend._active_key()
        if not isinstance(key, str) or not key:
            raise VLMNotConfigured("vlm_key_unset")
        if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise VLMNotConfigured("vlm_key_invalid")
        return VLMConfig(
            backend="anthropic", base_url=ANTHROPIC_API_BASE, model=selected_model,
            api_key=key, is_local=False, wire_mode="anthropic_messages",
            route_source="auto:main",
        )
    if isinstance(backend, GeminiBackend):
        if route not in {"cloud", "cloud-fallback", "cloud-flash", "cloud-pro"}:
            raise VLMNotConfigured("vlm_route_invalid")
        selected_model = _model(model)
        from .video_native import VideoNativeRefused, gemini_request_url
        try:
            gemini_request_url(GEMINI_API_BASE, selected_model)
            key = backend.acquire_lease().api_key
        except (VideoNativeRefused, RuntimeError):
            raise VLMNotConfigured("vlm_gemini_authority_invalid") from None
        if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise VLMNotConfigured("vlm_key_invalid")
        return VLMConfig(
            backend="gemini", base_url=GEMINI_API_BASE, model=selected_model,
            api_key=key, is_local=False, wire_mode="gemini_generate_content",
            route_source="auto:main",
        )
    if isinstance(backend, OllamaBackend):
        if not isinstance(route, str) or not route.startswith("local"):
            raise VLMNotConfigured("vlm_route_invalid")
        selected_model = _model(model)
        base, local = _base(getattr(backend, "base_url", None))
        return VLMConfig(
            backend="ollama", base_url=base, model=selected_model,
            api_key="", is_local=local, wire_mode="ollama_chat",
            route_source="auto:main",
        )
    if isinstance(backend, LMStudioBackend):
        if not isinstance(route, str) or not route.startswith("local"):
            raise VLMNotConfigured("vlm_route_invalid")
        selected_model = _model(model)
        base, local = _base(getattr(backend, "base_url", None))
        if not local:
            raise VLMNotConfigured("vlm_locality_invalid")
        parts = urlsplit(base)
        return VLMConfig(
            backend="lmstudio", base_url=f"{parts.scheme}://{parts.netloc}/v1",
            model=selected_model, api_key="", is_local=True, route_source="auto:main",
        )
    if isinstance(backend, OpenRouterBackend):
        profile_id = getattr(getattr(backend, "profile", None), "id", None)
        if profile_id not in {"openrouter", "openai-compatible"}:
            raise VLMNotConfigured("vlm_profile_unsupported")
        if route != "cloud-compatible":
            raise VLMNotConfigured("vlm_route_invalid")
        selected_model = _model(model)
        base, local = _base(getattr(backend, "base_url", None))
        if local:
            # The current vision policy infers loopback locality from URL.
            # A compatible profile can be a remote proxy behind that URL;
            # do not issue a contradictory config before that is modeled.
            raise VLMNotConfigured("vlm_proxy_locality_unproven")
        key = getattr(backend, "api_key", None)
        if not isinstance(key, str) or not key:
            raise VLMNotConfigured("vlm_key_unset")
        if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise VLMNotConfigured("vlm_key_invalid")
        return VLMConfig(
            backend="openrouter" if profile_id == "openrouter" else "custom",
            base_url=base, model=selected_model, api_key=key,
            is_local=False, route_source="auto:main",
        )
    return None
