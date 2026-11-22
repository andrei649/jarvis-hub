"""Handle-relative access to a vault folder: no symlink, junction or hard link is followed.

Every read and every create under a vault goes through `VaultFs`. A path is never handed
to the operating system as a whole. Each component is opened relative to the handle of
its already-verified parent, with link following switched off, so:

- a symlink or junction anywhere in the path is refused, not followed;
- replacing an ancestor directory while a request is in flight cannot redirect it, because
  the walk holds the parent's handle rather than re-resolving its name;
- a regular file with more than one hard link is refused by default: its other name may
  live outside the vault, and nothing on the handle can prove otherwise. Some sync
  clients hard-link a file while they upload it (Google Drive does), so a caller that
  trusts the folder can pass `allow_hardlinks=True`; refusals are recorded, never silent;
- a new note is created relative to the verified inbox handle, exclusively.

POSIX uses `openat`-style calls (`dir_fd=` with `O_NOFOLLOW`). Windows uses `NtCreateFile`
with a `RootDirectory` handle and `OBJ_DONT_REPARSE`, which is the native equivalent; there
is no path-based fallback on either platform. A platform that offers neither raises
`UnsafePath` and the caller reports the operation as unavailable.

The vault root itself is configuration and is trusted: it is resolved once and pinned by
handle for the lifetime of the `VaultFs`.

Standard library only (ctypes on Windows), like the rest of this app.
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

SF_DATALESS = 0x40000000


class UnsafePath(OSError):
    """The entry is a link, a reparse point, multiply linked, or not a plain file/folder."""


@dataclass(frozen=True)
class Entry:
    """What an opened (or, for a dataless cloud file, merely stat-ed) entry is."""

    is_dir: bool
    size: int
    #: macOS: the file's data lives in the cloud and opening it would download it.
    dataless: bool = False
    #: Number of names this file has. More than one means a hard link exists.
    links: int = 1


def check_name(name: str) -> str:
    """One path component, never a path."""
    if (not name or name in (".", "..") or "\x00" in name or "/" in name or "\\" in name
            or (os.name == "nt" and (":" in name or name != name.rstrip(" .")))):
        raise UnsafePath(f"not a single path component: {name!r}")
    return name


# ── POSIX ────────────────────────────────────────────────────────

class _PosixApi:
    def __init__(self):
        if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
            raise UnsafePath("this platform has no handle-relative open")
        self._flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)

    def open_root(self, path: str) -> int:
        return os.open(os.path.realpath(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                       | getattr(os, "O_CLOEXEC", 0))

    def open_child(self, parent: int, name: str) -> tuple[int | None, Entry]:
        # A dataless (cloud-evicted) file is reported without being opened: opening it
        # would make macOS download it. lstat-relative, so still no link is followed.
        if os.stat in os.supports_dir_fd:
            pre = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(pre.st_mode):
                raise UnsafePath("symlink")
            if stat.S_ISREG(pre.st_mode) and getattr(pre, "st_flags", 0) & SF_DATALESS:
                return None, Entry(is_dir=False, size=pre.st_size, dataless=True, links=pre.st_nlink)
        try:
            fd = os.open(name, self._flags, dir_fd=parent)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise UnsafePath("symlink") from None
            raise
        try:
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode):
                return fd, Entry(is_dir=True, size=0)
            if not stat.S_ISREG(info.st_mode):
                raise UnsafePath("not a regular file")
            return fd, Entry(is_dir=False, size=info.st_size, links=info.st_nlink)
        except BaseException:
            os.close(fd)
            raise

    def list_names(self, handle: int) -> list[str]:
        return os.listdir(handle)

    def read(self, handle: int, cap: int) -> bytes:
        chunks, remaining = [], cap
        os.lseek(handle, 0, os.SEEK_SET)
        while remaining > 0:
            chunk = os.read(handle, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def make_dir(self, parent: int, name: str) -> None:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, dir_fd=parent)

    def create_file(self, parent: int, name: str) -> int:
        return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                       | getattr(os, "O_CLOEXEC", 0), 0o644, dir_fd=parent)

    def write(self, handle: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            view = view[os.write(handle, view):]

    def identity(self, handle: int) -> tuple[int, int]:
        info = os.fstat(handle)
        return info.st_dev, info.st_ino

    def flush(self, handle: int) -> None:
        os.fsync(handle)

    def publish(self, parent: int, handle: int, temporary: str, final: str) -> None:
        os.link(temporary, final, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)

    def discard(self, parent: int, handle: int, temporary: str) -> None:
        os.unlink(temporary, dir_fd=parent)

    def close(self, handle: int) -> None:
        os.close(handle)


# ── Windows ──────────────────────────────────────────────────────

class _WindowsApi:
    _STATUS_REPARSE = 0xC000050B           # STATUS_REPARSE_POINT_ENCOUNTERED
    _STATUS_COLLISION = 0xC0000035         # STATUS_OBJECT_NAME_COLLISION
    _STATUS_NOT_A_DIRECTORY = 0xC0000103
    _OBJ = 0x40 | 0x1000                   # OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE
    _SYNC_NO_REPARSE = 0x20 | 0x00200000   # FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
    _SHARE_ALL = 0x1 | 0x2 | 0x4
    _INVALID = -1

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w

        self.c, self.w = ctypes, w
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.n = ctypes.WinDLL("ntdll", use_last_error=True)

        class Unicode(ctypes.Structure):
            _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", ctypes.c_void_p)]

        class ObjAttr(ctypes.Structure):
            _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE),
                        ("ObjectName", ctypes.POINTER(Unicode)), ("Attributes", w.ULONG),
                        ("SecurityDescriptor", ctypes.c_void_p),
                        ("SecurityQualityOfService", ctypes.c_void_p)]

        class IoStatus(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_size_t), ("Information", ctypes.c_size_t)]

        class Standard(ctypes.Structure):
            _fields_ = [("AllocationSize", ctypes.c_int64), ("EndOfFile", ctypes.c_int64),
                        ("NumberOfLinks", w.DWORD), ("DeletePending", w.BOOLEAN),
                        ("Directory", w.BOOLEAN)]

        class AttrTag(ctypes.Structure):
            _fields_ = [("FileAttributes", w.DWORD), ("ReparseTag", w.DWORD)]

        self.Unicode, self.ObjAttr, self.IoStatus = Unicode, ObjAttr, IoStatus
        self.Standard, self.AttrTag = Standard, AttrTag
        self.k.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                       w.DWORD, w.DWORD, w.HANDLE)
        self.k.CreateFileW.restype = w.HANDLE
        self.k.GetFileInformationByHandleEx.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        self.k.GetFileInformationByHandleEx.restype = w.BOOL
        self.k.GetFinalPathNameByHandleW.argtypes = (w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
        self.k.GetFinalPathNameByHandleW.restype = w.DWORD
        self.k.ReadFile.argtypes = (w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p)
        self.k.ReadFile.restype = w.BOOL
        self.k.WriteFile.argtypes = (w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p)
        self.k.WriteFile.restype = w.BOOL
        self.k.SetFilePointerEx.argtypes = (w.HANDLE, ctypes.c_int64, ctypes.c_void_p, w.DWORD)
        self.k.SetFilePointerEx.restype = w.BOOL
        self.k.CloseHandle.argtypes = (w.HANDLE,)
        self.k.CloseHandle.restype = w.BOOL
        self.k.FlushFileBuffers.argtypes = (w.HANDLE,)
        self.k.FlushFileBuffers.restype = w.BOOL
        self.k.SetFileInformationByHandle.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        self.k.SetFileInformationByHandle.restype = w.BOOL

        class FileIdInfo(ctypes.Structure):
            _fields_ = [("VolumeSerialNumber", ctypes.c_uint64), ("FileId", ctypes.c_ubyte * 16)]

        class RenameInfo(ctypes.Structure):
            _fields_ = [("ReplaceIfExists", w.DWORD), ("RootDirectory", w.HANDLE),
                        ("FileNameLength", w.DWORD), ("FileName", w.WCHAR * 1)]

        self.FileIdInfo, self.RenameInfo = FileIdInfo, RenameInfo
        self.n.NtCreateFile.argtypes = (
            ctypes.POINTER(w.HANDLE), w.DWORD, ctypes.POINTER(ObjAttr), ctypes.POINTER(IoStatus),
            ctypes.c_void_p, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD)
        self.n.NtCreateFile.restype = ctypes.c_long
        self.n.NtSetInformationFile.argtypes = (w.HANDLE, ctypes.POINTER(IoStatus),
                                               ctypes.c_void_p, w.ULONG, w.ULONG)
        self.n.NtSetInformationFile.restype = ctypes.c_long
        self.n.RtlNtStatusToDosError.argtypes = (w.ULONG,)
        self.n.RtlNtStatusToDosError.restype = w.ULONG

    def _last_error(self, what: str) -> OSError:
        code = self.c.get_last_error()
        return OSError(code, f"{what} failed (winerror {code})")

    def _nt_open(self, parent: int, name: str, *, access: int, share: int, disposition: int,
                 options: int) -> int:
        """One component, relative to `parent`'s handle, refusing any reparse point."""
        text = self.c.create_unicode_buffer(name)
        size = len(name.encode("utf-16-le"))
        counted = self.Unicode(size, size + 2, self.c.cast(text, self.c.c_void_p))
        attr = self.ObjAttr(self.c.sizeof(self.ObjAttr), parent, self.c.pointer(counted),
                            self._OBJ, None, None)
        io, result = self.IoStatus(), self.w.HANDLE()
        status = self.n.NtCreateFile(self.c.byref(result), access, self.c.byref(attr),
                                     self.c.byref(io), None, 0x80, share, disposition,
                                     options | self._SYNC_NO_REPARSE, None, 0)
        if status >= 0:
            return result.value
        code = status & 0xFFFFFFFF
        if code == self._STATUS_REPARSE:
            raise UnsafePath("reparse point")
        if code == self._STATUS_COLLISION:
            raise FileExistsError(errno.EEXIST, "already exists", name)
        dos = int(self.n.RtlNtStatusToDosError(code))
        if dos in (2, 3):
            raise FileNotFoundError(errno.ENOENT, "not found", name)
        if code == self._STATUS_NOT_A_DIRECTORY:
            raise UnsafePath("not a folder")
        raise OSError(errno.EIO, f"open failed (winerror {dos}, status {code:#x})", name)

    def _info(self, handle: int, info_class: int, kind):
        value = kind()
        if not self.k.GetFileInformationByHandleEx(handle, info_class, self.c.byref(value),
                                                    self.c.sizeof(value)):
            raise self._last_error("file information")
        return value

    def _entry(self, handle: int) -> Entry:
        """Describe the opened object itself, refusing a reparse point."""
        tag = self._info(handle, 9, self.AttrTag)          # FileAttributeTagInfo
        if tag.FileAttributes & 0x400:                     # FILE_ATTRIBUTE_REPARSE_POINT
            raise UnsafePath("reparse point")
        standard = self._info(handle, 1, self.Standard)    # FileStandardInfo
        if standard.Directory:
            return Entry(is_dir=True, size=0)
        return Entry(is_dir=False, size=int(standard.EndOfFile), links=int(standard.NumberOfLinks))

    def open_root(self, path: str) -> int:
        # FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE, OPEN_EXISTING,
        # FILE_FLAG_BACKUP_SEMANTICS (required to open a directory).
        handle = self.k.CreateFileW(os.path.realpath(path), 0x1 | 0x80 | 0x100000, self._SHARE_ALL,
                                    None, 3, 0x02000000, None)
        if handle in (None, self.c.c_void_p(self._INVALID).value):
            code = self.c.get_last_error()
            if code in (2, 3):
                raise FileNotFoundError(errno.ENOENT, "vault not found", path)
            raise OSError(code, f"cannot open the vault (winerror {code})", path)
        return handle

    def open_child(self, parent: int, name: str) -> tuple[int, Entry]:
        # FILE_READ_DATA / FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE, FILE_OPEN.
        handle = self._nt_open(parent, name, access=0x1 | 0x80 | 0x100000, share=self._SHARE_ALL,
                               disposition=1, options=0)
        try:
            return handle, self._entry(handle)
        except BaseException:
            self.close(handle)
            raise

    def list_names(self, handle: int) -> list[str]:
        # Names only. Each one is then opened relative to `handle`, so a listing taken
        # from a swapped path can at worst name entries that fail to open.
        buffer = self.c.create_unicode_buffer(32768)
        length = self.k.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise self._last_error("final path")
        return os.listdir(buffer.value)

    def read(self, handle: int, cap: int) -> bytes:
        if not self.k.SetFilePointerEx(handle, 0, None, 0):
            raise self._last_error("seek")
        chunks, remaining = [], cap
        while remaining > 0:
            size = min(remaining, 1 << 20)
            buffer, count = self.c.create_string_buffer(size), self.w.DWORD()
            if not self.k.ReadFile(handle, buffer, size, self.c.byref(count), None):
                raise self._last_error("read")
            if not count.value:
                break
            chunks.append(buffer.raw[:count.value])
            remaining -= count.value
        return b"".join(chunks)

    def make_dir(self, parent: int, name: str) -> None:
        # FILE_OPEN_IF + FILE_DIRECTORY_FILE: create the folder, or open the one there.
        handle = self._nt_open(parent, name, access=0x1 | 0x80 | 0x100000, share=self._SHARE_ALL,
                               disposition=3, options=0x1)
        self.close(handle)

    def create_file(self, parent: int, name: str) -> int:
        # FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE, FILE_CREATE (fails if present),
        # FILE_NON_DIRECTORY_FILE.
        return self._nt_open(parent, name, access=0x2 | 0x80 | 0x100000, share=0x1,
                             disposition=2, options=0x40)

    def create_publish_file(self, parent: int, name: str) -> int:
        return self._nt_open(parent, name, access=0x2 | 0x80 | 0x10000 | 0x100000,
                             share=self._SHARE_ALL, disposition=2, options=0x40)

    def identity(self, handle: int) -> tuple[int, str]:
        info = self._info(handle, 18, self.FileIdInfo)  # FileIdInfo
        return int(info.VolumeSerialNumber), bytes(info.FileId).hex()

    def flush(self, handle: int) -> None:
        if not self.k.FlushFileBuffers(handle):
            raise self._last_error("flush")

    def publish(self, parent: int, handle: int, temporary: str, final: str) -> None:
        encoded = final.encode("utf-16-le")
        size = self.c.sizeof(self.RenameInfo) + len(encoded)
        buffer = self.c.create_string_buffer(size)
        info = self.c.cast(buffer, self.c.POINTER(self.RenameInfo)).contents
        info.ReplaceIfExists = 0
        info.RootDirectory = parent
        info.FileNameLength = len(encoded)
        self.c.memmove(self.c.addressof(buffer) + self.RenameInfo.FileName.offset,
                       encoded, len(encoded))
        io = self.IoStatus()
        status = self.n.NtSetInformationFile(handle, self.c.byref(io), buffer, size,
                                             10)  # FileRenameInformation
        if status < 0:
            code = status & 0xFFFFFFFF
            if code == self._STATUS_COLLISION:
                raise FileExistsError(errno.EEXIST, "already exists", final)
            dos = int(self.n.RtlNtStatusToDosError(code))
            raise OSError(dos, f"publish failed (winerror {dos}, status {code:#x})", final)

    def discard(self, parent: int, handle: int, temporary: str) -> None:
        flag = self.w.BOOLEAN(1)
        if not self.k.SetFileInformationByHandle(handle, 4, self.c.byref(flag),
                                                 self.c.sizeof(flag)):  # FileDispositionInfo
            raise self._last_error("discard")

    def write(self, handle: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + (1 << 20)]
            count = self.w.DWORD()
            if not self.k.WriteFile(handle, chunk, len(chunk), self.c.byref(count), None) or not count.value:
                raise self._last_error("write")
            offset += count.value

    def close(self, handle: int) -> None:
        self.k.CloseHandle(handle)


def _platform_api():
    return _WindowsApi() if sys.platform == "win32" else _PosixApi()


# ── the vault ────────────────────────────────────────────────────

class VaultFs:
    """A vault folder, pinned by handle. Use as a context manager."""

    def __init__(self, root: str | os.PathLike, *, allow_hardlinks: bool = False, api=None):
        self.root = Path(root)
        self.allow_hardlinks = allow_hardlinks
        self._api = api or _platform_api()
        self._root = self._api.open_root(str(self.root))
        #: Relative paths refused during a walk, with the reason (symlink, hard link, ...).
        self.skipped: list[tuple[str, str]] = []

    def __enter__(self) -> VaultFs:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._root is not None:
            self._api.close(self._root)
            self._root = None

    def _check_links(self, entry: Entry) -> None:
        if not entry.is_dir and entry.links != 1 and not self.allow_hardlinks:
            raise UnsafePath("hard link")

    # -- handles ---------------------------------------------------

    def open_dir(self, parts=(), *, create: bool = False) -> int:
        """Walk `parts` from the root and return the last folder's handle (caller closes).

        With `create`, a missing folder is made relative to its verified parent.
        """
        current, owned = self._root, False
        try:
            for name in parts:
                check_name(name)
                if create:
                    self._api.make_dir(current, name)
                handle, entry = self._api.open_child(current, name)
                if owned:
                    self._api.close(current)
                current, owned = handle, True
                if not entry.is_dir:
                    raise UnsafePath("not a folder")
            if not owned:
                raise ValueError("use the VaultFs itself for the root")
            return current
        except BaseException:
            if owned:
                self._api.close(current)
            raise

    def close_dir(self, handle: int) -> None:
        self._api.close(handle)

    def dir_identity(self, parts) -> tuple:
        handle = self.open_dir(parts)
        try:
            return self._api.identity(handle)
        finally:
            self._api.close(handle)

    def folder_identity(self, handle: int) -> tuple:
        return self._api.identity(handle)

    def root_identity(self) -> tuple:
        return self._api.identity(self._root)

    def _parent_of(self, parts) -> tuple[int, bool]:
        parts = tuple(parts)
        if not parts:
            raise UnsafePath("empty path")
        check_name(parts[-1])
        if len(parts) == 1:
            return self._root, False
        return self.open_dir(parts[:-1]), True

    def list_names(self, parts=()) -> list[str]:
        """Sorted entry names of the folder at `parts` (the root when empty)."""
        if not tuple(parts):
            return sorted(self._api.list_names(self._root))
        handle = self.open_dir(tuple(parts))
        try:
            return sorted(self._api.list_names(handle))
        finally:
            self._api.close(handle)

    # -- reads -----------------------------------------------------

    def read_in(self, dir_handle: int, name: str, cap: int) -> tuple[Entry, bytes]:
        """Read a plain file by name inside an already-open folder handle."""
        handle, entry = self._api.open_child(dir_handle, check_name(name))
        try:
            if entry.is_dir:
                raise UnsafePath("not a file")
            self._check_links(entry)
            if entry.dataless or handle is None:
                return entry, b""
            return entry, self._api.read(handle, cap)
        finally:
            if handle is not None:
                self._api.close(handle)

    def read_file(self, parts, cap: int) -> tuple[Entry, bytes]:
        """Read the plain file at `parts` (path components), at most `cap` bytes."""
        parent, owned = self._parent_of(parts)
        try:
            return self.read_in(parent, tuple(parts)[-1], cap)
        finally:
            if owned:
                self._api.close(parent)

    def walk(self, want=lambda name: True, cap=lambda name: 0,
             allow_dir=lambda parts: True, allow_file=lambda parts: True):
        """Yield `(parts, entry, data)` for every wanted plain file, folders in sorted order.

        Dot-names are skipped. Links, reparse points and multiply-linked files are not
        followed and not yielded; they are recorded in `skipped`. `cap(name)` is how many
        bytes of that file to read (0 reads nothing).
        """
        yield from self._walk(self._root, (), want, cap, allow_dir, allow_file)

    def _walk(self, handle: int, prefix: tuple, want, cap, allow_dir, allow_file):
        folders = []
        for name in sorted(self._api.list_names(handle)):
            if name.startswith("."):
                continue
            parts = prefix + (name,)
            # Decide from the listed name before opening a file or descending a folder.
            if not allow_dir(parts) and not allow_file(parts):
                continue
            try:
                check_name(name)
                child, entry = self._api.open_child(handle, name)
            except UnsafePath as exc:
                self.skipped.append(("/".join(parts), str(exc)))
                continue
            except OSError:
                continue                      # vanished or unreadable between list and open
            try:
                if entry.is_dir:
                    if allow_dir(parts):
                        folders.append(name)
                    continue
                if not allow_file(parts) or not want(name):
                    continue
                try:
                    self._check_links(entry)
                except UnsafePath as exc:
                    self.skipped.append(("/".join(parts), str(exc)))
                    continue
                size = 0 if entry.dataless or child is None else cap(name)
                data = self._api.read(child, size) if size else b""
            finally:
                if child is not None:
                    self._api.close(child)
            yield parts, entry, data
        for name in folders:
            try:
                child, entry = self._api.open_child(handle, name)
            except (UnsafePath, OSError) as exc:
                self.skipped.append(("/".join(prefix + (name,)), str(exc)))
                continue
            try:
                if entry.is_dir:
                    yield from self._walk(child, prefix + (name,), want, cap, allow_dir, allow_file)
            finally:
                self._api.close(child)

    # -- writes ----------------------------------------------------

    def create_exclusive(self, dir_parts, name: str, data: bytes, *, create_dirs: bool = True) -> None:
        """Create `name` inside the folder `dir_parts`; `FileExistsError` if it is taken.

        The folder is made if missing. It and every ancestor must be real folders inside
        the vault: a symlink or junction in their place is refused before anything is
        written, and the file is created relative to the verified folder's handle.
        """
        check_name(name)
        try:
            folder = self.open_dir(tuple(dir_parts), create=create_dirs)
        except FileNotFoundError as exc:
            raise UnsafePath("inbox folder does not exist") from exc
        try:
            handle = self._api.create_file(folder, name)
            try:
                self._api.write(handle, data)
            finally:
                self._api.close(handle)
        finally:
            self._api.close(folder)

    def publish_in(self, folder: int, name: str, data: bytes) -> None:
        """Publish complete bytes through a pinned folder, without replacing an entry."""
        check_name(name)
        temporary = ".chat-note-" + uuid.uuid4().hex + ".tmp"
        create = getattr(self._api, "create_publish_file", self._api.create_file)
        handle = create(folder, temporary)
        published = False
        try:
            self._api.write(handle, data)
            self._api.flush(handle)
            self._api.publish(folder, handle, temporary, name)
            published = True
        finally:
            try:
                if not published:
                    self._api.discard(folder, handle, temporary)
            finally:
                self._api.close(handle)
