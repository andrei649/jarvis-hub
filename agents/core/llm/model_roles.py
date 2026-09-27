"""model_roles.py — H277: separate models for separate jobs.

One small, frozen table of the model *roles* Nerva knows — ``main``, ``deep``,
``vision``, ``video`` and ``approval_judge`` — so a cheap local model can judge an
approval and the vision model can read a screenshot independently of the main model.

Each role resolves ``{provider_id, model, base_url}`` from
``JARVIS_ROLE_<NAME>_PROVIDER`` / ``_MODEL`` / ``_BASE_URL``. The names that predate
the table stay as fallbacks (``JARVIS_VLM_BACKEND`` / ``_MODEL`` / ``_URL`` for vision,
``JARVIS_DEEP_MODEL`` for deep), so an install that sets only those behaves exactly as
before; when both are set the new name wins and the listing names the shadowed one.

A provider value is a ProviderProfile id (``agents/core/llm/providers``): an unknown id
is refused as ``role_provider_unknown`` and a real id the role's code path cannot speak
to (``anthropic`` for vision) as ``role_provider_unsupported``, never guessed around.

What is *not* here, on purpose:

- ``main`` is not env-selectable. The main model is chosen on the settings surfaces that
  run the H378 cost and data-policy guards; an env override would be a second, unguarded
  selection path. ``JARVIS_ROLE_MAIN_*`` is reported as ignored.
- ``deep`` has no provider: it is served by the router's detected local backend, so
  ``JARVIS_ROLE_DEEP_PROVIDER`` / ``_BASE_URL`` are reported as ignored and never raise
  (boot cannot break on the deep slot).
- ``video`` is declared with no consumer: nothing in Nerva reads video yet (inbound video
  is not read, ``/api/media`` reports ``video: false``). The listing says so.
- Keys stay where they were: ``JARVIS_VLM_KEY`` for vision, the provider profile's own
  ``auth_env`` for the judge. No new secret variable exists.

Every read goes through ``env_config`` (or the caller's ``env`` mapping, as
``resolve_vlm_config(env=...)`` always allowed); this module never reads the process
environment directly.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlsplit

from ..env_config import env_str
from .providers import BUILTIN_PROVIDER_IDS, get_profile

__all__ = ["ROLES", "RoleSpec", "ResolvedRole", "RoleConfigError", "resolve", "describe",
           "vision_env_view", "LMSTUDIO_VLM_BASE", "VIDEO_NOTE"]

# LM Studio's OpenAI-compatible server with the ``/v1`` suffix the VLM adapter posts under
# (re-exported by ``vlm`` under the same name). The judge and video roles use the profile's
# own base URL instead (``http://localhost:1234``, no ``/v1``), like ``HybridRouter.detect``.
LMSTUDIO_VLM_BASE = "http://localhost:1234/v1"

VIDEO_NOTE = ("declared; nothing reads video yet in Nerva (inbound video is not read: "
              "channels/inbound_media.py; /api/media reports video: false)")

_FIELDS = ("provider", "model", "base_url")


@dataclass(frozen=True)
class RoleSpec:
    """One job a model can be given, and where its choice comes from."""

    name: str
    purpose: str
    env_prefix: str
    legacy: Mapping[str, str]            # field -> legacy env name (the fallback)
    providers: frozenset[str] | None     # provider ids this role can use; None = not env-selectable
    consumers: tuple[str, ...]           # the code that really reads the role (() = none)
    default_model: str = ""

    def env_name(self, fld: str) -> str:
        return f"{self.env_prefix}_{fld.upper()}"


@dataclass(frozen=True)
class ResolvedRole:
    role: str
    configured: bool
    provider_id: str                     # "" when unset
    model: str
    base_url: str
    source: Mapping[str, str]            # field -> env name it came from, or "default"
    local: bool | None                   # local-policy provider on a loopback base; None = unknown
    data_policy: str                     # ProviderProfile.data_policy_for(model), "" when unset
    reason: str = ""                     # stable "not configured" reason
    ignored: tuple[str, ...] = ()        # env names set that have no effect for this role


class RoleConfigError(ValueError):
    """A role's provider is not a provider id, or not one the role can use."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


ROLES: Mapping[str, RoleSpec] = MappingProxyType({
    "main": RoleSpec(
        "main", "the conversation model", "JARVIS_ROLE_MAIN", MappingProxyType({}), None,
        ("agents/core/llm/hybrid_router.py (settings llm.*)",)),
    "deep": RoleSpec(
        "deep", "the deep-reasoning slot on the local backend", "JARVIS_ROLE_DEEP",
        MappingProxyType({"model": "JARVIS_DEEP_MODEL"}), None,
        ("agents/core/llm/hybrid_router.py (deep slot)",)),
    "vision": RoleSpec(
        "vision", "reads screenshots, documents and images", "JARVIS_ROLE_VISION",
        MappingProxyType({"provider": "JARVIS_VLM_BACKEND", "model": "JARVIS_VLM_MODEL",
                          "base_url": "JARVIS_VLM_URL"}),
        frozenset({"lm-studio", "openai-compatible"}),
        ("agents/core/llm/vlm.py resolve_vlm_config",)),
    "video": RoleSpec(
        "video", "would read video; nothing does yet", "JARVIS_ROLE_VIDEO", MappingProxyType({}),
        frozenset({"lm-studio", "ollama", "openai-compatible"}), ()),
    "approval_judge": RoleSpec(
        "approval_judge", "scores a queued tool-call approval (advisory only)",
        "JARVIS_ROLE_APPROVAL_JUDGE", MappingProxyType({}),
        frozenset({"lm-studio", "ollama", "openai-compatible"}),
        ("agents/core/autonomy/approval_judge.py",)),
})

# The VLM adapter's backend selector <-> the provider profile id it speaks to.
_VISION_BACKEND_OF = MappingProxyType({"lm-studio": "lmstudio", "openai-compatible": "custom"})
_VISION_PROVIDER_OF = MappingProxyType({v: k for k, v in _VISION_BACKEND_OF.items()})


def _is_loopback_base(url: str) -> bool:
    """Best-effort loopback check for provenance labeling (never raises).

    ``_is_loopback_base`` is a *label*: it computes ``VLMConfig.is_local`` and
    ``VLMBackend.is_local`` and never blocks anything itself. The **gate** is
    enforced by the callers that hold screen bytes — ``routers/multimodal.py``
    (``screen_reflex`` refuses a non-local config with 503 before generating)
    and ``screen_locator.LocalVLMLocator`` (refuses ``local_vlm_not_proven_local``
    before any bytes leave the process). The consent-scoped camera path keeps
    its own strict fail-closed validator (``cameras/vlm._local_endpoint``), which
    cannot be imported here without a package cycle. (Moved here from ``vlm`` by
    H277 so the role table can label a role's locality; ``vlm`` re-exports it.)
    """
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _reader(env: Mapping[str, str] | None):
    if env is not None:
        return lambda name: str(env.get(name, "") or "")
    return lambda name: env_str(name, "")


def _validate(spec: RoleSpec, raw: str) -> str:
    value = raw.strip().lower()
    try:
        get_profile(value)
    except KeyError:
        raise RoleConfigError("role_provider_unknown",
                              f"{spec.env_name('provider')}={value!r}; provider ids: {', '.join(BUILTIN_PROVIDER_IDS)}"
                              ) from None
    if spec.providers is None or value not in spec.providers:
        raise RoleConfigError("role_provider_unsupported",
                              f"{spec.name} can use {', '.join(sorted(spec.providers or ()))}, not {value}")
    return value


def _locality(provider_id: str, model: str, base_url: str) -> tuple[bool | None, str]:
    if not provider_id:
        return None, ""
    profile = get_profile(provider_id)
    policy = profile.data_policy_for(model)[0]
    return (policy == "local" and _is_loopback_base(base_url)), policy


def vision_env_view(env: Mapping[str, str] | None = None) -> tuple[str, str, str, str, str]:
    """``(backend, url, model, api_key, preset)`` for ``resolve_vlm_config``.

    ``JARVIS_ROLE_VISION_PROVIDER`` maps ``lm-studio`` → ``lmstudio`` and
    ``openai-compatible`` → ``custom``; unset, ``JARVIS_VLM_BACKEND`` is returned raw and
    unchanged, so ``off``, empty, URL-only and unknown-selector behaviour stay identical.
    Raises :class:`RoleConfigError` for an unknown or unsupported role provider.
    """
    read = _reader(env)
    spec = ROLES["vision"]
    role_provider = read(spec.env_name("provider")).strip()
    backend = (_VISION_BACKEND_OF[_validate(spec, role_provider)] if role_provider
               else read("JARVIS_VLM_BACKEND"))
    url = read(spec.env_name("base_url")).strip() or read("JARVIS_VLM_URL")
    model = read(spec.env_name("model")).strip() or read("JARVIS_VLM_MODEL")
    return backend, url, model, read("JARVIS_VLM_KEY"), read("JARVIS_VLM_PRESET")


def _pick(read, spec: RoleSpec, fld: str) -> tuple[str, str, list[str]]:
    """``(value, source, shadowed)`` for one field: the role name, else its legacy name."""
    new_name = spec.env_name(fld)
    new = read(new_name).strip()
    legacy_name = spec.legacy.get(fld, "")
    legacy = read(legacy_name).strip() if legacy_name else ""
    if new:
        return new, new_name, ([legacy_name] if legacy and legacy.lower() != new.lower() else [])
    if legacy:
        return legacy, legacy_name, []
    return "", "default", []


def _resolve_vision(read, spec: RoleSpec) -> ResolvedRole:
    source: dict[str, str] = {}
    ignored: list[str] = []
    role_provider = read(spec.env_name("provider")).strip()
    legacy_backend = read("JARVIS_VLM_BACKEND").strip().lower()
    url, source["base_url"], shadow = _pick(read, spec, "base_url")
    ignored += shadow
    model, source["model"], shadow = _pick(read, spec, "model")
    ignored += shadow
    reason = ""
    if role_provider:
        provider = _validate(spec, role_provider)
        source["provider"] = spec.env_name("provider")
        if legacy_backend and legacy_backend != _VISION_BACKEND_OF[provider]:
            ignored.append("JARVIS_VLM_BACKEND")
    else:
        source["provider"] = "JARVIS_VLM_BACKEND" if legacy_backend else "default"
        if legacy_backend in {"", "off"} and not (legacy_backend == "" and url):
            provider, reason = "", "vlm_disabled"
        elif legacy_backend not in {"", "lmstudio", "custom"}:
            provider, reason = "", "vlm_backend_unknown"
        else:
            provider = _VISION_PROVIDER_OF.get(legacy_backend or "custom", "")
            if not legacy_backend:
                source["provider"] = "JARVIS_VLM_URL"
    if provider == "lm-studio":
        url = url or LMSTUDIO_VLM_BASE
    elif provider == "openai-compatible" and not model:
        model = "qwen2-vl"   # the adapter's historical default for a custom endpoint
    local, policy = _locality(provider, model, url)
    return ResolvedRole("vision", bool(provider), provider, model if provider else "",
                        url if provider else "", MappingProxyType(source), local, policy,
                        reason, tuple(ignored))


def _resolve_env_role(read, spec: RoleSpec) -> ResolvedRole:
    """video and approval_judge: provider (default lm-studio), model, base URL."""
    model = read(spec.env_name("model")).strip()
    raw_provider = read(spec.env_name("provider")).strip()
    provider = _validate(spec, raw_provider) if raw_provider else "lm-studio"
    source = {"model": spec.env_name("model") if model else "default",
              "provider": spec.env_name("provider") if raw_provider else "default"}
    base = read(spec.env_name("base_url")).strip()
    if base:
        source["base_url"] = spec.env_name("base_url")
    else:
        profile = get_profile(provider)
        env_base = read(profile.base_url_env).strip() if profile.base_url_env else ""
        base = env_base or profile.default_base_url or ""
        source["base_url"] = profile.base_url_env if env_base else "default"
    if not model:
        return ResolvedRole(spec.name, False, "", "", "", MappingProxyType(source), None, "",
                            "role_model_unset")
    local, policy = _locality(provider, model, base)
    return ResolvedRole(spec.name, True, provider, model, base, MappingProxyType(source), local, policy)


def resolve(role: str, env: Mapping[str, str] | None = None) -> ResolvedRole:
    """Resolve *role* from the environment (or *env*). Raises ``KeyError`` for a name that
    is not a role and :class:`RoleConfigError` for a provider id it cannot use."""
    spec = ROLES[role]
    read = _reader(env)
    if role == "main":
        ignored = tuple(spec.env_name(f) for f in _FIELDS if read(spec.env_name(f)).strip())
        return ResolvedRole("main", False, "", "", "", MappingProxyType({}), None, "",
                            "role_not_env_selectable", ignored)
    if role == "deep":
        from .model_config import DEFAULT_DEEP_MODEL

        model, src, shadow = _pick(read, spec, "model")
        ignored = tuple(shadow) + tuple(spec.env_name(f) for f in ("provider", "base_url")
                                        if read(spec.env_name(f)).strip())
        return ResolvedRole("deep", True, "", model or DEFAULT_DEEP_MODEL, "",
                            MappingProxyType({"model": src}), None, "", "", ignored)
    if role == "vision":
        return _resolve_vision(read, spec)
    return _resolve_env_role(read, spec)


def describe(env: Mapping[str, str] | None = None) -> list[dict]:
    """A read-only listing of every role (doctor, status). Never raises, never a secret."""
    rows = []
    for name, spec in ROLES.items():
        row: dict = {"role": name, "purpose": spec.purpose, "consumers": list(spec.consumers),
                     "error": False, "note": VIDEO_NOTE if name == "video" else ""}
        try:
            resolved = resolve(name, env)
        except RoleConfigError as exc:
            row.update(configured=False, reason=exc.reason, detail=exc.detail, error=True,
                       provider="", model="", local=None, data_policy="", source={}, ignored=[])
        else:
            row.update(configured=resolved.configured, reason=resolved.reason,
                       provider=resolved.provider_id, model=resolved.model, local=resolved.local,
                       data_policy=resolved.data_policy, source=dict(resolved.source),
                       ignored=list(resolved.ignored),
                       base_url=resolved.base_url if resolved.local else "")
        rows.append(row)
    return rows

