"""Best-effort, value-free authentication events in the security audit chain."""

from __future__ import annotations

import ipaddress
import json
import logging
import queue
import threading
import time
from contextlib import suppress
from typing import Any

from agents.core.app_state import get_orch

from .audit import AuditLogger
from .types import SecurityEvent, SecurityEventType

logger = logging.getLogger(__name__)

_sink: AuditLogger | None = None
_sink_lock = threading.Lock()
_FALLBACK = object()
_queue: queue.Queue[tuple[SecurityEventType | str, dict[str, object], float]] = queue.Queue(maxsize=64)
_slots = threading.BoundedSemaphore(64)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_pending_count = 0
_pending_cv = threading.Condition()
_last_warning = 0.0
_warning_lock = threading.Lock()
_KINDS = {
    SecurityEventType.AUTH_SUCCESS, SecurityEventType.AUTH_FAILURE,
    SecurityEventType.TOKEN_ISSUED, SecurityEventType.TOKEN_ROTATED,
    SecurityEventType.TOKEN_REVOKED,
}
_MCP_SURFACE_KINDS = {
    SecurityEventType.AUTH_SUCCESS, SecurityEventType.AUTH_FAILURE,
    SecurityEventType.TOKEN_ISSUED,
}
_REASONS = {
    "credential", "admin_credential", "local_bypass", "missing", "invalid",
    "network_disabled", "issue", "rotate", "revoke",
}


def _warn(message: str) -> None:
    """Limit warning volume during a sustained sink outage."""
    global _last_warning
    with _warning_lock:
        now = time.monotonic()
        if now - _last_warning < 60:
            return
        _last_warning = now
    # A broken logging handler is still an audit failure, never an auth failure.
    with suppress(Exception):
        logger.warning("authentication audit %s", message)


def _resolve_sink() -> AuditLogger:
    """Share the live orchestrator's chain; the CLI owns a lazy fallback sink."""
    active = _active_sink()
    return active if active is not None else _fallback_sink()


def _fallback_sink() -> AuditLogger:
    """Resolve only the offline sink, regardless of later orchestrator changes."""
    global _sink
    if _sink is None:
        with _sink_lock:
            if _sink is None:
                _sink = AuditLogger()
    return _sink


def _active_sink() -> Any:
    """Capture the live sink without opening SQLite on an async guard path."""
    orch = get_orch()
    return getattr(orch, "audit", None) if orch is not None else None


def _safe_client(client: object) -> str:
    if client == "localhost":
        return "localhost"
    try:
        value = str(client)
        if len(value) > 64:
            return "unknown"
        return str(ipaddress.ip_address(value.split("%", 1)[0]))
    except (ipaddress.AddressValueError, ValueError, TypeError):
        return "unknown"


def record_auth_event(
    kind: SecurityEventType | str, *, tier: str, outcome: str = "",
    reason: str, client: object = "", token: object = None,
    count: int | None = None, revoke_env: bool = False,
    sink: Any = None, surface: object = None, **meta: object,
) -> None:
    """Append one whitelist-only event; drop secrets and arbitrary metadata.

    ``token`` and ``meta`` are accepted solely so callers can hand over mixed
    metadata safely. Neither is inspected, formatted, or serialized.
    """
    _record_auth_event(
        kind, time.time(), tier=tier, reason=reason, client=client,
        count=count, revoke_env=revoke_env, sink=sink, surface=surface,
    )


def _record_auth_event(
    kind: SecurityEventType | str, event_time: float, /, *, tier: str,
    reason: str, client: object = "", count: int | None = None,
    revoke_env: bool = False, sink: Any = None, surface: object = None,
) -> None:
    """Internal writer; ``event_time`` is captured by our submitter, never input."""
    try:
        event_type = SecurityEventType(kind)
        if event_type not in _KINDS:
            return
        safe_tier = tier if tier in ("admin", "user", "all") else "unknown"
        safe_reason = reason if reason in _REASONS else "unknown"
        fields: dict[str, object] = {
            "tier": safe_tier,
            "outcome": "success" if event_type in (
                SecurityEventType.AUTH_SUCCESS, SecurityEventType.TOKEN_ISSUED,
                SecurityEventType.TOKEN_ROTATED, SecurityEventType.TOKEN_REVOKED,
            ) else "failure",
            "reason": safe_reason,
        }
        if event_type in (SecurityEventType.AUTH_SUCCESS, SecurityEventType.AUTH_FAILURE):
            fields["client"] = _safe_client(client)
        else:
            fields["count"] = max(0, min(int(count or 0), 1_000_000))
            fields["revoke_env"] = bool(revoke_env)
        if event_type in _MCP_SURFACE_KINDS and type(surface) is str and surface == "mcp":
            fields["surface"] = "mcp"
        event = SecurityEvent(
            event_type=event_type,
            timestamp=event_time,
            content_preview=json.dumps(fields, sort_keys=True, separators=(",", ":")),
            action_taken=f"{safe_tier}:{safe_reason}",
        )
        target = _fallback_sink() if sink is _FALLBACK else sink
        (target if target is not None else _resolve_sink()).log(event)
    except Exception as exc:
        _warn(f"write failed ({type(exc).__name__})")


def _run_worker() -> None:
    global _pending_count
    while True:
        kind, fields, submitted_at = _queue.get()
        try:
            _record_auth_event(kind, submitted_at, **fields)
        except Exception as exc:
            _warn(f"worker failed ({type(exc).__name__})")
        finally:
            _slots.release()
            _queue.task_done()
            with _pending_cv:
                _pending_count -= 1
                _pending_cv.notify_all()


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                worker = threading.Thread(target=_run_worker, name="auth-audit", daemon=True)
                worker.start()
                _worker = worker


def submit_auth_event(kind: SecurityEventType | str, **fields: object) -> None:
    """Queue a guard event without waiting for SQLite; drop at 64 pending."""
    global _pending_count
    try:
        event_type = SecurityEventType(kind)
        if event_type not in _KINDS:
            return
        tier = fields.get("tier")
        reason = fields.get("reason")
        safe_fields: dict[str, object] = {
            "tier": tier if tier in ("admin", "user", "all") else "unknown",
            "reason": reason if reason in _REASONS else "unknown",
            "client": _safe_client(fields.get("client", "")),
            "count": max(0, min(int(fields.get("count") or 0), 1_000_000)),
            "revoke_env": bool(fields.get("revoke_env", False)),
        }
        if (event_type in _MCP_SURFACE_KINDS
                and type(fields.get("surface")) is str and fields["surface"] == "mcp"):
            safe_fields["surface"] = "mcp"
        # The orchestrator may be replaced between submission and writing. Keep
        # the request's original sink rather than routing its row into a new one.
        sink = fields.get("sink")
        if sink is None:
            active = _active_sink()
            sink = active if active is not None else _FALLBACK
        if sink is not _FALLBACK and not callable(getattr(sink, "log", None)):
            sink = _FALLBACK
        safe_fields["sink"] = sink
    except Exception as exc:
        _warn(f"prepare failed ({type(exc).__name__})")
        return
    if not _slots.acquire(blocking=False):
        _warn("queue full; event dropped")
        return
    counted = False
    try:
        _ensure_worker()
        with _pending_cv:
            _pending_count += 1
            counted = True
        _queue.put_nowait((event_type, safe_fields, time.time()))
    except Exception as exc:
        _slots.release()
        if counted:
            with _pending_cv:
                _pending_count -= 1
                _pending_cv.notify_all()
        _warn(f"enqueue failed ({type(exc).__name__})")


def wait_pending(timeout: float | None) -> bool:
    """Wait for already queued rows up to ``timeout`` seconds."""
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    with _pending_cv:
        while _pending_count:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            _pending_cv.wait(remaining)
    return True


def flush_pending() -> None:
    """Wait for submitted rows in deterministic tests only.

    Production never calls this: a stuck audit sink must not delay shutdown.
    """
    wait_pending(None)
