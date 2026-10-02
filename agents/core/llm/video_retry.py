"""Fixed, bounded retry policy for an approved native video primary request."""
from __future__ import annotations

import os
from collections.abc import Mapping


class VideoRetryConfigError(ValueError):
    """The fixed video retry setting is ambiguous or out of range."""


class VideoEmptyRetryConfigError(ValueError):
    """The owner-controlled empty-result retry setting is invalid."""


def resolve_video_retry_count(env: Mapping[str, str] | None = None) -> int:
    """Resolve only the owner setting; never accept a caller-supplied budget."""
    source = os.environ if env is None else env
    raw = source.get("JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES", "")
    if not isinstance(raw, str) or len(raw) > 16:
        raise VideoRetryConfigError("invalid video retry setting")
    value = raw.strip(" ")
    if value in {"", "0"}:
        return 0
    if value == "1":
        return 1
    raise VideoRetryConfigError("invalid video retry setting")


def resolve_video_empty_retry_count(env: Mapping[str, str] | None = None) -> int:
    """Resolve the signed consumer retry count; callers cannot supply a budget."""
    source = os.environ if env is None else env
    raw = source.get("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "")
    if not isinstance(raw, str) or len(raw) > 16:
        raise VideoEmptyRetryConfigError("invalid video empty retry setting")
    value = raw.strip(" ")
    if value in {"", "0"}:
        return 0
    if value == "1":
        return 1
    raise VideoEmptyRetryConfigError("invalid video empty retry setting")


def native_retryable_status(status: int) -> bool:
    """Accept only bounded, exact HTTP transient response codes."""
    return type(status) is int and (status == 408 or 500 <= status <= 599)
