"""Explicit OpenRouter vision configuration and live upstream routing policy.

This module does not discover a route from ambient credentials. It is used only
when the owner selects the ``openrouter`` vision role. No image or network I/O
occurs here.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from urllib.parse import urlsplit

from ..env_config import env_str
from .provider_routing import (
    DEFAULT_DATA_COLLECTION,
    SETTINGS_KEYS,
    ProviderRoutingInvalid,
    build_provider_block,
)

OPENROUTER_VISION_BASE = "https://openrouter.ai/api/v1"
_DEFAULTS = {
    "sort": "",
    "only": [],
    "ignore": [],
    "order": [],
    "require_parameters": False,
    "data_collection": DEFAULT_DATA_COLLECTION,
}


def _read(env: Mapping[str, str] | None, name: str) -> str:
    return str(env.get(name, "") or "") if env is not None else env_str(name, "")


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_base(raw: str) -> tuple[str, bool, tuple[str, str, int]]:
    """Bounded OpenRouter-compatible base and its credential scope."""
    if (not raw or len(raw) > 2048 or raw != raw.strip()
            or any(ord(char) <= 32 or ord(char) == 127 for char in raw)):
        raise ValueError("vlm_url_invalid")
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
        if (scheme not in {"http", "https"} or not host or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or "?" in raw or "#" in raw or "\\" in raw or port == 0):
            raise ValueError
        local = _loopback(host)
        if scheme != "https" and not local:
            raise ValueError
        if port is None:
            port = 443 if scheme == "https" else 80
    except ValueError:
        raise ValueError("vlm_url_invalid") from None
    return raw, local, (scheme, host, port)


def resolve_config(env: Mapping[str, str] | None = None):
    """Resolve the explicitly selected role to a native ``VLMConfig``.

    A model and scoped key are mandatory. ``OPENROUTER_BASE_URL`` is deliberately
    ignored: only ``JARVIS_ROLE_VISION_BASE_URL`` can change this role's endpoint.
    An ambient OpenRouter key can serve the canonical origin, including its
    explicit default port. Any other origin requires a dedicated role key.
    """
    # Import lazily: vlm imports model_roles, and model_roles uses this resolver.
    from .vlm import VLMConfig, VLMNotConfigured

    if _read(env, "JARVIS_ROLE_VISION_PROVIDER").strip().lower() != "openrouter":
        raise VLMNotConfigured("vlm_disabled")
    raw_model = _read(env, "JARVIS_ROLE_VISION_MODEL")
    model = raw_model.strip()
    if not model:
        raise VLMNotConfigured("vlm_model_unset")
    if len(raw_model) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in raw_model):
        raise VLMNotConfigured("vlm_model_invalid")
    raw_base = _read(env, "JARVIS_ROLE_VISION_BASE_URL")
    base = raw_base if raw_base else OPENROUTER_VISION_BASE
    try:
        base, local, origin = _validated_base(base)
    except ValueError:
        raise VLMNotConfigured("vlm_url_invalid") from None
    dedicated = _read(env, "JARVIS_ROLE_VISION_KEY").strip()
    canonical_origin = ("https", "openrouter.ai", 443)
    key = dedicated or (_read(env, "OPENROUTER_API_KEY").strip()
                        if origin == canonical_origin else "")
    if not key:
        raise VLMNotConfigured("vlm_key_unset")
    if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise VLMNotConfigured("vlm_key_invalid")
    return VLMConfig(backend="openrouter", base_url=base, model=model,
                     api_key=key, is_local=local)


def current_provider_block() -> dict:
    """Read and validate every live ``llm.openrouter_*`` routing setting.

    A missing row takes its safe default. Any unreadable or malformed stored row
    refuses the request without exposing DB contents or dropping a restriction.
    The returned block always states ``data_collection``, including the default
    ``deny``; callers can bind its canonical JSON to the approved destination.
    """
    from .. import settings_db

    knobs = {}
    present = {}
    try:
        for name, key in SETTINGS_KEYS.items():
            found, raw = settings_db.read_setting("llm", key)
            if not isinstance(found, bool):
                raise ValueError("invalid setting presence")
            present[name] = found
            knobs[name] = raw if found else _DEFAULTS[name]
    except Exception:
        raise ValueError("openrouter_routing_unavailable") from None

    # build_provider_block treats None/empty as an unset value for some knobs.
    # That is appropriate for missing rows, but a present malformed row must
    # never erase a privacy or provider constraint.
    try:
        if (knobs["sort"] is None or knobs["only"] is None or knobs["ignore"] is None
                or knobs["order"] is None or knobs["data_collection"] in ("", None)):
            raise ProviderRoutingInvalid("empty routing value")
        if any(present[name] and knobs[name] == "" for name in ("only", "ignore", "order")):
            raise ProviderRoutingInvalid("empty provider list value")
        block = build_provider_block(**knobs)
        if not block or "data_collection" not in block:
            raise ProviderRoutingInvalid("data collection missing")
        return block
    except (ProviderRoutingInvalid, TypeError, ValueError):
        raise ValueError("openrouter_routing_invalid") from None


def policy_for(model: str, block: dict) -> tuple[str, str]:
    """Apply the same live routing policy used by Nerva's text OpenRouter path."""
    from .providers import get_profile

    policy, note = get_profile("openrouter").data_policy_for(model)
    if block["data_collection"] == "allow":
        return "trains-on-inputs", "OpenRouter data collection is allowed on this vision route."
    return policy, f"{note} Outgoing OpenRouter requests restrict data collection to deny.".strip()
