"""Private NTFS ownership records, with mutations relative to held directories."""

from __future__ import annotations

import ctypes
import json
import re
import secrets
import sys
import time
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path

from .checkpoint_windows_fs import HeldHandle, WindowsFsRefusal, WindowsHistoryFs

_SID = re.compile(r"[0-9a-f]{32}\Z")
_NAME = re.compile(r"[0-9a-f]{32}\.json\Z")
_SCRATCH = re.compile(r"\.[0-9a-f]{32}\.[0-9a-f]{16}\Z")
_CAP = 4096


def _nt_error(api, status: int, operation: str) -> OSError:
    code = int(api.n.RtlNtStatusToDosError(status & 0xffffffff))
    error = WindowsFsRefusal(f"{operation}:{code}")
    error.winerror = code
    return error


class _Native:
    def __init__(self, fs: WindowsHistoryFs):
        self.fs = fs
        self.api = fs.api
        self.api.k.WriteFile.argtypes = (w.HANDLE, ctypes.c_void_p, w.DWORD,
                                         ctypes.POINTER(w.DWORD), ctypes.c_void_p)
        self.api.k.WriteFile.restype = w.BOOL
        self.api.k.FlushFileBuffers.argtypes = (w.HANDLE,)
        self.api.k.FlushFileBuffers.restype = w.BOOL
        self.api.n.NtSetInformationFile.argtypes = (w.HANDLE, ctypes.POINTER(self.api.IoStatus),
                                                    ctypes.c_void_p, w.ULONG, w.ULONG)
        self.api.n.NtSetInformationFile.restype = ctypes.c_long
        self.api.n.NtQueryDirectoryFile.argtypes = (
            w.HANDLE, w.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(self.api.IoStatus), ctypes.c_void_p, w.ULONG,
            ctypes.c_int, w.BOOLEAN, ctypes.c_void_p, w.BOOLEAN)
        self.api.n.NtQueryDirectoryFile.restype = ctypes.c_long
        self.api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD))
        self.api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL

    def open(self, parent, name: str, *, create=False, directory=False,
             share_delete=True):
        from .checkpoint_windows_fs import _counted_name, _marshal_counted_name

        counted = _counted_name(name)
        chars = ctypes.create_unicode_buffer(name)
        uni = _marshal_counted_name(counted, chars, self.api.Unicode, chars)
        descriptor = ctypes.c_void_p()
        if create:
            sid = self.api._current_sid()
            sddl = f"O:{sid}D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{sid})"
            if not self.api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            attrs = self.api.ObjAttr(ctypes.sizeof(self.api.ObjAttr), parent.raw,
                                     ctypes.pointer(uni), 0x1000 | 0x40,
                                     descriptor.value, None)
            io = self.api.IoStatus()
            result = w.HANDLE()
            access = 0x100000 | 0x20000 | 0x80 | 0x10000 | (0x2 if not directory else 0x3)
            options = 0x20 | (0x1 if directory else 0x40 | 0x2 | 0x00200000)
            status = self.api.n.NtCreateFile(ctypes.byref(result), access,
                                             ctypes.byref(attrs), ctypes.byref(io),
                                             None, 0x80 if not directory else 0x10,
                                             0x1 | 0x2 | (0x4 if share_delete else 0),
                                             2 if create else 1,
                                             options, None, 0)
            if status < 0:
                error = int(self.api.n.RtlNtStatusToDosError(status & 0xffffffff))
                if not create and error in (2, 3):
                    return None
                if status & 0xffffffff == 0xC000050B:
                    raise WindowsFsRefusal("reparse_encountered")
                raise _nt_error(self.api, status, "open_failed")
            return result.value
        finally:
            if descriptor.value:
                self.api.k.LocalFree(descriptor)

    def check(self, handle: int, *, directory: bool, volume: bytes):
        stamp = self.fs.verified_stamp(handle, directory=directory, volume=volume)
        from .checkpoint_windows_fs import HeldHandle
        self.fs.verify_private_acl(HeldHandle(self.api, handle, stamp))
        return stamp

    def write(self, handle: int, data: bytes) -> None:
        buffer = ctypes.create_string_buffer(data)
        count = w.DWORD()
        if not self.api.k.WriteFile(handle, buffer, len(data), ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if count.value != len(data):
            raise WindowsFsRefusal("short_write")
        self.flush(handle)

    def flush(self, handle: int) -> None:
        if not self.api.k.FlushFileBuffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def rename(self, handle: int, root, name: str) -> None:
        encoded = name.encode("utf-16-le")
        class RenameInfo(ctypes.Structure):
            _fields_ = (("replace", w.BOOLEAN), ("root", w.HANDLE),
                        ("length", w.ULONG), ("name", w.WCHAR * 1))

        offset = RenameInfo.name.offset
        info = ctypes.create_string_buffer(offset + len(encoded))
        header = RenameInfo.from_buffer(info)
        header.replace = 1
        header.root = root.raw
        header.length = len(encoded)
        ctypes.memmove(ctypes.addressof(info) + offset, encoded, len(encoded))
        io = self.api.IoStatus()
        status = self.api.n.NtSetInformationFile(handle, ctypes.byref(io), info,
                                                 len(info), 10)
        if status < 0:
            raise _nt_error(self.api, status, "rename_failed")

    def delete(self, handle: int) -> None:
        info = w.BOOLEAN(1)
        io = self.api.IoStatus()
        status = self.api.n.NtSetInformationFile(handle, ctypes.byref(io),
                                                 ctypes.byref(info), ctypes.sizeof(info), 13)
        if status < 0:
            raise _nt_error(self.api, status, "delete_failed")

    def names(self, root) -> list[str]:
        names = []
        buffer = ctypes.create_string_buffer(65536)
        restart = True
        while True:
            io = self.api.IoStatus()
            status = self.api.n.NtQueryDirectoryFile(root.raw, None, None, None,
                                                     ctypes.byref(io), buffer, len(buffer),
                                                     12, False, None, restart)
            if status & 0xffffffff == 0x80000006:
                return names
            if status < 0:
                raise _nt_error(self.api, status, "list_failed")
            end = int(io.Information)
            offset = 0
            while True:
                if offset + 12 > end:
                    raise WindowsFsRefusal("directory_entry_invalid")
                next_offset = w.DWORD.from_buffer(buffer, offset).value
                length = w.DWORD.from_buffer(buffer, offset + 8).value
                if length % 2 or offset + 12 + length > end:
                    raise WindowsFsRefusal("directory_entry_invalid")
                name = buffer.raw[offset + 12:offset + 12 + length].decode("utf-16-le")
                if name not in (".", ".."):
                    names.append(name)
                if not next_offset:
                    break
                if next_offset < 12 or offset + next_offset > end:
                    raise WindowsFsRefusal("directory_entry_invalid")
                offset += next_offset
            restart = False


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate journal key")
        result[key] = value
    return result


class WindowsJournal:
    def __init__(self, root: Path):
        if sys.platform != "win32":
            raise OSError("Windows journal requires Windows")
        self.root = Path(root)
        self.fs = WindowsHistoryFs()
        self.native = _Native(self.fs)

    @staticmethod
    def _name(sid: str) -> str:
        if type(sid) is not str or _SID.fullmatch(sid) is None:
            raise ValueError("invalid browser session ID")
        return sid + ".json"

    def _file(self, sid: str) -> Path:
        return self.root / self._name(sid)

    def _verify_root_name(self, parent, held) -> None:
        current = self.fs.open_child(parent, self.root.name, directory=True)
        if current is None:
            raise WindowsFsRefusal("name_changed")
        with current:
            if current.stamp.identity != held.stamp.identity:
                raise WindowsFsRefusal("name_changed")

    @contextmanager
    def _root(self, *, create=False):
        if not self.root.is_absolute() or self.root.anchor.startswith("\\\\"):
            raise ValueError("journal root must be a local absolute path")
        try:
            parent = self.fs.open_root(str(self.root.parent))
        except WindowsFsRefusal as error:
            if not create and error.reason == "root_missing":
                yield None
                return
            raise
        with parent:
            raw = self.native.open(parent, self.root.name, directory=True)
            if raw is None and create:
                try:
                    raw = self.native.open(parent, self.root.name, create=True, directory=True)
                except OSError as error:
                    if getattr(error, "winerror", None) != 183:
                        raise
                    raw = self.native.open(parent, self.root.name, directory=True)
                if raw is None:
                    raise WindowsFsRefusal("root_missing")
            if raw is None:
                yield None
                return
            try:
                stamp = self.native.check(raw, directory=True,
                                          volume=parent.stamp.identity.volume_serial)
            except BaseException:
                self.fs.api.close(raw)
                raise
            held = HeldHandle(self.fs.api, raw, stamp)
            with held:
                self._verify_root_name(parent, held)
                self.fs.verify_mount(parent)
                try:
                    yield held
                finally:
                    self._verify_root_name(parent, held)
                    self.fs.verify_mount(parent)

    def entries(self) -> list[Path]:
        with self._root() as root:
            return [] if root is None else [self.root / name for name in self.native.names(root)
                                            if _SCRATCH.fullmatch(name) is None]

    def write(self, sid: str, record: dict) -> None:
        name = self._name(sid)
        if type(record) is not dict:
            raise ValueError("invalid journal record")
        try:
            data = json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")
        except TypeError as error:
            raise ValueError("invalid journal record") from error
        if len(data) > _CAP:
            raise ValueError("journal record too large")
        json.loads(data, object_pairs_hook=_json_pairs)
        with self._root(create=True) as root:
            if root is None:
                raise WindowsFsRefusal("root_missing")
            existing = self.fs.open_child(root, name, directory=False)
            if existing is not None:
                with existing:
                    self.fs.verify_private_acl(existing)
                    self.fs.verify_name(root, name, existing)
            temporary = "." + sid + "." + secrets.token_hex(8)
            raw = self.native.open(root, temporary, create=True)
            published = False
            created_stamp = None
            try:
                created_stamp = self.native.check(raw, directory=False,
                                                  volume=root.stamp.identity.volume_serial)
                self.native.write(raw, data)
                for attempt in range(10):
                    try:
                        self.native.rename(raw, root, name)
                        break
                    except OSError as error:
                        if getattr(error, "winerror", None) not in (5, 32) or attempt == 9:
                            raise
                        time.sleep(0.01)
                published = True
            finally:
                self.fs.api.close(raw)
                if not published and created_stamp is not None:
                    scratch = self.native.open(root, temporary)
                    if scratch is not None:
                        try:
                            if self.native.check(scratch, directory=False,
                                                 volume=root.stamp.identity.volume_serial).identity != created_stamp.identity:
                                raise WindowsFsRefusal("scratch_changed")
                            self.native.delete(scratch)
                        finally:
                            self.fs.api.close(scratch)
            current = self.fs.open_child(root, name, directory=False)
            if current is None:
                raise WindowsFsRefusal("name_changed")
            with current:
                self.fs.verify_private_acl(current)
                self.fs.verify_name(root, name, current)
                if current.stamp.identity != created_stamp.identity:
                    raise WindowsFsRefusal("published_changed")
            self.native.flush(root.raw)

    def read(self, path: Path) -> dict:
        path = Path(path)
        if path.parent != self.root or _NAME.fullmatch(path.name) is None:
            raise ValueError("invalid journal path")
        with self._root() as root:
            if root is None:
                raise FileNotFoundError(path)
            child = self.fs.open_child(root, path.name, directory=False)
            if child is None:
                raise FileNotFoundError(path)
            with child:
                self.fs.verify_private_acl(child)
                self.fs.verify_name(root, path.name, child)
                data = self.fs.read_exact_bounded(child, _CAP)
                self.fs.verify_name(root, path.name, child)
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_json_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant")))
        if type(value) is not dict:
            raise ValueError("invalid journal record")
        return value

    def remove(self, sid: str) -> None:
        name = self._name(sid)
        with self._root() as root:
            if root is None:
                return
            child = self.native.open(root, name)
            if child is None:
                return
            try:
                stamp = self.native.check(child, directory=False,
                                          volume=root.stamp.identity.volume_serial)
                current = self.native.open(root, name)
                if current is None:
                    raise WindowsFsRefusal("name_changed")
                try:
                    if self.native.check(current, directory=False,
                                         volume=root.stamp.identity.volume_serial).identity != stamp.identity:
                        raise WindowsFsRefusal("name_changed")
                finally:
                    self.fs.api.close(current)
                self.native.delete(child)
            finally:
                self.fs.api.close(child)
            self.native.flush(root.raw)
