"""H328 — when a skill is shown: the host it runs on, the environment, the channel and
the tools this turn is offered.

A SKILL.md can say where it makes sense (H327 keeps the fields): ``platforms`` (the
operating systems it works on), ``environments`` (``docker``, ``s6``, ``kanban`` ...),
``metadata.hermes.session_platforms`` (the channels it is meant for) and
``metadata.hermes.requires_tools`` / ``requires_toolsets`` / ``fallback_for_tools`` /
``fallback_for_toolsets`` (the tools it needs, or the tools it stands in for). Hermes
reads them as four gates split in two, and so does Nerva:

- **hard** — ``platforms``: a skill for another operating system is *unsupported*
  here. It is left out of every offer, ``skill_view`` answers ``skill_unsupported``
  with ``readiness_status: unsupported``, and a command naming it is refused. A skill
  that declares no platforms is supported everywhere; on Termux the host counts as
  ``linux`` and ``android``.
- **soft** — the other three only hide the skill from what the model is offered (the
  prompt catalog and ``skills_list``). Named explicitly (``skill_view``, a command),
  it still works: an explicit request is explicit consent, and a gate must never
  become a capability removal nobody can see.

  * ``environments``: shown only where one of them holds. ``docker`` / ``container``
    (``/.dockerenv``, ``/run/.containerenv``), ``s6`` (``/run/s6``,
    ``/command/s6-svscan``), ``kanban`` (a turn with no human in it: a job, a
    workflow, the heartbeat), and any tag the owner lists in
    ``JARVIS_SKILL_ENVIRONMENTS``.
  * ``session_platforms``: shown only on the channels named (``cli`` names the
    operator channels, the HUD and voice); a turn bound to no channel is not gated.
  * ``requires_*``: hidden unless every named tool (or one tool of every named
    toolset) is offered this turn; ``fallback_for_*``: hidden while the tools it stands
    in for are offered. When the offer cannot be read, these two are not applied.

Every hide is logged once per skill and reason. Nothing here enables a skill or a
tool: it only narrows what is shown.
"""
from __future__ import annotations

import contextvars
import logging
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.skills.visibility")

HARD_GATES = frozenset({"unsupported"})
SOFT_GATES = frozenset({"environment", "channel", "tools"})
ENV_OVERRIDE = "JARVIS_SKILL_ENVIRONMENTS"
#: Hermes toolset names → the Nerva tools that provide them (one is enough).
TOOLSETS: dict[str, tuple[str, ...]] = {
    "web": ("web_search", "web_extract"),
    "search": ("web_search",),
    "terminal": ("terminal_run",),
    "file": ("file_read", "file_list", "file_search", "file_write", "file_delete"),
    "files": ("file_read", "file_list", "file_search", "file_write", "file_delete"),
    "code_execution": ("execute_code",),
    "image_gen": ("image_generate",),
    "memory": ("memory",),
    "todo": ("todo",),
    "tts": ("speak",),
    "session_search": ("session_search",),
    "skills": ("skills_list", "skill_view"),
    "desktop": ("desktop_plan", "desktop_run"),
    "basic": ("echo", "time"),
}
_SYS_PLATFORMS = (("darwin", "macos"), ("linux", "linux"), ("win", "windows"))
_CLI_ALIAS = "cli"
#: The tools this turn is offered, bound around the prompt catalog (None: unknown).
_OFFER: contextvars.ContextVar = contextvars.ContextVar("nerva_skill_offer", default=None)
_logged: set[tuple[str, str]] = set()
_logged_lock = threading.Lock()


def _termux() -> bool:
    from agents.core.env_config import env_str

    return "com.termux" in env_str("PREFIX") or Path("/data/data/com.termux").is_dir()


def host_platforms(platform: str | None = None) -> frozenset[str]:
    """The operating-system names a ``platforms:`` entry may use for this host."""
    sys_platform = (platform if platform is not None else sys.platform).lower()
    names = {nerva for prefix, nerva in _SYS_PLATFORMS if sys_platform.startswith(prefix)}
    if platform is None and _termux():
        names |= {"linux", "android"}
    return frozenset(names)


def readiness(skill: Any, *, host: frozenset[str] | None = None) -> tuple[str, str]:
    """``("ready", "")``, or ``("unsupported", why)`` when the skill declares only
    other operating systems."""
    declared = [p for p in (getattr(skill, "platforms", None) or []) if isinstance(p, str)]
    if not declared:
        return "ready", ""
    here = host_platforms() if host is None else host
    if here & set(declared):
        return "ready", ""
    on = "/".join(sorted(here)) or sys.platform
    return "unsupported", f"unsupported on {on} (it declares {', '.join(declared)})"


def host_environments() -> frozenset[str]:
    """The environment tags that hold for this process (the turn adds ``kanban``)."""
    tags: set[str] = set()
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        tags |= {"docker", "container"}
    if Path("/run/s6").is_dir() or Path("/command/s6-svscan").exists():
        tags.add("s6")
    from agents.core.env_config import env_str

    extra = env_str(ENV_OVERRIDE)
    tags |= {part.strip().lower() for part in extra.split(",") if part.strip()}
    return frozenset(tags)


def bind_offer(tools) -> contextvars.Token:
    """Bind the tools this turn is offered (a set of names, or None when unknown)."""
    return _OFFER.set(None if tools is None else frozenset(tools))


def reset_offer(token: contextvars.Token) -> None:
    _OFFER.reset(token)


def current_offer() -> frozenset[str] | None:
    """The tools this turn is offered: bound around the catalog, or the tool loop's own
    offer inside it (``skills_list``), or None when neither is known."""
    offer = _OFFER.get()
    if offer is not None:
        return offer
    try:
        from agents.core.autonomy_coordinator import _TURN_TOOL_OFFER

        loop_offer = _TURN_TOOL_OFFER.get()
    except Exception:
        return None
    return None if loop_offer is None else frozenset(loop_offer)


def context(*, channel: str | None = None, environments: frozenset[str] | None = None,
            offered_tools: frozenset[str] | None = None, host: frozenset[str] | None = None) -> dict:
    """What the gates read, taken once for a catalog: the turn's channel (``""`` when
    none), the environment tags, the tools offered (None when unknown) and the host."""
    from .switches import current_channel

    turn_channel = current_channel() if channel is None else str(channel or "").strip().lower()
    envs = host_environments() if environments is None else frozenset(environments)
    if _unattended():
        envs = envs | {"kanban"}
    return {"channel": turn_channel, "environments": envs,
            "offered_tools": current_offer() if offered_tools is None else frozenset(offered_tools),
            "host": host_platforms() if host is None else host}


def _unattended() -> bool:
    """A turn with no human at the keyboard (a job, a workflow, the heartbeat)."""
    try:
        from agents.core.action_origin import current_action_origin
        from agents.core.orchestrator import current_principal
        from agents.core.tool_profiles import SURFACE_INTERNAL, classify_turn

        return classify_turn(current_principal(), current_action_origin()).surface == SURFACE_INTERNAL
    except Exception:
        return False


def _names(skill: Any, key: str) -> list[str]:
    meta = getattr(skill, "hermes_meta", None) or {}
    value = meta.get(key) if isinstance(meta, dict) else None
    return [str(v).strip().lower() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _toolset_offered(name: str, offered: frozenset[str]) -> bool:
    return any(tool in offered for tool in TOOLSETS.get(name, ()))


def offer_gate(skill: Any, ctx: dict) -> str:
    """The soft gate that hides ``skill`` from this turn's offer (``environment``,
    ``channel`` or ``tools``), or ``""``."""
    wanted_envs = [e for e in (getattr(skill, "environments", None) or []) if isinstance(e, str)]
    if wanted_envs and not set(wanted_envs) & set(ctx.get("environments") or ()):
        return "environment"
    channels = _names(skill, "session_platforms")
    channel = ctx.get("channel") or ""
    if channels and channel:
        from agents.core.action_origin import OPERATOR_TURN_CHANNELS

        if channel not in channels and not (_CLI_ALIAS in channels and channel in OPERATOR_TURN_CHANNELS):
            return "channel"
    offered = ctx.get("offered_tools")
    if offered is not None:
        offered = frozenset(offered)
        if any(tool not in offered for tool in _names(skill, "requires_tools")):
            return "tools"
        if any(not _toolset_offered(ts, offered) for ts in _names(skill, "requires_toolsets")):
            return "tools"
        if any(tool in offered for tool in _names(skill, "fallback_for_tools")):
            return "tools"
        if any(_toolset_offered(ts, offered) for ts in _names(skill, "fallback_for_toolsets")):
            return "tools"
    return ""


def note_hidden(skill: Any, gate: str) -> None:
    """Log a hide once per skill and gate, so a skill never leaves the offer silently."""
    key = (str(getattr(skill, "name", "")), gate)
    with _logged_lock:
        if key in _logged:
            return
        _logged.add(key)
    logger.info("Skill '%s' is not offered to the model on this turn: %s gate", key[0], gate)


__all__ = [
    "ENV_OVERRIDE", "HARD_GATES", "SOFT_GATES", "TOOLSETS", "bind_offer", "context", "current_offer",
    "host_environments", "reset_offer",
    "host_platforms", "note_hidden", "offer_gate", "readiness",
]
