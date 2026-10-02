"""Nerva-owned, synchronous Nous Portal device authentication.

The service holds no credential cache. Every refresh re-reads encrypted profile state
under the store transaction, and every public result omits OAuth secrets.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlsplit

import httpx

from .nous_credentials import NousAuthStore, usable_inference_token

PORTAL_URL = "https://portal.nousresearch.com"
INFERENCE_URL = "https://inference-api.nousresearch.com/v1"
_NETWORK_INFERENCE_HOSTS = frozenset({"inference-api.nousresearch.com", "welcome-api.nousresearch.com"})
_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_MAX_RESPONSE_BYTES = 65_536
_MAX_DEVICE_LIFETIME = 1_800
_MAX_INTERVAL = 60
_MAX_TOKEN_LIFETIME = 31_536_000
_REQUEST_DEADLINE_SECONDS = 10.0
_TERMINAL_REFRESH_CODES = frozenset({
    "invalid_grant", "invalid_token", "refresh_token_reused", "token_reused",
    "access_denied", "denied", "revoked_token",
})


class NousAuthError(Exception):
    """Public, bounded error; never stores provider diagnostics or token material."""

    _REASONS = frozenset({
        "client_id_required", "invalid_configuration", "invalid_response",
        "temporarily_unavailable", "login_not_found", "authorization_denied",
        "reauth_required", "unusable_token",
    })

    def __init__(self, reason: str):
        self.reason = reason if reason in self._REASONS else "temporarily_unavailable"
        super().__init__(self.reason)


@dataclass(frozen=True)
class NousCredentials:
    profile: str
    api_key: str = field(repr=False)
    base_url: str
    portal_base_url: str
    expires_at: int | None


def _contains_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _url(value: Any, *, portal: bool = False, operator: bool = False) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip() or _contains_control(value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host or parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment or parsed.path.startswith("//"):
        return None
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (operator and parsed.scheme == "http" and loopback):
        return None
    if parsed.scheme == "https" and port not in {None, 443} and not operator:
        return None
    if parsed.scheme == "http" and not loopback:
        return None
    if portal:
        if parsed.path not in {"", "/"}:
            return None
        if not operator and host != "portal.nousresearch.com":
            return None
    elif not operator and (host not in _NETWORK_INFERENCE_HOSTS or port not in {None, 443}):
        return None
    return value.rstrip("/")


def _jwt_exp(token: str) -> int | None:
    try:
        payload = token.split(".")[1]
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
        if not isinstance(claims, dict):
            return None
        exp = claims.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(float(exp)):
            return None
        return int(exp)
    except (ValueError, IndexError, TypeError, UnicodeDecodeError, OverflowError):
        return None


def _stored_expiry(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return None
                number = parsed.timestamp()
        else:
            return None
        return int(number) if math.isfinite(number) else None
    except (ValueError, OverflowError, OSError):
        return None


def _token_expiry(token: str, payload: dict[str, Any], now: float) -> int | None:
    jwt_expiry = _jwt_exp(token)
    if jwt_expiry is not None:
        return jwt_expiry
    ttl = _positive_int(payload.get("expires_in"), maximum=_MAX_TOKEN_LIFETIME)
    return int(now) + ttl if ttl is not None else None


def _portal_link(value: Any, portal: str) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048 or _contains_control(value):
        return None
    try:
        parsed, base = urlsplit(value), urlsplit(portal)
        if (
            parsed.scheme != base.scheme or parsed.hostname != base.hostname
            or parsed.port != base.port or parsed.username is not None
            or parsed.password is not None or parsed.fragment
        ):
            return None
    except ValueError:
        return None
    return value


def _reveals_device_code(url: str, device_code: str) -> bool:
    # OAuth complete links may carry a public user_code. A private device_code,
    # including URL-encoded or doubly encoded copies, may never enter public output.
    decoded = url
    for _ in range(4):
        parsed = urlsplit(decoded)
        if any(key.lower() == "device_code" or value == device_code
               for key, value in parse_qsl(parsed.query, keep_blank_values=True)):
            return True
        if len(device_code) >= 6 and (device_code in parsed.path or device_code in parsed.query):
            return True
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return False


def _scope(value: Any) -> str | list[str] | None:
    if isinstance(value, str):
        return value if len(value) <= 4096 and not _contains_control(value) else None
    if (isinstance(value, list) and len(value) <= 64
            and all(isinstance(item, str) and len(item) <= 256 and not _contains_control(item)
                    for item in value)):
        return value
    return None


def _positive_int(value: Any, *, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if 1 <= parsed <= maximum else None


def _nonempty(value: Any, *, limit: int = 4096) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit and not _contains_control(value) else None


def _transport_factory() -> httpx.AsyncBaseTransport:
    """Native default; tests may replace this with a synthetic MockTransport."""
    from agents.core.tls_trust import tls_verify

    return httpx.AsyncHTTPTransport(verify=tls_verify(), trust_env=False, retries=0)


class _GuardedTransport(httpx.AsyncBaseTransport):
    """Last in-process check, after every httpx request event hook."""

    def __init__(self, inner: httpx.AsyncBaseTransport, guard):
        self.inner = inner
        self.guard = guard

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.guard(request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class NousAuthService:
    def __init__(
        self,
        store: NousAuthStore | None = None,
        *,
        env: Mapping[str, str] | None = None,
        client_factory=None,
        clock=None,
    ):
        self.store = store if store is not None else NousAuthStore()
        self.env = os.environ if env is None else env
        self._default_client_factory = client_factory is None
        if client_factory is None:
            from .egress import llm_async_client
            client_factory = llm_async_client
        self._client_factory = client_factory
        self._clock = clock if clock is not None else time.time

    def _now(self) -> float:
        return float(self._clock())

    def _client_id(self) -> str:
        value = _nonempty(self.env.get("JARVIS_NOUS_CLIENT_ID"), limit=256)
        if value is None or value != value.strip():
            raise NousAuthError("client_id_required")
        return value

    def _portal(self) -> str:
        raw = self.env.get("JARVIS_NOUS_PORTAL_URL")
        if not raw:
            return PORTAL_URL
        portal = _url(raw, portal=True, operator=True)
        if portal is None:
            raise NousAuthError("invalid_configuration")
        return portal

    def _inference_override(self) -> str | None:
        raw = self.env.get("JARVIS_NOUS_INFERENCE_BASE_URL")
        if not raw:
            return None
        base = _url(raw, operator=True)
        if base is None:
            raise NousAuthError("invalid_configuration")
        return base

    def _network_inference(self, value: Any) -> str:
        # Provider data has no authority to choose an arbitrary bearer destination.
        canonical = _url(value)
        if canonical is not None:
            return canonical
        override = self._inference_override()
        return override if value == override and override is not None else INFERENCE_URL

    def _inference(self, value: Any) -> str:
        override = self._inference_override()
        if override is not None:
            return override
        return self._network_inference(value)

    def _post(self, portal: str, endpoint: str, form: dict[str, str], *, refresh_token: str | None = None) -> tuple[int, dict[str, Any], httpx.Headers]:
        url = f"{portal}{endpoint}"
        headers = {"Accept": "application/json"}
        if refresh_token is not None:
            headers["x-nous-refresh-token"] = refresh_token
        config = (self._portal(), self._client_id(), self._inference_override())
        if config[0] != portal or config[1] != form.get("client_id"):
            raise NousAuthError("invalid_configuration")

        def physical_guard(request: httpx.Request) -> None:
            # A native transport wrapper runs after *all* request event hooks, including
            # hooks added by a client factory. No changed request reaches the socket.
            if (
                (self._portal(), self._client_id(), self._inference_override()) != config
                or request.method != "POST" or str(request.url) != url
            ):
                raise NousAuthError("invalid_configuration")
            if any(name in request.headers for name in ("authorization", "cookie", "proxy-authorization")):
                raise NousAuthError("invalid_configuration")
            if parse_qs(request.content.decode("utf-8"), keep_blank_values=True) != {key: [value] for key, value in form.items()}:
                raise NousAuthError("invalid_configuration")
            present = request.headers.get("x-nous-refresh-token")
            if present != refresh_token:
                raise NousAuthError("invalid_configuration")

        async def exchange():
            kwargs = {
                "timeout": httpx.Timeout(_REQUEST_DEADLINE_SECONDS),
                "trust_env": False, "follow_redirects": False, "headers": headers,
            }
            if self._default_client_factory:
                kwargs["transport"] = _GuardedTransport(_transport_factory(), physical_guard)
            client = self._client_factory("nous-auth", **kwargs)
            if not isinstance(client, httpx.AsyncClient):
                raise NousAuthError("invalid_configuration")
            if not self._default_client_factory:
                # Test and owner-injected clients retain their own synthetic/native
                # transport, but cannot bypass the final physical check.
                if any(value is not None for value in client._mounts.values()):
                    raise NousAuthError("invalid_configuration")
                client._transport = _GuardedTransport(client._transport, physical_guard)
            async with (
                asyncio.timeout(_REQUEST_DEADLINE_SECONDS),
                client,
                client.stream("POST", url, data=form, follow_redirects=False) as response,
            ):
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise NousAuthError("invalid_response")
                status = response.status_code
                result_headers = httpx.Headers(response.headers)
            if (self._portal(), self._client_id(), self._inference_override()) != config:
                raise NousAuthError("invalid_configuration")
            return status, body, result_headers

        try:
            status, body, result_headers = asyncio.run(exchange())
            if 300 <= status < 400:
                raise NousAuthError("temporarily_unavailable")
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError, RecursionError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            return status, payload, result_headers
        except NousAuthError:
            raise
        except (httpx.HTTPError, OSError, ValueError, UnicodeError, TimeoutError):
            raise NousAuthError("temporarily_unavailable") from None

    def start_login(self, profile: str = "default") -> dict[str, Any]:
        with self.store.transaction(profile) as state:
            # The profile lock covers issuance and persistence. A concurrent logout
            # therefore cannot be undone by a delayed device-code response.
            client_id = self._client_id()
            portal = self._portal()
            status, payload, _ = self._post(
                portal, "/api/oauth/device/code",
                {"client_id": client_id, "scope": "inference:invoke"},
            )
            if status != 200:
                raise NousAuthError("temporarily_unavailable")
            device_code = _nonempty(payload.get("device_code"))
            user_code = _nonempty(payload.get("user_code"), limit=128)
            verify = _portal_link(payload.get("verification_uri"), portal)
            complete = _portal_link(payload.get("verification_uri_complete"), portal)
            expires_in = _positive_int(payload.get("expires_in"), maximum=_MAX_DEVICE_LIFETIME)
            interval = _positive_int(payload.get("interval"), maximum=_MAX_INTERVAL)
            if not (device_code and user_code and verify and complete and expires_in and interval):
                raise NousAuthError("invalid_response")
            if (device_code == user_code or _reveals_device_code(verify, device_code)
                    or _reveals_device_code(complete, device_code)):
                raise NousAuthError("invalid_response")
            login_id = secrets.token_urlsafe(32)
            now = self._now()
            state["pending"] = {
                "login_id": login_id, "device_code": device_code,
                "portal_base_url": portal, "client_id": client_id,
                "expires_at": now + expires_in,
                "interval": interval, "next_poll_at": now + interval,
            }
        return {
            "login_id": login_id, "user_code": user_code,
            "verification_uri": verify, "verification_uri_complete": complete,
            "expires_in": expires_in, "interval": interval,
        }

    def poll_login(self, profile: str, login_id: str) -> dict[str, Any]:
        outcome: dict[str, Any] | None = None
        error: NousAuthError | None = None
        with self.store.transaction(profile) as state:
            pending = state.get("pending")
            if not isinstance(pending, dict) or not secrets.compare_digest(str(pending.get("login_id", "")), str(login_id)):
                raise NousAuthError("login_not_found")
            if pending.get("portal_base_url") != self._portal() or pending.get("client_id") != self._client_id():
                raise NousAuthError("invalid_configuration")
            now = self._now()
            if now >= pending["expires_at"]:
                state.pop("pending", None)
                outcome = {"state": "expired"}
            elif now < pending["next_poll_at"]:
                outcome = {"state": "pending", "retry_after": max(1, math.ceil(pending["next_poll_at"] - now))}
            else:
                client_id = self._client_id()
                portal = self._portal()
                try:
                    status, payload, headers = self._post(portal, "/api/oauth/token", {
                        "grant_type": _DEVICE_GRANT, "client_id": client_id,
                        "device_code": pending["device_code"],
                    })
                except NousAuthError as exc:
                    if exc.reason == "temporarily_unavailable":
                        pending["next_poll_at"] = now + pending["interval"]
                        outcome = {"state": "pending", "retry_after": pending["interval"]}
                    else:
                        error = exc
                else:
                    if status == 200:
                        token = _nonempty(payload.get("access_token"))
                        candidate = {
                            "access_token": token, "scope": _scope(payload.get("scope")),
                            "expires_at": _token_expiry(token, payload, now) if token else None,
                        }
                        if not token or usable_inference_token(candidate, now=now) != token:
                            error = NousAuthError("unusable_token")
                        else:
                            self._replace_tokens(state, payload, portal, client_id, now)
                            state.pop("pending", None)
                            outcome = {"state": "complete"}
                    else:
                        code = _nonempty(payload.get("error"))
                        if code == "expired_token":
                            state.pop("pending", None)
                            outcome = {"state": "expired"}
                        elif code in {"access_denied", "denied"}:
                            state.pop("pending", None)
                            error = NousAuthError("authorization_denied")
                        elif code == "slow_down":
                            pending["interval"] = min(_MAX_INTERVAL, pending["interval"] + 5)
                            pending["next_poll_at"] = now + pending["interval"]
                            outcome = {"state": "pending", "retry_after": pending["interval"]}
                        elif code == "authorization_pending" or status in {408, 429} or status >= 500 or (status == 403 and "x-vercel-mitigated" in headers):
                            pending["next_poll_at"] = now + pending["interval"]
                            outcome = {"state": "pending", "retry_after": pending["interval"]}
                        else:
                            error = NousAuthError("temporarily_unavailable")
        if error is not None:
            raise error
        assert outcome is not None
        return outcome

    def _replace_tokens(
        self, state: dict[str, Any], payload: dict[str, Any], portal: str,
        client_id: str, now: float, *, preserve_scope: bool = False,
    ) -> None:
        # Only this service's configured Portal may receive a refresh token later.
        state.update({
            "access_token": payload["access_token"],
            "refresh_token": _nonempty(payload.get("refresh_token")),
            "scope": _scope(payload.get("scope")) or (state.get("scope") if preserve_scope else None),
            "portal_base_url": portal, "client_id": client_id,
            "inference_base_url": self._network_inference(payload.get("inference_base_url")),
            "obtained_at": now,
            "expires_at": _token_expiry(payload["access_token"], payload, now),
        })
        state.pop("agent_key", None)
        state.pop("quarantine_reason", None)

    def status(self, profile: str = "default") -> dict[str, Any]:
        state = self.store.read(profile)
        issuer_matches = (
            state.get("portal_base_url") == self._portal()
            and state.get("client_id") == self.env.get("JARVIS_NOUS_CLIENT_ID")
            and bool(state.get("client_id"))
        )
        token = usable_inference_token(state, now=self._now()) if issuer_matches else None
        return {
            "profile": profile,
            "authenticated": bool(state.get("access_token") or state.get("agent_key") or state.get("refresh_token")),
            "usable": token is not None,
            "has_refresh_token": bool(state.get("refresh_token")),
        }

    def peek_credentials(self, profile: str = "default") -> NousCredentials:
        """Read a usable owned credential without refresh, network, or mutation."""
        return self._credentials_from_state(profile, self.store.read(profile))

    def _credentials_from_state(self, profile: str, state: dict[str, Any]) -> NousCredentials:
        if state.get("quarantine_reason") or not (
            state.get("access_token") or state.get("agent_key") or state.get("refresh_token")
        ):
            raise NousAuthError("reauth_required")
        if state.get("portal_base_url") != self._portal() or state.get("client_id") != self._client_id():
            raise NousAuthError("invalid_configuration")
        token = usable_inference_token(state, now=self._now())
        if token is None:
            raise NousAuthError("unusable_token")
        return self._credentials(profile, token, state)

    def logout(self, profile: str = "default") -> dict[str, Any]:
        with self.store.transaction(profile) as state:
            state.clear()
        return {"profile": profile, "authenticated": False, "usable": False, "has_refresh_token": False}

    def prepare_credentials(
        self,
        profile: str = "default",
        *,
        force_refresh: bool = False,
        stale_access_token: str | None = None,
    ) -> NousCredentials:
        error: NousAuthError | None = None
        credentials: NousCredentials | None = None
        with self.store.transaction(profile) as state:
            now = self._now()
            has_credentials = bool(state.get("access_token") or state.get("agent_key") or state.get("refresh_token"))
            if has_credentials and (
                state.get("portal_base_url") != self._portal()
                or state.get("client_id") != self._client_id()
            ):
                error = NousAuthError("invalid_configuration")
            token = usable_inference_token(state, now=now)
            peer_rotated = (
                force_refresh and stale_access_token is not None and token is not None
                and token != stale_access_token
            )
            if error is not None:
                pass
            elif state.get("quarantine_reason"):
                error = NousAuthError("reauth_required")
            elif not force_refresh and token is not None or peer_rotated:
                credentials = self._credentials(profile, token, state)
            elif not _nonempty(state.get("refresh_token")):
                error = NousAuthError("reauth_required")
            else:
                portal = self._portal()  # Persisted network data cannot choose a token destination.
                client_id = self._client_id()
                refresh = state["refresh_token"]
                try:
                    status, payload, headers = self._post(
                        portal, "/api/oauth/token",
                        {"grant_type": "refresh_token", "client_id": client_id},
                        refresh_token=refresh,
                    )
                except NousAuthError as exc:
                    error = exc
                else:
                    code = _nonempty(payload.get("error"))
                    transient = (
                        status in {408, 429} or status >= 500
                        or (status == 403 and "x-vercel-mitigated" in headers)
                    )
                    terminal = not transient and (code in _TERMINAL_REFRESH_CODES or (
                        status in {401, 403} and "x-vercel-mitigated" not in headers
                    ))
                    if status == 200:
                        new_access = _nonempty(payload.get("access_token"))
                        if new_access is None:
                            error = NousAuthError("invalid_response")
                        else:
                            # Persist the rotated pair before reporting an unusable JWT.
                            self._replace_tokens(state, payload, portal, client_id, now, preserve_scope=True)
                            # Pinned Portal behavior permits a successful refresh response
                            # without a replacement grant; retain the previous grant then.
                            state["refresh_token"] = _nonempty(payload.get("refresh_token")) or refresh
                            token = usable_inference_token(state, now=now)
                            if token is None:
                                error = NousAuthError("unusable_token")
                            else:
                                credentials = self._credentials(profile, token, state)
                    elif terminal:
                        for key in ("access_token", "agent_key", "refresh_token", "scope", "expires_at"):
                            state.pop(key, None)
                        state["quarantine_reason"] = "reauth_required"
                        error = NousAuthError("reauth_required")
                    else:
                        error = NousAuthError("temporarily_unavailable")
        # Raising outside the transaction is essential: terminal quarantine must commit.
        if error is not None:
            raise error
        assert credentials is not None
        return credentials

    def _credentials(self, profile: str, token: str, state: dict[str, Any]) -> NousCredentials:
        return NousCredentials(
            profile=profile, api_key=token,
            base_url=self._inference(state.get("inference_base_url")),
            portal_base_url=self._portal(),
            expires_at=_jwt_exp(token) or _stored_expiry(state.get("expires_at")),
        )
