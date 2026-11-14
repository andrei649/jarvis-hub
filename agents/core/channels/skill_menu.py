"""Owner-only native picker candidates for installed skill slash commands.

Project only names the ordinary skill slash path will resolve. Channel menus must
still scope these names to the owner; this helper does not grant authority.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..skills import bundles, slash_load, switches
from .native_metadata import name_allowed, safe_description

_NATIVE_NAME = {
    "telegram": re.compile(r"[a-z][a-z0-9_]{0,31}\Z"),
    "discord": re.compile(r"[a-z][a-z0-9_-]{0,31}\Z"),
}
_DESCRIPTION_LIMIT = {"telegram": 256, "discord": 100}
logger = logging.getLogger("jarvis.channels.skill_menu")


@dataclass(frozen=True)
class Entry:
    name: str
    description: str
    skill_name: str


@dataclass(frozen=True)
class Projection:
    entries: tuple[Entry, ...]
    hidden_count: int
    unavailable: bool = False


def project_skill_menu(loader: Any, *, platform: str, slots: int,
                       taken: Callable[[str], bool], reserved: Iterable[str] = ()) -> Projection:
    """Project skill names that are readable and route to exactly one installed skill.

    ``taken`` is the gateway's canonical-command/alias/quick predicate. Bundle
    names precede skills separately. The platform switch is bound for catalog
    checks because a startup/menu callback has no conversation turn to supply it.
    Invalid names are omitted; Telegram's ``-`` to ``_`` rewrite is checked *after*
    rewriting, so the displayed command has the same dispatch identity.
    """
    if platform not in _NATIVE_NAME or type(slots) is not int or slots < 0 or not callable(taken):
        return Projection((), 0, unavailable=True)
    try:
        pool = list((getattr(loader, "skills", None) or {}).values())
        bundle_names = {bundle.slug for bundle in bundles.list_bundles()}
    except (AttributeError, OSError, TypeError):
        return Projection((), 0, unavailable=True)
    entries: list[Entry] = []
    hidden = 0
    collisions = 0
    used = {str(name).lower() for name in reserved}
    token = switches.bind_turn_channel(platform)
    try:
        for skill in sorted(pool, key=lambda item: str(getattr(item, "name", "")).casefold()):
            name = bundles.slugify(getattr(skill, "name", ""))
            wire = name.replace("-", "_") if platform == "telegram" else name
            if (not _NATIVE_NAME[platform].fullmatch(wire) or wire in used
                    or not name_allowed(str(getattr(skill, "name", "")), wire)
                    or bundles.slugify(wire) in bundle_names):
                hidden += 1
                continue
            try:
                if loader.catalog_gate(skill):
                    hidden += 1
                    continue
                if taken(wire) or taken(name):
                    collisions += 1
                    hidden += 1
                    continue
                inv = slash_load.resolve("/" + wire, loader, taken=taken)
                if inv is None or inv.problem or inv.skill_name != skill.name:
                    hidden += 1
                    continue
            except Exception:
                hidden += 1
                continue
            # Telegram has a provider-wide command cap. Discord uses one generic
            # command and may autocomplete any installed skill within its 25
            # choices per response.
            capacity = min(slots, 100) if platform == "telegram" else slots
            if len(entries) >= capacity:
                hidden += 1
                continue
            description = safe_description(str(getattr(skill, "description", "") or skill.name),
                                           _DESCRIPTION_LIMIT[platform])
            entries.append(Entry(wire, description, skill.name))
            used.add(wire)
    finally:
        switches.reset_turn_channel(token)
    if collisions:
        logger.warning("Skill command collision refusals: %d", collisions)
    return Projection(tuple(entries), hidden)
