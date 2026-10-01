"""Pure parsing of the owner's ordered video fallback destinations.

The existing primary/vision resolver stays in ``model_roles``. A fallback has
its own explicit endpoint and fixed slot credential; no other role's credential
is read or inferred here.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from ..env_config import env_str
from .host_protocol import protocol_refusal

_CHAIN_NAME = "JARVIS_ROLE_VIDEO_FALLBACKS"
_FIELDS = frozenset({"provider", "model", "base_url"})
_PROVIDERS = frozenset({"lm-studio", "openai-compatible"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_CHAIN_BYTES = 8192
_MAX_PROVIDER = 64
_MAX_MODEL = 256
_MAX_URL = 2048
_MAX_KEY = 4096
_MAX_ROUTES = 4


class VideoRouteConfigError(ValueError):
    """Sanitized refusal of the complete configured fallback chain."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VideoFallbackRoute:
    slot: int
    provider: str
    model: str
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)


def _read(env: Mapping[str, str] | None, name: str) -> str:
    value = env_str(name, "") if env is None else env.get(name, "")
    if not isinstance(value, str):
        raise VideoRouteConfigError("video_fallback_value_invalid")
    return value


def _string(row: dict, name: str, maximum: int) -> str:
    value = row[name]
    if not isinstance(value, str) or len(value) > maximum:
        raise VideoRouteConfigError("video_fallback_field_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise VideoRouteConfigError("video_fallback_field_invalid") from None
    return value.strip()


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base_url(raw: str, provider: str) -> str:
    if (not raw or len(raw) > _MAX_URL or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw)
            or any(c in raw for c in ("?", "#", "\\"))):
        raise VideoRouteConfigError("video_fallback_url_invalid")
    try:
        parts = urlsplit(raw)
        scheme, host, port = parts.scheme.lower(), parts.hostname, parts.port
    except ValueError:
        raise VideoRouteConfigError("video_fallback_url_invalid") from None
    if (scheme not in _DEFAULT_PORTS or not host or "@" in parts.netloc
            or parts.username is not None or parts.password is not None
            or port == 0 or "%" in parts.netloc):
        raise VideoRouteConfigError("video_fallback_url_invalid")
    host = host.lower()
    if (provider == "lm-studio" and not _loopback(host)) or (not _loopback(host) and scheme != "https"):
        raise VideoRouteConfigError("video_fallback_url_invalid")
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise VideoRouteConfigError("video_fallback_url_invalid") from None
        authority = f"[{host}]"
    else:
        if (not all(c.isascii() and (c.isalnum() or c in "-._") for c in host)
                or host.startswith((".", "-")) or ".." in host):
            raise VideoRouteConfigError("video_fallback_url_invalid")
        authority = host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        authority += f":{port}"
    normalized = urlunsplit((scheme, authority, parts.path.rstrip("/"), "", ""))
    if protocol_refusal(provider, normalized):
        raise VideoRouteConfigError("video_fallback_protocol_invalid")
    return normalized


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    row: dict = {}
    for name, value in pairs:
        if name in row:
            raise VideoRouteConfigError("video_fallback_fields_invalid")
        row[name] = value
    return row


def resolve_video_fallbacks(env: Mapping[str, str] | None = None) -> tuple[VideoFallbackRoute, ...]:
    """Read and validate the complete bounded chain before returning any route."""
    raw = _read(env, _CHAIN_NAME)
    try:
        raw_size = len(raw.encode("utf-8"))
    except UnicodeError:
        raise VideoRouteConfigError("video_fallback_json_invalid") from None
    if raw_size > _MAX_CHAIN_BYTES:
        raise VideoRouteConfigError("video_fallback_chain_too_large")
    if not raw.strip():
        return ()
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except VideoRouteConfigError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise VideoRouteConfigError("video_fallback_json_invalid") from None
    if not isinstance(parsed, list) or len(parsed) > _MAX_ROUTES:
        raise VideoRouteConfigError("video_fallback_chain_invalid")
    routes: list[VideoFallbackRoute] = []
    for slot, row in enumerate(parsed, 1):
        if not isinstance(row, dict) or row.keys() != _FIELDS:
            raise VideoRouteConfigError("video_fallback_fields_invalid")
        provider = _string(row, "provider", _MAX_PROVIDER).lower()
        model = _string(row, "model", _MAX_MODEL)
        base = _string(row, "base_url", _MAX_URL)
        if provider not in _PROVIDERS:
            raise VideoRouteConfigError("video_fallback_provider_unsupported")
        if not model or model.lower() == "auto":
            raise VideoRouteConfigError("video_fallback_model_invalid")
        base = _base_url(base, provider)
        key = _read(env, f"JARVIS_ROLE_VIDEO_FALLBACK_{slot}_KEY")
        if (len(key) > _MAX_KEY or any(not 32 <= ord(c) <= 126 for c in key)):
            raise VideoRouteConfigError("video_fallback_key_invalid")
        routes.append(VideoFallbackRoute(slot, provider, model, base, key.strip()))
    return tuple(routes)
