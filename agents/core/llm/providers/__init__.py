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
from fnmatch import fnmatchcase
from types import MappingProxyType

from ..model_config import DEFAULT_CLAUDE_MODEL
from ..reasoning_effort import (
    _model_key,
    clamp_reasoning_effort,
    clamp_vocabulary,
    normalize_efforts,
    supported_reasoning_efforts,
    vendor_efforts,
)

#: H378 — what a vendor does with the prompts it is sent, as its published API terms say.
#: ``local`` never leaves the machine; ``trains-on-inputs`` needs the owner's
#: acknowledgement before it is chosen (agents/core/llm/selection_guards.py).
DATA_POLICIES = ("local", "no-training", "trains-on-inputs", "unknown")


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
    # None preserves legacy registry lookup; a mapping is a backend-owned
    # snapshot, where missing models are undeclared, never global fallbacks.
    reasoning_declarations: Mapping[str, tuple[str, ...]] | None = field(
        default=None, repr=False, compare=False,
    )
    # H378 — one of DATA_POLICIES for the provider, with a note that says why, and
    # (pattern, policy, note) rows for models the provider serves differently: an
    # OpenRouter ``:free`` variant is served by providers that may train on prompts.
    data_policy: str = "unknown"
    data_policy_note: str = ""
    data_policy_models: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip().lower())
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "fallback_models", tuple(self.fallback_models))
        object.__setattr__(self, "reasoning_efforts", tuple(self.reasoning_efforts))
        object.__setattr__(self, "data_policy_models", tuple(tuple(row) for row in self.data_policy_models))
        if self.data_policy not in DATA_POLICIES or any(row[1] not in DATA_POLICIES for row in self.data_policy_models):
            raise ValueError(f"provider profile data_policy must be one of {DATA_POLICIES}")
        if self.reasoning_declarations is not None:
            object.__setattr__(self, "reasoning_declarations", MappingProxyType({
                _model_key(model): normalize_efforts(levels)
                for model, levels in self.reasoning_declarations.items()
            }))
        if not self.id:
            raise ValueError("provider profile id is required")
        if not self.display_name:
            raise ValueError("provider profile display_name is required")
        if not self.backend_kind:
            raise ValueError("provider profile backend_kind is required")

    def data_policy_for(self, model: str) -> tuple[str, str]:
        """``(policy, note)`` for *model* under this provider: the first matching model
        row (case-insensitive glob), else the provider's own."""
        name = str(model or "").strip().lower()
        for pattern, policy, note in self.data_policy_models:
            if name and fnmatchcase(name, pattern.lower()):
                return policy, note
        return self.data_policy, self.data_policy_note

    @property
    def supports_prompt_cache_key(self) -> bool:
        return "prompt-cache-key" in self.capabilities

    def supported_reasoning_efforts(self, model: str) -> tuple[str, ...] | None:
        """What *model* accepts under this provider — tri-state (H679).

        ``None`` means undeclared: nobody has told this build what the model
        takes, so a transport must keep the defaults it already had. ``()`` means
        declared empty — omit all reasoning parameters. A non-empty tuple lists
        product reasoning levels, weakest first; adapters map them to their actual
        wire schema (an effort field or a token budget).

        The two ``None``-ish answers are not interchangeable, which is why this
        cannot be an attribute: ``reasoning_efforts`` below is the vendor-level
        union for display, and an empty one there says nothing about any model.
        Answered from cache; a cold catalog reads as undeclared rather than
        blocking a request to find out.
        """
        if self.reasoning_declarations is not None:
            return self.reasoning_declarations.get(_model_key(model))
        return supported_reasoning_efforts(self.id, model)

    def clamp_reasoning_effort(self, model: str, level: object) -> tuple[str | None, str]:
        """``(effort_to_send, reason)`` for *model* — the one canonical clamp.

        Nearest **weaker** supported rung, never an escalation. Providers do not
        get to hand-roll this: an inverted ladder is silent, and it is wrong in
        the expensive direction exactly when the owner asked for the cheap one.
        """
        if self.reasoning_declarations is not None:
            return clamp_vocabulary(self.supported_reasoning_efforts(model), level)
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
            "supports_prompt_cache_key": self.supports_prompt_cache_key,
            "data_policy": {"policy": self.data_policy, "note": self.data_policy_note,
                            "models": [{"pattern": p, "policy": pol, "note": n} for p, pol, n in self.data_policy_models]},
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
        data_policy="local", data_policy_note="runs on this machine; prompts never leave it",
    ),
    ProviderProfile(
        id="ollama",
        display_name="Ollama",
        backend_kind="ollama",
        default_base_url="http://localhost:11434",
        base_url_env="JARVIS_OLLAMA_URL",
        capabilities=frozenset({"chat", "streaming", "local"}),
        data_policy="local", data_policy_note="runs on this machine; prompts never leave it",
    ),
    ProviderProfile(
        id="gemini",
        display_name="Google Gemini",
        backend_kind="gemini",
        auth_type="api-key",
        auth_env="GEMINI_API_KEY",
        capabilities=frozenset({"chat", "long-context", "cloud"}),
        fallback_models=("gemini-2.5-flash", "gemini-2.5-pro"),
        data_policy_note=("depends on the key: Google may use prompts sent with an unbilled (free-tier) "
                          "Gemini API key to improve its products; a billed key's are not"),
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
        data_policy="no-training", data_policy_note="Anthropic's API terms: prompts are not used for training by default",
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
        data_policy_note=("depends on the upstream provider; llm.openrouter_data_collection=deny (the default) "
                          "keeps requests off providers that store or train on prompts"),
        data_policy_models=(("*:free", "trains-on-inputs",
                             "OpenRouter's free variants are served by providers that may log and train on prompts"),),
    ),
    ProviderProfile(
        id="deepinfra",
        display_name="DeepInfra Vision",
        backend_kind="deepinfra-vision",
        auth_type="bearer",
        auth_env="DEEPINFRA_API_KEY",
        default_base_url="https://api.deepinfra.com/v1/openai",
        base_url_env="DEEPINFRA_BASE_URL",
        capabilities=frozenset({"vision", "model-catalog", "cloud"}),
        data_policy="unknown",
        data_policy_note="DeepInfra's data policy has not been verified for this vision route",
    ),
    ProviderProfile(
        id="nous", display_name="Nous Vision", backend_kind="nous-vision",
        auth_type="oauth", default_base_url="https://inference-api.nousresearch.com/v1",
        base_url_env="JARVIS_NOUS_INFERENCE_BASE_URL",
        capabilities=frozenset({"vision", "model-catalog", "cloud"}),
        data_policy="unknown",
        data_policy_note="Nous model data handling has not been verified for this vision route",
    ),
    ProviderProfile(
        id="xai", display_name="xAI Grok (Responses)", backend_kind="xai-responses",
        auth_type="bearer", auth_env="XAI_API_KEY", default_base_url="https://api.x.ai/v1",
        fallback_models=("grok-4.6", "grok-4.5"),
        capabilities=frozenset({"chat", "streaming", "cloud", "reasoning-effort"}),
        reasoning_declarations={"grok-4.6": ("low", "medium", "high", "xhigh"),
                                "grok-4.5": ("low", "medium", "high")},
    ),
    ProviderProfile(
        id="openai-responses", display_name="OpenAI Responses (API key, GPT-4.1)",
        backend_kind="openai-responses", auth_type="bearer", auth_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        capabilities=frozenset({"chat", "streaming", "cloud", "prompt-cache-key"}),
        reasoning_declarations={"gpt-4.1": (), "gpt-4.1-2025-04-14": ()},
        data_policy="no-training", data_policy_note="OpenAI's API terms: API inputs are not used for training by default",
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
        data_policy_note="depends on the endpoint it is pointed at",
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
    "DATA_POLICIES",
    "BUILTIN_PROVIDER_IDS",
    "DEFAULT_REGISTRY",
    "ProviderProfile",
    "ProviderRegistry",
    "get_profile",
    "list_profiles",
    "provider_catalog",
]
