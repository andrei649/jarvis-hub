"""hermes_profiles.py — run Hermes's model-provider profiles inside Nerva (Adopt lane, slice 2).

Hermes keeps its per-provider knowledge in small ``ProviderProfile`` subclasses
(``plugins/model-providers/*``): the base URL, the model ids it offers, and the request
extras each vendor wants (DeepSeek's ``thinking`` toggle, GLM's effort scale, Fireworks's
top-level ``reasoning_effort`` …). Those files are vendored unchanged under
``agents/vendor/hermes`` (``docs/hermes/ADOPT_LANE.md``). This module is the bridge that turns
each one into a Nerva :class:`~agents.core.llm.providers.ProviderProfile` the existing
OpenAI-compatible backend (``OpenRouterBackend``) runs.

What comes from the Hermes profile: the base URL (fixed: a profile's ``*_BASE_URL``
override is not read), the model list, the message hook, the output cap, the fixed
temperature and the request extras (``build_extra_body`` / ``build_api_kwargs_extras``).

What stays Nerva's: the HTTP client (``egress.llm_async_client``: egress ledger, quota
guard, TLS anchor, host protocol, data-handling gate), streaming, tool calls, retries,
cost, the kernel, the request headers, and the key. Plus three rules of this bridge:

* **Fixed destination.** :func:`adopted_client` adds a request hook that refuses any
  request whose origin is not the profile's own ``https://<host>`` (or whose host resolves
  local), records the refusal in the egress ledger and raises before the transport.
* **Keys per provider.** A provider reads only the key names its row in
  ``hermes_provider_table`` lists, through ``agents.core.env_config``. It is off until one
  is set and the owner picks it (``llm.compatible_provider``).
* **Reasoning stays the owner's.** Effort is clamped by Nerva first, to the levels the
  vendored profile itself sends verbatim (:func:`derived_efforts`; nearest weaker, below the
  minimum refused). With no effort chosen, no reasoning field is sent. What the profile then
  emits must restate the choice (:func:`check_reasoning`): an on/off toggle that matches
  it, or a level no stronger than the one chosen. Anything else refuses the request.

Attribution headers naming Hermes Agent (``User-Agent``, ``HTTP-Referer``, ``X-Title``) and
``Accept-Encoding`` are dropped: they are Nerva's to set.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx

from .hermes_provider_table import ADOPTED_MODEL_PROVIDERS
from .host_protocol import HostProtocolRefused
from .providers import OMIT_TEMPERATURE, ProviderProfile

logger = logging.getLogger("jarvis.llm.hermes_profiles")

_ROWS = {row[0]: row for row in ADOPTED_MODEL_PROVIDERS}
#: Headers a Hermes profile sets that Nerva does not forward (attribution and transport).
DROPPED_HEADERS = frozenset({"user-agent", "http-referer", "x-title", "accept-encoding"})
#: Body/top-level keys that carry a reasoning control.
REASONING_KEYS = frozenset({"reasoning", "reasoning_effort", "thinking"})
#: Ladder levels probed to learn what a profile sends verbatim (``none`` / ``ultra`` are not
#: levels a vendor wire takes).
_PROBE_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
_LOAD_LOCK = threading.Lock()
_LOADED = False


class AdoptedDestinationRefused(HostProtocolRefused):
    """An adopted provider's client was pointed somewhere other than its profile's host.

    Subclasses :class:`HostProtocolRefused` so connection-failure handlers do not read it
    as "backend down": the request and its key never left.
    """


# ── loading the vendored profiles ────────────────────────────────────────────

def _load() -> dict[str, Any]:
    """Import the vendored profile modules once (table order) and return the registry."""
    global _LOADED
    from agents.vendor.hermes_compat import providers as registry

    with _LOAD_LOCK:
        if not _LOADED:
            for directory in dict.fromkeys(row[1] for row in ADOPTED_MODEL_PROVIDERS):
                registry.load_profile_module(directory)
            _LOADED = True
    return registry.registered()


def upstream_profile(provider_id: str) -> Any:
    """The vendored Hermes profile behind an adopted provider id."""
    if provider_id not in _ROWS:
        raise KeyError(f"not an adopted provider: {provider_id}")
    profile = _load().get(provider_id)
    if profile is None:
        raise KeyError(f"vendored profile did not register: {provider_id}")
    return profile


# ── reasoning: Nerva's clamp first, then the profile's wire, checked ─────────

def _wire_level(extra: dict, top: dict) -> str | None:
    merged = {**extra, **top}
    if isinstance(merged.get("reasoning_effort"), str):
        return merged["reasoning_effort"]
    reasoning = merged.get("reasoning")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("effort"), str):
        return reasoning["effort"]
    return None


def _upstream_extras(provider_id: str, base_url: str, model: str, reasoning_config) -> tuple[dict, dict]:
    extra, top = upstream_profile(provider_id).build_api_kwargs_extras(
        reasoning_config=reasoning_config, model=model, base_url=base_url,
        supports_reasoning=isinstance(reasoning_config, dict))
    return dict(extra or {}), dict(top or {})


@lru_cache(maxsize=1024)
def derived_efforts(provider_id: str, base_url: str, model: str) -> tuple[str, ...]:
    """The effort levels the vendored profile sends unchanged for *model*, weakest first.

    Probed by asking the profile for each ladder level: a level it sends as itself is one
    the vendor takes. A profile that answers every level with a bare on-toggle (GLM-4.6's
    ``thinking``) takes any level as "on". A profile that sends nothing for any level
    declares no reasoning control (``()``). Pure: the profiles do no I/O.
    """
    verbatim: list[str] = []
    toggled: list[str] = []
    for level in _PROBE_LEVELS:
        extra, top = _upstream_extras(provider_id, base_url, model, {"enabled": True, "effort": level})
        if _wire_level(extra, top) == level:
            verbatim.append(level)
        elif _wire_level(extra, top) is None and "thinking" in {**extra, **top}:
            toggled.append(level)
    return tuple(verbatim or toggled)


def _refuse(message: str):
    from .provider_request import ProfileRequestRefused

    raise ProfileRequestRefused(message)


def check_reasoning(requested: dict, configuration: Any) -> None:
    """Refuse adopted reasoning fields that do not restate the owner's choice.

    *requested* holds the reasoning keys the profile emitted, *configuration* the choice
    Nerva handed it (``{"enabled": False}`` or ``{"enabled": True, "effort": level}``).
    """
    from .reasoning_effort import LADDER, rank

    if type(configuration) is not dict or type(configuration.get("enabled")) is not bool:
        _refuse("profile reasoning is not declared")
    if configuration["enabled"] is False:
        for key, value in requested.items():
            if not ((key == "thinking" and value == {"type": "disabled"})
                    or (key == "reasoning" and value == {"enabled": False})
                    or (key == "reasoning_effort" and value == "none")):
                _refuse("the provider cannot turn reasoning off for this model")
        return
    level = configuration.get("effort")
    if type(level) is not str or level not in LADDER:
        _refuse("profile reasoning is not declared")

    def weaker(value: Any) -> bool:
        return type(value) is str and value in LADDER and value != "none" and rank(value) <= rank(level)

    for key, value in requested.items():
        if key == "thinking":
            ok = (type(value) is dict and value.get("type") in {"enabled", "adaptive"}
                  and set(value) <= {"type", "clear_thinking", "keep"})
        elif key == "reasoning_effort":
            ok = weaker(value)
        else:  # "reasoning"
            ok = (type(value) is dict and set(value) <= {"effort", "enabled"}
                  and value.get("enabled", True) is True and weaker(value.get("effort")))
        if not ok:
            _refuse("profile reasoning exceeds the selected effort")


# ── the Nerva profile ────────────────────────────────────────────────────────

class HermesAdoptedProfile(ProviderProfile):
    """A Nerva provider declaration whose request hooks run a vendored Hermes profile.

    No fields of its own, so ``dataclasses.replace`` keeps it whole; the Hermes profile is
    found again from ``id``.
    """

    #: The profile, not ``compatible_parameters``, shapes the reasoning wire.
    owns_reasoning_wire = True

    def _upstream(self) -> Any:
        return upstream_profile(self.id)

    def prepare_messages(self, messages: list) -> list:
        return self._upstream().prepare_messages(messages)

    def build_extra_body(self, *, session_id=None, **context) -> dict:
        return dict(self._upstream().build_extra_body(session_id=session_id) or {})

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context) -> tuple[dict, dict]:
        model = context.get("model") if type(context.get("model")) is str else ""
        extra, top = _upstream_extras(self.id, self.default_base_url or "", model, reasoning_config)
        if not isinstance(reasoning_config, dict):
            # Unset stays unset: the vendor's own default applies, as for every Nerva route.
            for key in REASONING_KEYS:
                extra.pop(key, None)
                top.pop(key, None)
        return extra, top

    def get_max_tokens(self, model: str) -> int | None:
        cap = self._upstream().get_max_tokens(model)
        return cap if type(cap) is int and cap > 0 else None

    def supported_reasoning_efforts(self, model: str) -> tuple[str, ...] | None:
        from .reasoning_effort import _model_key

        declared = self.reasoning_declarations or {}
        key = _model_key(model)
        if key in declared:
            return declared[key]
        return derived_efforts(self.id, self.default_base_url or "", str(model or ""))

    def clamp_reasoning_effort(self, model: str, level: object) -> tuple[str | None, str]:
        from .reasoning_effort import clamp_vocabulary

        return clamp_vocabulary(self.supported_reasoning_efforts(model), level)

    def auth_key(self, environ=None) -> str:
        """The first of this provider's own key names that is set (env registry)."""
        if environ is None:
            from agents.core.env_config import env_str

            read = env_str
        else:
            def read(name, default=""):
                return environ.get(name, default)
        for name in _ROWS[self.id][2]:
            value = str(read(name, "") or "").strip()
            if value:
                return value
        return ""


def is_adopted_profile(profile: Any) -> bool:
    return isinstance(profile, HermesAdoptedProfile)


def _nerva_profile(provider_id: str) -> HermesAdoptedProfile:
    upstream = upstream_profile(provider_id)
    _, _, keys, display = _ROWS[provider_id]
    if upstream.api_mode != "chat_completions" or upstream.auth_type != "api_key":
        raise ValueError(f"{provider_id}: only API-key chat-completions profiles are bridged")
    base = str(upstream.base_url or "").rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.query:
        raise ValueError(f"{provider_id}: the profile has no fixed HTTPS base URL")
    headers = {name: value for name, value in dict(upstream.default_headers or {}).items()
               if name.lower() not in DROPPED_HEADERS}
    fixed = upstream.fixed_temperature
    from agents.vendor.hermes.providers.base import OMIT_TEMPERATURE as HERMES_OMIT

    return HermesAdoptedProfile(
        id=provider_id,
        display_name=upstream.display_name or display or provider_id,
        backend_kind="openai-compatible",
        auth_type="bearer",
        auth_env=keys[0],
        env_vars=keys,
        default_base_url=base,
        capabilities=frozenset({"chat", "streaming", "cloud"}),
        fallback_models=tuple(upstream.fallback_models),
        data_policy="unknown",
        data_policy_note=(f"{upstream.display_name or display or provider_id}: data handling has not "
                          "been verified (profile adopted from Hermes Agent)"),
        supports_health_check=bool(upstream.supports_health_check),
        supports_model_listing=False,
        description=upstream.description,
        signup_url=upstream.signup_url,
        default_headers=headers,
        supports_vision_tool_messages=bool(upstream.supports_vision_tool_messages),
        hostname=upstream.get_hostname(),
        fixed_temperature=OMIT_TEMPERATURE if fixed is HERMES_OMIT else fixed,
        default_max_tokens=upstream.default_max_tokens,
        default_aux_model=upstream.default_aux_model,
    )


def adopted_profiles() -> tuple[HermesAdoptedProfile, ...]:
    """Every adopted provider as a Nerva declaration, in table order."""
    return tuple(_nerva_profile(row[0]) for row in ADOPTED_MODEL_PROVIDERS)


# ── the client: Nerva's egress client, pinned to the profile's host ──────────

def _origin(base_url: str) -> tuple[str, int]:
    parts = urlsplit(base_url)
    return (parts.hostname or "").lower().rstrip("."), parts.port or 443


def _pin_hook(profile: ProviderProfile):
    host, port = _origin(profile.default_base_url or "")

    async def _pin(request: httpx.Request) -> None:
        from agents.core.http_client import host_is_local

        from .egress import _record

        target = (request.url.host or "").lower().rstrip(".")
        reason = ""
        if request.url.scheme != "https" or target != host or (request.url.port or 443) != port:
            reason = f"llm:{profile.id} may only reach https://{host} — refused before the request or its key left"
        elif host_is_local(target):
            reason = f"llm:{profile.id}: {host} resolves to a local address — refused"
        if reason:
            _record(profile.id, request, allowed=False, reason=reason)
            raise AdoptedDestinationRefused(reason)

    _pin._nerva_adopted_pin = profile.id
    return _pin


def adopted_client(profile: ProviderProfile, *, transport: httpx.AsyncBaseTransport | None = None):
    """Nerva's ledgered model client for an adopted provider, refusing every other host."""
    from .egress import llm_async_client

    if not is_adopted_profile(profile):
        raise ValueError("not an adopted provider profile")
    kwargs: dict[str, Any] = {"base_url": profile.default_base_url, "timeout": 120.0,
                              "follow_redirects": False,
                              "event_hooks": {"request": [_pin_hook(profile)]}}
    if transport is not None:
        kwargs["transport"] = transport
    return llm_async_client(profile.id, **kwargs)


def require_adopted_client(client: Any, profile: ProviderProfile):
    """Accept an injected client only if it carries this profile's pin and the ledger hook."""
    hooks = list(getattr(client, "event_hooks", {}).get("request", [])) if client is not None else []
    if (not hooks or getattr(hooks[0], "_nerva_adopted_pin", None) != profile.id
            or not getattr(hooks[-1], "_nerva_egress_recorder", False)):
        raise ValueError("adopted provider egress guard unavailable")
    return client


def build_backend(provider_id: str, *, settings=None, transport=None):
    """The compatible-slot backend for an adopted provider, or None while it has no key.

    *settings* reads ``llm`` settings (``(name, default) -> value``), as the router passes.
    """
    from dataclasses import replace

    from .openrouter import OpenRouterBackend
    from .providers import DEFAULT_REGISTRY

    def setting(name, default=None):
        return settings(name, default) if callable(settings) else default

    profile = DEFAULT_REGISTRY.get(provider_id)
    if not is_adopted_profile(profile):
        raise ValueError("not an adopted provider")
    key = profile.auth_key()
    if not key:
        return None
    caps = set(profile.capabilities)
    if setting("compatible_reasoning_enabled", False):
        caps.add("reasoning-effort")
    profile = replace(profile, capabilities=frozenset(caps))
    return OpenRouterBackend(
        api_key=key, base_url=profile.default_base_url, profile=profile,
        client=adopted_client(profile, transport=transport),
        reasoning_effort=setting("reasoning_effort", ""),
        effort_declarations=setting("compatible_effort_declarations", ""),
    )


__all__ = [
    "AdoptedDestinationRefused", "DROPPED_HEADERS", "HermesAdoptedProfile", "adopted_client",
    "adopted_profiles", "build_backend", "check_reasoning", "derived_efforts",
    "is_adopted_profile", "require_adopted_client", "upstream_profile",
]
