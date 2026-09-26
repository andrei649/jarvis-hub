"""H285 — the owner declares which skills, plugins and MCP servers load at boot.

Narrowing what loads existed only piecemeal and did not survive a restart: a plugin
toggle flipped an in-memory flag, an MCP server could only be disconnected or deleted,
and a skill could not be switched off at all. Hermes keeps ``skills.disabled``,
``plugins.enabled``/``disabled`` and a per-server ``enabled`` in its config. Nerva keeps
six declared settings rows (category ``loadset``), each a comma list of names:

- ``skills_disabled`` / ``skills_only``;
- ``plugins_disabled`` / ``plugins_only``;
- ``mcp_disabled`` / ``mcp_only``.

A name in ``*_disabled`` does not load; a non-empty ``*_only`` loads only the names it
lists. They are read at boot by the skill loader, the plugin gate and the MCP load,
and the plugin toggle writes them, so a toggle survives a restart. The per-plugin
``plugins.<id>`` switches of the settings page count too: off is off.

The lists only ever take away. A name that is not installed is reported as unknown
and nothing else happens: nothing is installed, approved, registered or written to the
approval store, so a list is never a way around ``skill.install`` or the admin MCP add
route. An MCP server switched off keeps its saved configuration.
"""
from __future__ import annotations

import logging
import threading
import unicodedata

logger = logging.getLogger("jarvis.load_set")

CATEGORY = "loadset"
KINDS = ("skills", "plugins", "mcp")
#: The most names one list holds, and the longest name.
MAX_NAMES = 256
MAX_NAME_CHARS = 128

_lock = threading.Lock()
_skipped: dict[str, set[str]] = {kind: set() for kind in KINDS}
_unknown: dict[str, set[str]] = {kind: set() for kind in KINDS}


def parse_names(raw: object) -> list[str]:
    """A declared list as names: comma- or line-separated, trimmed, de-duplicated in
    order, bounded; a name with a control character is dropped."""
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    elif isinstance(raw, str):
        parts = raw.replace("\n", ",").split(",")
    else:
        return []
    out: list[str] = []
    for part in parts:
        name = part.strip()
        if (not name or len(name) > MAX_NAME_CHARS or name in out
                or any(unicodedata.category(ch).startswith("C") for ch in name)):
            continue
        out.append(name)
        if len(out) >= MAX_NAMES:
            break
    return out


def _setting(key: str) -> object:
    try:
        from .settings_db import get_value

        return get_value(CATEGORY, key, "")
    except Exception:  # noqa: BLE001 - an unreadable store narrows nothing
        logger.warning("load set: settings unreadable; %s not applied", key)
        return ""


def declared(kind: str) -> dict[str, list[str]]:
    """``{"disabled": [...], "only": [...]}`` for *kind*, read now."""
    if kind not in KINDS:
        raise ValueError(f"unknown load-set kind: {kind!r}")
    disabled = parse_names(_setting(f"{kind}_disabled"))
    if kind == "plugins":
        disabled += [name for name in _plugin_switches_off() if name not in disabled]
    return {"disabled": disabled, "only": parse_names(_setting(f"{kind}_only"))}


def _plugin_switches_off() -> list[str]:
    """The settings page's ``plugins.<id>`` switches that are off."""
    try:
        from .settings_db import get_category

        rows = get_category("plugins")
    except Exception:  # noqa: BLE001
        return []
    return [str(row["key"]) for row in rows
            if row.get("kind") == "toggle" and row.get("value") is False]


def permits(kind: str, *names: str, lists: dict | None = None) -> bool:
    """Whether something known by any of *names* may load. Off when any name is in
    the disabled list, or when an only-list is declared and none of them is in it."""
    lists = declared(kind) if lists is None else lists
    named = {n for n in names if n}
    if named & set(lists["disabled"]):
        return False
    return not lists["only"] or bool(named & set(lists["only"]))


def begin(kind: str) -> None:
    """A fresh pass over *kind* (a discovery, a boot): forget what the last one found."""
    with _lock:
        _skipped[kind] = set()
        _unknown[kind] = set()


def note_skipped(kind: str, name: str) -> None:
    with _lock:
        first = name not in _skipped[kind]
        _skipped[kind].add(name)
    if first:
        logger.info("Load set: %s %r is switched off", kind.rstrip("s"), name)


def finish(kind: str, present: set[str], lists: dict | None = None) -> list[str]:
    """Record the declared names that name nothing installed (reported, never acted on)."""
    lists = declared(kind) if lists is None else lists
    unknown = sorted({*lists["disabled"], *lists["only"]} - set(present))
    with _lock:
        _unknown[kind] = set(unknown)
    if unknown:
        logger.warning("Load set: %s names nothing installed: %s", kind, ", ".join(unknown))
    return unknown


def status(kind: str) -> dict:
    """What the status rows show for *kind*: the declared lists, what was switched off
    at the last pass, and the declared names that match nothing installed."""
    lists = declared(kind)
    with _lock:
        return {**lists, "skipped": sorted(_skipped[kind]), "unknown": sorted(_unknown[kind])}


def persist_plugin(plugin_id: str, enabled: bool) -> bool:
    """The plugin toggle, kept across a restart: out of (or into) ``plugins_disabled``,
    into ``plugins_only`` when one is declared, and its own settings switch if it has one."""
    from .settings_db import get_category, put_category

    lists = {"disabled": parse_names(_setting("plugins_disabled")), "only": parse_names(_setting("plugins_only"))}
    disabled = [n for n in lists["disabled"] if n != plugin_id] + ([] if enabled else [plugin_id])
    write = {"plugins_disabled": ",".join(disabled)}
    if enabled and lists["only"] and plugin_id not in lists["only"]:
        write["plugins_only"] = ",".join([*lists["only"], plugin_id])
    updated, skipped = put_category(CATEGORY, write)
    if any(row.get("key") == plugin_id and row.get("kind") == "toggle" for row in get_category("plugins")):
        put_category("plugins", {plugin_id: bool(enabled)})
    return updated == len(write) and not skipped
