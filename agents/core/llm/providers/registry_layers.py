"""Immutable, inert effective view of byte-bound provider candidates.

The caller supplies trusted ``AdmissionSnapshot`` objects from a future signed
promotion authority. This module never creates trust from manifest data and is
not wired to runtime transport, selection, credentials, or hook execution.
External admission defaults to empty. The existing duplicate-refusing
``ProviderRegistry`` remains the authority for reviewed builtin declarations.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from . import ProviderProfile, ProviderRegistry
from .candidates import Candidate, candidate_bytes_match

_IDENTITY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RANK = {"pip": 0, "bundled": 1, "legacy": 2, "user": 3}


@dataclass(frozen=True)
class AdmissionSnapshot:
    """Trusted input contract; exact candidate bytes, identity, scope, target.

    A future signer/approval store must construct and validate these records.
    Merely constructing one here does not install or activate provider code.
    Pip entry-point metadata lacks exact package bytes and cannot be admitted.
    """

    provider_id: str
    source: str
    home: str | None
    digest: str
    replacement_target: str | None

    def __post_init__(self) -> None:
        if type(self.provider_id) is not str or not _IDENTITY.fullmatch(self.provider_id):
            raise ValueError("invalid admission provider identity")
        if self.source not in {"bundled", "legacy", "user"}:
            raise ValueError("source has no byte-bound admission")
        if self.source == "user":
            if type(self.home) is not str or not self.home or len(self.home) > 256:
                raise ValueError("user admission requires a bounded home")
        elif self.home is not None:
            raise ValueError("non-user admission cannot own a home")
        if type(self.digest) is not str or not _DIGEST.fullmatch(self.digest):
            raise ValueError("invalid admission digest")
        if (self.replacement_target is not None
                and (type(self.replacement_target) is not str
                     or not _IDENTITY.fullmatch(self.replacement_target)
                     or self.replacement_target != self.provider_id)):
            raise ValueError("replacement target must name the exact canonical ID")


@dataclass(frozen=True)
class RegistryEntry:
    """Effective metadata entry. An external entry has no runnable profile."""

    id: str
    aliases: tuple[str, ...]
    source: str
    profile: ProviderProfile | None = None
    candidate: Candidate | None = None
    admission: AdmissionSnapshot | None = None


@dataclass(frozen=True, init=False)
class LayeredRegistry:
    """Snapshot precedence: builtin, pip, bundled, legacy, then scoped user.

    Last admitted writer within a layer wins. Aliases are rebuilt only from
    winners. ``get``/``canonical_id``/``list`` recheck bytes and optional live
    revocation callback; a stale view fails closed and must be rebuilt by its
    trusted caller. It never changes saved provider/model or credential owner.
    """

    _entries: Mapping[str, RegistryEntry] = field(repr=False)
    _aliases: Mapping[str, str] = field(repr=False)
    _is_live: Callable[[AdmissionSnapshot], bool] = field(repr=False)

    def __init__(self, builtins: Iterable[ProviderProfile],
                 candidates: Iterable[Candidate] = (), *,
                 admissions: Iterable[AdmissionSnapshot] = (), home: str | None = None,
                 is_live: Callable[[AdmissionSnapshot], bool] | None = None) -> None:
        # Preserve the core's duplicate guard; never relax its register method.
        core = ProviderRegistry(tuple(builtins))
        entries = {
            profile.id: RegistryEntry(profile.id, profile.aliases, "builtin", profile=profile)
            for profile in core.list()
        }
        approvals = frozenset(admissions)
        live = is_live if is_live is not None else lambda _admission: True
        if not callable(live):
            raise ValueError("is_live must be a callback")
        ordered = sorted(enumerate(tuple(candidates)), key=lambda row: (_RANK[row[1].source], row[0]))
        for _, candidate in ordered:
            if candidate.source == "pip" or (candidate.source == "user" and candidate.home != home):
                continue
            admission = AdmissionSnapshot(candidate.id, candidate.source, candidate.home,
                                          candidate.digest, candidate.replacement_target)
            if (admission not in approvals or live(admission) is not True
                    or not candidate_bytes_match(candidate)):
                continue
            existing = candidate.id in entries
            if existing and candidate.replacement_target != candidate.id:
                continue
            if not existing and candidate.replacement_target is not None:
                continue
            entries[candidate.id] = RegistryEntry(candidate.id, candidate.aliases,
                                                  candidate.source, candidate=candidate,
                                                  admission=admission)
        aliases: dict[str, str] = {}
        for entry in entries.values():
            for alias in entry.aliases:
                if alias in entries or alias in aliases:
                    raise ValueError(f"alias collision: {alias}")
                aliases[alias] = entry.id
        object.__setattr__(self, "_entries", MappingProxyType(entries))
        object.__setattr__(self, "_aliases", MappingProxyType(aliases))
        object.__setattr__(self, "_is_live", live)

    def _available(self, entry: RegistryEntry) -> bool:
        if entry.admission is None:
            return True
        return (self._is_live(entry.admission) is True
                and entry.candidate is not None
                and candidate_bytes_match(entry.candidate))

    def canonical_id(self, provider_id: str) -> str:
        key = str(provider_id or "").strip().lower()
        # Exact canonical IDs always precede aliases.
        key = key if key in self._entries else self._aliases.get(key, key)
        entry = self._entries.get(key)
        if entry is None or not self._available(entry):
            raise KeyError(f"unknown or inactive provider candidate: {key}")
        return key

    def get(self, provider_id: str) -> RegistryEntry:
        return self._entries[self.canonical_id(provider_id)]

    def list(self) -> list[RegistryEntry]:
        return [entry for entry in self._entries.values() if self._available(entry)]
