"""Configuration-bound data and physical-wire policy for approved video analysis."""
from __future__ import annotations

import hashlib
import hmac
import inspect
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
from .model_roles import RoleConfigError, _is_loopback_base, resolve_video_route
from .providers import get_profile
from .video_native import GEMINI_VIDEO_MAX_REQUEST_BYTES, gemini_request_url
from .video_routes import VideoRouteConfigError, resolve_video_fallbacks


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

    @property
    def request_headers(self) -> dict[str, str]:
        if not self.authorization:
            return {}
        if self.provider == "gemini":
            return {"x-goog-api-key": self.authorization}
        return {"Authorization": self.authorization}


def _describe_primary_video_target() -> VideoIdentity | None:
    """The exact currently configured role; listing never enables the tool."""
    try:
        route = resolve_video_route()
    except RoleConfigError as exc:
        raise VideoPolicyRefused("invalid video role configuration") from exc
    role = route.role
    if not role.configured:
        return None
    if role.provider_id not in {"lm-studio", "openai-compatible", "gemini"}:
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
        request_url = (gemini_request_url(role.base_url, role.model) if role.provider_id == "gemini" else
                       route.request_url if route.inherited else
                       base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"))
    except Exception as exc:
        raise VideoPolicyRefused("invalid video role destination") from exc
    profile = get_profile(role.provider_id)
    policy, note = profile.data_policy_for(role.model)
    if role.provider_id == "openai-compatible" or not local:
        policy, note = "unknown", "Video endpoint data handling is unknown."
    raw_key = env_str("JARVIS_ROLE_VIDEO_KEY", "")
    if role.provider_id == "gemini" and (len(raw_key) > 4096 or any(not 32 <= ord(c) <= 126 for c in raw_key)):
        raise VideoPolicyRefused("invalid video role key")
    key = raw_key.strip()
    if not key and role.provider_id != "gemini":
        # Only the vision adapter's guarded effective key may cross to video,
        # and only onto its own exact native endpoint and provider.
        try:
            from .vision_policy import VisionPolicyUnavailable
            from .vision_policy import describe as describe_vision
            from .vlm import VLMNotConfigured, resolve_vlm_config

            vision = resolve_vlm_config()
            native = describe_vision(vision)
            if (native.provider == role.provider_id
                    and str(httpx.URL(native.request_url)) == str(httpx.URL(request_url))):
                key = vision.api_key
        except (ValueError, VLMNotConfigured, VisionPolicyUnavailable):
            pass
    authorization = key if role.provider_id == "gemini" else f"Bearer {key}" if key else ""
    binding = (role.provider_id, role.model, role.base_url, request_url, authorization,
               local, policy, note, env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE"))
    if role.provider_id == "gemini":
        binding += ("gemini_generate_content", "x-goog-api-key")
    return VideoIdentity(VIDEO_TARGET, role.provider_id, role.model, "dedicated", policy, note,
                         local, request_url, authorization, binding)


def describe_video_route_set() -> tuple[VideoIdentity, ...]:
    """Resolve the complete configured chain before exposing any usable candidate."""
    try:
        fallbacks = resolve_video_fallbacks()
    except VideoRouteConfigError as exc:
        raise VideoPolicyRefused("invalid video fallback configuration") from exc
    primary = _describe_primary_video_target()
    if primary is None:
        if fallbacks:
            raise VideoPolicyRefused("video fallback requires a configured primary")
        return ()
    identities = [primary]
    for route in fallbacks:
        local = _is_loopback_base(route.base_url)
        profile = get_profile(route.provider)
        policy, note = profile.data_policy_for(route.model)
        if route.provider == "openai-compatible" or not local:
            policy, note = "unknown", "Video endpoint data handling is unknown."
        base = route.base_url.rstrip("/")
        request_url = (gemini_request_url(base, route.model) if route.provider == "gemini" else
                       str(httpx.URL(base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"))))
        authorization = route.api_key if route.provider == "gemini" else f"Bearer {route.api_key}" if route.api_key else ""
        binding = (route.provider, route.model, route.base_url, request_url, authorization,
                   local, policy, note, env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE"))
        if route.provider == "gemini":
            binding += ("gemini_generate_content", "x-goog-api-key")
        identities.append(VideoIdentity(f"role:video_fallback_{route.slot}", route.provider,
                                        route.model, "dedicated", policy, note, local,
                                        request_url, authorization, binding))
    return tuple(identities)


def describe_video_data_target(target_id: str = VIDEO_TARGET) -> VideoIdentity | None:
    """Return a current finite candidate descriptor, or refuse an unknown target."""
    if target_id not in (VIDEO_TARGET, *(f"role:video_fallback_{slot}" for slot in range(1, 5))):
        raise VideoPolicyRefused("unknown video target")
    return next((identity for identity in describe_video_route_set()
                 if identity.target_id == target_id), None)


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
    current = describe_video_data_target(identity.target_id)
    if current is None or current != identity:
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


def chain_class_binding(identities: tuple[VideoIdentity, ...], args: dict,
                        roots: tuple[str, ...]) -> str:
    """Bind every ordered destination; retain the original class for one lane."""
    if len(identities) == 1:
        return class_binding(identities[0], args, roots)
    material = json.dumps([[(identity.target_id, identity.binding) for identity in identities],
                           args, roots], sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(_scope_key(), b"H277:video-approval:chain:v1\0" + material,
                      hashlib.sha256).hexdigest()
    return "video." + digest[:56]


@contextmanager
def native_video_request_scope(identity: VideoIdentity, client: httpx.AsyncClient, *,
                               expected_body: dict, check, record_use=None, mark_dispatch=None):
    """Recheck authority and exact native request at each physical send and cleanup."""
    marker = object()
    # Freeze before the adapter sees the mutable json kwargs. A later mutation of
    # both the body and its Python alias cannot redefine what the owner approved.
    expected_digest = hashlib.sha256(json.dumps(
        expected_body, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).digest()

    def guarded_check():
        try:
            check()
        except VideoPolicyRefused:
            raise
        except Exception as exc:
            raise VideoPolicyRefused("video authority check refused") from exc

    def validate(request: httpx.Request, *, marked: bool):
        try:
            require_direct_async_transport(client, request.url)
            if (identity.provider == "gemini"
                    and len(request.content) >= GEMINI_VIDEO_MAX_REQUEST_BYTES):
                raise VideoPolicyRefused("video physical request too large")
            body = json.loads(request.content)
            actual_digest = hashlib.sha256(json.dumps(
                body, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode()).digest()
            valid = hmac.compare_digest(actual_digest, expected_digest)
        except (TypeError, ValueError, httpx.RequestNotRead):
            valid = False
        except Exception as exc:
            raise VideoPolicyRefused("video physical request refused") from exc
        if ((request.extensions.get("nerva_video_request") is marker) != marked
                or request.method != "POST" or str(request.url) != identity.request_url
                or request.headers.get_list("Authorization") != ([identity.authorization] if identity.provider != "gemini" and identity.authorization else [])
                or request.headers.get_list("x-goog-api-key") != ([identity.authorization] if identity.provider == "gemini" and identity.authorization else [])
                or request.headers.get("Cookie") or not valid):
            raise VideoPolicyRefused("video physical request changed")

    def physical(request: httpx.Request):
        validate(request, marked=False)
        request.extensions["nerva_video_request"] = marker

    async def last_request_hook(request: httpx.Request):
        # The egress recorder runs physical() before transport. A user hook added
        # after that recorder may still fail or mutate the request. This final
        # hook proves all earlier hooks finished before counting a real send.
        if client.event_hooks["request"][-1] is not last_request_hook:
            raise VideoPolicyRefused("video request hooks changed")
        guarded_check()
        validate(request, marked=True)
        if mark_dispatch is not None:
            mark_dispatch()
        if record_use is not None:
            try:
                record_use()
            except Exception as exc:
                raise VideoPolicyRefused("video actual-use refused") from exc

    guarded_check()
    require_direct_async_transport(client, identity.request_url)
    response_hooks = client.event_hooks["response"]
    wrapped_response_hooks = []
    for hook in response_hooks:
        async def guarded_response_hook(response, callback=hook):
            try:
                result = callback(response)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                raise VideoPolicyRefused("video response hook refused") from exc

        wrapped_response_hooks.append(guarded_response_hook)
    client.event_hooks["response"] = wrapped_response_hooks
    client.event_hooks["request"].append(last_request_hook)
    try:
        with physical_request_scope(guarded_check, request_check=physical):
            yield
            guarded_check()
    finally:
        client.event_hooks["request"].remove(last_request_hook)
        client.event_hooks["response"] = response_hooks
