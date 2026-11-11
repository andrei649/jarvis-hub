"""A stand-in for ``httpx`` that vendored Hermes code imports instead of the real one.

It exposes only what the vendored files use — ``get`` / ``post`` / ``request``, a small
``Client``, ``Response`` (``status_code`` / ``text`` / ``json()`` / ``headers`` /
``raise_for_status()``) and the ``HTTPStatusError`` / ``RequestError`` family — and it owns
**no network client at all**. Every request is handed to the Nerva ``PluginHTTPClient`` the
adapter bound for the current search (:func:`bound_egress`), so the manifest allowlist, SSRF
resolution with IP pinning, the per-plugin breaker, the egress ledger and the kernel's
``plugin.egress`` hook apply exactly as they do to a native provider.

With nothing bound (vendored code called outside an adapter, or from a thread that did not
inherit the binding) a request is refused: there is no fallback to a direct dial.

The vendored code is synchronous and catches broad exceptions itself, so a refusal could be
swallowed into a generic ``{"success": False}`` and look like an ordinary failure. The
binding therefore keeps the outcome: the first gate refusal is recorded on it, every later
request in the same call is refused without dialling (a refusal is never retried), and the
adapter raises Nerva's ``PolicyBlock`` from that record whatever the vendored code returned.
Exception messages carry a status code or an exception type only — never a URL, a query,
a header or a key.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json as _json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

#: Upper bound on how long a vendored call may wait for one request (seconds).
MAX_WAIT_SECONDS = 90.0
#: How often a waiting worker thread checks whether its caller gave up (seconds).
POLL_SECONDS = 0.1
#: Request headers that carry a credential. A request carrying one is never sent with
#: ``follow_redirects`` (the egress client strips only Authorization/Cookie cross-origin).
CREDENTIAL_HEADERS = frozenset({"authorization", "x-api-key", "x-subscription-token",
                                "api-key", "x-goog-api-key", "proxy-authorization", "cookie"})


class HTTPError(Exception):
    """Base of the stand-in's errors (``httpx.HTTPError``)."""


class RequestError(HTTPError):
    """The request did not get an answer (``httpx.RequestError``)."""


class ConnectError(RequestError):
    """Refused or failed before an answer (``httpx.ConnectError``)."""


class TimeoutException(RequestError):
    """No answer in time (``httpx.TimeoutException``)."""


class EgressRefused(ConnectError):
    """Nerva's egress layer refused the request (allowlist, SSRF guard, kernel, no binding)."""


class HTTPStatusError(HTTPError):
    """``raise_for_status`` on a >= 400 answer (``httpx.HTTPStatusError``)."""

    def __init__(self, message: str, *, request: Any = None, response: Response) -> None:
        super().__init__(message)
        self.request = request
        self.response = response


class Response:
    """The parts of ``httpx.Response`` vendored code reads."""

    def __init__(self, status_code: int, content: bytes = b"", headers: Any = None,
                 encoding: str | None = None) -> None:
        self.status_code = int(status_code)
        self.content = content
        self.headers = dict(headers or {})
        self._encoding = encoding or "utf-8"

    @classmethod
    def from_egress(cls, resp: Any) -> Response:
        content = getattr(resp, "content", b"")
        if not isinstance(content, (bytes, bytearray)):
            content = str(getattr(resp, "text", "") or "").encode("utf-8")
        headers = getattr(resp, "headers", {}) or {}
        try:
            headers = dict(headers.items())
        except Exception:
            headers = {}
        return cls(int(getattr(resp, "status_code", 0) or 0), bytes(content), headers,
                   getattr(resp, "encoding", None))

    @property
    def text(self) -> str:
        return self.content.decode(self._encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> Response:
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code}", response=self)
        return self

    def __repr__(self) -> str:
        return f"<Response [{self.status_code}]>"


@dataclass
class EgressCall:
    """One adapter call: the egress client, the loop that owns it, and what happened."""

    client: Any
    loop: asyncio.AbstractEventLoop
    loop_thread: int
    policy_block: str = ""
    failure: str = ""
    statuses: list[int] = field(default_factory=list)
    requests: int = 0
    #: ``time.monotonic()`` after which no request may start or keep waiting.
    deadline: float = float("inf")
    #: Set by the adapter when its caller left (cancelled or timed out).
    abandoned: threading.Event = field(default_factory=threading.Event)
    #: Slice 4: one sub-call per fan-out task (``bind_child``), each with its own latch.
    children: list = field(default_factory=list)

    def abandon(self) -> None:
        self.abandoned.set()


_CALL: contextvars.ContextVar[EgressCall | None] = contextvars.ContextVar(
    "hermes_compat_egress_call", default=None)


@contextlib.contextmanager
def bound_egress(client: Any, loop: asyncio.AbstractEventLoop, *,
                 deadline: float = float("inf")) -> Iterator[EgressCall]:
    """Bind *client* for requests made in this context (and threads that copy it)."""
    call = EgressCall(client=client, loop=loop, loop_thread=threading.get_ident(),
                      deadline=deadline)
    token = _CALL.set(call)
    try:
        yield call
    finally:
        _CALL.reset(token)


def current_call() -> EgressCall | None:
    return _CALL.get()


@contextlib.contextmanager
def bind_child() -> Iterator[EgressCall | None]:
    """A fan-out task's own call: same client, loop, deadline and abandonment as the call
    it belongs to, but its own refusal latch, so one peer's refusal does not refuse the
    others. The parent keeps every child to report them. Nothing bound: nothing changes."""
    parent = _CALL.get()
    if parent is None:
        yield None
        return
    child = EgressCall(client=parent.client, loop=parent.loop, loop_thread=parent.loop_thread,
                       deadline=parent.deadline, abandoned=parent.abandoned)
    parent.children.append(child)
    token = _CALL.set(child)
    try:
        yield child
    finally:
        _CALL.reset(token)


def _is_dns_failure(text: str) -> bool:
    return text.startswith(("egress blocked: DNS resolution failed",
                            "egress blocked: empty DNS answer"))


def _timeout_seconds(timeout: Any) -> float:
    if isinstance(timeout, (int, float)) and timeout > 0:
        return min(float(timeout) + 5.0, MAX_WAIT_SECONDS)
    return MAX_WAIT_SECONDS


def request(method: str, url: str, *, params: Any = None, headers: Any = None,
            json: Any = None, data: Any = None, content: Any = None, timeout: Any = None,
            follow_redirects: bool = False) -> Response:
    """Send one request through the bound Nerva egress client, or refuse."""
    # A blocking wait on the loop that must run the request would deadlock it (_ready).
    call = _ready(_CALL.get())
    if follow_redirects and any(str(k).lower() in CREDENTIAL_HEADERS for k in dict(headers or {})):
        call.failure = call.failure or "redirect_with_credentials"
        raise ConnectError("a credential-bearing request does not follow redirects")
    kwargs: dict[str, Any] = {}
    for key, value in (("params", params), ("headers", headers), ("json", json),
                       ("data", data), ("content", content), ("timeout", timeout)):
        if value is not None:
            kwargs[key] = value
    if follow_redirects:
        kwargs["follow_redirects"] = True
    call.requests += 1
    sender = getattr(call.client, str(method).lower(), None)
    if not callable(sender):
        call.failure = call.failure or "unsupported_method"
        raise ConnectError("unsupported method")
    future = asyncio.run_coroutine_threadsafe(sender(url, **kwargs), call.loop)
    resp = _wait(call, future, timeout)
    wrapped = Response.from_egress(resp)
    call.statuses.append(wrapped.status_code)
    if wrapped.status_code >= 400:
        call.failure = call.failure or f"http_{wrapped.status_code}"
    return wrapped


def _ready(call: EgressCall | None) -> EgressCall:
    """The bound call, refused when there is none or it may not send any more."""
    if call is None:
        raise EgressRefused("no Nerva egress client is bound")
    if call.policy_block:
        raise EgressRefused("refused earlier in this call")
    if call.abandoned.is_set() or time.monotonic() >= call.deadline:
        call.failure = call.failure or "timeout"
        raise TimeoutException("timeout")
    if threading.get_ident() == call.loop_thread:
        call.failure = call.failure or "called_on_event_loop"
        raise ConnectError("vendored code ran on the event loop")
    return call


def _wait(call: EgressCall, future: Any, timeout: Any) -> Any:
    """Wait for *future* (scheduled on the call's loop) in short polls; classify errors."""
    give_up = min(call.deadline, time.monotonic() + _timeout_seconds(timeout))
    try:
        while True:
            # Short waits, so a worker never outlives the caller that left it.
            if call.abandoned.is_set() or time.monotonic() >= give_up:
                future.cancel()
                call.failure = call.failure or "timeout"
                raise TimeoutException("timeout")
            try:
                resp = future.result(timeout=POLL_SECONDS)
                break
            except TimeoutError:
                if future.done():  # the request itself raised TimeoutError
                    raise
                continue
    except TimeoutException:
        raise
    except PermissionError as exc:  # PluginEgressError: allowlist, SSRF, kernel
        if _is_dns_failure(str(exc)):
            call.failure = call.failure or "dns_failed"
            raise ConnectError("dns_failed") from None
        call.policy_block = "egress_blocked"
        raise EgressRefused("egress_blocked") from None
    except TimeoutError:
        call.failure = call.failure or "timeout"
        raise TimeoutException("timeout") from None
    except DownloadTooLarge:
        call.failure = call.failure or "too_large"
        raise
    except Exception as exc:
        call.failure = call.failure or type(exc).__name__
        raise ConnectError(type(exc).__name__) from None
    return resp


class DownloadTooLarge(HTTPError):
    """A capped download went over its byte limit (G19: generated video files)."""


def download(url: str, *, max_bytes: int, headers: Any = None,
             timeout: Any = None) -> tuple[int, bytes, str]:
    """GET *url* through the bound egress client as a stream, keeping at most *max_bytes*.

    Returns ``(status, body, content type)``; the body is empty for a non-200 answer. A
    declared or streamed length over the cap raises :class:`DownloadTooLarge` before more
    is read. Never follows a redirect. Same binding, refusal latch, deadline and
    abandonment as :func:`request`."""
    call = _ready(_CALL.get())
    limit = int(max_bytes)
    if limit <= 0:
        raise DownloadTooLarge("no download allowance")
    stream = getattr(call.client, "stream", None)
    if not callable(stream):
        call.failure = call.failure or "unsupported_method"
        raise ConnectError("unsupported method")
    request_headers = {**dict(headers or {}), "Accept-Encoding": "identity"}
    call.requests += 1

    async def fetch() -> tuple[int, bytes, str]:
        async with stream("GET", url, headers=request_headers, follow_redirects=False) as resp:
            status = int(getattr(resp, "status_code", 0) or 0)
            kind = str(resp.headers.get("content-type", "") or "").split(";", 1)[0].strip().lower()
            if status != 200:
                return status, b"", kind
            if resp.headers.get("content-encoding", "identity") not in ("identity", ""):
                raise DownloadTooLarge("encoded body refused")
            declared = resp.headers.get("content-length")
            if declared is not None and str(declared).isdigit() and int(declared) > limit:
                raise DownloadTooLarge("declared length over the cap")
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                if len(body) + len(chunk) > limit:
                    raise DownloadTooLarge("body over the cap")
                body.extend(chunk)
            return status, bytes(body), kind

    future = asyncio.run_coroutine_threadsafe(fetch(), call.loop)
    status, body, kind = _wait(call, future, timeout)
    call.statuses.append(status)
    if status >= 400:
        call.failure = call.failure or f"http_{status}"
    return status, body, kind


class AsyncClient:
    """``httpx.AsyncClient`` as the adopted xAI video plugin uses it (G19): ``post`` /
    ``get`` awaited inside a private event loop that the vendored code runs on its own
    worker thread. Each call is the synchronous :func:`request` above (the worker's loop
    is not the hub's, so blocking it is the vendored code's own business), so the egress
    binding, refusal latch, deadline and abandonment all apply. No transport, proxy, TLS
    or base-URL override is honoured."""

    def __init__(self, *, headers: Any = None, timeout: Any = None, **_ignored: Any) -> None:
        self.headers = dict(headers or {})
        self.timeout = timeout

    async def request(self, method: str, url: str, **kwargs: Any) -> Response:
        headers = {**self.headers, **dict(kwargs.pop("headers", None) or {})}
        kwargs.setdefault("timeout", self.timeout)
        return request(method, url, headers=headers, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def get(url: str, **kwargs: Any) -> Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> Response:
    return request("POST", url, **kwargs)


class Client:
    """``httpx.Client`` as vendored code uses it: verbs, headers, a context manager."""

    def __init__(self, *, headers: Any = None, timeout: Any = None, base_url: str = "",
                 **_ignored: Any) -> None:
        # No transport, proxy, TLS or base-URL host override is honoured: the bound egress
        # client decides all of that. ``base_url`` may only prefix a path.
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.base_url = str(base_url or "")

    def _merge(self, url: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self.base_url and url.startswith("/"):
            url = self.base_url.rstrip("/") + url
        headers = {**self.headers, **dict(kwargs.pop("headers", None) or {})}
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", self.timeout)
        return url, kwargs

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        url, kwargs = self._merge(url, kwargs)
        return request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        return None

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = [
    "AsyncClient", "Client", "ConnectError", "DownloadTooLarge", "EgressRefused", "HTTPError",
    "HTTPStatusError", "RequestError", "Response", "TimeoutException", "bound_egress", "current_call",
    "download", "get", "post", "request",
]
