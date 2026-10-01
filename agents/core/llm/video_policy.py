"""Configuration-bound data and physical-wire policy for approved video analysis."""
from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from agents.core.env_config import env_flag, env_str

from . import selection_guards as sg
from .data_handling import (
    VIDEO_TARGET,
    DataHandlingRefused,
    _scope_key,
    authorize_role_target,
    physical_request_scope,
)
from .direct_transport import require_direct_async_transport
from .model_roles import _is_loopback_base, resolve
from .providers import get_profile


class VideoPolicyRefused(DataHandlingRefused):
    """The approved video destination or its authority changed."""


@dataclass(frozen=True)
class VideoIdentity:
    target_id: str
    provider: str
    model: str
    mode: str
    policy: str
    note: str
    local: bool
    request_url: str = field(repr=False)
    authorization: str = field(repr=False)
    binding: tuple = field(repr=False)


def describe_video_data_target() -> VideoIdentity | None:
    """The exact currently configured role; listing never enables the tool."""
    role = resolve("video")
    if not role.configured:
        return None
    if role.provider_id not in {"lm-studio", "openai-compatible"}:
        raise VideoPolicyRefused("video provider has no native adapter")
    try:
        url = httpx.URL(role.base_url)
        parts = urlsplit(role.base_url)
        if (url.scheme not in {"http", "https"} or not url.host or url.username or url.password
                or parts.query or parts.fragment or not role.model or len(role.model) > 256):
            raise ValueError("invalid video role URL")
        local = _is_loopback_base(role.base_url)
        if (role.provider_id == "lm-studio" and not local) or (not local and url.scheme != "https"):
            raise ValueError("video role locality or TLS changed")
        base = role.base_url.rstrip("/")
        request_url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    except Exception as exc:
        raise VideoPolicyRefused("invalid video role destination") from exc
    profile = get_profile(role.provider_id)
    policy, note = profile.data_policy_for(role.model)
    if role.provider_id == "openai-compatible" or not local:
        policy, note = "unknown", "Video endpoint data handling is unknown."
    key = env_str("JARVIS_ROLE_VIDEO_KEY", "").strip()
    authorization = f"Bearer {key}" if key else ""
    binding = (role.provider_id, role.model, role.base_url, request_url, authorization,
               local, policy, note, env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE"))
    return VideoIdentity(VIDEO_TARGET, role.provider_id, role.model, "dedicated", policy, note,
                         local, request_url, authorization, binding)


def authorization_check(identity: VideoIdentity, *, allow_remote: bool,
                        confirm_expensive: bool, router=None, actor: str = "") -> None:
    """Call at intake, execution, each physical send, and before result disclosure."""
    if not env_flag("JARVIS_VIDEO_ANALYSIS"):
        raise VideoPolicyRefused("video analysis is disabled")
    from agents.core import safe_mode

    from .host_protocol import protocol_refusal
    from .hybrid_router import LOCAL_ONLY_AGENTS

    if safe_mode.enabled():
        raise VideoPolicyRefused("video analysis is unavailable in safe mode")
    current = describe_video_data_target()
    if current is None or current.binding != identity.binding:
        raise VideoPolicyRefused("video role configuration changed")
    if not current.local:
        if not (allow_remote is True and env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE")):
            raise VideoPolicyRefused("remote video analysis requires explicit approval and role opt-in")
        if env_flag("JARVIS_STRICT_LOCAL"):
            raise VideoPolicyRefused("strict-local mode refuses remote video analysis")
        if safe_mode.get_value("llm", "cloud_fallback", "on-demand") == "never":
            raise VideoPolicyRefused("cloud fallback is disabled")
        if str(actor or "").strip().lower() in LOCAL_ONLY_AGENTS:
            raise VideoPolicyRefused("local-only agent cannot use a remote video model")
    if protocol_refusal(identity.provider, identity.request_url):
        raise VideoPolicyRefused("video role host requires another protocol")
    findings = sg.evaluate([sg.Choice("role.video", identity.provider, identity.model)])
    missing = {finding.needs for finding in findings}
    if "confirm_expensive" in missing and confirm_expensive is not True:
        raise VideoPolicyRefused("video model cost confirmation required")
    row = authorize_role_target(router, identity, actual_use=False)
    if not identity.local and not row["acknowledged"]:
        raise VideoPolicyRefused("remote video role acknowledgment required")


def class_binding(identity: VideoIdentity, args: dict, roots: tuple[str, ...]) -> str:
    """Secret-keyed, bounded ToolRPC class (the only label execute compares)."""
    import hashlib
    material = json.dumps([identity.binding, args, roots], sort_keys=True,
                          separators=(",", ":")).encode()
    digest = hmac.new(_scope_key(), b"H277:video-approval:v1\0" + material,
                      hashlib.sha256).hexdigest()
    return "video." + digest[:56]


@contextmanager
def native_video_request_scope(identity: VideoIdentity, client: httpx.AsyncClient, *,
                               expected_body: dict, check, record_use=None):
    """Recheck authority and exact native request at each physical send and cleanup."""
    marker = object()
    # Freeze before the adapter sees the mutable json kwargs. A later mutation of
    # both the body and its Python alias cannot redefine what the owner approved.
    expected_digest = hashlib.sha256(json.dumps(
        expected_body, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).digest()

    def physical(request: httpx.Request):
        require_direct_async_transport(client, request.url)
        try:
            body = json.loads(request.content)
            actual_digest = hashlib.sha256(json.dumps(
                body, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode()).digest()
            valid = hmac.compare_digest(actual_digest, expected_digest)
        except (TypeError, ValueError, httpx.RequestNotRead):
            valid = False
        if (request.extensions.get("nerva_video_request") is marker
                or request.method != "POST" or str(request.url) != identity.request_url
                or request.headers.get("Authorization", "") != identity.authorization
                or request.headers.get("Cookie") or not valid):
            raise VideoPolicyRefused("video physical request changed")
        request.extensions["nerva_video_request"] = marker
        if record_use is not None:
            record_use()

    check()
    require_direct_async_transport(client, identity.request_url)
    with physical_request_scope(check, request_check=physical):
        yield
        check()
