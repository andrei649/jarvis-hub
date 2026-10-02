"""Opt-in vision auto selection over the existing, scoped provider adapters.

Only ``prepare_config`` may perform provider metadata I/O. Normal resolution
uses an explicitly supplied main route or locally available provider state.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace

from ..env_config import env_str
from . import vision_deepinfra, vision_nous, vision_openrouter
from .vision_openrouter import _validated_base

_OPENROUTER_FALLBACK_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
_SUPPORTED_MAIN = frozenset({"lmstudio", "ollama", "custom", "openrouter", "nous", "deepinfra", "anthropic", "gemini", "openai-responses"})
_UNAVAILABLE = frozenset({"vlm_key_unset", "vlm_model_unset"})
_AUTHORITY_KEYS = (
    "JARVIS_ROLE_VISION_PROVIDER", "JARVIS_ROLE_VISION_MODEL",
    "JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_KEY",
    "JARVIS_ROLE_VISION_PROFILE", "JARVIS_VLM_BACKEND", "JARVIS_VLM_URL",
    "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY", "JARVIS_VLM_PRESET",
    "OPENROUTER_API_KEY", "DEEPINFRA_API_KEY", "DEEPINFRA_BASE_URL",
    "JARVIS_NOUS_ANTHROPIC_WIRE", "JARVIS_NOUS_PORTAL_URL",
    "JARVIS_NOUS_INFERENCE_BASE_URL", "JARVIS_NOUS_CLIENT_ID",
)


def _read(env: Mapping[str, str] | None, name: str) -> str:
    return str(env.get(name, "") or "") if env is not None else env_str(name, "")


class _ProviderView(Mapping[str, str]):
    """Live provider scope; never snapshot credentials before an awaited lookup."""

    def __init__(self, env: Mapping[str, str] | None, provider: str):
        self.env = env
        self.provider = provider

    def __getitem__(self, key: str) -> str:
        if key == "JARVIS_ROLE_VISION_PROVIDER":
            return self.provider
        if self.provider in {"openrouter", "nous", "deepinfra"}:
            if key == "JARVIS_ROLE_VISION_KEY":
                # A role key is authority for an explicit endpoint, not for an
                # automatically discovered provider's canonical origin.
                return ""
            if key == "JARVIS_ROLE_VISION_BASE_URL":
                return ""
            if key == "JARVIS_ROLE_VISION_MODEL" and self.provider == "openrouter":
                return _read(self.env, key) or _OPENROUTER_FALLBACK_MODEL
        return _read(self.env, key)

    def __iter__(self) -> Iterator[str]:
        keys = set(self.env) if self.env is not None else set()
        keys.update(("JARVIS_ROLE_VISION_PROVIDER", "JARVIS_ROLE_VISION_KEY",
                     "JARVIS_ROLE_VISION_BASE_URL", "JARVIS_ROLE_VISION_MODEL"))
        return iter(keys)

    def __len__(self) -> int:
        return len(set(iter(self)))


def _snapshot(env: Mapping[str, str] | None) -> tuple[str, ...]:
    return tuple(_read(env, name) for name in _AUTHORITY_KEYS)


def _check_auto(env: Mapping[str, str] | None) -> None:
    from .vlm import VLMNotConfigured

    if _read(env, "JARVIS_ROLE_VISION_PROVIDER").strip().lower() != "auto":
        raise VLMNotConfigured("vlm_disabled")


def _role_model(env: Mapping[str, str] | None) -> str:
    from .vlm import VLMNotConfigured

    raw = _read(env, "JARVIS_ROLE_VISION_MODEL")
    if raw and (len(raw) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        raise VLMNotConfigured("vlm_model_invalid")
    return raw.strip()


def _override(env: Mapping[str, str] | None):
    from .vlm import VLMNotConfigured, resolve_vlm_config

    raw_base = _read(env, "JARVIS_ROLE_VISION_BASE_URL")
    if not raw_base:
        return None
    try:
        _validated_base(raw_base)
    except ValueError:
        raise VLMNotConfigured("vlm_url_invalid") from None
    if not _role_model(env):
        raise VLMNotConfigured("vlm_model_unset")
    config = resolve_vlm_config(_ProviderView(env, "openai-compatible"))
    if not config.api_key:
        raise VLMNotConfigured("vlm_key_unset")
    if len(config.api_key) > 4096 or any(ord(char) < 33 or ord(char) > 126
                                         for char in config.api_key):
        raise VLMNotConfigured("vlm_key_invalid")
    return replace(config, route_source="auto:override")


def _main(main_config, model: str):
    from .vlm import VLMConfig

    if (isinstance(main_config, VLMConfig) and main_config.backend in _SUPPORTED_MAIN
            and main_config.base_url and main_config.model):
        return replace(main_config, model=model or main_config.model, route_source="auto:main")
    return None


def _policy() -> None:
    from .vlm import VLMNotConfigured

    try:
        vision_openrouter.current_provider_block()
    except ValueError as exc:
        raise VLMNotConfigured(str(exc)) from None


def _candidate(provider: str, env: Mapping[str, str] | None):
    view = _ProviderView(env, provider)
    if provider == "openrouter":
        _policy()
        return vision_openrouter.resolve_config(view)
    if provider == "nous":
        return vision_nous.resolve_config(view)
    return vision_deepinfra.resolve_config(view)


def resolve_config(env: Mapping[str, str] | None = None, *, main_config=None):
    """Read the first available route without HTTP or OAuth refresh."""
    from .vlm import VLMNotConfigured

    _check_auto(env)
    model = _role_model(env)
    override = _override(env)
    if override is not None:
        return override
    main = _main(main_config, model)
    if main is not None:
        return main
    for provider in ("openrouter", "nous", "deepinfra"):
        try:
            config = _candidate(provider, env)
        except VLMNotConfigured as exc:
            if exc.reason in _UNAVAILABLE:
                continue
            raise
        return replace(config, route_source=f"auto:{provider}")
    raise VLMNotConfigured("vlm_model_unset")


async def prepare_config(env: Mapping[str, str] | None = None, *,
                         force_refresh: bool = False, main_config=None):
    """Prepare provider metadata in order, refusing changed authority on resume."""
    from .vlm import VLMNotConfigured

    _check_auto(env)
    model = _role_model(env)
    override = _override(env)
    if override is not None:
        return override
    main = _main(main_config, model)
    if main is not None:
        return main
    baseline = _snapshot(env)
    try:
        config = _candidate("openrouter", env)
    except VLMNotConfigured as exc:
        if exc.reason not in _UNAVAILABLE:
            raise
    else:
        return replace(config, route_source="auto:openrouter")
    for provider, module in (("nous", vision_nous), ("deepinfra", vision_deepinfra)):
        try:
            config = await module.prepare_config(
                _ProviderView(env, provider), force_refresh=force_refresh,
            )
        except VLMNotConfigured as exc:
            if _snapshot(env) != baseline:
                raise VLMNotConfigured("vlm_selection_changed") from None
            if exc.reason in _UNAVAILABLE:
                continue
            raise
        if _snapshot(env) != baseline:
            raise VLMNotConfigured("vlm_selection_changed")
        prepared = replace(config, route_source=f"auto:{provider}")
        try:
            current = resolve_config(env, main_config=main_config)
        except VLMNotConfigured:
            raise VLMNotConfigured("vlm_selection_changed") from None
        if current != prepared:
            raise VLMNotConfigured("vlm_selection_changed")
        return prepared
    raise VLMNotConfigured("vlm_model_unset")
