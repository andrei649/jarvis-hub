"""Bounded, owner-only metadata projection for the web command picker.

This module never loads a skill or invokes a command. The only source-derived
strings returned are validated names; descriptions and usage are fixed text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from . import quick_commands, settings_db
from .channels.native_metadata import name_allowed
from .commands import ALIASES, CommandRegistry
from .skills import bundles, slash_load, switches

MAX_ROWS = 256
MAX_SKILL_CANDIDATES = 512
_QUICK = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SKILL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_BUNDLE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
logger = logging.getLogger("jarvis.commands.shortcuts")


@dataclass(frozen=True)
class Projection:
    rows: list[dict]
    truncated: bool = False
    unavailable: bool = False


def _row(kind: str, name: str, command: str) -> dict:
    return {"kind": kind, "name": name, "command": command,
            "description": {"quick": "Quick command", "skill": "Skill",
                            "bundle": "Skill bundle"}[kind],
            "tier": "admin", "usage": "[args]" if kind == "quick" else "[instruction]"}


def _quick_inventory() -> dict[str, Any]:
    raw = settings_db.get_value("commands", "quick_commands", {})
    if quick_commands.configuration_problem(raw) is not None:
        raise ValueError("invalid quick command inventory")
    return raw


def project(registry: CommandRegistry, loader: Any, *, slots: int) -> Projection:
    """Return executable owner shortcuts, with registry/alias precedence reserved.

    The 512-skill ceiling bounds the resolver's full-pool scan for every skill.
    Above that ceiling no skill is advertised: a partial pool could conceal an
    ambiguity. Bundle and quick failures are isolated, except that skills need
    both inventories to establish their namespace and precedence.
    """
    rows: list[dict] = []
    unavailable = False
    truncated = False
    slots = max(0, min(MAX_ROWS, slots))

    try:
        quick = _quick_inventory()
        quick_names = {name.lower() for name in quick}
    except Exception:
        quick = None
        quick_names = set()
        unavailable = True

    try:
        stored, problems = bundles.snapshot()
        if len(stored) > bundles.MAX_BUNDLES:
            raise ValueError("oversized bundle inventory")
        unavailable |= bool(problems)
        bundle_names = {bundle.slug for bundle in stored}
    except Exception:
        stored = None
        bundle_names = set()
        unavailable = True

    def taken(name: str) -> bool:
        word = name.lower()
        return (word == "nerva" or word in ALIASES or registry.get(word) is not None
                or word in quick_names)

    if quick is not None:
        for raw in sorted(quick, key=str.lower):
            name = raw.lower()
            if not _QUICK.fullmatch(name) or not name_allowed(raw, name) or taken_by_registry(name, registry):
                continue
            if len(rows) >= slots:
                truncated = True
                break
            rows.append(_row("quick", name, f"/{name}"))

    if stored is not None:
        for bundle in stored:
            name = bundle.slug
            if (not isinstance(name, str) or not _BUNDLE.fullmatch(name)
                    or bundles.slugify(bundle.name) != name
                    or not name_allowed(bundle.name, name)):
                continue
            if len(rows) >= slots:
                truncated = True
                break
            rows.append(_row("bundle", name, f"/bundle {name}"))

    # Skills require both inventories. An unavailable source could hide a name
    # that would take precedence at dispatch, so no skill is guessed in that case.
    if quick is None or stored is None:
        return Projection(rows, truncated, unavailable)
    if loader is None:
        return Projection(rows, truncated, True)
    try:
        skills = loader.skills
        if not isinstance(skills, dict):
            raise TypeError("skill inventory unavailable")
        if len(skills) > MAX_SKILL_CANDIDATES:
            return Projection(rows, True, True)
        pool = sorted(skills.values(), key=lambda item: str(getattr(item, "name", "")).casefold())
    except Exception:
        return Projection(rows, truncated, True)

    used: set[str] = set()
    collisions = 0
    try:
        token = switches.bind_turn_channel("web")
    except Exception:
        return Projection(rows, truncated, True)
    try:
        for skill in pool:
            try:
                raw = skill.name
                name = bundles.slugify(raw)
                if (not isinstance(raw, str) or not _SKILL.fullmatch(name)
                        or not name_allowed(raw, name) or name in bundle_names
                        or name in used):
                    continue
                if taken(name):
                    collisions += 1
                    continue
                if loader.catalog_gate(skill):
                    continue
                inv = slash_load.resolve("/" + name, loader, taken=taken)
                if inv is None or inv.problem or inv.skill_name != raw:
                    continue
            except Exception:
                unavailable = True
                continue
            used.add(name)
            if len(rows) >= slots:
                truncated = True
                break
            rows.append(_row("skill", name, f"/{name}"))
    finally:
        switches.reset_turn_channel(token)
    if collisions:
        logger.warning("Skill command collision refusals: %d", collisions)
    return Projection(rows, truncated, unavailable)


def taken_by_registry(name: str, registry: CommandRegistry) -> bool:
    return name == "nerva" or name in ALIASES or registry.get(name) is not None
