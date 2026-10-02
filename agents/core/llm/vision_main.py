"""Convert a selected conversation backend to its scoped vision authority.

This is a pure adapter for a prepared turn. The caller must pass the backend,
model and route returned by ``HybridRouter.select_backend`` for that same turn.
It never reads ambient configuration or constructs a transport.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .base import LMStudioBackend, OllamaBackend
from .job_selection import _ScopedBackend
from .openrouter import OpenRouterBackend
from .vision_openrouter import _validated_base
from .vlm import VLMConfig, VLMNotConfigured


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

    Native backends without this chat-completions image wire return ``None``.
    A scoped job wrapper is refused because its lifetime cannot safely be
    carried into a later image request by this synchronous adapter.
    """
    if isinstance(backend, _ScopedBackend):
        raise VLMNotConfigured("vlm_scoped_backend_unsupported")
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
