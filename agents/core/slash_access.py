"""H058 — per-command access tiers on the chat command plane (Hermes ``gateway/slash_access.py``).

Of the people a channel already lets talk to the hub, the **owner** (the admin tier: the
principal the turn established as the owner — the Telegram owner, a configured Slack/
Discord/ntfy owner, an admin token on the web door) may run every command. Everyone else is
the **user** tier and runs the floor — ``/help`` and ``/whoami``, which no setting removes —
plus the user-tier commands the owner allows for that channel and scope in
``commands.user_allowed_commands``, keyed separately for a DM and a group::

    {"telegram": {"dm": ["status", "voice"], "group": []},
     "*":        {"dm": ["status", "sessions", "recap", "btw", "jobs", "voice"]}}

A channel's own entry wins over ``"*"``; a DM list that is not set falls back to the same
entry's group list (Hermes' rule — a DM is never given a wider list by accident); a channel
and scope nobody configured keeps the registry's user tier, which is what a non-owner could
run before this gate existed. An unreadable store or a malformed value reads as an empty
list: the floor only. The list can never grant an owner command (or an owner quick command)
— that tier is the owner's, whatever the setting says.

Where Hermes fails open (no admin list for a scope = everyone runs everything), this gate
has no off state: an owner command answers only the owner on every surface, configured or
not. The gate decides who may *reach* a handler; it is in front of the Action Kernel, never
instead of it — a handler that acts still crosses its own kernel kind and approval.

A denial reads ``⛔ /<cmd> is admin-only here. You can run: …`` (Hermes' text, at most 12
names, then ``Use /whoami for the full list``), is logged, and is written to the security
audit log (``SecurityEventType.AUDIT_LOG``, ``slash_command_denied``) — the audit row the
Hermes rebuild note asked for and never shipped. ``/whoami`` reports the platform, scope,
sender id, tier and the exact command list. The orchestrator asks this module on the cold
path (``CommandRegistry.dispatch``), on the busy path (a channel command is judged before
the session lease and the running-work interrupt; the ``/btw`` side question is judged as
it is answered beside a running turn) and again for quick commands, on the raw typed name.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from typing import Any

logger = logging.getLogger("jarvis.commands.access")

CATEGORY = "commands"
KEY = "user_allowed_commands"
SETTING = f"{CATEGORY}.{KEY}"
#: The commands every admitted sender may run, whatever the setting says.
FLOOR = ("help", "whoami")
SCOPES = ("dm", "group")
ANY_CHANNEL = "*"
#: Hermes ``_DM_CHAT_TYPES`` (plus Slack's ``im``): everything else is a group.
DM_CHAT_TYPES = frozenset({"", "dm", "direct", "private", "im"})
PREVIEW = 12
AUDIT_ACTION = "slash_command_denied"

_CHANNEL = re.compile(r"[a-z][a-z0-9_.-]{0,31}\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_MAX_CHANNELS = 64
_MAX_NAMES = 128
_OWNER_HINT = "send it from the owner's channel or with an admin token"


def scope_for_chat_type(chat_type: Any) -> str:
    """``dm`` for a direct chat (or a channel that reports no chat type), else ``group``."""
    return "dm" if str(chat_type or "").strip().lower() in DM_CHAT_TYPES else "group"


def _name(raw: Any) -> str | None:
    if type(raw) is not str:
        return None
    name = raw[1:] if raw.startswith("/") else raw
    return name.lower() if _NAME.fullmatch(name) else None


@lru_cache(maxsize=1)
def _owner_commands() -> frozenset[str]:
    """The built-in owner commands, which no list may grant."""
    from .commands import ADMIN, build_default_registry

    return frozenset(command.name for command in build_default_registry().commands()
                     if command.tier == ADMIN)


def configuration_problem(value: Any) -> str | None:
    """Why a ``commands.user_allowed_commands`` write is refused, or None."""
    if type(value) is not dict or len(value) > _MAX_CHANNELS:
        return f"{KEY}: expected an object of at most {_MAX_CHANNELS} channels"
    owner = _owner_commands()
    for channel, entry in value.items():
        if type(channel) is not str or not (channel == ANY_CHANNEL or _CHANNEL.fullmatch(channel)):
            return f"{KEY}: {channel!r} is not a channel name (lower-case letters, digits, _ . -) or \"*\""
        if type(entry) is not dict or not set(entry) <= set(SCOPES):
            return f"{KEY}: {channel}: expected an object with \"dm\" and/or \"group\" lists"
        for scope, names in entry.items():
            if type(names) is not list or len(names) > _MAX_NAMES:
                return f"{KEY}: {channel}.{scope}: expected a list of at most {_MAX_NAMES} command names"
            for raw in names:
                name = _name(raw)
                if name is None:
                    return f"{KEY}: {channel}.{scope}: {raw!r} is not a slash-command name"
                if name in owner:
                    return (f"{KEY}: {channel}.{scope}: /{name} is an owner command; this list "
                            "grants only user-tier commands")
    return None


def _policy() -> dict:
    """The stored policy, ``{}`` when the owner never set one; None fails closed."""
    from . import settings_db

    try:
        found, value = settings_db.read_setting(CATEGORY, KEY)
    except settings_db.SettingsUnreadable:
        logger.warning("%s unreadable; non-owners keep only /help and /whoami", SETTING)
        return None
    if not found:
        return {}
    problem = configuration_problem(value)
    if problem is not None:
        logger.warning("%s ignored (%s); non-owners keep only /help and /whoami", SETTING, problem)
        return None
    return value


def _scope_list(entry: Any, scope: str) -> list | None:
    if type(entry) is not dict:
        return None
    if scope in entry:
        return entry[scope]
    if scope == "dm" and "group" in entry:
        return entry["group"]       # Hermes: an unset DM list uses the group list
    return None


def _user_tier(registry) -> list[str]:
    from .commands import USER

    return [command.name for command in registry.commands() if command.tier == USER]


def allowed_names(registry, principal) -> list[str] | None:
    """The commands *principal* may run here, floor first; None for the owner (all)."""
    if principal.admin is True:
        return None
    user_tier = _user_tier(registry)
    policy = _policy()
    listed = None
    if policy is not None:
        listed = _scope_list(policy.get(principal.channel), principal.scope)
        if listed is None:
            listed = _scope_list(policy.get(ANY_CHANNEL), principal.scope)
    if policy is None:
        granted: set[str] = set()
    elif listed is None:
        granted = set(user_tier)
    else:
        granted = {name for name in (_name(raw) for raw in listed) if name in user_tier}
    return [*FLOOR, *sorted(granted - set(FLOOR))]


def can_run(registry, principal, name: str, *, quick: bool = False) -> bool:
    """Whether *principal* may run ``/name``. A quick command is the owner's tier."""
    if principal.admin is True:
        return True
    if quick:
        return False
    from .commands import ADMIN

    command = registry.get(name)
    if command is not None and command.tier == ADMIN:
        return False                # the setting can never widen the owner tier
    return name in allowed_names(registry, principal)


def _commands_line(names: list[str]) -> str:
    shown = ", ".join(f"/{name}" for name in names[:PREVIEW])
    return shown + (", …" if len(names) > PREVIEW else "")


def denial_reply(name: str, allowed: list[str], *, owner_tier: bool, scope: str) -> str:
    reply = (f"⛔ /{name} is admin-only here. You can run: {_commands_line(allowed)}. "
             "Use /whoami for the full list.")
    if owner_tier:
        return reply + f" /{name} is an owner command — {_OWNER_HINT}."
    where = "a DM" if scope == "dm" else "a group"
    return reply + f" The owner can allow it in {where} here with {SETTING}."


def _safe(value: Any, limit: int = 64) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit and text.isprintable() else "unprintable"


async def _audit(orch: Any, principal, name: str, reason: str) -> None:
    """One audit row per denial: command, channel, scope, sender, why — never the args."""
    from .security.types import SecurityEvent, SecurityEventType

    audit = getattr(orch, "audit", None) if orch is not None else None
    log = getattr(audit, "log", None)
    if not callable(log):
        logger.warning("slash command denial not audited: no audit log on this hub")
        return
    preview = json.dumps({"command": name, "channel": _safe(principal.channel, 32),
                          "scope": principal.scope, "sender": _safe(principal.sender),
                          "tier": "user", "reason": reason}, sort_keys=True, separators=(",", ":"))
    try:
        await asyncio.to_thread(log, SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
            content_preview=preview, action_taken=AUDIT_ACTION))
    except Exception:  # noqa: BLE001 — the denial stands; a lost audit row is logged
        logger.warning("slash command denial for /%s could not be audited", name, exc_info=True)


async def refusal(registry, name: str, *, orch: Any, principal, quick: bool = False):
    """None when *principal* may run ``/name``; otherwise the audited denial outcome.

    *name* is a registry command name or a configured quick-command name — never text
    the sender typed that names nothing — so the log line and the audit row carry only
    command names."""
    if can_run(registry, principal, name, quick=quick):
        return None
    from .commands import ADMIN, CommandOutcome

    command = None if quick else registry.get(name)
    owner_tier = quick or (command is not None and command.tier == ADMIN)
    logger.info("Slash command /%s denied for %s:%s (%s, not the owner, not in %s)",
                name, principal.channel, principal.sender or "?", principal.scope, SETTING)
    await _audit(orch, principal, name, "owner_tier" if owner_tier else "not_allowed")
    allowed = allowed_names(registry, principal) or list(FLOOR)
    return CommandOutcome(name, "refused", denial_reply(
        name, allowed, owner_tier=owner_tier, scope=principal.scope))


def gated_name(registry, text: str) -> tuple[str, bool] | None:
    """``(name, quick)`` when *text* asks for a registry or quick command, else None."""
    parsed = registry.parse(text)
    if parsed is None:
        return None
    name = parsed[0]
    if registry.get(name) is not None:
        return name, False
    from .quick_commands import configured

    try:
        quick = name in configured()
    except Exception:  # noqa: BLE001 — unreadable quick commands: the registry decides later
        quick = False
    return (name, True) if quick else None


def whoami(registry, principal) -> str:
    """Hermes ``/whoami``: platform, scope, sender id, tier and the exact command list."""
    scope = "DM" if principal.scope == "dm" else "group"
    lines = [f"You — {principal.channel or '?'} ({scope})", f"Sender ID: {principal.sender or '?'}"]
    if principal.admin is True:
        from .quick_commands import configured

        names = sorted(command.name for command in registry.commands())
        try:
            names += sorted(name for name in configured() if registry.get(name) is None)
        except Exception:  # noqa: BLE001 — the owner still sees the registry
            pass
        lines += ["Tier: admin (the owner) — every command answers you here",
                  "Slash commands you can run: " + ", ".join(f"/{name}" for name in names)]
    else:
        names = allowed_names(registry, principal) or list(FLOOR)
        lines += [f"Tier: user — owner commands answer only the owner; {SETTING} sets the rest",
                  "Slash commands you can run: " + ", ".join(f"/{name}" for name in names)]
    return "\n".join(lines)
