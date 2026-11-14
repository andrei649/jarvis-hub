"""Owner chat view and failed-channel controls (H083)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from .channels.outbound_safety import sanitize_text
from .security.types import SecurityEvent, SecurityEventType

_MAX_ROWS = 12
_MAX_NAME = 256
_USAGE = "Usage: /platform [list|pause <name>|resume <name>]."
_AUDIT_UNAVAILABLE = " Audit record unavailable."
_KNOWN_TARGETS = frozenset({"telegram", "discord", "slack", "ntfy", "web", "voice", "email", "sms"})
_PAUSE_OUTCOMES = frozenset({
    "paused", "unknown", "not_failed", "already_paused", "stop_unconfirmed",
    "owner_changed", "shutdown",
})
_RESUME_OUTCOMES = frozenset({
    "resumed", "unknown", "not_paused", "stop_unconfirmed", "start_unconfirmed",
    "start_failed", "cleanup_unconfirmed", "owner_changed", "shutdown", "safe_mode",
})
_OUTCOMES = _PAUSE_OUTCOMES | _RESUME_OUTCOMES | {"refused_target"}
logger = logging.getLogger(__name__)


def _audit_target(target: str) -> str:
    """Show a canonical platform or a grouped full SHA256 of a registered custom ID."""
    canonical = target.casefold()
    if canonical in _KNOWN_TARGETS:
        return canonical
    # A registered custom ID may contain private data. A domain-separated stable
    # fingerprint identifies its audit rows without writing the ID itself.
    # Short colon-separated groups survive AuditLogger's secret scanner, which
    # correctly redacts uninterrupted high-entropy strings.
    fingerprint = hashlib.sha256(b"platform-control-target\0" + target.encode("utf-8", "surrogatepass")).hexdigest()
    return "custom:" + ":".join(fingerprint[i:i + 16] for i in range(0, len(fingerprint), 16))


def _audit(orch, action: str, target: str, outcome: str) -> bool:
    """Append one existing hash-chained security row; report unavailable on failure.

    Synchronous logging after the manager await has no cancellation point where
    a completed operation could be mistaken for a cancelled one.
    """
    audit = getattr(orch, "audit", None)
    log = getattr(audit, "log", None)
    if not callable(log):
        return False
    preview = json.dumps({"action": action, "actor": "owner", "target": target,
                          "outcome": outcome if outcome in _OUTCOMES else "unknown"},
                         sort_keys=True, separators=(",", ":"))
    try:
        log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE,
                          timestamp=time.time(), content_preview=preview,
                          action_taken="platform_control"))
    except Exception:
        return False
    return True


def _audited_reply(orch, action: str, target: str, outcome: str, reply: str) -> str:
    return reply if _audit(orch, action, target, outcome) else reply + _AUDIT_UNAVAILABLE


def _label(value: object) -> str:
    raw = str(value)
    if len(raw) > _MAX_NAME:
        return "(name withheld)"
    return " ".join(sanitize_text(raw).split())[:64] or "(name withheld)"


def _target(manager, raw: str) -> str | None:
    if not raw or len(raw) > _MAX_NAME:
        return None
    found = [name for name in manager.channels if name.casefold() == raw.casefold()]
    return found[0] if len(found) == 1 else None


async def platform_command(ctx) -> str:
    if not ctx.principal.admin:
        return "Only the owner can inspect or control gateway platforms."
    manager = getattr(ctx.orch, "channel_manager", None)
    if manager is None or not all(callable(getattr(manager, method, None)) for method in (
        "platform_snapshot", "pause_failed", "resume_paused")):
        return "Gateway platform manager unavailable."
    parts = ctx.args.split()
    if not parts or parts == ["list"]:
        rows = await manager.platform_snapshot()
        lines = [f"Gateway platforms ({len(rows)} loaded):"]
        for name in sorted(rows)[:_MAX_ROWS]:
            row = rows[name]
            state = _label(row.get("state", "unknown"))
            pause = row.get("pause_state")
            status = _label(pause) if pause else state
            lines.append(f"  { _label(name) }: {status}")
        if len(rows) > _MAX_ROWS:
            lines.append(f"  +{len(rows) - _MAX_ROWS} more")
        return "\n".join(lines)
    if len(parts) != 2 or parts[0] not in {"pause", "resume"}:
        return _USAGE
    action, raw = parts
    target = _target(manager, raw)
    if target is None:
        return _audited_reply(ctx.orch, action, "unresolved", "refused_target",
                              "Unknown platform or ambiguous platform name.")
    audit_target = _audit_target(target)
    try:
        result = (await manager.pause_failed(target) if action == "pause"
                  else await manager.resume_paused(target))
        status = result.get("status")
    except asyncio.CancelledError:
        if not _audit(ctx.orch, action, audit_target, "unknown"):
            logger.warning("platform control cancellation audit unavailable")
        raise
    except Exception:
        return _audited_reply(ctx.orch, action, audit_target, "unknown",
                              "Platform operation could not be confirmed.")
    allowed = _PAUSE_OUTCOMES if action == "pause" else _RESUME_OUTCOMES
    recognized = type(status) is str and status in allowed
    status = status if recognized else "unknown"
    name = _label(target)
    if not recognized:
        return _audited_reply(ctx.orch, action, audit_target, status,
                              "Platform operation could not be confirmed.")
    if status == "paused":
        reply = f"{name} paused; its loaded adapter remains registered."
        return _audited_reply(ctx.orch, action, audit_target, status, reply)
    if status == "resumed":
        reply = f"{name} restart attempted; check /platform list for current health."
        return _audited_reply(ctx.orch, action, audit_target, status, reply)
    messages = {
        "unknown": "Platform is no longer registered.",
        "not_failed": f"{name} has no confirmed failed retry loop; nothing was stopped.",
        "already_paused": f"{name} is already paused.",
        "not_paused": f"{name} is not paused.",
        "stop_unconfirmed": f"{name} stop could not be confirmed; pause intent remains set.",
        "start_unconfirmed": f"{name} restart is still being cleaned up; pause intent remains set.",
        "start_failed": f"{name} restart failed; pause intent remains set.",
        "cleanup_unconfirmed": f"{name} prior adapter cleanup is unconfirmed; nothing was started.",
        "owner_changed": f"{name} adapter changed during the operation; result withheld.",
        "shutdown": "Gateway is stopping; platform operation refused.",
        "safe_mode": "Safe mode refuses platform restart; pause intent remains set.",
    }
    return _audited_reply(ctx.orch, action, audit_target, status,
                          messages.get(status, "Platform operation could not be confirmed."))


__all__ = ["platform_command"]
