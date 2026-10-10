"""H329 — switch a skill off without uninstalling it, everywhere or on one channel.

An owner who distrusted one skill could only uninstall it, which deletes its folder
and with it the usage history, the signature and the owner approval. Hermes keeps
``skills.disabled`` and ``skills.platform_disabled.<platform>``; Nerva keeps two
declared settings rows:

- ``skills.disabled``: the skills switched off everywhere (a list of names);
- ``skills.channel_disabled``: ``{channel: [names]}``, the skills switched off on one
  channel (``telegram``, ``voice``, ``web``, ...) only.

An entry is a skill's name as the skills list shows it, ignoring case (the route and the
CLI also take a folder, and store the name it resolves to, so an entry never matches one
skill by name and another by folder). A switched-off
skill stays installed, signed, approved and counted; it is left out of the model's
skill catalog and of ``skills_list`` / ``skill_view`` (the shared
``SkillLoader.catalog_gate``), and a command that names it is refused with the reason
instead of running. The switch reads the rows at call time, so it applies at once,
without a restart.

:data:`ESSENTIAL_SKILLS` cannot be switched off: the security monitor is how the owner
sees an open port or a new device on the network, and a switch that hid it would hide
exactly what the owner needs to see. Only the shipped copy is essential, never an
imported skill that takes its folder or name (review-H329 F2). A stored entry for one is
ignored.

Switching off narrows what the hub does and is immediate. Switching back on widens
it, so the admin route queues an exact, once-scoped human approval; the worker
changes the rows only after approval and writes attribution in the same transaction.
An optional intent-log projection does not carry that authority. Settings writes,
imports, resets and ``nerva config set`` cannot widen these rows
(``settings_db.ROUTE_ONLY``). No model-facing tool writes them.

This is not the H285 load set (``loadset.skills_*``), which keeps a skill from being
loaded at all at boot, for a skill that breaks the hub; a switched-off skill is loaded
and listed, only not used.
"""
from __future__ import annotations

import contextvars
import logging
import re
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.skills.switches")

CATEGORY = "skills"
GLOBAL_KEY = "disabled"
CHANNEL_KEY = "channel_disabled"
#: Shipped skills (folder names) that cannot be switched off.
ESSENTIAL_SKILLS: frozenset[str] = frozenset({"security_monitor"})
MAX_NAMES = 256
MAX_NAME_CHARS = 128
MAX_CHANNELS = 32
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

_WRITE_LOCK = threading.Lock()
#: The channel ``handle_input`` was given for the turn in progress (review-H329 F4: an
#: mcp, webhook or workflow turn binds no principal, so the catalog read "no channel"
#: while a command of the same turn was refused on its channel).
_TURN_CHANNEL: contextvars.ContextVar[str] = contextvars.ContextVar("nerva_skill_turn_channel", default="")


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def clean_names(value: Any) -> list[str]:
    """A stored list as names: strings only, trimmed, de-duplicated (ignoring case),
    printable, bounded."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or len(name) > MAX_NAME_CHARS or not name.isprintable() or _key(name) in seen:
            continue
        seen.add(_key(name))
        out.append(name)
        if len(out) >= MAX_NAMES:
            break
    return out


def clean_channel(value: Any) -> str:
    """A channel name, lower-cased, or ``""`` when it is not one."""
    channel = str(value or "").strip().lower()
    return channel if CHANNEL_RE.fullmatch(channel) else ""


def clean_channel_map(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for raw, names in value.items():
        channel = clean_channel(raw)
        cleaned = clean_names(names)
        if channel and cleaned and channel not in out:
            out[channel] = cleaned
        if len(out) >= MAX_CHANNELS:
            break
    return out


def channel_map_problem(value: Any) -> str | None:
    """Why a ``skills.channel_disabled`` write is refused, or None."""
    if not isinstance(value, dict):
        return f"{CHANNEL_KEY}: expected an object {{channel: [skill names]}}"
    if len(value) > MAX_CHANNELS:
        return f"{CHANNEL_KEY}: at most {MAX_CHANNELS} channels"
    for channel, names in value.items():
        if not isinstance(channel, str) or not CHANNEL_RE.fullmatch(channel):
            return f"{CHANNEL_KEY}: {channel!r} is not a channel name (lower-case letters, digits, _ . -)"
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return f"{CHANNEL_KEY}: {channel}: expected a list of skill names"
    return None


def state() -> dict:
    """The current complete switch state, or an unreadable-store refusal."""
    return strict_state()


def strict_state() -> dict:
    """Read both rows consistently; malformed or missing rows never mean enabled."""
    from agents.core import settings_db

    preflight_persisted_rows()
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        marker = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_switch_revision'"
        ).fetchone()
        if marker is None:
            # The first H329 read marks this store. Later startup must
            # never treat a missing switch row as a fresh-install default.
            from . import switch_approval

            conn.executescript(switch_approval._SCHEMA)
        return state_from_connection(conn)
    finally:
        conn.close()


def preflight_persisted_rows() -> None:
    """A post-H329 store missing a row is damage, not a new default to reseed."""
    from agents.core import settings_db

    path = settings_db.DB_PATH
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            marker = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_switch_revision'"
            ).fetchone()
            if marker is None:
                return  # fresh install or a legacy pre-bridge schema
            rows = conn.execute("SELECT key FROM settings WHERE category='skills' "
                                "AND key IN ('disabled','channel_disabled')").fetchall()
            if {row[0] for row in rows} != {GLOBAL_KEY, CHANNEL_KEY}:
                raise settings_db.SettingsUnreadable("skill switch row missing from initialized store")
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        raise settings_db.SettingsUnreadable("skill switch store unavailable") from exc


def state_from_connection(conn) -> dict:
    """Strict switch snapshot for a caller's SQLite transaction."""
    import json

    from agents.core.settings_db import SettingsUnreadable

    try:
        rows = conn.execute(
            "SELECT key, value, opts FROM settings WHERE category=? AND key IN (?, ?)",
            (CATEGORY, GLOBAL_KEY, CHANNEL_KEY),
        ).fetchall()
        raw = {row["key"]: json.loads(row["value"]) for row in rows}
        for row in rows:
            json.loads(row["opts"])
        if set(raw) != {GLOBAL_KEY, CHANNEL_KEY}:
            raise ValueError("missing skill switch row")
        names, channels = raw[GLOBAL_KEY], raw[CHANNEL_KEY]
        if (not isinstance(names, list) or len(names) > MAX_NAMES
                or clean_names(names) != names or not isinstance(channels, dict)
                or len(channels) > MAX_CHANNELS or clean_channel_map(channels) != channels):
            raise ValueError("invalid skill switch state")
        return {GLOBAL_KEY: names, CHANNEL_KEY: channels}
    except (ValueError, TypeError, KeyError) as exc:
        raise SettingsUnreadable("skill switch state is unreadable") from exc


def identities(skill: Any) -> set[str]:
    """The names an owner may use for ``skill`` at the route or the CLI: its name and its
    folder (a stored entry is always the name)."""
    keys = {_key(getattr(skill, "name", ""))}
    path = getattr(skill, "path", None)
    folder = getattr(path, "name", "") if path is not None else ""
    keys.add(_key(folder))
    keys.discard("")
    return keys


def _entry(skill: Any) -> str:
    """The key a stored entry must have to name ``skill``: its name, ignoring case."""
    return _key(getattr(skill, "name", ""))


def is_essential(skill: Any) -> bool:
    """Whether ``skill`` is the shipped copy of an essential skill: loaded as the
    product's own (not external) from its place in the shipped tree. A name or a folder
    an imported skill can also carry is not enough (review-H329 F2)."""
    path = getattr(skill, "path", None)
    if path is None or getattr(skill, "external", True) or Path(path).name not in ESSENTIAL_SKILLS:
        return False
    from .loader import _shipped_location

    return _shipped_location(Path(path))


def bind_turn_channel(channel: Any) -> contextvars.Token:
    """Bind the channel of the turn ``handle_input`` runs (``""`` when it is not one)."""
    return _TURN_CHANNEL.set(clean_channel(channel))


def reset_turn_channel(token: contextvars.Token) -> None:
    _TURN_CHANNEL.reset(token)


def current_channel() -> str:
    """The channel of the turn in progress: the one ``handle_input`` was given, else the
    bound principal's, or ``""`` outside a turn."""
    channel = _TURN_CHANNEL.get()
    if not channel:
        try:
            from agents.core.orchestrator import current_principal

            channel = clean_channel(getattr(current_principal(), "channel", ""))
        except Exception:
            return ""
    # A turn nobody bound says "unknown": that is no channel, not one named "unknown".
    return "" if channel == "unknown" else channel


def off_reason(skill: Any, channel: str | None = None, *, current: dict | None = None) -> str:
    """Why ``skill`` is switched off for a turn on ``channel`` (``"everywhere"`` or
    ``"on <channel>"``), or ``""`` when it is on. No ``channel`` (or not one) means the current
    turn's; ``current`` is a :func:`state` already read (a catalog reads it once)."""
    if is_essential(skill):
        return ""
    try:
        now = state() if current is None else current
    except Exception:
        logger.warning("skill switches unreadable; nonessential skills stay off", exc_info=True)
        return "switches unavailable"
    if now.get("__unavailable__"):
        return "switches unavailable"
    name = _entry(skill)
    if name in {_key(n) for n in now.get(GLOBAL_KEY, [])}:
        return "everywhere"
    where = clean_channel(channel) or current_channel()
    if where and name in {_key(n) for n in now.get(CHANNEL_KEY, {}).get(where, [])}:
        return f"on {where}"
    return ""


def refusal(skill: Any, reason: str) -> str:
    """The reply a command of a switched-off skill gets instead of running."""
    if reason == "switches unavailable":
        return f"[skill:{getattr(skill, 'name', '?')}] switches unavailable until the store is repaired"
    return (f"[skill:{getattr(skill, 'name', '?')}] is switched off {reason}; "
            "the owner can switch it back on in Console → Trust → Skill Switches")


def _without(names: Iterable[str], drop: set[str]) -> list[str]:
    return [n for n in names if _key(n) not in drop]


def plan(skills: list, *, enabled: bool, channel: str, now: dict) -> dict:
    """Compute a switch change without writing it.

    Essential skills are never switched off (they are returned under ``essential``).
    Switching on removes the entries that name the skill (ignoring case): every entry
    when no channel is given, that channel's otherwise; a skill switched on for one
    channel that stays off everywhere is also named under ``off_everywhere`` (review-H329
    F3). A switch-off the rows cannot hold (a name the read drops, or past MAX_NAMES /
    MAX_CHANNELS) is not written and is named under ``unstorable`` (F6). The base is read
    strictly: an unreadable store raises and nothing is written (F7).
    Returns ``{"changed", "unchanged", "essential", "off_everywhere", "unstorable",
    "state", "before"}``, ``state`` being the proposed result."""
    changed: list[str] = []
    unchanged: list[str] = []
    essential: list[str] = []
    off_everywhere: list[str] = []
    unstorable: list[str] = []
    before = {GLOBAL_KEY: list(now[GLOBAL_KEY]), CHANNEL_KEY: {k: list(v) for k, v in now[CHANNEL_KEY].items()}}
    glob = list(now[GLOBAL_KEY])
    chans = {k: list(v) for k, v in now[CHANNEL_KEY].items()}
    for skill in skills:
            name = getattr(skill, "name", "")
            ids = {_entry(skill)}
            target = chans.setdefault(channel, []) if channel else glob
            if not enabled:
                present = bool(ids & {_key(n) for n in target})
                if is_essential(skill):
                    essential.append(name)
                    continue
                if present:
                    unchanged.append(name)
                    continue
                # What the read would drop must not be reported (and recorded) as off.
                full = bool(channel) and not target and sum(1 for names in chans.values() if names) >= MAX_CHANNELS
                if full or len(clean_names([*target, name])) != len(target) + 1:
                    unstorable.append(name)
                    continue
                target.append(name)
                changed.append(name)
                continue
            # On everywhere clears every entry; on for one channel clears that channel's.
            lists = [target] if channel else [glob, *chans.values()]
            still_off = bool(channel) and bool(ids & {_key(n) for n in glob})
            if not any(ids & {_key(n) for n in names} for names in lists):
                (off_everywhere if still_off else unchanged).append(name)
                continue
            for names in lists:
                names[:] = _without(names, ids)
            changed.append(name)
            if still_off:
                off_everywhere.append(name)
    chans = {k: v for k, v in chans.items() if v}
    return {"changed": changed, "unchanged": unchanged, "essential": essential,
            "off_everywhere": off_everywhere, "unstorable": unstorable,
            "state": {GLOBAL_KEY: clean_names(glob), CHANNEL_KEY: clean_channel_map(chans)}, "before": before}


def apply(skills: list, *, enabled: bool, channel: str = "") -> dict:
    """Compatibility entry for narrowing; widening requires an approved task."""
    if enabled:
        raise PermissionError("switch-on requires a human-approved permission.grant task")
    from . import switch_approval

    return switch_approval.disable(skills, channel=channel, actor="owner")


def restore(before: dict, expected: dict) -> bool:
    """Legacy API: restoration could widen access without approval and is refused."""
    raise PermissionError("restoring skill switches requires an approved task")


__all__ = [
    "CATEGORY", "CHANNEL_KEY", "ESSENTIAL_SKILLS", "GLOBAL_KEY", "apply", "bind_turn_channel",
    "channel_map_problem", "clean_channel", "clean_channel_map", "clean_names", "current_channel",
    "identities", "is_essential", "off_reason", "refusal", "reset_turn_channel", "restore", "state",
    "strict_state",
]
