"""Bounded read-only Krea job polling after a separately governed submit.

The caller owns the signed task, persisted job id, credentials, transport,
egress policy, and local artifact publication. Polling never submits a POST.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import time

import httpx

from .krea_image import parse_job_id, parse_job_status, poll_endpoint

_RETRYABLE_HTTP = frozenset({408, 409, 425, 429})
_INITIAL_INTERVAL = 2.0
_MAX_INTERVAL = 5.0
_BACKOFF = 1.3


class KreaPollDeadline(TimeoutError):
    def __init__(self):
        super().__init__("krea_poll_deadline")


class KreaJobFailed(RuntimeError):
    def __init__(self, state):
        self.state = state
        super().__init__("krea_job_" + state)


class KreaPollResponseError(ValueError):
    def __init__(self):
        super().__init__("krea_poll_invalid_response")


async def poll_job(
    job_id, get_status, *, check, sleep=asyncio.sleep,
    monotonic=time.monotonic, deadline_seconds=180,
):
    """Poll one fixed-origin job endpoint and return its untrusted URL candidate.

    ``get_status(endpoint)`` must be an async callback returning ``(HTTP status,
    decoded JSON dict or None)``. Its transport must be credential-bound and
    DNS-pinned by the caller. ``check()`` may be sync or async and is never caught.
    """
    if (type(deadline_seconds) not in {int, float} or
            not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= 180):
        raise ValueError("invalid Krea poll deadline")
    endpoint = poll_endpoint(job_id)
    if not callable(get_status) or not callable(check):
        raise ValueError("Krea poll callbacks required")
    deadline = monotonic() + deadline_seconds
    interval = _INITIAL_INTERVAL

    async def recheck():
        result = check()
        if inspect.isawaitable(result):
            await result

    while True:
        await recheck()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise KreaPollDeadline()
        await sleep(min(interval, remaining))
        await recheck()
        if monotonic() >= deadline:
            raise KreaPollDeadline()
        try:
            response = await get_status(endpoint)
        except (httpx.TimeoutException, httpx.NetworkError):
            await recheck()
            if monotonic() >= deadline:
                raise KreaPollDeadline() from None
            interval = min(interval * _BACKOFF, _MAX_INTERVAL)
            continue
        except Exception:
            # A transport admission check can fail after the earlier check (DNS
            # may yield while the owner disables the provider). Preserve that
            # live governance cause before classifying machinery as a response error.
            await recheck()
            raise KreaPollResponseError() from None
        await recheck()
        if monotonic() >= deadline:
            raise KreaPollDeadline()
        if not isinstance(response, tuple) or len(response) != 2 or type(response[0]) is not int:
            raise KreaPollResponseError()
        status, body = response
        if status in _RETRYABLE_HTTP or 500 <= status <= 599:
            interval = min(interval * _BACKOFF, _MAX_INTERVAL)
            continue
        if not 200 <= status < 300 or not isinstance(body, dict):
            raise KreaPollResponseError()
        try:
            if "job_id" in body and parse_job_id(body) != job_id:
                raise ValueError("Krea job identity changed")
            parsed = parse_job_status(body)
        except ValueError:
            raise KreaPollResponseError() from None
        if parsed["state"] == "completed":
            return parsed["url"]
        if parsed["state"] in {"failed", "cancelled"}:
            raise KreaJobFailed(parsed["state"])
        interval = min(interval * _BACKOFF, _MAX_INTERVAL)
