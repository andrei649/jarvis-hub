"""Send to a destination the owner configured, with no inbound thread first.

The gap H018 and H480 both record: `nerva send` could only propose a reply into a
thread Nerva had already *received*. Hermes' `send` needs no prior conversation — it
addresses a configured platform directly, and its own rebuild note calls that "the
single most useful automation primitive an agent framework can ship".

The resolution itself was not missing. ``JobRunner._send`` has resolved "where does a
message to this channel go" since wave 2 — telegram needs the owner chat id, the others
address themselves. What was missing is that the resolution lived inside the scheduler,
reachable only by a firing job. This module is that same decision, extracted so a route
and a shell can reach it, and wrapped in the two guarantees the capability's governance
note demands.

**Reversible, but never silent.** A bare outbound message to the owner's own configured
channel is the reversible tier: it does not queue for approval. That makes the audit
record the only trace it happened, so a send that cannot be recorded is still sent — the
message is the owner's, and losing it to a logging failure would be worse — but the
failure to record is returned in the result rather than swallowed. A reply *into a live
conversation* is a different action (`channel.reply`, KERNEL) and does not come through
here.

**Email is deliberately absent**, exactly as it is absent from ``ChannelManager.send``:
keeping SMTP out of the generic send API is what stops untrusted inbound mail from
gaining an outbound side effect. Adding it here would reopen that by the back door.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("jarvis.channels.outbound")

#: Channels that can accept a message addressed to the owner with no prior thread.
#: Mirrors the dispatch arms of ``ChannelManager.send``; email is excluded on purpose
#: (see the module docstring), and so are the reply-only transports.
DIRECT_SEND_CHANNELS = ("telegram", "web", "voice", "ntfy")

#: Longest message this seam will carry. The per-channel cap in the descriptor is
#: usually smaller and the adapter chunks to it; this is only the outer bound that
#: keeps a script from handing the transport an unbounded string.
MAX_TEXT_CHARS = 4_000

OWNER_CHAT_SETTING = "autonomy.owner_chat_id"
OWNER_CHAT_ENV = "AUTONOMY_OWNER_CHAT_ID"


def _owner_chat_id(orch: Any) -> str:
    """The owner's Telegram chat, from the environment or the settings store.

    Same precedence as ``JobRunner._send``: the environment wins, so a host can
    address a different chat without editing stored settings.
    """
    from agents.core.env_config import env_str

    from_env = env_str(OWNER_CHAT_ENV)
    if from_env.strip():
        return from_env.strip()
    get_setting = getattr(orch, "get_setting", None)
    if not callable(get_setting):
        return ""
    return str(get_setting(OWNER_CHAT_SETTING, "") or "").strip()


def resolve_destination(orch: Any, channel: str) -> tuple[dict[str, Any] | None, str]:
    """``(send kwargs, "")`` when *channel* can be addressed, ``(None, reason)`` when not.

    The reason is the owner's diagnosis and names the missing piece — "no owner chat is
    configured (autonomy.owner_chat_id)" is actionable; "unavailable" is not.
    """
    name = str(channel or "").strip().lower()
    if name not in DIRECT_SEND_CHANNELS:
        return None, f"{name or '(none)'} is not a direct-send channel"
    adapter = (getattr(orch, "channels", None) or {}).get(name)
    if adapter is None:
        return None, f"{name} is not connected on this hub"
    if name != "telegram":
        return {}, ""
    owner = _owner_chat_id(orch)
    if not owner:
        return None, f"no owner chat is configured ({OWNER_CHAT_SETTING})"
    try:
        return {"chat_id": int(owner)}, ""
    except (TypeError, ValueError):
        return None, f"{OWNER_CHAT_SETTING} is not a chat id: {owner!r}"


def configured_targets(orch: Any) -> list[dict[str, Any]]:
    """Every direct-send channel, whether it is ready, and why not when it is not.

    Unready channels are listed rather than hidden: "telegram is connected but no owner
    chat is configured" is the answer the owner needs, and an empty list would read as
    "this hub cannot send at all".
    """
    rows: list[dict[str, Any]] = []
    channels = getattr(orch, "channels", None) or {}
    for name in DIRECT_SEND_CHANNELS:
        adapter = channels.get(name)
        kwargs, reason = resolve_destination(orch, name)
        descriptor = getattr(type(adapter), "descriptor", None) if adapter else None
        rows.append({
            "channel": name,
            "connected": adapter is not None,
            "ready": kwargs is not None,
            "reason": reason,
            "max_message_length": getattr(descriptor, "max_message_length", None),
            "dialect": getattr(descriptor, "dialect", None),
        })
    return rows


def _audit(orch: Any, fields: dict[str, Any]) -> bool:
    """Record the send in the IntentLog. True when it landed."""
    sink = getattr(orch, "action_audit", None)
    if sink is None:
        return False
    try:
        return sink.log("channel.send", fields) is not None
    except Exception:  # pragma: no cover — the sink already swallows its own failures
        logger.warning("channel.send audit record failed", exc_info=True)
        return False


async def send_to_target(orch: Any, channel: str, text: str, *, source: str = "api") -> dict:
    """Send *text* to a configured destination. Never raises; every outcome is a dict.

    ``{"ok": True, "channel": …, "audited": bool}`` or
    ``{"ok": False, "reason": …}``. ``audited`` is reported rather than assumed: an
    unaudited send is a real (small) governance gap and the caller should be able to see
    it, not discover it later from an empty log.
    """
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "reason": "the message is empty"}
    if len(body) > MAX_TEXT_CHARS:
        return {"ok": False, "reason": f"the message is longer than {MAX_TEXT_CHARS} characters"}

    name = str(channel or "").strip().lower()
    kwargs, reason = resolve_destination(orch, name)
    if kwargs is None:
        return {"ok": False, "reason": reason}

    from agents.core.channels.send_rate_limit import allow_send
    if not allow_send(name):
        return {"ok": False, "reason": f"{name} is over its configured send rate"}

    manager = getattr(orch, "channel_manager", None)
    try:
        if manager is not None:
            delivered = bool(await manager.send(name, body, **kwargs))
        else:
            adapter = (getattr(orch, "channels", None) or {})[name]
            delivered = bool(await adapter.send(body, **kwargs))
    except Exception as exc:
        logger.warning("channel.send failed on %s (type=%s)", name, type(exc).__name__)
        return {"ok": False, "reason": f"{name} raised {type(exc).__name__}"}

    if not delivered:
        # A refusal is still an attempt the owner made; record it or the log implies
        # nothing was tried.
        _audit(orch, {"channel": name, "chars": len(body), "source": source, "delivered": False})
        return {"ok": False, "reason": f"{name} refused the message"}

    audited = _audit(orch, {
        "channel": name, "chars": len(body), "source": source, "delivered": True,
    })
    return {"ok": True, "channel": name, "audited": audited}


__all__ = [
    "DIRECT_SEND_CHANNELS", "MAX_TEXT_CHARS", "OWNER_CHAT_SETTING",
    "configured_targets", "resolve_destination", "send_to_target",
]
