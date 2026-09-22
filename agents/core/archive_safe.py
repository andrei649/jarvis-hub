"""archive_safe.py — the one place Nerva unpacks or produces an archive (H503).

Hermes keeps this logic in a single module on purpose: a second transfer surface
that grows its own extractor is exactly how a weaker one ships. Nerva had two — the
backup tar restore and the marketplace zip install — each correct against ``../``
and neither against the rest of the list. Both now call this module, and
``tests/test_archive_safe.py`` fails if any other product module extracts an archive.

Unpacking (``extract_tar`` / ``extract_zip``):

* **Names are normalised before they are trusted.** ``\\`` is folded to ``/`` first,
  so a Windows-authored member cannot smuggle a separator past a POSIX parse; then
  empty, POSIX-absolute, Windows-absolute, UNC, drive-lettered and any ``..`` part
  are refused (:func:`normalize_member`). Every target is also resolved and checked
  inside the destination, which catches a link that already exists there.
* **Directories and regular files only — anything else RAISES.** Symlinks, hardlinks,
  device nodes and fifos are not skipped: a tampered archive fails the import instead
  of restoring a quietly incomplete tree that reports success.
* **Validated before a byte is written.** A pre-scan checks every member (name, type,
  conflicts, count, declared size) so a rejection leaves nothing behind.
* **Bomb caps.** A member-count cap and a total-uncompressed-bytes cap
  (:class:`ArchiveLimits`), the byte budget also clamped to the destination's free
  space. The declared sizes are checked up front and the bytes are counted again while
  streaming, so a member that yields more than it declared is still stopped.

Producing (``atomic_write`` / ``collect_regular_files``):

* ``tarfile.open(path, "w")`` truncates the destination the instant it opens, so a
  failed backup used to leave a truncated archive under a final name. Writes go to a
  sibling temp file, are fsynced, then ``os.replace``d into place.
* The export walk skips symlinks, so a link planted in the tree cannot pull an
  arbitrary file (a key, ``/etc/shadow``) into an archive that leaves the machine.

This module performs file I/O only where a caller points it; it holds no authority of
its own. Who may restore or install is decided by the callers (an admin-guarded
route, the moderation/signature gates, the operator CLI).
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import stat
import tarfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger("jarvis.archive_safe")

_CHUNK = 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")
_MAX_NAME_IN_ERROR = 160


class ArchiveRejected(ValueError):
    """The archive is unsafe or over its limits; nothing from it may be trusted.

    A ``ValueError`` so every existing caller that maps ValueError to a refusal (the
    install-zip route → 400, the backup routes → a failed drill) keeps doing so.
    """


@dataclass(frozen=True)
class ArchiveLimits:
    """Caps against archive bombs: how many members, how many uncompressed bytes."""

    max_members: int
    max_bytes: int


DEFAULT_LIMITS = ArchiveLimits(max_members=10_000, max_bytes=2 * 1024 ** 3)


def _show(name: object) -> str:
    text = repr(name)
    return text if len(text) <= _MAX_NAME_IN_ERROR else text[:_MAX_NAME_IN_ERROR] + "…'"


# ── names ──────────────────────────────────────────────────────────
def normalize_member(name: str, *, allow_root: bool = False) -> tuple[str, ...]:
    """Return the safe relative parts of an archive member name, or raise.

    ``\\`` is folded to ``/`` BEFORE anything else, so ``..\\evil`` is seen as the
    traversal it is on every platform. Refused: empty names, NUL, a leading ``/``
    (POSIX-absolute, and — after the fold — Windows root-relative and UNC), a drive
    prefix (``C:/x``, ``c:x``), an empty interior part and any ``..`` part. ``.`` parts
    are dropped (``./dir/a`` is ``dir/a``). With *allow_root* a name that reduces to
    nothing (a ``./`` directory entry) returns ``()`` — the destination itself.
    """
    if not isinstance(name, str) or not name:
        raise ArchiveRejected(f"empty member name: {_show(name)}")
    if "\x00" in name:
        raise ArchiveRejected(f"NUL in member name: {_show(name)}")
    folded = name.replace("\\", "/")
    if folded.startswith("/"):
        raise ArchiveRejected(f"absolute member name: {_show(name)}")
    if _DRIVE.match(folded):
        raise ArchiveRejected(f"drive-lettered member name: {_show(name)}")
    body = folded.rstrip("/")  # a trailing slash only marks a directory
    if not body:
        raise ArchiveRejected(f"empty member name: {_show(name)}")
    parts: list[str] = []
    for part in body.split("/"):
        if part == "":
            raise ArchiveRejected(f"empty path part in member name: {_show(name)}")
        if part == "..":
            raise ArchiveRejected(f"'..' in member name: {_show(name)}")
        if part == ".":
            continue
        parts.append(part)
    if not parts and not allow_root:
        raise ArchiveRejected(f"member name names the destination itself: {_show(name)}")
    return tuple(parts)


# ── the shared plan: validate everything before writing anything ──
@dataclass(frozen=True)
class _Entry:
    parts: tuple[str, ...]
    kind: str  # "dir" | "file"
    size: int
    ref: object  # the TarInfo / ZipInfo to stream from
    name: str


class _Planner:
    """Accumulates validated entries; raises on the first unsafe one."""

    def __init__(self, dest: Path, limits: ArchiveLimits):
        self.root = dest
        self.limits = limits
        self.budget, self.budget_reason = _byte_budget(dest, limits)
        self.entries: list[_Entry] = []
        self.declared = 0
        self._files: set[tuple[str, ...]] = set()
        self._dirs: set[tuple[str, ...]] = set()

    def add(self, name: str, kind: str, size: int, ref: object) -> None:
        if len(self.entries) >= self.limits.max_members:
            raise ArchiveRejected(
                f"archive has more than {self.limits.max_members} members")
        parts = normalize_member(name, allow_root=(kind == "dir"))
        self._check_conflicts(parts, kind, name)
        if parts:
            _inside(self.root, parts, name)
        if kind == "file":
            self.declared += max(0, int(size))
            if self.declared > self.budget:
                raise ArchiveRejected(
                    f"archive expands past {self.budget} bytes ({self.budget_reason})")
        self.entries.append(_Entry(parts, kind, max(0, int(size)), ref, name))

    def _check_conflicts(self, parts: tuple[str, ...], kind: str, name: str) -> None:
        prefixes = [parts[:i] for i in range(1, len(parts))]
        if any(p in self._files for p in prefixes):
            raise ArchiveRejected(f"member nests under a file member: {_show(name)}")
        if kind == "file":
            if parts in self._files:
                raise ArchiveRejected(f"duplicate file member: {_show(name)}")
            if parts in self._dirs:
                raise ArchiveRejected(f"file member collides with a directory: {_show(name)}")
            self._files.add(parts)
        elif parts:
            if parts in self._files:
                raise ArchiveRejected(f"directory member collides with a file: {_show(name)}")
            self._dirs.add(parts)
        self._dirs.update(prefixes)


def _byte_budget(dest: Path, limits: ArchiveLimits) -> tuple[int, str]:
    """The byte cap, clamped to what the destination filesystem can actually take."""
    budget, reason = int(limits.max_bytes), "the configured bytes cap"
    try:
        free = shutil.disk_usage(dest).free
    except OSError:
        return budget, reason
    if free < budget:
        return int(free), "the free space on the destination, in bytes"
    return budget, reason


def _inside(root: Path, parts: tuple[str, ...], name: str) -> Path:
    """Resolve ``root/parts`` and require it to stay inside *root* (catches links in dest)."""
    target = root.joinpath(*parts).resolve()
    if target == root or root not in target.parents:
        raise ArchiveRejected(f"member resolves outside the destination: {_show(name)}")
    return target


def _write_capped(src: BinaryIO, target: Path, written: int, budget: int, name: str) -> int:
    """Stream *src* to *target*, counting against *budget*; remove the file on overrun."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_TRUNC
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    fd = os.open(target, flags, 0o666)
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > budget:
                    raise ArchiveRejected(
                        f"archive expands past {budget} bytes while streaming {_show(name)}")
                out.write(chunk)
    except BaseException:
        with suppress(OSError):
            target.unlink()
        raise
    return written


def _extract_plan(plan: _Planner, open_member) -> int:
    written = 0
    count = 0
    for entry in plan.entries:
        if not entry.parts:
            continue  # "./" — the destination itself
        target = _inside(plan.root, entry.parts, entry.name)  # re-checked at write time
        if entry.kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _inside(plan.root, entry.parts, entry.name)
        src = open_member(entry)
        if src is None:
            raise ArchiveRejected(f"regular member has no data: {_show(entry.name)}")
        with src:
            written = _write_capped(src, target, written, plan.budget, entry.name)
        count += 1
    return count


def _prepare_dest(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    return dest.resolve()


# ── tar ────────────────────────────────────────────────────────────
def _tar_kind(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "dir"
    if member.isreg():
        return "file"
    if member.issym():
        raise ArchiveRejected(f"symlink member refused: {_show(member.name)}")
    if member.islnk():
        raise ArchiveRejected(f"hardlink member refused: {_show(member.name)}")
    if member.ischr() or member.isblk():
        raise ArchiveRejected(f"device member refused: {_show(member.name)}")
    if member.isfifo():
        raise ArchiveRejected(f"fifo member refused: {_show(member.name)}")
    raise ArchiveRejected(f"unsupported member type {member.type!r}: {_show(member.name)}")


def extract_tar(tar: tarfile.TarFile, dest: Path, *,
                limits: ArchiveLimits = DEFAULT_LIMITS) -> int:
    """Extract *tar* into *dest* (regular files and directories only); return files written.

    Raises :class:`ArchiveRejected` — before writing anything — on an unsafe name, a
    link/device/fifo member, a file/directory conflict or duplicate, or a count or
    byte cap; and while streaming if a member yields more than the byte budget.
    Members are read lazily, so a count bomb stops at ``max_members + 1``.
    """
    root = _prepare_dest(dest)
    plan = _Planner(root, limits)
    for member in tar:  # lazy: TarFile iteration reads one header at a time
        plan.add(member.name, _tar_kind(member), member.size, member)
    return _extract_plan(plan, lambda entry: tar.extractfile(entry.ref))


# ── zip ────────────────────────────────────────────────────────────
_ZIP_ENCRYPTED = 0x1


def _zip_kind(info: zipfile.ZipInfo) -> str:
    mode = (info.external_attr >> 16) & 0xFFFF
    ftype = stat.S_IFMT(mode)
    if ftype == stat.S_IFLNK:
        raise ArchiveRejected(f"symlink entry refused: {_show(info.filename)}")
    if ftype in (stat.S_IFCHR, stat.S_IFBLK):
        raise ArchiveRejected(f"device entry refused: {_show(info.filename)}")
    if ftype == stat.S_IFIFO:
        raise ArchiveRejected(f"fifo entry refused: {_show(info.filename)}")
    if ftype == stat.S_IFSOCK:
        raise ArchiveRejected(f"socket entry refused: {_show(info.filename)}")
    if info.flag_bits & _ZIP_ENCRYPTED:
        raise ArchiveRejected(f"encrypted entry refused: {_show(info.filename)}")
    if info.is_dir() or ftype == stat.S_IFDIR:
        return "dir"
    return "file"


def extract_zip(zf: zipfile.ZipFile, dest: Path, *,
                limits: ArchiveLimits = DEFAULT_LIMITS) -> int:
    """Extract *zf* into *dest* under the same rules as :func:`extract_tar`.

    ``ZipFile.extractall`` is never used: it silently rewrites unsafe names instead
    of refusing them, and writes a symlink entry as a file holding its target path.
    """
    root = _prepare_dest(dest)
    infos = zf.infolist()
    if len(infos) > limits.max_members:
        raise ArchiveRejected(f"archive has more than {limits.max_members} members")
    plan = _Planner(root, limits)
    for info in infos:
        plan.add(info.filename, _zip_kind(info), info.file_size, info)
    return _extract_plan(plan, lambda entry: zf.open(entry.ref, "r"))


# ── producing side ─────────────────────────────────────────────────
@contextmanager
def atomic_write(path: Path, *, mode: int = 0o600) -> Iterator[BinaryIO]:
    """Write *path* all-or-nothing: a sibling temp file, fsynced, then ``os.replace``.

    On any exception the temp file is removed and an existing *path* is untouched —
    a failed backup no longer destroys (or impersonates) a good one. The temp name
    starts with ``.`` and ends ``.tmp-<hex>``, so archive globs never list it. The
    file is created owner-only (*mode*, default ``0o600``).
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    fd = os.open(tmp, flags, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            tmp.unlink()
        raise
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """Best effort: persist the rename itself (POSIX only; a no-op elsewhere)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def is_temp_name(name: str, prefix: str) -> bool:
    """True for an :func:`atomic_write` temp file of an archive named ``prefix…``."""
    return name.startswith("." + prefix) and ".tmp-" in name


def _is_link_like(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse and attributes & reparse)
    except OSError:
        return True


def collect_regular_files(root: Path) -> tuple[list[Path], int]:
    """Every regular file under *root*, sorted, never following a link; plus links skipped.

    The export side of an archive: a symlink (or junction) planted in the tree is
    skipped — neither archived as a link nor followed — so it cannot pull an arbitrary
    file in. *root* itself may be a link (a relocated data root). Unreadable
    directories are skipped with a warning, as the ``rglob`` this replaces did.
    """
    root = Path(root)
    files: list[Path] = []
    skipped = 0
    stack: list[Path] = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            logger.warning("archive export: cannot read a directory; skipped")
            continue
        for entry in entries:
            if _is_link_like(entry):
                skipped += 1
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path))
            except OSError:
                continue
    files.sort(key=lambda p: p.relative_to(root).as_posix())
    return files, skipped

