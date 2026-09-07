"""http_transport.py — MCP *Streamable HTTP* client transport (DRA-25 remainder).

The outbound MCP client (``client.py``) spoke only stdio. This module adds the
spec'd remote transport — **Streamable HTTP** (MCP 2025-03-26+, the successor of
the deprecated HTTP+SSE pair) — as a small, injectable object that
``MCPServer`` drives exactly like its stdio pipe:

* every JSON-RPC message is a ``POST`` to the single MCP endpoint URL with
  ``Accept: application/json, text/event-stream``;
* the reply is either one JSON body or a ``text/event-stream`` whose events carry
  JSON-RPC messages — the message whose ``id`` matches ours ends the read;
* ``Mcp-Session-Id`` handed out on ``initialize`` is echoed on every later call
  and released with ``DELETE`` on close; a ``404`` on a session call drops it;
* the negotiated ``MCP-Protocol-Version`` is echoed after the handshake.

Governance (MOONSHOT §5 — every cloud hop opt-in and auditable):

* the transport is **default-off**: ``MCPServer.connect`` refuses a
  ``streamable-http`` server with ``transport_disabled:JARVIS_MCP_HTTP_CLIENT``
  until the owner sets that flag; the tool-call contract in ``client.py`` denies
  the transport for the same reason, so a persisted config can never call out
  through a flag that is later unset;
* every byte leaves through ``agents.core.http_client.PluginHTTPClient`` — the
  same SSRF guard (resolve-then-pin, metadata hosts blocked, no cross-origin
  credential replay) and egress ledger every plugin uses. A loopback / RFC1918
  *literal* (or the reserved name ``localhost``) validates in ``lan`` mode so a
  self-hosted MCP server is reachable; any DNS name stays in ``public`` mode on
  purpose (a name that resolves somewhere private is the rebinding hole the
  guard exists to close);
* no new dependency: httpx is already a hard requirement of ``http_client``.

Nothing here authorizes anything — the ``mcp.tool_call`` contract and the
Action Kernel gates stay in ``client.py`` / the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from agents.core.env_config import env_flag
from agents.core.http_client import (
    PluginEgressError,
    PluginHTTPClient,
    PluginTimeouts,
    _address_mode,
    _host_of,
)

logger = logging.getLogger("jarvis.mcp.http")

TRANSPORT_STDIO = "stdio"
TRANSPORT_STREAMABLE_HTTP = "streamable-http"
SUPPORTED_TRANSPORTS = (TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP)

#: Owner flag that arms the outbound Streamable HTTP client. Default OFF.
HTTP_CLIENT_FLAG = "JARVIS_MCP_HTTP_CLIENT"

#: Protocol version this client offers on ``initialize`` (the server may pick an
#: older one; we echo whatever it negotiated).
CLIENT_PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "nerva-hub", "version": "1.0"}

_TRANSPORT_ALIASES = {
    "stdio": TRANSPORT_STDIO,
    "streamable-http": TRANSPORT_STREAMABLE_HTTP,
    "streamable_http": TRANSPORT_STREAMABLE_HTTP,
    "streamablehttp": TRANSPORT_STREAMABLE_HTTP,
    "http": TRANSPORT_STREAMABLE_HTTP,
}

# Bounds on what one reply may cost us: an SSE stream is read event-by-event
# until the matching response arrives, but never past these caps.
MAX_SSE_EVENTS = 256
MAX_REPLY_BYTES = 4 * 1024 * 1024
_ACCEPTED_STATUSES = frozenset({200, 202, 204})
_SESSION_HEADER = "Mcp-Session-Id"
_VERSION_HEADER = "MCP-Protocol-Version"
# Headers the transport owns; a caller-supplied header of the same name is
# dropped so a config cannot desync the session/version handshake.
_RESERVED_HEADERS = frozenset({
    "accept", "content-type", "host", _SESSION_HEADER.lower(), _VERSION_HEADER.lower(),
})


def http_client_enabled() -> bool:
    """True only when the owner armed ``JARVIS_MCP_HTTP_CLIENT``."""
    return env_flag(HTTP_CLIENT_FLAG)


def normalize_transport(value: Any) -> str:
    """Canonical transport name for a config spelling (``"HTTP"`` → ``streamable-http``).

    Unknown spellings come back lower-cased and stripped so the caller can
    refuse them with the exact value it saw — they are never silently mapped
    onto a transport the client actually speaks.
    """
    key = str(value or TRANSPORT_STDIO).strip().lower()
    return _TRANSPORT_ALIASES.get(key, key)


def transport_allowed(transport: Any) -> bool:
    """Is *transport* both implemented and (for HTTP) armed by the owner flag?"""
    name = normalize_transport(transport)
    if name == TRANSPORT_STDIO:
        return True
    if name == TRANSPORT_STREAMABLE_HTTP:
        return http_client_enabled()
    return False


def validate_mcp_url(url: Any) -> str | None:
    """Return a refusal reason for *url*, or ``None`` when it is a usable endpoint."""
    raw = str(url or "").strip()
    if not raw:
        return "bad_url:empty"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return "bad_url:scheme"
    if not parsed.hostname:
        return "bad_url:host"
    if parsed.username or parsed.password:
        return "bad_url:credentials_in_url"
    if any(ch in raw for ch in "\r\n\x00 "):
        return "bad_url:control_chars"
    return None


class MCPTransportError(RuntimeError):
    """A transport-level refusal with a stable, machine-readable ``reason``."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class _MCPHTTPClient(PluginHTTPClient):
    """PluginHTTPClient with the RESTRICTED-plugin address rule.

    There is no plugin manifest for an MCP endpoint, and the base class treats a
    manifest-less client as ``public`` — which rejects ``127.0.0.1``, i.e. every
    self-hosted MCP server. Reuse ``_address_mode``: a loopback / RFC1918
    literal (or ``localhost``) validates in ``lan`` mode, every DNS name stays
    ``public``. The resolve-then-pin guard itself is untouched.
    """

    def _manifest_mode(self, url: str) -> str:  # noqa: D401 - base-class hook
        return _address_mode(_host_of(url))


def _clean_headers(headers: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        name = str(key).strip()
        if not name or name.lower() in _RESERVED_HEADERS:
            continue
        text = str(value)
        if any(ch in name for ch in "\r\n\x00") or any(ch in text for ch in "\r\n\x00"):
            raise MCPTransportError("bad_header", name)
        out[name] = text
    return out


def parse_sse_events(text: str, *, max_events: int = MAX_SSE_EVENTS) -> list[Any]:
    """Decode the JSON ``data:`` payloads of a ``text/event-stream`` body.

    Multi-line ``data:`` fields are joined with ``\\n`` per the SSE spec; blank
    lines end an event; comment lines (``:``) and other fields are ignored.
    Non-JSON payloads are skipped rather than fatal.
    """
    events: list[Any] = []
    data_lines: list[str] = []

    def _flush() -> None:
        if not data_lines:
            return
        payload = "\n".join(data_lines)
        data_lines.clear()
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            logger.debug("MCP SSE event skipped: not JSON")

    for raw in text.splitlines():
        if len(events) >= max_events:
            break
        line = raw.rstrip("\r")
        if not line:
            _flush()
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
    _flush()
    return events


def _match_response(messages: Any, req_id: int) -> dict | None:
    """First JSON-RPC message (of a dict, list, or nested list) whose id is *req_id*."""
    if isinstance(messages, dict):
        return messages if messages.get("id") == req_id else None
    if isinstance(messages, list):
        for item in messages:
            found = _match_response(item, req_id)
            if found is not None:
                return found
    return None


class StreamableHttpTransport:
    """One MCP endpoint over Streamable HTTP. Drive it with ``request``/``notify``.

    ``http_client`` / ``transport_factory`` / ``resolver`` are test seams: the
    default client is a guarded ``PluginHTTPClient`` (breaker ``mcp:<name>``);
    tests inject an ``httpx.MockTransport`` factory so no socket is opened.
    """

    def __init__(
        self,
        url: str,
        headers: dict | None = None,
        *,
        name: str = "mcp",
        timeout: float = 10.0,
        http_client: PluginHTTPClient | None = None,
        transport_factory: Callable | None = None,
        resolver: Callable | None = None,
    ) -> None:
        reason = validate_mcp_url(url)
        if reason:
            raise MCPTransportError(reason, "streamable-http endpoint")
        self.url = str(url).strip()
        self.name = name
        self.timeout = float(timeout)
        self.headers = _clean_headers(headers)
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.server_info: dict = {}
        self.initialized = False
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._client = http_client or _MCPHTTPClient(
            f"mcp:{name}",
            timeouts=PluginTimeouts(connect=5.0, read=self.timeout, total=self.timeout + 5.0),
            resolver=resolver,
            transport_factory=transport_factory,
        )

    # ── headers ──────────────────────────────────────────────────────────────

    def _request_headers(self) -> dict[str, str]:
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers[_SESSION_HEADER] = self.session_id
        if self.protocol_version:
            headers[_VERSION_HEADER] = self.protocol_version
        return headers

    # ── JSON-RPC ─────────────────────────────────────────────────────────────

    async def initialize(self) -> dict:
        """``initialize`` + ``notifications/initialized``; returns the server result ({} on failure)."""
        resp = await self.request("initialize", {
            "protocolVersion": CLIENT_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        })
        result = resp.get("result") if isinstance(resp, dict) else None
        if not isinstance(result, dict):
            return {}
        version = result.get("protocolVersion")
        if isinstance(version, str) and version.strip():
            self.protocol_version = version.strip()
        info = result.get("serverInfo")
        self.server_info = dict(info) if isinstance(info, dict) else {}
        self.initialized = True
        await self.notify("notifications/initialized")
        return result

    async def request(self, method: str, params: dict | None = None) -> dict:
        """Send one request; return the matching JSON-RPC response (``{}`` on any failure)."""
        async with self._lock:
            self._next_id += 1
            req_id = self._next_id
            body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
            try:
                return await asyncio.wait_for(self._post(body, req_id), timeout=self.timeout)
            except MCPTransportError:
                raise
            except PluginEgressError as exc:
                raise MCPTransportError("egress_blocked", str(exc)) from exc
            except TimeoutError:
                logger.warning("MCP HTTP request timed out (server=%s method=%s)", self.name, method)
                return {}
            except Exception as exc:  # network / decode — degrade like the stdio path
                logger.warning(
                    "MCP HTTP request failed (server=%s method=%s type=%s)",
                    self.name, method, type(exc).__name__,
                )
                return {}

    async def notify(self, method: str, params: dict | None = None) -> None:
        """Send a notification (no id); the server answers 202 with no body."""
        body = {"jsonrpc": "2.0", "method": method}
        if params:
            body["params"] = params
        async with self._lock:
            try:
                await asyncio.wait_for(self._post(body, None), timeout=self.timeout)
            except MCPTransportError:
                raise
            except PluginEgressError as exc:
                raise MCPTransportError("egress_blocked", str(exc)) from exc
            except Exception as exc:
                logger.debug("MCP HTTP notification dropped (type=%s)", type(exc).__name__)

    async def _post(self, body: dict, req_id: int | None) -> dict:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        async with self._client.stream(
            "POST", self.url, headers=self._request_headers(), content=payload,
        ) as response:
            status = int(response.status_code)
            session = response.headers.get(_SESSION_HEADER.lower())
            if session and body.get("method") == "initialize":
                self.session_id = session.strip()
            if status == 404 and self.session_id:
                # Spec: the server forgot our session — start over next time.
                logger.warning("MCP HTTP session expired (server=%s)", self.name)
                self.session_id = None
                self.initialized = False
                return {}
            if status not in _ACCEPTED_STATUSES:
                logger.warning("MCP HTTP %s returned status %s", self.name, status)
                return {}
            if req_id is None or status in (202, 204):
                return {}
            ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ctype == "text/event-stream":
                return await self._read_sse(response, req_id)
            raw = await self._read_capped(response)
            try:
                messages = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.warning("MCP HTTP %s returned a non-JSON body", self.name)
                return {}
            return _match_response(messages, req_id) or {}

    @staticmethod
    async def _read_capped(response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_REPLY_BYTES:
                raise MCPTransportError("reply_too_large", f">{MAX_REPLY_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _read_sse(response, req_id: int) -> dict:
        """Consume an SSE stream until the response with our id arrives (or caps hit)."""
        data_lines: list[str] = []
        events = 0
        size = 0
        async for raw_line in response.aiter_lines():
            size += len(raw_line)
            if size > MAX_REPLY_BYTES:
                raise MCPTransportError("reply_too_large", f">{MAX_REPLY_BYTES} bytes")
            line = raw_line.rstrip("\r\n")
            if line:
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "data":
                    data_lines.append(value)
                continue
            if not data_lines:
                continue
            events += 1
            payload = "\n".join(data_lines)
            data_lines.clear()
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                continue
            found = _match_response(message, req_id)
            if found is not None:
                return found
            if events >= MAX_SSE_EVENTS:
                break
        # Stream ended without a terminating blank line — flush the tail.
        if data_lines:
            try:
                found = _match_response(json.loads("\n".join(data_lines)), req_id)
            except json.JSONDecodeError:
                found = None
            if found is not None:
                return found
        return {}

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release the server session (``DELETE``), then the pooled connections."""
        if self.session_id:
            try:
                headers = {**self.headers, _SESSION_HEADER: self.session_id}
                if self.protocol_version:
                    headers[_VERSION_HEADER] = self.protocol_version
                resp = await self._client.delete(self.url, headers=headers)
                await resp.aclose()
            except Exception as exc:  # best effort — a 405 is spec-legal
                logger.debug("MCP HTTP session release skipped (type=%s)", type(exc).__name__)
        self.session_id = None
        self.initialized = False
        try:
            await self._client.close()
        except Exception as exc:  # pragma: no cover - teardown must not raise
            logger.debug("MCP HTTP client close failed (type=%s)", type(exc).__name__)

    def status(self) -> dict:
        return {
            "transport": TRANSPORT_STREAMABLE_HTTP,
            "url": self.url,
            "initialized": self.initialized,
            "session": bool(self.session_id),
            "protocol_version": self.protocol_version,
            "server_info": dict(self.server_info),
            "header_names": sorted(self.headers),
        }
