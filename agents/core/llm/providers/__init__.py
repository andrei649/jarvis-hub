"""Declarative LLM provider profiles.

This is the lite Hermes-style provider registry: it describes known providers,
their auth shape, base URL knobs, capabilities, and fallback model hints without
creating clients or changing routing decisions. Runtime routing remains owned by
``HybridRouter`` and the existing backend classes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderProfile:
    """Static provider metadata safe to expose in status/UI surfaces."""

    id: str
    display_name: str
    backend_kind: str
    auth_type: str = "none"
    auth_env: str | None = None
    default_base_url: str | None = None
    base_url_env: str | None = None
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"chat"}))
    fallback_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip().lower())
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "fallback_models", tuple(self.fallback_models))
        if not self.id:
            raise ValueError("provider profile id is required")
        if not self.display_name:
            raise ValueError("provider profile display_name is required")
        if not self.backend_kind:
            raise ValueError("provider profile backend_kind is required")

    def status(self, environ: Mapping[str, str] | None = None) -> dict:
        """Return public configuration status without exposing secret values."""

        env = os.environ if environ is None else environ
        auth_configured = (
            self.auth_type == "none"
            or bool(self.auth_env and str(env.get(self.auth_env, "")).strip())
        )
        base_url = (
            str(env.get(self.base_url_env, "")).strip()
            if self.base_url_env else ""
        ) or self.default_base_url
        return {
            "id": self.id,
            "display_name": self.display_name,
            "backend_kind": self.backend_kind,
            "configured": bool(auth_configured),
            "auth": {
                "type": self.auth_type,
                "env": self.auth_env,
                "configured": bool(auth_configured),
            },
            "base_url": base_url,
            "base_url_env": self.base_url_env,
            "capabilities": sorted(self.capabilities),
            "fallback_models": list(self.fallback_models),
        }


class ProviderRegistry:
    """In-memory registry for provider profiles."""

    def __init__(self, profiles: list[ProviderProfile] | tuple[ProviderProfile, ...] = ()):
        self._profiles: dict[str, ProviderProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ProviderProfile) -> ProviderProfile:
        key = profile.id.strip().lower()
        if key in self._profiles:
            raise ValueError(f"duplicate provider profile: {key}")
        self._profiles[key] = profile
        return profile

    def get(self, provider_id: str) -> ProviderProfile:
        key = str(provider_id or "").strip().lower()
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise KeyError(f"unknown provider profile: {key}") from exc

    def list(self) -> list[ProviderProfile]:
        return list(self._profiles.values())

    def catalog(self, environ: Mapping[str, str] | None = None) -> list[dict]:
        return [profile.status(environ=environ) for profile in self.list()]


BUILTIN_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        id="lm-studio",
        display_name="LM Studio",
        backend_kind="openai-compatible-local",
        default_base_url="http://localhost:1234",
        base_url_env="JARVIS_LM_STUDIO_URL",
        capabilities=frozenset({"chat", "streaming", "local"}),
    ),
    ProviderProfile(
        id="ollama",
        display_name="Ollama",
        backend_kind="ollama",
        default_base_url="http://localhost:11434",
        base_url_env="JARVIS_OLLAMA_URL",
        capabilities=frozenset({"chat", "streaming", "local"}),
    ),
    ProviderProfile(
        id="gemini",
        display_name="Google Gemini",
        backend_kind="gemini",
        auth_type="api-key",
        auth_env="GEMINI_API_KEY",
        capabilities=frozenset({"chat", "long-context", "cloud"}),
        fallback_models=("gemini-2.5-flash", "gemini-2.5-pro"),
    ),
    ProviderProfile(
        id="anthropic",
        display_name="Anthropic Claude",
        backend_kind="anthropic",
        auth_type="api-key",
        auth_env="ANTHROPIC_API_KEY",
        capabilities=frozenset({"chat", "reasoning", "cloud"}),
        fallback_models=("claude-sonnet-4-20250514",),
    ),
    ProviderProfile(
        id="openrouter",
        display_name="OpenRouter",
        backend_kind="openai-compatible",
        auth_type="bearer",
        auth_env="OPENROUTER_API_KEY",
        default_base_url="https://openrouter.ai/api/v1",
        base_url_env="OPENROUTER_BASE_URL",
        capabilities=frozenset({"chat", "model-catalog", "cloud"}),
    ),
    ProviderProfile(
        id="openai-compatible",
        display_name="Custom OpenAI-Compatible",
        backend_kind="openai-compatible",
        auth_type="bearer",
        auth_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        capabilities=frozenset({"chat", "streaming", "cloud"}),
    ),
)

BUILTIN_PROVIDER_IDS = tuple(profile.id for profile in BUILTIN_PROFILES)
DEFAULT_REGISTRY = ProviderRegistry(BUILTIN_PROFILES)


def get_profile(provider_id: str) -> ProviderProfile:
    return DEFAULT_REGISTRY.get(provider_id)


def list_profiles() -> list[ProviderProfile]:
    return DEFAULT_REGISTRY.list()


def provider_catalog(environ: Mapping[str, str] | None = None) -> list[dict]:
    return DEFAULT_REGISTRY.catalog(environ=environ)


__all__ = [
    "BUILTIN_PROFILES",
    "BUILTIN_PROVIDER_IDS",
    "DEFAULT_REGISTRY",
    "ProviderProfile",
    "ProviderRegistry",
    "get_profile",
    "list_profiles",
    "provider_catalog",
]
