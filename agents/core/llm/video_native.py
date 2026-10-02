"""Pure Gemini generateContent codec for an approved video source.

This module never reads configuration or sends a request. The caller owns consent,
credential selection, source materialization, transport, and final wire validation.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .host_protocol import protocol_refusal

GEMINI_VIDEO_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_VIDEO_MAX_REQUEST_BYTES = 20_000_000
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/avi",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}

_SUPPORTED_MIME = frozenset(VIDEO_MIME.values()) - {"video/x-matroska"}
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z", re.ASCII)
_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}\Z", re.ASCII)
_DEFAULT_PORTS = {"http": 80, "https": 443}


class VideoNativeRefused(ValueError):
    """A sanitized refusal of an invalid native video request or response."""


class VideoNativeEmpty(VideoNativeRefused):
    """A valid unblocked STOP response containing no visible video answer."""


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base(raw: str) -> str:
    if (not isinstance(raw, str) or not raw or len(raw) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw)
            or any(c in raw for c in ("?", "#", "\\", "%"))):
        raise VideoNativeRefused("video_native_url_invalid")
    try:
        parts = urlsplit(raw)
        scheme, host, port = parts.scheme.lower(), parts.hostname, parts.port
    except ValueError:
        raise VideoNativeRefused("video_native_url_invalid") from None
    if (scheme not in _DEFAULT_PORTS or not host or "@" in parts.netloc
            or parts.username is not None or parts.password is not None or port == 0):
        raise VideoNativeRefused("video_native_url_invalid")
    host = host.lower()
    if not _loopback(host) and scheme != "https":
        raise VideoNativeRefused("video_native_url_invalid")
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise VideoNativeRefused("video_native_url_invalid") from None
        authority = f"[{host}]"
    else:
        if (not all(c.isascii() and (c.isalnum() or c in "-._") for c in host)
                or host.startswith((".", "-")) or ".." in host):
            raise VideoNativeRefused("video_native_url_invalid")
        authority = host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        authority += f":{port}"
    path = parts.path.rstrip("/")
    if any(segment in (".", "..") for segment in path.split("/")):
        raise VideoNativeRefused("video_native_url_invalid")
    if not all(c.isascii() and (c.isalnum() or c in "/-._") for c in path):
        raise VideoNativeRefused("video_native_url_invalid")
    normalized = urlunsplit((scheme, authority, path, "", ""))
    if protocol_refusal("gemini", normalized):
        raise VideoNativeRefused("video_native_protocol_invalid")
    return normalized


def gemini_request_url(base_url: str, model: str) -> str:
    """Build one native endpoint without permitting model or path injection."""
    if not isinstance(model, str) or len(model) > 256:
        raise VideoNativeRefused("video_native_model_invalid")
    slug = model.removeprefix("models/")
    if not _MODEL.fullmatch(slug):
        raise VideoNativeRefused("video_native_model_invalid")
    base = GEMINI_VIDEO_BASE if base_url == "" else _base(base_url)
    return f"{base}/models/{slug}:generateContent"


def gemini_video_mime(mime: str) -> str:
    """Permit only the declared containers this native adapter supports."""
    if not isinstance(mime, str) or mime not in _SUPPORTED_MIME:
        raise VideoNativeRefused("video_native_mime_unsupported")
    return mime


def gemini_video_body(prompt: str, data_url: str) -> dict:
    """Convert an exact prepared data URL into a bounded native request body."""
    if not isinstance(prompt, str) or not isinstance(data_url, str):
        raise VideoNativeRefused("video_native_body_invalid")
    prefix, marker, encoded = data_url.partition(";base64,")
    if not marker or not prefix.startswith("data:") or not encoded:
        raise VideoNativeRefused("video_native_data_invalid")
    mime = gemini_video_mime(prefix.removeprefix("data:"))
    if not _BASE64.fullmatch(encoded):
        raise VideoNativeRefused("video_native_data_invalid")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise VideoNativeRefused("video_native_data_invalid") from None
    if not decoded or base64.b64encode(decoded).decode("ascii") != encoded:
        raise VideoNativeRefused("video_native_data_invalid")
    body = {"contents": [{"role": "user", "parts": [
        {"text": prompt}, {"inline_data": {"mime_type": mime, "data": encoded}},
    ]}]}
    try:
        size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (UnicodeError, ValueError):
        raise VideoNativeRefused("video_native_body_invalid") from None
    if size >= GEMINI_VIDEO_MAX_REQUEST_BYTES:
        raise VideoNativeRefused("video_native_body_too_large")
    return body


def gemini_video_answer(payload: object) -> str:
    """Return visible text only from one unblocked STOP candidate."""
    if not isinstance(payload, dict):
        raise VideoNativeRefused("video_native_response_invalid")
    feedback = payload.get("promptFeedback")
    if feedback is not None and (not isinstance(feedback, dict) or feedback.get("blockReason")):
        raise VideoNativeRefused("video_native_response_invalid")
    if isinstance(feedback, dict) and _ratings_refused(feedback.get("safetyRatings", [])):
        raise VideoNativeRefused("video_native_response_invalid")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise VideoNativeRefused("video_native_response_invalid")
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("finishReason") != "STOP":
        raise VideoNativeRefused("video_native_response_invalid")
    ratings = candidate.get("safetyRatings", [])
    if _ratings_refused(ratings):
        raise VideoNativeRefused("video_native_response_invalid")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise VideoNativeRefused("video_native_response_invalid")
    visible: list[str] = []
    empty_parts_valid = True
    text_part_seen = False
    for part in parts:
        if not isinstance(part, dict) or type(part.get("thought", False)) is not bool:
            raise VideoNativeRefused("video_native_response_invalid")
        if part.get("thought") is True:
            if (not isinstance(part.get("text"), str)
                    or set(part) - {"thought", "text"}):
                empty_parts_valid = False
            else:
                text_part_seen = True
            continue
        if not isinstance(part.get("text"), str):
            raise VideoNativeRefused("video_native_response_invalid")
        text_part_seen = True
        if set(part) - {"thought", "text"}:
            empty_parts_valid = False
        visible.append(part["text"])
    answer = "".join(visible)
    if not answer.strip():
        if (empty_parts_valid and text_part_seen and "error" not in payload
                and "error" not in candidate and "error" not in content
                and not (isinstance(feedback, dict) and "error" in feedback)):
            raise VideoNativeEmpty("video_native_response_empty")
        raise VideoNativeRefused("video_native_response_invalid")
    return answer


def _ratings_refused(ratings: object) -> bool:
    return not isinstance(ratings, list) or any(
        not isinstance(row, dict)
        or ("blocked" in row and type(row["blocked"]) is not bool)
        or row.get("blocked") is True
        for row in ratings
    )
