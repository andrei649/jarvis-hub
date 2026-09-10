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

from ..model_config import DEFAULT_CLAUDE_MODEL
from ..reasoning_effort import (
    clamp_reasoning_effort,
    supported_reasoning_efforts,
    vendor_efforts,
)


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
    # H364 — the reasoning-effort vocabulary this vendor can express, weakest
    # first. It is a vendor-level union: which rungs a *given* model accepts is
    # decided per request by `reasoning_effort.anthropic_capability`, because
    # the families under one vendor disagree. Empty means this build never
    # sends an effort parameter to the provider.
    reasoning_efforts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip().lower())
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "fallback_models", tuple(self.fallback_models))
        object.__setattr__(self, "reasoning_efforts", tuple(self.reasoning_efforts))
        if not self.id:
            raise ValueError("provider profile id is required")
        if not self.display_name:
            raise ValueError("provider profile display_name is required")
        if not self.backend_kind:
            raise ValueError("provider profile backend_kind is required")

    def supported_reasoning_efforts(self, model: str) -> tuple[str, ...] | None:
        """What *model* accepts under this provider — tri-state (H679).

        ``None`` means undeclared: nobody has told this build what the model
        takes, so a transport must keep the defaults it already had. ``()`` means
        declared empty — the model accepts no effort level and the field has to be
        omitted. A non-empty tuple is a vocabulary to clamp into, weakest first.

        The two ``None``-ish answers are not interchangeable, which is why this
        cannot be an attribute: ``reasoning_efforts`` below is the vendor-level
        union for display, and an empty one there says nothing about any model.
        Answered from cache; a cold catalog reads as undeclared rather than
        blocking a request to find out.
        """
        return supported_reasoning_efforts(self.id, model)

    def clamp_reasoning_effort(self, model: str, level: object) -> tuple[str | None, str]:
        """``(effort_to_send, reason)`` for *model* — the one canonical clamp.

        Nearest **weaker** supported rung, never an escalation. Providers do not
        get to hand-roll this: an inverted ladder is silent, and it is wrong in
        the expensive direction exactly when the owner asked for the cheap one.
        """
        return clamp_reasoning_effort(self.id, model, level)

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
            "reasoning_efforts": list(self.reasoning_efforts),
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
        fallback_models=(DEFAULT_CLAUDE_MODEL,),
        # Read from the same table the request path uses, so the profile cannot
        # advertise a rung the wire would reject.
        reasoning_efforts=vendor_efforts("anthropic"),
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
