"""``agent.provider_media`` for the adopted video files (rewrite rule ``video-provider-media``).

Upstream saves a provider's video into ``$HERMES_HOME/cache/generated/videos/`` (a URL
download, raw bytes or base64). Here the bytes land only in the **staging folder of one
approved video task** (:func:`bound_sink`, set by Nerva's video runtime around the
vendored ``generate`` call); with nothing bound every save is refused. A URL download goes
through the compat ``httpx`` (the task's egress client: manifest host allowlist, SSRF
pinning, kernel hook, ledger), as a stream capped at the sink's byte limit, with no
redirect followed. The runtime then validates the file (MP4 or WebM), moves it into the
media store and records it; nothing here is served or trusted.

``trusted_origin`` and upstream's private-address exceptions are ignored: the egress
client decides where a request may go.
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from agents.vendor.hermes_compat import httpx

#: Upstream's sub-folder name (kept for the vendored ``_GENERATED_VIDEO_KIND`` constant).
GENERATED_SUBDIR = "generated"

_NAME = re.compile(r"[a-z0-9-]{1,32}")


class SinkRefused(PermissionError):
    """No approved video task is bound, or a file would break its limits."""


@dataclass
class VideoSink:
    """Where one approved task's provider files may land, and how much."""

    directory: Path
    max_bytes: int
    files: list[Path] = field(default_factory=list)
    #: Hosts a provider URL may be fetched from (the task's manifest); a URL elsewhere is
    #: refused here, before any dial, so the task's egress latch stays open for a fallback.
    hosts: tuple[str, ...] = ()
    #: Job ids the compat OpenAI ``videos.create`` saw (DeepInfra's download fallback).
    job_ids: list[str] = field(default_factory=list)


_SINK: contextvars.ContextVar[VideoSink | None] = contextvars.ContextVar(
    "hermes_compat_video_sink", default=None)


@contextlib.contextmanager
def bound_sink(directory: Path, max_bytes: int, hosts: tuple[str, ...] = ()) -> Iterator[VideoSink]:
    sink = VideoSink(Path(directory), int(max_bytes), hosts=tuple(hosts))
    token = _SINK.set(sink)
    try:
        yield sink
    finally:
        _SINK.reset(token)


def current_sink() -> VideoSink | None:
    return _SINK.get()


def _write(raw: bytes, *, prefix: str, extension: str) -> str:
    sink = _SINK.get()
    if sink is None:
        raise SinkRefused("no approved video task is bound")
    if not raw:
        raise ValueError("empty video")
    if len(raw) > sink.max_bytes:
        raise SinkRefused("video over the size cap")
    name_prefix = prefix if _NAME.fullmatch(str(prefix or "")) else "video"
    ext = extension if str(extension or "") in ("mp4", "webm", "mov", "mkv") else "mp4"
    target = sink.directory / f"{name_prefix}-{uuid.uuid4().hex}.{ext}"
    with open(target, "xb") as handle:
        handle.write(raw)
    sink.files.append(target)
    return str(target)


def save_bytes(kind: str, raw: bytes, *, prefix: str = "video", extension: str = "mp4") -> str:
    del kind
    return _write(bytes(raw or b""), prefix=prefix, extension=extension)


def save_b64(kind: str, b64_data: str, *, prefix: str = "video", extension: str = "mp4") -> str:
    del kind
    sink = _SINK.get()
    if sink is None:
        raise SinkRefused("no approved video task is bound")
    text = str(b64_data or "")
    if len(text) > (sink.max_bytes * 4) // 3 + 8:
        raise SinkRefused("video over the size cap")
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError:  # binascii.Error is a ValueError
        raise ValueError("invalid base64 video") from None
    return _write(raw, prefix=prefix, extension=extension)


def host_admitted(url: str, sink: VideoSink | None = None) -> bool:
    """True when *url* is https on one of the sink's hosts (or a sub-domain of one)."""
    from urllib.parse import urlsplit

    sink = sink or _SINK.get()
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower().rstrip(".")
    return bool(sink and parts.scheme == "https" and host
                and any(host == h or host.endswith("." + h) for h in sink.hosts))


def save_data_uri(url: str, *, prefix: str = "video") -> str:
    """A ``data:video/...;base64,...`` answer (DeepInfra documents one) into the sink, capped."""
    if _SINK.get() is None:
        raise SinkRefused("no approved video task is bound")
    head, _, payload = str(url or "").partition(",")
    kind = head[5:].split(";", 1)[0].lower() if head.startswith("data:") else ""
    if not head.endswith(";base64") or kind not in ("video/mp4", "video/webm", "video/quicktime"):
        raise ValueError("not a base64 video data URI")
    return save_b64("videos", payload, prefix=prefix,
                    extension={"video/webm": "webm", "video/quicktime": "mov"}.get(kind, "mp4"))


def save_url(kind: str, url: str, *, prefix: str = "video", timeout: float = 180.0,
             max_bytes: int = 0, chunk_size: int = 0, content_types: dict | None = None,
             url_extensions: tuple = (), default_extension: str = "mp4", label: str = "Video",
             empty_error: str = "", headers: dict | None = None,
             require_known_content_type: bool = False, trusted_origin: bool = False) -> str:
    """Download *url* into the bound sink through the task's egress client."""
    del kind, chunk_size, url_extensions, label, empty_error, trusted_origin
    sink = _SINK.get()
    if sink is None:
        raise SinkRefused("no approved video task is bound")
    if str(url or "").startswith("data:"):
        return save_data_uri(str(url), prefix=prefix)
    if not host_admitted(str(url), sink):
        raise SinkRefused("video host not admitted")
    limit = min(int(max_bytes or sink.max_bytes), sink.max_bytes)
    status, body, ctype = httpx.download(str(url), max_bytes=limit, headers=headers,
                                         timeout=min(float(timeout or 85.0), 85.0))
    if status != 200:
        raise httpx.HTTPStatusError(f"HTTP {status}", response=httpx.Response(status))
    known = dict(content_types or {})
    if require_known_content_type and ctype not in known:
        raise ValueError("not a video content type")
    return _write(body, prefix=prefix, extension=known.get(ctype, default_extension))


__all__ = ["GENERATED_SUBDIR", "SinkRefused", "VideoSink", "bound_sink", "current_sink",
           "host_admitted", "save_b64", "save_bytes", "save_data_uri", "save_url"]
