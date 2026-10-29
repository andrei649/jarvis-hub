"""Declarative LLM provider profiles.

Profiles own provider identity, defaults and request hooks. The backend-kind
factory consumes the same declarations as discovery, setup and model pickers.
Agent policy and approved-model limits remain owned by ``HybridRouter``.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import MappingProxyType
from urllib.parse import urlsplit

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
OMIT_TEMPERATURE = "omit"
_IDENTITY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")
_OWNED_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "host",
                            "x-api-key", "x-goog-api-key", "content-length", "transfer-encoding"})


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
    # Keep additions after the original fields to preserve positional callers.
    supports_health_check: bool = True
    supports_model_listing: bool = True
    api_mode: str = "chat_completions"
    aliases: tuple[str, ...] = ()
    description: str = ""
    signup_url: str = ""
    hidden: bool = False
    env_vars: tuple[str, ...] = ()
    models_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    supports_vision_tool_messages: bool = True
    hostname: str = ""
    fixed_temperature: float | str | None = None
    default_max_tokens: int | None = None
    default_aux_model: str = ""
    is_aggregator: bool = False
    is_routing_aggregator: bool = False
    is_user_defined: bool = False
    catalog_upstream: str = ""

    def __post_init__(self) -> None:
        if (type(self.supports_health_check) is not bool
                or type(self.supports_model_listing) is not bool):
            raise ValueError("provider discovery gates must be literal booleans")
        object.__setattr__(self, "id", self.id.strip().lower())
        if not _IDENTITY.fullmatch(self.id):
            raise ValueError("provider profile id must be a bounded canonical identity")
        aliases = tuple(str(alias).strip().lower() for alias in self.aliases)
        if (any(not _IDENTITY.fullmatch(alias) or alias == self.id for alias in aliases)
                or len(set(aliases)) != len(aliases)):
            raise ValueError("provider aliases must be unique canonical identities")
        object.__setattr__(self, "aliases", aliases)
        for flag in (self.hidden, self.supports_vision_tool_messages,
                     self.is_aggregator, self.is_routing_aggregator, self.is_user_defined):
            if type(flag) is not bool:
                raise ValueError("provider behavior flags must be literal booleans")
        if self.is_routing_aggregator and not self.is_aggregator:
            raise ValueError("routing aggregators must declare aggregator identity")
        if (type(self.catalog_upstream) is not str
                or self.catalog_upstream and not _IDENTITY.fullmatch(self.catalog_upstream)):
            raise ValueError("catalog upstream must be a bounded canonical identity")
        envs = tuple(dict.fromkeys(((self.auth_env,) if self.auth_env else ()) + tuple(self.env_vars)))
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name)
               for name in envs):
            raise ValueError("provider auth environment names invalid")
        object.__setattr__(self, "env_vars", envs)
        headers = dict(self.default_headers)
        folded = set()
        for name, value in headers.items():
            if (not isinstance(name, str) or not _HEADER.fullmatch(name)
                    or name.lower() in _OWNED_HEADERS or name.lower() in folded
                    or not isinstance(value, str) or len(value) > 2048
                    or any(ord(char) < 32 or ord(char) > 126 for char in value)):
                raise ValueError("provider default headers cannot replace wire authority")
            folded.add(name.lower())
        object.__setattr__(self, "default_headers", MappingProxyType(headers))
        if self.fixed_temperature not in (None, OMIT_TEMPERATURE) and (
                type(self.fixed_temperature) not in (int, float)
                or not math.isfinite(self.fixed_temperature) or not 0 <= self.fixed_temperature <= 2):
            raise ValueError("provider fixed temperature invalid")
        if self.default_max_tokens is not None and (type(self.default_max_tokens) is not int
                                                    or self.default_max_tokens <= 0):
            raise ValueError("provider maximum tokens must be positive")
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

    @property
    def supports_vision(self) -> bool:
        return "vision" in self.capabilities

    def resolve_aux_model(self, *, vision: bool = False) -> str:
        """Cheap declaration/cache hook: no network, auth or implicit activation."""
        if vision:
            return self.default_vision_model() or ""
        return self.default_aux_model

    def get_hostname(self) -> str:
        return self.hostname or (urlsplit(self.default_base_url or "").hostname or "")

    def prepare_messages(self, messages: list) -> list:
        return messages

    def build_extra_body(self, *, session_id=None, **context) -> dict:
        return {}

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context) -> tuple[dict, dict]:
        return {}, {}

    def default_vision_model(self) -> str | None:
        # Endpoint vision support does not prove that any particular fallback
        # model accepts images. A provider must explicitly override this hook.
        return None

    def get_max_tokens(self, model: str) -> int | None:
        return self.default_max_tokens

    def auth_key(self, environ: Mapping[str, str] | None = None) -> str:
        env = os.environ if environ is None else environ
        return next((str(env.get(name, "")).strip() for name in self.env_vars
                     if str(env.get(name, "")).strip()), "")

    def resolve_base_url(self, environ: Mapping[str, str] | None = None) -> str | None:
        env = os.environ if environ is None else environ
        return (str(env.get(self.base_url_env, "")).strip() if self.base_url_env else "") or self.default_base_url

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
            or bool(self.auth_key(env))
        )
        base_url = (
            str(env.get(self.base_url_env, "")).strip()
            if self.base_url_env else ""
        ) or self.default_base_url
        return {
            "id": self.id,
            "api_mode": self.api_mode,
            "aliases": list(self.aliases),
            "description": self.description,
            "signup_url": self.signup_url,
            "hidden": self.hidden,
            "env_vars": list(self.env_vars),
            "models_url": self.models_url,
            "default_header_names": sorted(self.default_headers),
            "hostname": self.get_hostname(),
            "supports_vision": self.supports_vision,
            "supports_vision_tool_messages": self.supports_vision_tool_messages,
            "default_aux_model": self.default_aux_model,
            "default_max_tokens": self.default_max_tokens,
            "is_aggregator": self.is_aggregator,
            "is_routing_aggregator": self.is_routing_aggregator,
            "is_user_defined": self.is_user_defined,
            "catalog_upstream": self.catalog_upstream,
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
            "supports_health_check": self.supports_health_check,
            "supports_model_listing": self.supports_model_listing,
            "reasoning_efforts": list(self.reasoning_efforts),
            "supports_prompt_cache_key": self.supports_prompt_cache_key,
            "data_policy": {"policy": self.data_policy, "note": self.data_policy_note,
                            "models": [{"pattern": p, "policy": pol, "note": n} for p, pol, n in self.data_policy_models]},
        }


class ProviderRegistry:
    """In-memory registry for provider profiles."""

    def __init__(self, profiles: list[ProviderProfile] | tuple[ProviderProfile, ...] = ()):
        self._profiles: dict[str, ProviderProfile] = {}
        self._aliases: dict[str, str] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ProviderProfile) -> ProviderProfile:
        key = profile.id.strip().lower()
        identities = (key,) + profile.aliases
        if any(identity in self._profiles or identity in self._aliases for identity in identities):
            raise ValueError(f"duplicate provider profile: {key}")
        self._profiles[key] = profile
        self._aliases.update(dict.fromkeys(profile.aliases, key))
        return profile

    def canonical_id(self, provider_id: str) -> str:
        key = str(provider_id or "").strip().lower()
        key = self._aliases.get(key, key)
        if key not in self._profiles:
            raise KeyError(f"unknown provider profile: {key}")
        return key

    def get(self, provider_id: str) -> ProviderProfile:
        key = self.canonical_id(provider_id)
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
        api_mode="gemini_generate_content",
        display_name="Google Gemini",
        backend_kind="gemini",
        auth_type="api-key",
        auth_env="GEMINI_API_KEY",
        capabilities=frozenset({"chat", "long-context", "vision", "cloud"}),
        fallback_models=("gemini-2.5-flash", "gemini-2.5-pro"),
        data_policy_note=("depends on the key: Google may use prompts sent with an unbilled (free-tier) "
                          "Gemini API key to improve its products; a billed key's are not"),
    ),
    ProviderProfile(
        id="anthropic",
        api_mode="anthropic_messages",
        display_name="Anthropic Claude",
        backend_kind="anthropic",
        auth_type="api-key",
        auth_env="ANTHROPIC_API_KEY",
        capabilities=frozenset({"chat", "reasoning", "vision", "cloud"}),
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
        display_name="DeepInfra",
        backend_kind="openai-compatible",
        auth_type="bearer",
        auth_env="DEEPINFRA_API_KEY",
        default_base_url="https://api.deepinfra.com/v1/openai",
        base_url_env="DEEPINFRA_BASE_URL",
        capabilities=frozenset({"chat", "vision", "model-catalog", "cloud"}),
        data_policy="unknown",
        data_policy_note="DeepInfra chat and vision data handling has not been verified",
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
        api_mode="responses",
        auth_type="bearer", auth_env="XAI_API_KEY", default_base_url="https://api.x.ai/v1",
        fallback_models=("grok-4.6", "grok-4.5"),
        capabilities=frozenset({"chat", "streaming", "cloud", "reasoning-effort", "vision"}),
        reasoning_declarations={"grok-4.6": ("low", "medium", "high", "xhigh"),
                                "grok-4.5": ("low", "medium", "high")},
    ),
    ProviderProfile(
        id="openai-responses", display_name="OpenAI Responses (API key, GPT-4.1)",
        api_mode="responses",
        backend_kind="openai-responses", auth_type="bearer", auth_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        capabilities=frozenset({"chat", "streaming", "cloud", "prompt-cache-key", "vision"}),
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


def custom_provider_registry() -> ProviderRegistry:
    """A current owner catalog view, never a mutation of built-in declarations."""
    from ..custom_endpoint_service import profile_for
    from ..custom_endpoints import list_endpoints

    return ProviderRegistry([*BUILTIN_PROFILES,
                             *(profile_for(endpoint) for endpoint in list_endpoints())])


__all__ = [
    "BUILTIN_PROFILES",
    "DATA_POLICIES",
    "BUILTIN_PROVIDER_IDS",
    "DEFAULT_REGISTRY",
    "ProviderProfile",
    "ProviderRegistry",
    "OMIT_TEMPERATURE",
    "get_profile",
    "list_profiles",
    "provider_catalog",
    "custom_provider_registry",
]
