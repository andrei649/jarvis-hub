"""archive_safe.py — the one place Nerva unpacks or produces an archive (H503).

Hermes keeps this logic in a single module on purpose: a second transfer surface
that grows its own extractor is exactly how a weaker one ships. Nerva had two — the
backup tar restore and the marketplace zip install — each correct against ``../``
and neither against the rest of the list. Both now call this module, and
``tests/test_archive_safe.py`` fails if any other product module opens an archive for
reading or calls an extract-family method.

Unpacking (``extract_tar`` / ``extract_tar_path`` / ``extract_zip`` / ``extract_zip_bytes``):

* **Names are normalised before they are trusted.** ``\\`` is folded to ``/`` first,
  so a Windows-authored member cannot smuggle a separator past a POSIX parse; then
  empty, POSIX-absolute, Windows-absolute, UNC, drive-lettered and any ``..`` part
  are refused (:func:`normalize_member`).
* **Directories and regular files only — anything else RAISES.** Symlinks, hardlinks,
  device nodes, fifos and sparse members are not skipped: a tampered archive fails the
  import instead of restoring a quietly incomplete tree that reports success.
* **Validated before a byte is written.** A pre-scan checks every member (name, type,
  conflicts, count, declared size) and what already exists in the destination, and reads
  the stream to its end (so a gzip CRC or a corrupt header is seen) — so a rejection
  leaves nothing behind. :attr:`ArchiveRejected.partial` says when a failure came after
  the first write instead (a read error mid-stream), so a caller never claims "nothing
  restored" when that is not true.
* **Existing content is replaced, never written through.** A path is never followed
  through a link that already exists in the destination: a link on the way to a member
  is refused; a link, a hardlinked name or a special file AT a file member's name is
  unlinked and the file created fresh (``O_EXCL | O_NOFOLLOW``). A directory where a file
  goes, or a file where a directory goes, is refused in the pre-scan.
* **Bomb caps.** A member-count cap and a total-uncompressed-bytes cap
  (:class:`ArchiveLimits`). The byte budget is also clamped to the destination's free
  space, crediting the bytes of the files the archive replaces (so an in-place restore
  of a large data root still fits). Declared sizes are checked up front and bytes are
  counted again while streaming. Tar header payloads (PAX records, GNU long names) are
  capped before tarfile reads them into memory (:class:`_GuardedTarInfo`).

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

import errno
import gzip
import io
import logging
import os
import re
import secrets
import shutil
import stat
import tarfile
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger("jarvis.archive_safe")

_CHUNK = 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")
_MAX_NAME_IN_ERROR = 160

# Tar header payloads — PAX records and GNU long names/links — are read whole into memory
# by tarfile BEFORE a member exists to check. A real one is a few hundred bytes; these
# caps keep a tiny compressed archive from declaring gigabytes of "header".
_MAX_HEADER_PAYLOAD = 1024 * 1024
_MAX_HEADER_TOTAL = 256 * 1024 * 1024
# Zeros after the end-of-archive marker are record padding (10 KiB for tarfile and GNU
# tar's default); anything non-zero there, or more than this much, is not a clean end.
_MAX_TRAILING_PADDING = 64 * 1024 * 1024

# What a damaged stream raises from tarfile / gzip / zlib / zipfile while it is read.
_CORRUPT = (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile, zipfile.BadZipFile)


class ArchiveRejected(ValueError):
    """The archive is unsafe, corrupt or over its limits; nothing from it may be trusted.

    A ``ValueError`` so every existing caller that maps ValueError to a refusal (the
    install-zip route → 400, the backup routes → a failed drill) keeps doing so.

    ``partial`` is False when the rejection came before the first write (the pre-scan),
    True when extraction had already changed the destination (a read error mid-stream,
    or the destination changing underneath it).
    """

    def __init__(self, message: str, *, partial: bool = False):
        super().__init__(message)
        self.partial = partial


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


def _freed_by_unlink(st: os.stat_result) -> int:
    """Bytes the filesystem gets back when this (single-link) file is replaced."""
    blocks = getattr(st, "st_blocks", None)
    return int(blocks) * 512 if blocks is not None else int(st.st_size)


class _Planner:
    """Accumulates validated entries; raises on the first unsafe one."""

    def __init__(self, dest: Path, limits: ArchiveLimits):
        self.root = dest
        self.limits = limits
        self.cap = int(limits.max_bytes)
        self.free = _free_space(dest)
        self.reclaimable = 0  # bytes of existing files that members will replace
        self.budget, self.budget_reason = self.cap, "the configured bytes cap"
        self.entries: list[_Entry] = []
        self.declared = 0
        self._files: set[tuple[str, ...]] = set()
        self._dirs: set[tuple[str, ...]] = set()
        self._real_dirs: set[tuple[str, ...]] = set()  # verified directories already in dest

    def add(self, name: str, kind: str, size: int, ref: object) -> None:
        if len(self.entries) >= self.limits.max_members:
            raise ArchiveRejected(
                f"archive has more than {self.limits.max_members} members")
        parts = normalize_member(name, allow_root=(kind == "dir"))
        self._check_conflicts(parts, kind, name)
        if parts:
            self._check_existing(parts, kind, name)
            _contained(self.root, parts, kind, name)
        if kind == "file":
            self.declared += max(0, int(size))
            if self.declared > self.cap:
                raise ArchiveRejected(
                    f"archive expands past {self.cap} bytes (the configured bytes cap)")
        self.entries.append(_Entry(parts, kind, max(0, int(size)), ref, name))

    def finish(self) -> None:
        """Settle the byte budget once every member (and every file it replaces) is known."""
        if self.free is not None:
            room = self.free + self.reclaimable
            if room < self.budget:
                self.budget = room
                self.budget_reason = ("the free space on the destination, counting the "
                                      "files this archive replaces" if self.reclaimable
                                      else "the free space on the destination")
        if self.declared > self.budget:
            raise ArchiveRejected(
                f"archive expands past {self.budget} bytes ({self.budget_reason})")

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

    def _check_existing(self, parts: tuple[str, ...], kind: str, name: str) -> None:
        """Validate *parts* against what the destination already holds, never following a link.

        Every existing component on the way must be a real directory (a link is refused,
        in-tree or not: extraction never writes through one). At a file member's own name
        a directory is refused; anything else there is replaced at write time, and a
        single-link regular file's blocks are credited to the free-space budget.
        """
        current = self.root
        for depth, part in enumerate(parts, 1):
            current = current / part
            prefix = parts[:depth]
            if prefix in self._real_dirs:
                continue
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                return  # nothing below a missing component exists either
            except OSError as exc:
                if exc.errno == errno.ENAMETOOLONG:
                    raise ArchiveRejected(
                        f"member name too long for the destination: {_show(name)}") from None
                raise
            if depth == len(parts) and kind == "file":
                if stat.S_ISDIR(st.st_mode):
                    raise ArchiveRejected(
                        f"file member would replace a directory in the destination: {_show(name)}")
                if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
                    self.reclaimable += _freed_by_unlink(st)
                return
            if stat.S_ISLNK(st.st_mode):
                raise ArchiveRejected(
                    f"member path crosses a link already in the destination: {_show(name)}")
            if not stat.S_ISDIR(st.st_mode):
                raise ArchiveRejected(
                    f"member path runs through a non-directory already in the destination: "
                    f"{_show(name)}")
            self._real_dirs.add(prefix)


def _free_space(dest: Path) -> int | None:
    try:
        return int(shutil.disk_usage(dest).free)
    except OSError:
        return None


def _contained(root: Path, parts: tuple[str, ...], kind: str, name: str) -> Path:
    """Require ``root/parts`` to stay inside *root* (defence in depth over _check_existing).

    A file member's PARENT is resolved and its own name joined lexically: a link at the
    final component is replaced, not followed, so resolving through it would be wrong.
    """
    if kind == "file":
        parent = root.joinpath(*parts[:-1]).resolve()
        if parent != root and root not in parent.parents:
            raise ArchiveRejected(f"member resolves outside the destination: {_show(name)}")
        return parent / parts[-1]
    target = root.joinpath(*parts).resolve()
    if target == root or root not in target.parents:
        raise ArchiveRejected(f"member resolves outside the destination: {_show(name)}")
    return target


class _Progress:
    """Whether the write phase has changed the destination yet (for ``partial``)."""

    touched = False


def _ensure_dirs(root: Path, parts: tuple[str, ...], name: str, progress: _Progress) -> Path:
    """Create ``root/parts`` one real directory at a time; refuse anything else in the way."""
    current = root
    for part in parts:
        current = current / part
        try:
            os.mkdir(current)
            progress.touched = True
            continue
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(current).st_mode):  # a link lstat()s as S_IFLNK
            raise ArchiveRejected(
                f"destination changed during extraction under {_show(name)}")
    return current


def _clear_final(target: Path, name: str, progress: _Progress) -> None:
    """Unlink whatever holds a file member's name, so the file is created fresh.

    A link there is removed (not followed), a hardlinked name is split off (writing through
    it would change the other name too), a special file is replaced.
    """
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode):
        raise ArchiveRejected(f"destination changed during extraction at {_show(name)}")
    progress.touched = True
    os.unlink(target)


def _write_capped(src: BinaryIO, target: Path, written: int, budget: int, name: str) -> int:
    """Stream *src* to a NEW *target*, counting against *budget*; remove it on any failure."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
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


def _extract_plan(plan: _Planner,
                  open_member: Callable[[_Entry], BinaryIO | None]) -> list[tuple[str, ...]]:
    """Write every planned entry; return the parts of each file written, in archive order."""
    progress = _Progress()
    files: list[tuple[str, ...]] = []
    written = 0
    try:
        for entry in plan.entries:
            if not entry.parts:
                continue  # "./" — the destination itself
            if entry.kind == "dir":
                _ensure_dirs(plan.root, entry.parts, entry.name, progress)
                continue
            parent = _ensure_dirs(plan.root, entry.parts[:-1], entry.name, progress)
            target = parent / entry.parts[-1]
            src = open_member(entry)
            if src is None:
                raise ArchiveRejected(f"regular member has no data: {_show(entry.name)}")
            with src:
                _clear_final(target, entry.name, progress)
                progress.touched = True
                written = _write_capped(src, target, written, plan.budget, entry.name)
            files.append(entry.parts)
    except ArchiveRejected as exc:
        exc.partial = exc.partial or progress.touched
        raise
    except _CORRUPT as exc:
        raise ArchiveRejected(f"archive is corrupt or truncated: {exc}",
                              partial=progress.touched) from exc
    return files


def _prepare_dest(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    return dest.resolve()


# ── tar ────────────────────────────────────────────────────────────
_TAR_HEADER_TYPES = (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                     tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)


class _GuardedTarInfo(tarfile.TarInfo):
    """A TarInfo that refuses what tarfile would otherwise read or trust blindly.

    * A PAX / GNU long-name header payload over ``_MAX_HEADER_PAYLOAD`` (or all of them
      past ``_MAX_HEADER_TOTAL``) is refused from its declared size, before tarfile reads
      the payload into memory.
    * Sparse members (GNU ``S`` headers and PAX ``GNU.sparse.*`` records) are refused: the
      sparse map is read into memory unbounded, and Nerva never writes one.
    * A corrupt or truncated header part-way through the archive is refused. tarfile's
      default is to treat it as the end of the archive — a quietly shortened tree.

    ``_proc_member`` and ``_proc_gnusparse_*`` are tarfile internals (stable since 3.2);
    ``tests/test_archive_safe.py`` fails loudly if a Python release renames them.
    """

    @classmethod
    def fromtarfile(cls, tarfile_obj):
        try:
            return super().fromtarfile(tarfile_obj)
        except (tarfile.InvalidHeaderError, tarfile.TruncatedHeaderError) as exc:
            raise ArchiveRejected(f"archive is corrupt or truncated: {exc}") from None

    def _proc_member(self, tarfile_obj):
        if self.type in _TAR_HEADER_TYPES:
            if self.size > _MAX_HEADER_PAYLOAD:
                raise ArchiveRejected(
                    f"tar header payload of {self.size} bytes refused "
                    f"(limit {_MAX_HEADER_PAYLOAD})")
            total = getattr(tarfile_obj, "_nerva_header_bytes", 0) + self.size
            if total > _MAX_HEADER_TOTAL:
                raise ArchiveRejected(
                    f"tar header payloads exceed {_MAX_HEADER_TOTAL} bytes in total")
            tarfile_obj._nerva_header_bytes = total
        elif self.type == tarfile.GNUTYPE_SPARSE:
            raise ArchiveRejected(f"sparse member refused: {_show(self.name)}")
        return super()._proc_member(tarfile_obj)

    def _refuse_sparse(self, *_args, **_kwargs):
        raise ArchiveRejected("sparse member refused (PAX GNU.sparse records)")

    _proc_gnusparse_00 = _proc_gnusparse_01 = _proc_gnusparse_10 = _refuse_sparse


def _tar_kind(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "dir"
    if member.type == tarfile.GNUTYPE_SPARSE or member.sparse is not None:
        raise ArchiveRejected(f"sparse member refused: {_show(member.name)}")
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


def _drain_padding(fileobj) -> None:
    """Read past the end-of-archive marker: zeros only, and not unboundedly many.

    This is also what makes gzip check the stream's CRC32 and length (it does so only on
    reaching its trailer, which the member walk never does).
    """
    seen = 0
    while True:
        chunk = fileobj.read(_CHUNK)
        if not chunk:
            return
        seen += len(chunk)
        if chunk.count(0) != len(chunk) or seen > _MAX_TRAILING_PADDING:
            raise ArchiveRejected(
                "archive is corrupt or truncated: data after the end-of-archive marker")


def extract_tar(tar: tarfile.TarFile, dest: Path, *,
                limits: ArchiveLimits = DEFAULT_LIMITS) -> int:
    """Extract *tar* into *dest* (regular files and directories only); return files written.

    Raises :class:`ArchiveRejected` — before writing anything — on an unsafe name, a
    link/device/fifo/sparse member, a file/directory conflict or duplicate (within the
    archive or with the destination), a count or byte cap, an oversized header, or a
    corrupt stream; and while streaming if a member yields more than the byte budget or
    the data cannot be read (then with ``partial=True``). Members are read lazily, so a
    count bomb stops at ``max_members + 1``. Prefer :func:`extract_tar_path`, which also
    guards the first header (read while the archive is opened).
    """
    return len(_extract_tar(tar, dest, limits))


def _extract_tar(tar: tarfile.TarFile, dest: Path,
                 limits: ArchiveLimits) -> list[tuple[str, ...]]:
    if not (isinstance(tar.tarinfo, type) and issubclass(tar.tarinfo, _GuardedTarInfo)):
        tar.tarinfo = _GuardedTarInfo  # guard every header read from here on
    root = _prepare_dest(dest)
    plan = _Planner(root, limits)
    try:
        for member in tar:  # lazy: TarFile iteration reads one header at a time
            plan.add(member.name, _tar_kind(member), member.size, member)
        _drain_padding(tar.fileobj)
    except _CORRUPT as exc:
        raise ArchiveRejected(f"archive is corrupt or truncated: {exc}") from exc
    plan.finish()
    return _extract_plan(plan, lambda entry: tar.extractfile(entry.ref))


def extract_tar_path(path: Path, dest: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS,
                     compression: str = "*") -> list[tuple[str, ...]]:
    """Open the tar at *path* with every header guarded and extract it into *dest*.

    Returns the parts of each regular file written, in archive order. *compression* is
    the ``tarfile.open`` suffix (``"gz"``, or ``"*"`` to detect). A file that is not a
    readable archive raises :class:`ArchiveRejected`, like any other refusal.
    """
    try:
        with tarfile.open(path, f"r:{compression}", tarinfo=_GuardedTarInfo) as tar:
            return _extract_tar(tar, dest, limits)
    except _CORRUPT as exc:  # raised while opening; _extract_tar maps its own
        raise ArchiveRejected(f"archive is corrupt or truncated: {exc}") from exc


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
    return len(_extract_zip(zf, dest, limits))


def _extract_zip(zf: zipfile.ZipFile, dest: Path,
                 limits: ArchiveLimits) -> list[tuple[str, ...]]:
    root = _prepare_dest(dest)
    infos = zf.infolist()
    if len(infos) > limits.max_members:
        raise ArchiveRejected(f"archive has more than {limits.max_members} members")
    plan = _Planner(root, limits)
    for info in infos:
        plan.add(info.filename, _zip_kind(info), info.file_size, info)
    plan.finish()
    return _extract_plan(plan, lambda entry: zf.open(entry.ref, "r"))


def extract_zip_bytes(data: bytes, dest: Path, *,
                      limits: ArchiveLimits = DEFAULT_LIMITS) -> list[tuple[str, ...]]:
    """Extract the zip held in *data* into *dest*; return each file's parts, in archive order.

    Bytes that are not a readable zip raise :class:`ArchiveRejected`, like any other
    refusal (an upload route maps it to a 400, not a 500).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except (*_CORRUPT, ValueError) as exc:
        raise ArchiveRejected(f"archive is corrupt or not a zip: {exc}") from exc
    with zf:
        return _extract_zip(zf, dest, limits)


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
