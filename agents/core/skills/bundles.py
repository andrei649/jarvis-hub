"""H026 — named skill bundles: several skills under one name, switched as one unit.

Hermes keeps ``*.yaml`` files in ``<HERMES_HOME>/skill-bundles/`` (``hermes bundles
list|show|create|delete|reload``), each ``{name, skills[], description?}``, slugged
from the name. Nerva keeps the same files in ``<data root>/skill-bundles/`` with the
same slug rule, so a bundle the owner writes by hand, or copies from Hermes, loads.

A bundle is metadata only. It names skills; it installs nothing, signs nothing and
grants nothing. The one thing it does is let the owner switch its skills off or on as
one unit through the H329 switch (``POST /api/skills/switch`` with ``bundle``), which
is the same path one skill takes: off narrows at once, on queues one exact, once-scoped
human approval for the installed members, and the worker re-checks that the bundle
still means those skills before it widens anything. So a bundle never reaches further
than switching each of its skills one by one would.

Members are skill names. Creating a bundle through the hub resolves each one against
the installed skills (a name or a folder, the manifest name winning, as the switch
does) and stores the name; a member that is not installed later is reported as
missing and skipped by a switch, never matched loosely.

Reads re-scan the folder when a file in it changed (a stat per file); ``reload``
re-reads every file whatever the stat says and reports what was added, removed or
changed since the hub last looked. A file that does not parse, has no name or no
skills, is too large, is a link, or repeats another file's slug is skipped and named
under ``problems``; a broken file never hides the others.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import stat
import tempfile
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import switches

logger = logging.getLogger("jarvis.skills.bundles")

DIR_NAME = "skill-bundles"
MAX_BUNDLES = 64
MAX_MEMBERS = 64
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 200
MAX_FILE_BYTES = 16 * 1024
SUFFIXES = (".yaml", ".yml")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"dir": None, "key": None, "bundles": {}, "problems": []}


class BundleError(ValueError):
    """A refused bundle operation; ``reason`` is the route's machine-readable code."""

    def __init__(self, reason: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.extra = extra


@dataclass(frozen=True)
class Bundle:
    name: str
    slug: str
    skills: tuple[str, ...]
    description: str
    path: Path

    def as_dict(self) -> dict:
        return {"name": self.name, "slug": self.slug, "skills": list(self.skills),
                "description": self.description, "file": str(self.path)}


def bundles_dir() -> Path:
    """The bundles folder under the profile's data root (not created here)."""
    from agents.core.paths import data_path

    return data_path(DIR_NAME)


def slugify(name: Any) -> str:
    """Hermes' slug: lower case, spaces and underscores to ``-``, anything else that is
    not ``[a-z0-9-]`` dropped, runs of ``-`` collapsed, edges trimmed. ``""`` when
    nothing is left or the result is too long to be a file name here."""
    text = str(name or "").strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text if SLUG_RE.fullmatch(text) else ""


def clean_name(value: Any) -> str:
    """A bundle's display name, or raise :class:`BundleError` (``bad_name``)."""
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        raise BundleError("bad_name", "a bundle needs a name")
    if len(name) > MAX_NAME_CHARS or not name.isprintable():
        raise BundleError("bad_name", f"a bundle name is at most {MAX_NAME_CHARS} printable characters")
    if not slugify(name):
        raise BundleError("bad_name", f"bundle name {name!r} has no letter or digit to name its file by")
    return name


def clean_members(value: Any) -> list[str]:
    """The member list as skill names (trimmed, de-duplicated ignoring case), or raise."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BundleError("bad_skills", "a bundle's skills are a list of skill names")
    distinct = {item.strip().casefold() for item in value if item.strip()}
    if not distinct:
        raise BundleError("no_skills", "a bundle must name at least one skill")
    if len(distinct) > MAX_MEMBERS:
        raise BundleError("too_many", f"a bundle names at most {MAX_MEMBERS} skills")
    members = switches.clean_names(value)
    if len(members) != len(distinct):
        raise BundleError("bad_skills", f"a skill name is at most {switches.MAX_NAME_CHARS} printable characters")
    return members


def clean_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BundleError("bad_description", "a bundle's description is text")
    text = " ".join(value.split())
    if len(text) > MAX_DESCRIPTION_CHARS:
        raise BundleError("bad_description", f"a bundle's description is at most {MAX_DESCRIPTION_CHARS} characters")
    return text


# ── reading the folder ───────────────────────────────────────────────────────────

def _entries(directory: Path) -> list[tuple[str, os.stat_result]]:
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(SUFFIXES) and not n.startswith("."))
    except FileNotFoundError:
        return []
    out = []
    for name in names:
        try:
            out.append((name, os.lstat(directory / name)))
        except FileNotFoundError:
            continue
    return out


def _signature(directory: Path) -> tuple:
    try:
        top = os.stat(directory).st_mtime_ns
    except FileNotFoundError:
        return ("absent",)
    return (top, tuple((n, s.st_mtime_ns, s.st_size, s.st_ino) for n, s in _entries(directory)))


def _parse(path: Path, info: os.stat_result) -> Bundle:
    if not stat.S_ISREG(info.st_mode):
        raise BundleError("not_a_file", "not a regular file (a link or a folder is not read)")
    if info.st_size > MAX_FILE_BYTES:
        raise BundleError("too_large", f"{info.st_size:,} bytes; at most {MAX_FILE_BYTES:,}")
    import yaml

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BundleError("unreadable", f"cannot be read ({exc.strerror or exc})") from None
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise BundleError("too_large", f"more than {MAX_FILE_BYTES:,} bytes")
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        raise BundleError("invalid_yaml", "not UTF-8 YAML") from None
    if not isinstance(data, Mapping):
        raise BundleError("invalid_yaml", "not a mapping of name, skills and description")
    name = clean_name(data.get("name"))
    return Bundle(name=name, slug=slugify(name), skills=tuple(clean_members(data.get("skills"))),
                  description=clean_description(data.get("description")), path=path)


def _scan(directory: Path) -> tuple[dict[str, Bundle], list[dict]]:
    bundles: dict[str, Bundle] = {}
    problems: list[dict] = []
    for name, info in _entries(directory):
        try:
            bundle = _parse(directory / name, info)
        except BundleError as exc:
            problems.append({"file": name, "reason": exc.reason, "detail": str(exc)})
            continue
        if bundle.slug in bundles:
            problems.append({"file": name, "reason": "duplicate",
                             "detail": f"{bundles[bundle.slug].path.name} already defines {bundle.slug!r}"})
            continue
        if len(bundles) >= MAX_BUNDLES:
            problems.append({"file": name, "reason": "too_many_bundles",
                             "detail": f"past the {MAX_BUNDLES}-bundle limit"})
            continue
        bundles[bundle.slug] = bundle
    for problem in problems:
        logger.warning("skill bundle %s skipped: %s", problem["file"], problem["detail"])
    return bundles, problems


def _refresh(*, force: bool = False) -> tuple[dict[str, Bundle], dict[str, Bundle], list[dict]]:
    """(previous, current, problems): re-scan when the folder changed, or always when *force*."""
    directory = bundles_dir()
    with _LOCK:
        previous = dict(_CACHE["bundles"]) if _CACHE["dir"] == directory else {}
        key = _signature(directory)
        if not force and _CACHE["dir"] == directory and _CACHE["key"] == key:
            return previous, previous, list(_CACHE["problems"])
        current, problems = _scan(directory)
        _CACHE.update({"dir": directory, "key": key, "bundles": current, "problems": problems})
        return previous, dict(current), list(problems)


def snapshot() -> tuple[list[Bundle], list[dict]]:
    """One consistent read: every loaded bundle (sorted by slug) and the skipped files."""
    _previous, current, skipped = _refresh()
    return [bundle for _slug, bundle in sorted(current.items())], skipped


def list_bundles() -> list[Bundle]:
    """Every loaded bundle, sorted by slug."""
    return snapshot()[0]


def get(name: Any) -> Bundle | None:
    """The bundle *name* names (any casing, spaces or underscores: the slug decides)."""
    slug = slugify(name)
    return _refresh()[1].get(slug) if slug else None


def reload() -> dict:
    """Re-read every file and report what changed since the hub last looked."""
    previous, current, skipped = _refresh(force=True)
    added = [current[s] for s in sorted(set(current) - set(previous))]
    removed = [previous[s] for s in sorted(set(previous) - set(current))]
    changed = sorted(s for s in set(current) & set(previous) if current[s] != previous[s])
    return {"added": [{"name": b.name, "slug": b.slug, "description": b.description} for b in added],
            "removed": [{"name": b.name, "slug": b.slug} for b in removed],
            "changed": changed, "total": len(current), "problems": skipped}


# ── writing ──────────────────────────────────────────────────────────────────────

def _dump(name: str, members: list[str], description: str) -> bytes:
    import yaml

    payload: dict[str, Any] = {"name": name, "skills": list(members)}
    if description:
        payload["description"] = description
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).encode("utf-8")


def save(name: Any, members: Any, *, description: Any = "", overwrite: bool = False) -> tuple[Bundle, bool]:
    """Write one bundle file; ``(bundle, replaced)``. Members must already be the skill
    names the caller resolved (the route resolves them against the installed skills)."""
    name = clean_name(name)
    members = clean_members(members)
    description = clean_description(description)
    slug = slugify(name)
    data = _dump(name, members, description)
    if len(data) > MAX_FILE_BYTES:
        raise BundleError("too_large", f"the bundle file would be more than {MAX_FILE_BYTES:,} bytes")
    directory = bundles_dir()
    with _LOCK:
        _prev, current, _skipped = _refresh(force=True)
        existing = current.get(slug)
        target = existing.path if existing is not None else directory / f"{slug}.yaml"
        if existing is None and len(current) >= MAX_BUNDLES:
            raise BundleError("too_many_bundles", f"at most {MAX_BUNDLES} bundles; delete one first")
        if not overwrite and (existing is not None or os.path.lexists(target)):
            raise BundleError("exists", f"bundle {slug!r} already exists at {target}", path=str(target))
        if os.path.lexists(target) and not stat.S_ISREG(os.lstat(target).st_mode):
            raise BundleError("not_a_file", f"{target} is not a regular file; it is not replaced")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(prefix=f".{slug}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        _prev, current, _skipped = _refresh(force=True)
    bundle = current.get(slug)
    if bundle is None:   # the file it just wrote does not load: never report it as saved
        raise BundleError("write_failed", f"{target} was written but does not load")
    return bundle, existing is not None


def delete(name: Any) -> Bundle:
    """Remove one bundle's file. Its skills and their switches are not touched."""
    with _LOCK:
        _prev, current, _skipped = _refresh(force=True)
        bundle = current.get(slugify(name))
        if bundle is None:
            raise BundleError("not_found", f"no bundle named {str(name)!r}")
        os.unlink(bundle.path)
        _refresh(force=True)
    return bundle


# ── members against the installed skills ─────────────────────────────────────────

def resolve(members: Iterable[str], loaded: Iterable[Any]) -> tuple[list[Any], list[str]]:
    """``(installed skills, member names not installed)`` for a bundle's members, each
    resolved as ``POST /api/skills/switch`` resolves one skill (:func:`switches.find`)."""
    pool = list(loaded)
    targets: list[Any] = []
    missing: list[str] = []
    seen: set[str] = set()
    for member in members:
        skill = switches.find(pool, member)
        if skill is None:
            missing.append(member)
        elif skill.name.casefold() not in seen:
            seen.add(skill.name.casefold())
            targets.append(skill)
    return targets, missing


def describe(bundle: Bundle, loaded: Iterable[Any]) -> dict:
    """The owner-facing row: the bundle plus which members are installed and which not."""
    targets, missing = resolve(bundle.skills, loaded)
    return {**bundle.as_dict(), "installed": [s.name for s in targets], "missing": missing}


__all__ = [
    "Bundle", "BundleError", "MAX_BUNDLES", "MAX_MEMBERS", "bundles_dir", "delete", "describe",
    "get", "list_bundles", "reload", "resolve", "save", "slugify", "snapshot",
]
