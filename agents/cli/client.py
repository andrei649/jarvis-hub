"""A stdlib-only client for the running hub, used by every online `nerva` verb.

Nothing here is a second API: the client speaks to the same routes the HUD speaks to,
with the same credentials (`JARVIS_ADMIN_TOKEN` / `JARVIS_USER_TOKEN`), so a verb can do
exactly what the HUD can do and nothing more. Stdlib only so it runs in a broken install.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_HUB_URL = "http://127.0.0.1:8080"


class HubError(Exception):
    """The hub answered with an error status."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(f"HTTP {status}: {reason}")
        self.status = status
        self.reason = reason


class HubUnavailable(HubError):
    """No hub answered at the configured address."""

    def __init__(self, url: str, detail: str) -> None:
        super().__init__(0, f"no hub at {url} ({detail})")
        self.url = url


#: Bind addresses that mean "every interface" — a hub bound there is dialled over
#: loopback (connecting *to* 0.0.0.0 fails on Windows; ``http://:::8080`` is no URL).
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})  # nosec B104 — compared against, never bound


def hub_url(environ: Mapping[str, str] | None = None) -> str:
    """The hub's base URL: ``NERVA_HUB_URL``, else the hub's own bind
    (``JARVIS_HOST``/``JARVIS_PORT``). ``scripts/doctor.py`` mirrors this (stdlib-only,
    import-light); ``tests/test_doctor.py`` pins the two equal."""
    env = os.environ if environ is None else environ
    explicit = (env.get("NERVA_HUB_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = (env.get("JARVIS_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (env.get("JARVIS_PORT") or "8080").strip() or "8080"
    if host in WILDCARD_HOSTS:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is refused: the 3xx stays an error. urllib carries every header but
    the content ones to wherever a redirect points, both tokens included."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_loopback_url(url: str) -> bool:
    """Whether *url* names this machine, by address rather than spelling: ``localhost``
    (a trailing dot too) or any loopback address (``127.0.0.2``, ``127.1``, ``::1`` …).
    ``scripts/doctor.py`` keeps the same rule in its own stdlib-only copy."""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    host = host.strip("[]").rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return False
    # An IPv4-mapped loopback (::ffff:127.0.0.1): the patched ipaddress counts it as
    # loopback, the 3.12 releases before that fix do not.
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(address.is_loopback or (mapped is not None and mapped.is_loopback))


def hub_open(request, timeout: float = 30.0):
    """Open a request to the hub over http or https (H273 third review, the doctor's A1
    for the CLI): a redirect is refused, and a hub on this machine is never reached
    through a proxy (an ``http_proxy`` with no ``no_proxy`` entry would otherwise receive
    the tokens in clear text). Any other scheme is a ``ValueError``."""
    url = str(getattr(request, "full_url", request))
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError("the hub address is not http or https")
    handlers: list = [_RefuseRedirects()]
    if is_loopback_url(url):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


class HubClient:
    def __init__(
        self,
        base_url: str = DEFAULT_HUB_URL,
        *,
        admin_token: str = "",
        user_token: str = "",
        opener: Callable[..., Any] = hub_open,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.user_token = user_token
        self._opener = opener
        self._timeout = timeout

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **kwargs: Any) -> HubClient:
        env = os.environ if environ is None else environ
        return cls(
            hub_url(env),
            admin_token=(env.get("JARVIS_ADMIN_TOKEN") or "").strip(),
            user_token=(env.get("JARVIS_USER_TOKEN") or "").strip(),
            **kwargs,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.admin_token:
            headers["x-admin-token"] = self.admin_token
        if self.user_token:
            headers["x-user-token"] = self.user_token
        return headers

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=self._headers()
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise HubError(exc.code, _error_reason(exc)) from None
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException, ValueError) as exc:
            # HTTPException: a reply cut off mid-body (IncompleteRead) or a garbled
            # status line is the hub being unreachable, not a crash in the verb; a
            # ValueError is an address that is not an http(s) URL.
            raise HubUnavailable(self.base_url, str(getattr(exc, "reason", exc))) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode("utf-8", errors="replace")

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body if body is not None else {})


def _error_reason(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return exc.reason if isinstance(exc.reason, str) else str(exc.code)
    if isinstance(payload, dict):
        for key in ("detail", "error", "reason", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return exc.reason if isinstance(exc.reason, str) else str(exc.code)
