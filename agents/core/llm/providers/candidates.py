"""Inert, bounded model-provider candidate metadata discovery.

Only explicit roots and explicitly supplied entry-point metadata are inspected.
No package or provider module is imported; ``EntryPoint.load`` is never called.
The v1 ``provider.json`` schema is exactly ``schema_version``, ``id``,
``aliases``, and optional ``replacement_target``. It cannot declare trust,
credentials, profiles, hooks, or paths. A manifest digest binds these metadata
bytes only; it is not a package signature or code admission.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MAX_ENTRIES = 128
MAX_MANIFEST_BYTES = 16_384
ENTRY_POINT_GROUP = "nerva.model_providers"
_IDENTITY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_SOURCES = frozenset({"pip", "bundled", "legacy", "user"})


def _identity(value: object) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise ValueError("invalid candidate identity")
    return value


@dataclass(frozen=True)
class Candidate:
    """Untrusted inventory record; never a runnable ProviderProfile."""

    id: str
    aliases: tuple[str, ...]
    source: str
    home: str | None
    digest: str | None
    replacement_target: str | None
    root: Path | None = None
    directory: str | None = None
    entry_point_value: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id)
        if self.source not in _SOURCES:
            raise ValueError("invalid candidate source")
        aliases = tuple(_identity(alias) for alias in self.aliases)
        if len(set(aliases)) != len(aliases) or self.id in aliases or len(aliases) > 32:
            raise ValueError("invalid candidate aliases")
        object.__setattr__(self, "aliases", aliases)
        if self.replacement_target is not None:
            _identity(self.replacement_target)
        if self.source == "user":
            if type(self.home) is not str or not self.home or len(self.home) > 256:
                raise ValueError("user candidate requires a bounded home")
        elif self.home is not None:
            raise ValueError("only user candidates have a home")
        if self.source == "pip":
            if self.digest is not None or self.root is not None or self.directory is not None:
                raise ValueError("entry-point metadata has no byte-bound admission")
            if type(self.entry_point_value) is not str or not self.entry_point_value:
                raise ValueError("entry-point value required")
        else:
            if (type(self.digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.digest)
                    or self.root is None or self.directory is None
                    or not self.directory or self.directory in {".", ".."}
                    or "/" in self.directory or "\\" in self.directory
                    or self.entry_point_value is not None):
                raise ValueError("invalid rooted candidate snapshot")
            object.__setattr__(self, "root", Path(self.root))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _manifest_fields(raw: bytes) -> tuple[str, tuple[str, ...], str | None]:
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid candidate JSON") from exc
    if (type(data) is not dict or set(data) - {"schema_version", "id", "aliases", "replacement_target"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or type(data.get("aliases")) is not list):
        raise ValueError("invalid candidate manifest schema")
    provider_id = _identity(data.get("id"))
    aliases = tuple(_identity(alias) for alias in data["aliases"])
    if len(aliases) > 32 or len(set(aliases)) != len(aliases) or provider_id in aliases:
        raise ValueError("invalid candidate aliases")
    target = data.get("replacement_target")
    if target is not None:
        _identity(target)
    return provider_id, aliases, target


def _open_directory(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if dir_fd is not None:
        name = str(path)
        if name in {"", ".", ".."} or "/" in name or "\\" in name:
            raise ValueError("candidate directory escapes root")
        try:
            return os.open(name, flags, dir_fd=dir_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ValueError("candidate root contains a symlink or non-directory") from exc

    root = Path(path)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("candidate root must be an absolute path without traversal")
    try:
        current_fd = os.open(root.anchor, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError("candidate root contains a symlink or non-directory") from exc
    try:
        for component in root.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise ValueError("candidate root contains a symlink or non-directory") from exc
            os.close(current_fd)
            current_fd = next_fd
        result = current_fd
        current_fd = -1
        return result
    finally:
        if current_fd != -1:
            os.close(current_fd)


def _read_manifest(root: Path, directory: str) -> bytes:
    """Read an immediate child manifest through no-follow directory descriptors."""
    if not directory or directory in {".", ".."} or "/" in directory or "\\" in directory:
        raise ValueError("candidate directory escapes root")
    root_fd = _open_directory(root)
    try:
        child_fd = _open_directory(directory, dir_fd=root_fd)
        try:
            try:
                file_fd = os.open("provider.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=child_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise ValueError("candidate manifest is a symlink or unreadable") from exc
            try:
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
                    raise ValueError("candidate manifest is not a bounded regular file")
                chunks = []
                remaining = MAX_MANIFEST_BYTES + 1
                while remaining:
                    chunk = os.read(file_fd, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
                if len(raw) > MAX_MANIFEST_BYTES:
                    raise ValueError("candidate manifest exceeds size limit")
                return raw
            finally:
                os.close(file_fd)
        finally:
            os.close(child_fd)
    finally:
        os.close(root_fd)


def candidate_bytes_match(candidate: Candidate) -> bool:
    """Recheck exact manifest bytes at resolution and every view lookup."""
    if candidate.digest is None or candidate.root is None or candidate.directory is None:
        return False
    try:
        raw = _read_manifest(candidate.root, candidate.directory)
    except (OSError, ValueError):
        return False
    if hashlib.sha256(raw).hexdigest() != candidate.digest:
        return False
    try:
        provider_id, aliases, target = _manifest_fields(raw)
    except ValueError:
        return False
    return (provider_id == candidate.id and aliases == candidate.aliases
            and target == candidate.replacement_target)


def _root_candidates(root: Path | None, source: str, home: str | None) -> list[Candidate]:
    if root is None:
        return []
    root = Path(root)
    try:
        root_fd = _open_directory(root)
    except FileNotFoundError:
        return []
    try:
        names = []
        with os.scandir(root_fd) as scanner:
            for entry in scanner:
                if len(names) >= MAX_ENTRIES:
                    raise ValueError("candidate root entry count exceeds limit")
                names.append(entry.name)
        directories = []
        for name in sorted(names):
            info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("candidate root contains a symlink")
            if stat.S_ISDIR(info.st_mode):
                directories.append(name)
    finally:
        os.close(root_fd)
    found = []
    for directory in directories:
        try:
            raw = _read_manifest(root, directory)
        except FileNotFoundError:
            continue
        provider_id, aliases, target = _manifest_fields(raw)
        found.append(Candidate(provider_id, aliases, source, home,
                               hashlib.sha256(raw).hexdigest(), target, root, directory))
    return found


def discover_candidates(*, bundled_root: Path | None = None,
                        legacy_root: Path | None = None,
                        user_root: Path | None = None, home: str | None = None,
                        entry_points: Iterable[object] = ()) -> tuple[Candidate, ...]:
    """Enumerate supplied metadata only; no ambient scan, import, or activation.

    Source order is pip, bundled, legacy, user. ``entry_points`` must be
    supplied by a caller; pip metadata has no package-byte proof and can never
    be admitted by this substrate.
    """
    if user_root is not None and (type(home) is not str or not home or len(home) > 256):
        raise ValueError("explicit user root requires a bounded home")
    found: list[Candidate] = []
    for index, point in enumerate(entry_points):
        if index >= MAX_ENTRIES:
            raise ValueError("entry-point metadata count exceeds limit")
        if getattr(point, "group", None) != ENTRY_POINT_GROUP:
            continue
        name = _identity(getattr(point, "name", None))
        value = getattr(point, "value", None)
        if type(value) is not str or not value or len(value) > 512:
            raise ValueError("invalid entry-point metadata")
        found.append(Candidate(name, (), "pip", None, None, None,
                               entry_point_value=value))
    found.extend(_root_candidates(bundled_root, "bundled", None))
    found.extend(_root_candidates(legacy_root, "legacy", None))
    found.extend(_root_candidates(user_root, "user", home))
    if len(found) > MAX_ENTRIES:
        raise ValueError("candidate count exceeds limit")
    return tuple(found)
