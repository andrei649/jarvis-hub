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
exactly what the owner needs to see. A stored entry for one is ignored.

Switching off narrows what the hub does and is always allowed. Switching back on widens
it, so it is the owner's act only: the admin route records it in the intent log and
refuses when it cannot (a switch-off that cannot be recorded still applies and says
so). No tool the model is offered writes these rows.

This is not the H285 load set (``loadset.skills_*``), which keeps a skill from being
loaded at all at boot, for a skill that breaks the hub; a switched-off skill is loaded
and listed, only not used.
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger("jarvis.skills.switches")

CATEGORY = "skills"
GLOBAL_KEY = "disabled"
CHANNEL_KEY = "channel_disabled"
#: Skills (folder names) that cannot be switched off.
ESSENTIAL_SKILLS: frozenset[str] = frozenset({"security_monitor"})
MAX_NAMES = 256
MAX_NAME_CHARS = 128
MAX_CHANNELS = 32
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

_WRITE_LOCK = threading.Lock()


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
    """``{"disabled": [...], "channel_disabled": {...}}`` as stored now (cleaned)."""
    from agents.core.settings_db import get_value

    return {
        GLOBAL_KEY: clean_names(get_value(CATEGORY, GLOBAL_KEY, [])),
        CHANNEL_KEY: clean_channel_map(get_value(CATEGORY, CHANNEL_KEY, {})),
    }


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
    return bool(identities(skill) & {_key(n) for n in ESSENTIAL_SKILLS})


def current_channel() -> str:
    """The channel of the turn in progress, or ``""`` outside a bound turn."""
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
        logger.warning("skill switches unreadable; every skill stays on", exc_info=True)
        return ""
    name = _entry(skill)
    if name in {_key(n) for n in now.get(GLOBAL_KEY, [])}:
        return "everywhere"
    where = clean_channel(channel) or current_channel()
    if where and name in {_key(n) for n in now.get(CHANNEL_KEY, {}).get(where, [])}:
        return f"on {where}"
    return ""


def refusal(skill: Any, reason: str) -> str:
    """The reply a command of a switched-off skill gets instead of running."""
    return (f"[skill:{getattr(skill, 'name', '?')}] is switched off {reason}; "
            "the owner can switch it back on in Settings → Skills")


def _without(names: Iterable[str], drop: set[str]) -> list[str]:
    return [n for n in names if _key(n) not in drop]


def apply(skills: list, *, enabled: bool, channel: str = "") -> dict:
    """Switch ``skills`` on or off, everywhere or on ``channel``: one settings write.

    Essential skills are never switched off (they are returned under ``essential``).
    Switching on removes the entries that name the skill (ignoring case): every entry
    when no channel is given, that channel's otherwise.
    Returns ``{"changed", "unchanged", "essential", "state", "before"}``."""
    from agents.core.settings_db import put_category

    changed: list[str] = []
    unchanged: list[str] = []
    essential: list[str] = []
    with _WRITE_LOCK:
        now = state()
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
                target.append(name)
                changed.append(name)
                continue
            # On everywhere clears every entry; on for one channel clears that channel's.
            lists = [target] if channel else [glob, *chans.values()]
            if not any(ids & {_key(n) for n in names} for names in lists):
                unchanged.append(name)
                continue
            for names in lists:
                names[:] = _without(names, ids)
            changed.append(name)
        chans = {k: v for k, v in chans.items() if v}
        if changed:
            updated, skipped = put_category(CATEGORY, {GLOBAL_KEY: glob, CHANNEL_KEY: chans})
            if skipped or updated != 2:
                raise RuntimeError(f"the skill switches could not be saved: {skipped}")
        return {"changed": changed, "unchanged": unchanged, "essential": essential, "state": state(),
                "before": before}


def restore(before: dict, expected: dict) -> bool:
    """Put the switches back to ``before`` if they are still ``expected`` (what one
    :func:`apply` left); a write that landed in between wins. Whether it was put back."""
    from agents.core.settings_db import put_category

    with _WRITE_LOCK:
        if state() != expected:
            return False
        updated, skipped = put_category(CATEGORY, {GLOBAL_KEY: before[GLOBAL_KEY], CHANNEL_KEY: before[CHANNEL_KEY]})
        return not skipped and updated == 2


__all__ = [
    "CATEGORY", "CHANNEL_KEY", "ESSENTIAL_SKILLS", "GLOBAL_KEY", "apply", "channel_map_problem",
    "clean_channel", "clean_channel_map", "clean_names", "current_channel", "identities",
    "is_essential", "off_reason", "refusal", "restore", "state",
]
