"""A stdlib-only client for the running hub, used by every online `nerva` verb.

Nothing here is a second API: the client speaks to the same routes the HUD speaks to,
with the same credentials (`JARVIS_ADMIN_TOKEN` / `JARVIS_USER_TOKEN`), so a verb can do
exactly what the HUD can do and nothing more. Stdlib only so it runs in a broken install.
"""

from __future__ import annotations

import json
import os
import urllib.error
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


def hub_url(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    explicit = (env.get("NERVA_HUB_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = (env.get("JARVIS_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (env.get("JARVIS_PORT") or "8080").strip() or "8080"
    return f"http://{host}:{port}"


class HubClient:
    def __init__(
        self,
        base_url: str = DEFAULT_HUB_URL,
        *,
        admin_token: str = "",
        user_token: str = "",
        opener: Callable[..., Any] = urllib.request.urlopen,
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
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
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
