"""H057: bounded native Discord application-command projection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .native_metadata import name_allowed, safe_description

DISCORD_COMMAND_MAX = 100
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


@dataclass(frozen=True)
class Entry:
    name: str
    description: str


@dataclass(frozen=True)
class Projection:
    entries: tuple[Entry, ...]
    hidden_count: int


def project_commands(registry) -> Projection:
    """Project canonical registry commands before any future skill namespace.

    An invalid native name is left out rather than renamed: the interaction must
    dispatch exactly what the registry knows. The hidden count includes both names
    Discord cannot register and valid names beyond its 100-command budget.
    """
    entries = []
    hidden = 0
    for command in registry.commands():
        name = str(command.name).lower()
        if (not _NAME.fullmatch(name) or len(entries) >= DISCORD_COMMAND_MAX
                or not name_allowed(str(command.name), name)):
            hidden += 1
            continue
        description = safe_description(str(command.description or name), 100)
        entries.append(Entry(name, description))
    return Projection(tuple(entries), hidden)
