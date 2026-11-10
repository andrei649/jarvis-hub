"""The governed ``urllib`` of the vendored A2A client (rewrite rule ``a2a-urllib``, applied only
under ``plugins/platforms/a2a/``; ``import urllib.request`` anywhere else is still the refused
``urllib_refused``).

It offers what the three vendored files use: ``request.Request`` / ``request.urlopen``,
``error.URLError`` / ``error.HTTPError`` and ``parse`` (the standard library's, pure). It owns
no network client. ``urlopen`` does two things and nothing else:

1. It asks the **request guard** the Nerva outbound runtime bound for this call
   (:func:`bound_guard`) whether the request may go, and with which headers. The guard pins
   the request to the origins of the peers the owner configured and the call targets, and
   turns a peer's credential handle into its stored token only on that peer's own origin.
   No guard bound: refused.
2. It hands the request to the compat ``httpx``, so it goes through the ``PluginHTTPClient``
   bound for the call (manifest allowlist, SSRF resolution with IP pinning, breaker, egress
   ledger, the kernel's ``plugin.egress`` hook), with the same refusal latch, deadline and
   polled wait as the slice-1 searches. Redirects are not followed.

A refusal by the guard is recorded on the call's latch like an egress refusal, so every
later request of the call is refused without dialling and the runtime reports it whatever
the vendored code made of it. Messages carry a status code or a reason code only.
"""

from __future__ import annotations

import contextlib
import contextvars
import urllib.parse as parse
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

from agents.vendor.hermes_compat import httpx

#: The most a peer's answer may hold (bytes). A card or a reply is small; more is refused.
MAX_RESPONSE_BYTES = 1_000_000

#: ``guard(method, url, headers) -> headers`` or raise :class:`GuardRefused`.
Guard = Callable[[str, str, dict], dict]


class GuardRefused(Exception):
    """The request guard refused a request (carries a reason code)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class URLError(OSError):
    """``urllib.error.URLError``: no answer."""

    def __init__(self, reason: Any) -> None:
        super().__init__(reason)
        self.reason = reason

    def __str__(self) -> str:
        return f"<urlopen error {self.reason}>"


class HTTPError(URLError):
    """``urllib.error.HTTPError``: an answer with a status outside 2xx."""

    def __init__(self, url: str, code: int, msg: str = "", hdrs: Any = None, fp: Any = None) -> None:
        super().__init__(msg or f"HTTP {code}")
        self.code = int(code)
        self.msg = msg or f"HTTP {code}"
        self.hdrs = self.headers = dict(hdrs or {})
        self.filename = url
        self._body = b""

    def read(self, amt: int | None = None) -> bytes:
        return b""

    def __str__(self) -> str:
        return f"HTTP Error {self.code}"


class Request:
    """``urllib.request.Request``: URL, body, headers, method."""

    def __init__(self, url: str, data: bytes | None = None, headers: dict | None = None,
                 method: str | None = None, **_ignored: Any) -> None:
        self.full_url = str(url)
        self.data = data
        self.headers = {str(k): str(v) for k, v in dict(headers or {}).items()}
        self.method = method

    def get_method(self) -> str:
        return (self.method or ("POST" if self.data is not None else "GET")).upper()

    def add_header(self, key: str, value: str) -> None:
        self.headers[str(key)] = str(value)


class _Response:
    """What ``urlopen`` returns: ``read()``, ``status``, ``headers``, a context manager."""

    def __init__(self, url: str, status: int, body: bytes, headers: dict) -> None:
        self.url = url
        self.status = self.code = status
        self.headers = headers
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        body, self._body = (self._body, b"") if amt is None else (self._body[:amt], self._body[amt:])
        return body

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self._body = b""

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


_GUARD: contextvars.ContextVar[Guard | None] = contextvars.ContextVar(
    "hermes_compat_urllib_guard", default=None)


@contextlib.contextmanager
def bound_guard(guard: Guard) -> Iterator[Guard]:
    token = _GUARD.set(guard)
    try:
        yield guard
    finally:
        _GUARD.reset(token)


def _latch(reason: str) -> None:
    call = httpx.current_call()
    if call is not None and not call.policy_block:
        call.policy_block = reason


def urlopen(req: Request | str, data: bytes | None = None, timeout: Any = None, **_ignored: Any) -> _Response:
    """Send one request through the guard and the bound egress client, or refuse."""
    if not isinstance(req, Request):
        req = Request(str(req), data=data)
    elif data is not None:
        req.data = data
    method, url = req.get_method(), req.full_url
    guard = _GUARD.get()
    if guard is None:
        _latch("no_guard")
        raise URLError("egress_blocked")
    call = httpx.current_call()
    if call is not None and call.policy_block:
        raise URLError("egress_blocked")
    try:
        headers = guard(method, url, dict(req.headers))
    except GuardRefused as refusal:
        _latch(refusal.reason)
        raise URLError("egress_blocked") from None
    except Exception:
        _latch("guard_error")
        raise URLError("egress_blocked") from None
    try:
        resp = httpx.request(method, url, headers=headers, content=req.data, timeout=timeout)
    except httpx.EgressRefused:
        raise URLError("egress_blocked") from None
    except httpx.TimeoutException:
        raise URLError("timeout") from None
    except httpx.HTTPError as exc:
        raise URLError(str(exc) or "request_failed") from None
    if len(resp.content) > MAX_RESPONSE_BYTES:
        if call is not None:
            call.failure = call.failure or "response_too_large"
        raise URLError("response_too_large")
    if not 200 <= resp.status_code < 300:
        raise HTTPError(url, resp.status_code, hdrs=resp.headers)
    return _Response(url, resp.status_code, resp.content, resp.headers)


request = SimpleNamespace(Request=Request, urlopen=urlopen)
error = SimpleNamespace(URLError=URLError, HTTPError=HTTPError)
response = SimpleNamespace()

__all__ = ["GuardRefused", "HTTPError", "MAX_RESPONSE_BYTES", "Request", "URLError",
           "bound_guard", "error", "parse", "request", "response", "urlopen"]
