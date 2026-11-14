"""
browser_broker.py — H086 Identity-Scoped Browser-Control Broker & One-Shot HTTPS Artifact Store.

Connects a remotely driven browser (running on another machine, container, or isolated
desktop session) to callers through an identity-scoped, transport-agnostic broker, and
provides authenticated one-shot HTTPS upload/download of bounded browser-control artifacts
(screenshots, DOM snapshots, console logs, PDF exports).

Security invariants (Nerva > Hermes/OpenClaw):
  1. **Strict identity scoping (`principal_id`)**: every remote browser controller session,
     dispatched command, and artifact ticket is bound to one `principal_id`. Cross-identity
     reads, step dispatches, or ticket mints fail closed (`403 identity_mismatch`).
  2. **Transport-agnostic adapter protocol (`BrokerTransport`)**: callers dispatch steps
     uniformly whether the remote browser uses a push callback/WebSocket adapter
     (`CallbackBrokerTransport`) or an async poll/result queue (`QueueBrokerTransport`).
  3. **Governed step normalization & SSRF guard**: every step passes through
     `browser_kernel.normalize_step`, action allowlisting (`APPROVED_MUTATIONS | APPROVED_READS`),
     and `security.ssrf` URL validation before reaching any transport.
  4. **Authenticated one-shot HTTPS artifact transfer**: upload and download tickets are
     32-byte random secrets stored only as SHA-256 digests (`hmac.compare_digest`), capped at
     `5 MiB` (`MAX_ARTIFACT_BYTES`) and `64` retained items, require HTTPS (allowing loopback
     HTTP only for local development/tests when enabled), and burn atomically on first use
     (`410 ticket_already_used` on replay).
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from agents.core.browser_kernel import APPROVED_MUTATIONS, APPROVED_READS, normalize_step
from agents.core.env_config import env_flag
from agents.core.security.ssrf import BLOCKED_HOSTS, is_private_ip

ALLOWED_ACTIONS = APPROVED_MUTATIONS | APPROVED_READS
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024  # 5 MiB hard ceiling
MAX_ARTIFACTS = 64
MAX_SESSIONS = 64
MAX_COMMANDS_PER_SESSION = 128
DEFAULT_LEASE_TTL_S = 120.0
DEFAULT_TICKET_TTL_S = 300.0
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

ALLOWED_ARTIFACT_MIMES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/json",
        "text/plain",
        "text/html",
        "application/pdf",
    }
)


class BrowserBrokerError(Exception):
    """Structured error raised by the browser-control broker and artifact store."""

    def __init__(self, reason: str, status: int = 400, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.status = status
        self.detail = detail or reason


def _sha256_hex(raw: str | bytes) -> str:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(data).hexdigest()


def _normalize_principal(principal_id: str) -> str:
    cleaned = (principal_id or "").strip()
    if not cleaned or len(cleaned) > 120:
        raise BrowserBrokerError("invalid_principal", status=400, detail="valid principal_id required")
    return cleaned


def _check_https_transport(scheme: str, client_host: str, *, allow_loopback_http: bool | None = None) -> None:
    norm_scheme = (scheme or "").strip().lower()
    if norm_scheme == "https":
        return
    loopback_ok = (
        env_flag("JARVIS_BROWSER_BROKER_ALLOW_LOOPBACK_HTTP", default=True)
        if allow_loopback_http is None
        else bool(allow_loopback_http)
    )
    host = (client_host or "").strip().lower()
    if norm_scheme == "http" and loopback_ok and host in LOOPBACK_HOSTS:
        return
    raise BrowserBrokerError(
        "https_required",
        status=403,
        detail="one-shot browser artifact transfer requires HTTPS transport",
    )


def _validate_step_ssrf(normalized: Mapping[str, Any], *, allow_private_urls: bool) -> None:
    args = normalized.get("args") or {}
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise BrowserBrokerError(
            "disallowed_url_scheme",
            status=403,
            detail=f"browser step URL scheme {scheme!r} is forbidden",
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise BrowserBrokerError("invalid_url", status=422, detail="URL missing hostname")
    if host in BLOCKED_HOSTS:
        raise BrowserBrokerError("ssrf_blocked", status=403, detail=f"host {host} is blocked")
    if not allow_private_urls:
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise BrowserBrokerError("ssrf_blocked", status=403, detail="loopback/local host blocked")
        if is_private_ip(host):
            raise BrowserBrokerError("ssrf_blocked", status=403, detail="private/non-global IP blocked")


class BrokerTransport(Protocol):
    """Transport-agnostic interface between the broker and a remotely driven browser."""

    name: str

    async def send_command(self, session_id: str, command: dict[str, Any]) -> dict[str, Any] | None:
        """Deliver a normalized command. Return an immediate result dict if synchronous/RPC,
        or None if queued for asynchronous remote pickup."""


class QueueBrokerTransport:
    """Default transport-agnostic queue adapter (supports HTTP poll, SSE, or custom bridge)."""

    name = "queue"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, list[dict[str, Any]]] = {}

    async def send_command(self, session_id: str, command: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._pending.setdefault(session_id, [])
            bucket.append(dict(command))
        return None

    def drain(self, session_id: str, limit: int = 16) -> list[dict[str, Any]]:
        with self._lock:
            bucket = self._pending.get(session_id, [])
            take = bucket[: max(1, min(limit, 64))]
            self._pending[session_id] = bucket[len(take) :]
            return take

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._pending.pop(session_id, None)


class CallbackBrokerTransport:
    """Direct callback/RPC/WebSocket adapter for push-connected remote browsers."""

    def __init__(
        self,
        handler: Callable[[str, dict[str, Any]], Any],
        *,
        name: str = "callback",
    ) -> None:
        self.name = name
        self._handler = handler

    async def send_command(self, session_id: str, command: dict[str, Any]) -> dict[str, Any] | None:
        res = self._handler(session_id, dict(command))
        if inspect.isawaitable(res):
            res = await res
        return dict(res) if isinstance(res, Mapping) else {"result": res}


@dataclass
class _ControllerSession:
    session_id: str
    principal_id: str
    label: str
    token_sha256: str
    capabilities: list[str]
    allow_private_urls: bool
    transport_name: str
    transport: BrokerTransport
    lease_ttl_s: float
    created_at: float
    last_heartbeat_at: float
    expires_at: float
    detached: bool = False


@dataclass
class _BrokerCommand:
    command_id: str
    session_id: str
    principal_id: str
    step: dict[str, Any]
    status: str  # "queued" | "completed" | "failed"
    created_at: float
    completed_at: float | None = None
    output: dict[str, Any] | None = None
    error: str = ""


@dataclass
class _ArtifactEntry:
    artifact_id: str
    session_id: str
    principal_id: str
    filename: str
    mime_type: str
    max_bytes: int
    upload_token_sha256: str
    upload_expires_at: float
    created_at: float
    upload_used: bool = False
    uploaded_at: float | None = None
    data: bytes | None = None
    sha256: str = ""
    size_bytes: int = 0
    download_tickets: dict[str, tuple[str, float, bool]] = field(default_factory=dict)
    # ticket_id -> (token_sha256, expires_at, used)


class BrowserControlBroker:
    """Identity-scoped remote-browser broker + one-shot HTTPS bounded artifact store."""

    def __init__(self, *, allow_loopback_http: bool | None = None) -> None:
        self._lock = threading.Lock()
        self._default_queue = QueueBrokerTransport()
        self._sessions: dict[str, _ControllerSession] = {}
        self._commands: dict[str, _BrokerCommand] = {}
        self._artifacts: dict[str, _ArtifactEntry] = {}
        self._allow_loopback_http = allow_loopback_http

    # ── housekeeping ─────────────────────────────────────────────────────────

    def _evict_locked(self, now: float) -> None:
        expired_artifacts = [
            aid
            for aid, art in self._artifacts.items()
            if (not art.upload_used and now > art.upload_expires_at)
            or (art.uploaded_at is not None and now - art.uploaded_at > DEFAULT_TICKET_TTL_S * 4)
        ]
        for aid in expired_artifacts:
            self._artifacts.pop(aid, None)
        while len(self._artifacts) >= MAX_ARTIFACTS:
            oldest_id = min(self._artifacts, key=lambda k: self._artifacts[k].created_at)
            self._artifacts.pop(oldest_id, None)

    def _require_session_for_principal_locked(
        self, session_id: str, principal_id: str, *, require_live: bool = True
    ) -> _ControllerSession:
        principal = _normalize_principal(principal_id)
        sess = self._sessions.get(session_id)
        if sess is None:
            raise BrowserBrokerError("session_not_found", status=404, detail="controller session not found")
        if sess.principal_id != principal:
            raise BrowserBrokerError(
                "identity_mismatch",
                status=403,
                detail="caller identity is not permitted to access this browser session",
            )
        if require_live:
            if sess.detached:
                raise BrowserBrokerError("controller_detached", status=410, detail="controller detached")
            if time.time() > sess.expires_at:
                raise BrowserBrokerError(
                    "controller_lease_expired",
                    status=410,
                    detail="remote browser controller lease expired",
                )
        return sess

    def _require_controller_auth_locked(self, session_id: str, controller_token: str) -> _ControllerSession:
        sess = self._sessions.get(session_id)
        if sess is None:
            raise BrowserBrokerError("session_not_found", status=404, detail="controller session not found")
        presented_hash = _sha256_hex(controller_token or "")
        if not controller_token or not hmac.compare_digest(sess.token_sha256, presented_hash):
            raise BrowserBrokerError("invalid_controller_token", status=401, detail="invalid controller token")
        if sess.detached:
            raise BrowserBrokerError("controller_detached", status=410, detail="controller detached")
        return sess

    @staticmethod
    def _public_session(sess: _ControllerSession, now: float | None = None) -> dict[str, Any]:
        ts = now if now is not None else time.time()
        return {
            "session_id": sess.session_id,
            "principal_id": sess.principal_id,
            "label": sess.label,
            "capabilities": list(sess.capabilities),
            "allow_private_urls": sess.allow_private_urls,
            "transport": sess.transport_name,
            "created_at": sess.created_at,
            "last_heartbeat_at": sess.last_heartbeat_at,
            "expires_at": sess.expires_at,
            "detached": sess.detached,
            "live": (not sess.detached) and (ts <= sess.expires_at),
        }

    # ── controller registration & lifecycle ──────────────────────────────────

    def register_controller(
        self,
        *,
        principal_id: str,
        label: str = "",
        capabilities: list[str] | None = None,
        allow_private_urls: bool = False,
        lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
        transport: BrokerTransport | None = None,
    ) -> dict[str, Any]:
        principal = _normalize_principal(principal_id)
        ttl = max(10.0, min(float(lease_ttl_s), 3600.0))
        caps = sorted(
            {str(c).strip().lower() for c in (capabilities or list(ALLOWED_ACTIONS)) if str(c).strip()}
            & ALLOWED_ACTIONS
        )
        if not caps:
            caps = sorted(ALLOWED_ACTIONS)
        chosen_transport = transport if transport is not None else self._default_queue
        raw_token = secrets.token_urlsafe(32)
        session_id = f"bctl_{uuid.uuid4().hex[:16]}"
        now = time.time()

        sess = _ControllerSession(
            session_id=session_id,
            principal_id=principal,
            label=(label or "remote-browser").strip()[:80],
            token_sha256=_sha256_hex(raw_token),
            capabilities=caps,
            allow_private_urls=bool(allow_private_urls),
            transport_name=getattr(chosen_transport, "name", "custom"),
            transport=chosen_transport,
            lease_ttl_s=ttl,
            created_at=now,
            last_heartbeat_at=now,
            expires_at=now + ttl,
        )
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                # Evict detached or oldest expired session first.
                stale = [
                    sid
                    for sid, s in self._sessions.items()
                    if s.detached or now > s.expires_at
                ]
                if stale:
                    self._sessions.pop(stale[0], None)
                else:
                    raise BrowserBrokerError("broker_capacity_reached", status=429, detail="too many sessions")
            self._sessions[session_id] = sess
            return {
                "ok": True,
                "session": self._public_session(sess, now),
                "controller_token": raw_token,
            }

    def status(self, *, principal_id: str) -> dict[str, Any]:
        principal = _normalize_principal(principal_id)
        now = time.time()
        with self._lock:
            self._evict_locked(now)
            sessions = [
                self._public_session(s, now)
                for s in self._sessions.values()
                if s.principal_id == principal
            ]
            artifacts = [
                {
                    "artifact_id": a.artifact_id,
                    "session_id": a.session_id,
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "uploaded": a.upload_used and a.data is not None,
                    "size_bytes": a.size_bytes,
                    "sha256": a.sha256,
                    "created_at": a.created_at,
                }
                for a in self._artifacts.values()
                if a.principal_id == principal
            ]
            commands = [
                {
                    "command_id": c.command_id,
                    "session_id": c.session_id,
                    "action": c.step.get("action", ""),
                    "status": c.status,
                    "created_at": c.created_at,
                    "completed_at": c.completed_at,
                }
                for c in list(self._commands.values())[-30:]
                if c.principal_id == principal
            ]
        return {
            "ok": True,
            "principal_id": principal,
            "sessions": sessions,
            "artifacts": artifacts,
            "recent_commands": commands,
            "limits": {
                "max_artifact_bytes": MAX_ARTIFACT_BYTES,
                "max_artifacts": MAX_ARTIFACTS,
                "default_ticket_ttl_s": DEFAULT_TICKET_TTL_S,
            },
        }

    def heartbeat(self, session_id: str, *, controller_token: str) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sess = self._require_controller_auth_locked(session_id, controller_token)
            sess.last_heartbeat_at = now
            sess.expires_at = now + sess.lease_ttl_s
            return {"ok": True, "session": self._public_session(sess, now)}

    def detach_by_controller(self, session_id: str, *, controller_token: str) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sess = self._require_controller_auth_locked(session_id, controller_token)
            sess.detached = True
            self._default_queue.clear(session_id)
            return {"ok": True, "session": self._public_session(sess, now)}

    def detach_session(self, session_id: str, *, principal_id: str) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sess = self._require_session_for_principal_locked(
                session_id, principal_id, require_live=False
            )
            sess.detached = True
            self._default_queue.clear(session_id)
            return {"ok": True, "session": self._public_session(sess, now)}

    # ── governed step dispatch & remote pickup ───────────────────────────────

    async def dispatch_step(
        self,
        session_id: str,
        *,
        principal_id: str,
        step: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = normalize_step(step)
        action = normalized.get("action", "")
        if action not in ALLOWED_ACTIONS:
            raise BrowserBrokerError(
                "unsupported_action",
                status=422,
                detail=f"browser step action {action!r} is not permitted",
            )
        with self._lock:
            sess = self._require_session_for_principal_locked(session_id, principal_id, require_live=True)
            if action not in sess.capabilities:
                raise BrowserBrokerError(
                    "capability_not_granted",
                    status=403,
                    detail=f"controller session does not advertise capability {action!r}",
                )
            _validate_step_ssrf(normalized, allow_private_urls=sess.allow_private_urls)
            cmd_id = f"bcmd_{uuid.uuid4().hex[:16]}"
            now = time.time()
            if len(self._commands) >= MAX_SESSIONS * MAX_COMMANDS_PER_SESSION:
                oldest_cmd = min(self._commands, key=lambda k: self._commands[k].created_at)
                self._commands.pop(oldest_cmd, None)
            cmd = _BrokerCommand(
                command_id=cmd_id,
                session_id=session_id,
                principal_id=sess.principal_id,
                step=normalized,
                status="queued",
                created_at=now,
            )
            self._commands[cmd_id] = cmd
            transport = sess.transport

        wire_payload = {
            "command_id": cmd_id,
            "session_id": session_id,
            "step": normalized,
            "created_at": now,
        }
        immediate = await transport.send_command(session_id, wire_payload)
        if immediate is not None:
            with self._lock:
                stored = self._commands.get(cmd_id)
                if stored is not None:
                    stored.status = "failed" if immediate.get("ok") is False else "completed"
                    stored.output = dict(immediate)
                    stored.completed_at = time.time()
                    if immediate.get("error"):
                        stored.error = str(immediate["error"])[:500]
        return self.get_command_status(cmd_id, principal_id=principal_id)

    def poll_commands(
        self, session_id: str, *, controller_token: str, limit: int = 16
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sess = self._require_controller_auth_locked(session_id, controller_token)
            sess.last_heartbeat_at = now
            sess.expires_at = now + sess.lease_ttl_s
        commands = self._default_queue.drain(session_id, limit=limit)
        return {"ok": True, "session_id": session_id, "commands": commands}

    def submit_result(
        self,
        session_id: str,
        command_id: str,
        *,
        controller_token: str,
        ok: bool = True,
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            sess = self._require_controller_auth_locked(session_id, controller_token)
            sess.last_heartbeat_at = now
            sess.expires_at = now + sess.lease_ttl_s
            cmd = self._commands.get(command_id)
            if cmd is None or cmd.session_id != session_id:
                raise BrowserBrokerError("command_not_found", status=404, detail="command not found")
            if cmd.status != "queued":
                raise BrowserBrokerError(
                    "command_already_settled", status=409, detail="command result already recorded"
                )
            cmd.status = "completed" if ok else "failed"
            cmd.completed_at = now
            cmd.output = dict(output or {})
            cmd.error = (error or "")[:500]
            return {
                "ok": True,
                "command_id": cmd.command_id,
                "status": cmd.status,
                "completed_at": cmd.completed_at,
            }

    def get_command_status(self, command_id: str, *, principal_id: str) -> dict[str, Any]:
        principal = _normalize_principal(principal_id)
        with self._lock:
            cmd = self._commands.get(command_id)
            if cmd is None:
                raise BrowserBrokerError("command_not_found", status=404, detail="command not found")
            if cmd.principal_id != principal:
                raise BrowserBrokerError(
                    "identity_mismatch",
                    status=403,
                    detail="caller identity cannot read this command",
                )
            return {
                "ok": True,
                "command_id": cmd.command_id,
                "session_id": cmd.session_id,
                "principal_id": cmd.principal_id,
                "step": dict(cmd.step),
                "status": cmd.status,
                "created_at": cmd.created_at,
                "completed_at": cmd.completed_at,
                "output": dict(cmd.output) if isinstance(cmd.output, dict) else None,
                "error": cmd.error,
            }

    # ── one-shot HTTPS bounded artifact store ────────────────────────────────

    def mint_upload_ticket(
        self,
        session_id: str,
        *,
        principal_id: str,
        filename: str = "artifact.png",
        mime_type: str = "image/png",
        max_bytes: int = MAX_ARTIFACT_BYTES,
        ttl_s: float = DEFAULT_TICKET_TTL_S,
    ) -> dict[str, Any]:
        mime = (mime_type or "").strip().lower()
        if mime not in ALLOWED_ARTIFACT_MIMES:
            raise BrowserBrokerError(
                "unsupported_mime_type",
                status=415,
                detail=f"artifact mime_type {mime!r} is not allowed",
            )
        bounded_max = int(max_bytes)
        if bounded_max < 1 or bounded_max > MAX_ARTIFACT_BYTES:
            raise BrowserBrokerError(
                "artifact_too_large",
                status=413,
                detail=f"max_bytes must be between 1 and {MAX_ARTIFACT_BYTES}",
            )
        clean_name = (filename or "artifact.bin").strip().replace("/", "_").replace("\\", "_")[:120]
        now = time.time()
        bounded_ttl = max(5.0, min(float(ttl_s), 900.0))

        with self._lock:
            self._evict_locked(now)
            sess = self._require_session_for_principal_locked(session_id, principal_id, require_live=True)
            artifact_id = f"bart_{uuid.uuid4().hex[:16]}"
            upload_token = secrets.token_urlsafe(32)
            entry = _ArtifactEntry(
                artifact_id=artifact_id,
                session_id=sess.session_id,
                principal_id=sess.principal_id,
                filename=clean_name,
                mime_type=mime,
                max_bytes=bounded_max,
                upload_token_sha256=_sha256_hex(upload_token),
                upload_expires_at=now + bounded_ttl,
                created_at=now,
            )
            self._artifacts[artifact_id] = entry
            return {
                "ok": True,
                "artifact_id": artifact_id,
                "session_id": sess.session_id,
                "principal_id": sess.principal_id,
                "mime_type": mime,
                "max_bytes": bounded_max,
                "expires_at": entry.upload_expires_at,
                "upload_ticket": upload_token,
                "upload_path": f"/api/browser/broker/artifacts/{artifact_id}/upload",
            }

    def consume_upload(
        self,
        artifact_id: str,
        *,
        upload_ticket: str,
        data: bytes,
        content_type: str = "",
        scheme: str = "https",
        client_host: str = "",
    ) -> dict[str, Any]:
        _check_https_transport(
            scheme, client_host, allow_loopback_http=self._allow_loopback_http
        )
        if not isinstance(data, (bytes, bytearray)):
            raise BrowserBrokerError("invalid_payload", status=400, detail="bytes payload required")
        raw_bytes = bytes(data)
        now = time.time()

        with self._lock:
            entry = self._artifacts.get(artifact_id)
            if entry is None:
                raise BrowserBrokerError("artifact_not_found", status=404, detail="artifact not found")
            if entry.upload_used:
                raise BrowserBrokerError(
                    "ticket_already_used",
                    status=410,
                    detail="one-shot upload ticket has already been consumed",
                )
            presented_hash = _sha256_hex(upload_ticket or "")
            if not upload_ticket or not hmac.compare_digest(entry.upload_token_sha256, presented_hash):
                raise BrowserBrokerError("invalid_ticket", status=401, detail="invalid upload ticket")
            if now > entry.upload_expires_at:
                entry.upload_used = True
                raise BrowserBrokerError("ticket_expired", status=410, detail="upload ticket expired")
            if content_type:
                norm_ct = content_type.split(";", 1)[0].strip().lower()
                if norm_ct and norm_ct != entry.mime_type:
                    raise BrowserBrokerError(
                        "mime_mismatch",
                        status=415,
                        detail=f"expected {entry.mime_type}, got {norm_ct}",
                    )
            if len(raw_bytes) == 0:
                raise BrowserBrokerError("empty_artifact", status=400, detail="artifact payload is empty")
            if len(raw_bytes) > entry.max_bytes or len(raw_bytes) > MAX_ARTIFACT_BYTES:
                raise BrowserBrokerError(
                    "artifact_too_large",
                    status=413,
                    detail=f"artifact exceeds {entry.max_bytes} byte limit",
                )

            # Burn ticket atomically and store bounded bytes.
            entry.upload_used = True
            entry.uploaded_at = now
            entry.data = raw_bytes
            entry.size_bytes = len(raw_bytes)
            entry.sha256 = _sha256_hex(raw_bytes)
            return {
                "ok": True,
                "artifact_id": entry.artifact_id,
                "session_id": entry.session_id,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
                "mime_type": entry.mime_type,
            }

    def mint_download_ticket(
        self,
        artifact_id: str,
        *,
        principal_id: str,
        ttl_s: float = DEFAULT_TICKET_TTL_S,
    ) -> dict[str, Any]:
        principal = _normalize_principal(principal_id)
        now = time.time()
        bounded_ttl = max(5.0, min(float(ttl_s), 900.0))

        with self._lock:
            self._evict_locked(now)
            entry = self._artifacts.get(artifact_id)
            if entry is None:
                raise BrowserBrokerError("artifact_not_found", status=404, detail="artifact not found")
            if entry.principal_id != principal:
                raise BrowserBrokerError(
                    "identity_mismatch",
                    status=403,
                    detail="caller identity cannot mint a download ticket for this artifact",
                )
            if not entry.upload_used or entry.data is None:
                raise BrowserBrokerError(
                    "artifact_not_uploaded",
                    status=409,
                    detail="artifact bytes have not been uploaded yet",
                )
            ticket_id = uuid.uuid4().hex[:12]
            secret_part = secrets.token_urlsafe(32)
            compound_ticket = f"{ticket_id}.{secret_part}"
            expires_at = now + bounded_ttl
            entry.download_tickets[ticket_id] = (_sha256_hex(secret_part), expires_at, False)
            return {
                "ok": True,
                "artifact_id": entry.artifact_id,
                "filename": entry.filename,
                "mime_type": entry.mime_type,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
                "expires_at": expires_at,
                "download_ticket": compound_ticket,
                "download_path": f"/api/browser/broker/artifacts/{entry.artifact_id}/download",
            }

    def consume_download(
        self,
        artifact_id: str,
        *,
        download_ticket: str,
        scheme: str = "https",
        client_host: str = "",
        purge_on_read: bool = True,
    ) -> dict[str, Any]:
        _check_https_transport(
            scheme, client_host, allow_loopback_http=self._allow_loopback_http
        )
        raw_ticket = (download_ticket or "").strip()
        if "." not in raw_ticket:
            raise BrowserBrokerError("invalid_ticket", status=401, detail="invalid download ticket")
        ticket_id, secret_part = raw_ticket.split(".", 1)
        now = time.time()

        with self._lock:
            entry = self._artifacts.get(artifact_id)
            if entry is None:
                raise BrowserBrokerError("artifact_not_found", status=404, detail="artifact not found")
            record = entry.download_tickets.get(ticket_id)
            if record is None:
                raise BrowserBrokerError("invalid_ticket", status=401, detail="unknown download ticket")
            expected_hash, expires_at, already_used = record
            if already_used:
                raise BrowserBrokerError(
                    "ticket_already_used",
                    status=410,
                    detail="one-shot download ticket has already been consumed",
                )
            presented_hash = _sha256_hex(secret_part)
            if not hmac.compare_digest(expected_hash, presented_hash):
                raise BrowserBrokerError("invalid_ticket", status=401, detail="invalid download ticket")
            if now > expires_at:
                entry.download_tickets[ticket_id] = (expected_hash, expires_at, True)
                raise BrowserBrokerError("ticket_expired", status=410, detail="download ticket expired")
            if entry.data is None:
                raise BrowserBrokerError(
                    "artifact_already_consumed",
                    status=410,
                    detail="artifact bytes have already been consumed",
                )

            # Burn ticket atomically on first read.
            entry.download_tickets[ticket_id] = (expected_hash, expires_at, True)
            payload = entry.data
            if purge_on_read:
                entry.data = None
            return {
                "artifact_id": entry.artifact_id,
                "filename": entry.filename,
                "mime_type": entry.mime_type,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
                "data": payload,
            }
