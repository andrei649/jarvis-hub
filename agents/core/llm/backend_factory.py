"""Construct real adapters from trusted provider declarations, without dispatch.

This map is a map of wire implementations, not a provider allowlist. A new
compatible provider needs a profile declaration only. An unsupported dialect
still needs a reviewed adapter. No policy, auth, install or readiness is inferred
from successful construction; the router governs actual selection and dispatch.
"""
from dataclasses import replace
from urllib.parse import urlsplit


class BackendUnavailable(ValueError):
    """The declared route cannot be constructed under its native wire contract."""


def _setting(settings, name, default=None):
    if settings is None:
        return default
    return settings(name, default) if callable(settings) else settings.get(name, default)


def _compatible(profile, key, base, model, settings, pool):
    from .openrouter import OpenRouterBackend
    from .provider_routing import provider_routing_from_settings
    caps = set(profile.capabilities)
    if _setting(settings, "compatible_reasoning_enabled", False):
        caps.add("reasoning-effort")
    if _setting(settings, "compatible_prompt_cache_key", False):
        caps.add("prompt-cache-key")
    profile = replace(profile, capabilities=frozenset(caps))
    return OpenRouterBackend(
        key, base_url=base, profile=profile,
        reasoning_effort=_setting(settings, "reasoning_effort", ""),
        effort_declarations=_setting(settings, "compatible_effort_declarations", ""),
        provider_routing=lambda: provider_routing_from_settings(
            lambda name, default: _setting(settings, name, default)),
    )


def _deepinfra(profile, key, base, model, settings, pool):
    from .deepinfra import DeepInfraBackend, validated_main_base
    return DeepInfraBackend(key, base_url=validated_main_base(base),
                           reasoning_effort=_setting(settings, "reasoning_effort", ""),
                           effort_declarations=_setting(settings, "compatible_effort_declarations", ""))


def _responses(profile, key, base, model, settings, pool):
    from .responses import ResponsesBackend
    if base.rstrip("/") != "https://api.openai.com/v1":
        raise BackendUnavailable("Responses requires its fixed OpenAI authority")
    return ResponsesBackend(key,
                            retention=_setting(settings, "responses_cache_retention", "in_memory"))


def _xai(profile, key, base, model, settings, pool):
    from .xai import XAIBackend
    if base.rstrip("/") != "https://api.x.ai/v1":
        raise BackendUnavailable("xAI requires its fixed authority")
    return XAIBackend(key, reasoning_effort=_setting(settings, "reasoning_effort", ""),
                      effort_declarations=_setting(settings, "compatible_effort_declarations", ""))


def _gemini(profile, key, base, model, settings, pool):
    from .gemini import GeminiBackend
    return GeminiBackend(key, model=model or profile.fallback_models[0], auth_pool=pool,
                         reasoning_effort=_setting(settings, "reasoning_effort", ""),
                         effort_declarations=_setting(settings, "gemini_effort_declarations", ""))


def _anthropic(profile, key, base, model, settings, pool):
    from .anthropic import ClaudeBackend
    return ClaudeBackend(key, model=model or profile.fallback_models[0], auth_pool=pool,
                         reasoning_effort=_setting(settings, "reasoning_effort", ""),
                         effort_overrides=_setting(settings, "reasoning_effort_overrides", ""))


def _local_chat(profile, key, base, model, settings, pool):
    from .base import LMStudioBackend
    return LMStudioBackend(base_url=base)


def _ollama(profile, key, base, model, settings, pool):
    from .base import OllamaBackend
    return OllamaBackend(base_url=base, num_ctx=_setting(settings, "ollama_num_ctx", 0))


_KINDS = {
    "openai-compatible": ("chat_completions", _compatible),
    "deepinfra-chat": ("chat_completions", _deepinfra),
    "openai-responses": ("responses", _responses),
    "xai-responses": ("responses", _xai),
    "gemini": ("gemini_generate_content", _gemini),
    "anthropic": ("anthropic_messages", _anthropic),
    "openai-compatible-local": ("chat_completions", _local_chat),
    "ollama": ("chat_completions", _ollama),
}


def supports_chat_profile(profile):
    kind = _KINDS.get(profile.backend_kind)
    return (kind is not None and profile.api_mode == kind[0] and "chat" in profile.capabilities
            and not ({"local", "cloud"} <= profile.capabilities))


def construct_backend(provider_id, *, model="", api_key=None, base_url=None, settings=None,
                      auth_pool=None, registry=None):
    """Construct one registered declaration. No auth or HTTP request is made."""
    from . import providers
    from .host_protocol import protocol_refusal

    registry = providers.DEFAULT_REGISTRY if registry is None else registry
    try:
        profile = registry.get(provider_id)
    except KeyError as exc:
        raise BackendUnavailable("provider declaration is unknown") from exc
    from .providers.admitted_profiles import AdmittedProviderProfile
    if isinstance(profile, AdmittedProviderProfile) and (
            profile.backend_kind != 'openai-compatible' or 'cloud' not in profile.capabilities
            or 'local' in profile.capabilities):
        raise BackendUnavailable('admitted native dialect has no async hook bridge')
    kind = _KINDS.get(profile.backend_kind)
    if not supports_chat_profile(profile):
        raise BackendUnavailable("provider has no compatible chat implementation")
    # Current main declares DeepInfra as OpenAI-compatible metadata, while its
    # reviewed physical client has stricter native destination and egress guards.
    if profile is next((item for item in providers.BUILTIN_PROFILES if item.id == "deepinfra"), None):
        kind = ("chat_completions", _deepinfra)
    base = profile.resolve_base_url() if base_url is None else base_url
    base = str(base or "").rstrip("/")
    if (isinstance(profile, AdmittedProviderProfile)
            and base != str(profile.default_base_url or '').rstrip('/')):
        raise BackendUnavailable('admitted provider destination differs from signed declaration')
    if isinstance(profile, AdmittedProviderProfile):
        try:
            destination = urlsplit(base)
            if (destination.scheme != "https" or not destination.hostname
                    or destination.username or destination.password
                    or destination.query or destination.fragment):
                raise BackendUnavailable("admitted provider requires a fixed HTTPS authority")
        except ValueError as exc:
            raise BackendUnavailable("admitted provider destination is invalid") from exc
    refusal = protocol_refusal(profile.id, base) if base else ""
    if refusal:
        raise BackendUnavailable(refusal)
    key = profile.auth_key() if api_key is None else api_key
    if profile.auth_type not in {"none", "subscription"} and not key and not getattr(auth_pool, "size", 0):
        raise BackendUnavailable("provider credential is not configured")
    try:
        return kind[1](profile, key or "", base, model, settings, auth_pool)
    except (ValueError, IndexError) as exc:
        from .provider_routing import ProviderRoutingInvalid
        if isinstance(exc, ProviderRoutingInvalid):
            raise BackendUnavailable("provider routing configuration refused") from exc
        raise BackendUnavailable("provider native construction refused") from exc
