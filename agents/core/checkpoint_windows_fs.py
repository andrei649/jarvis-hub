"""Isolated native Windows H011 filesystem primitives.

The private-child and lock primitives are used only by the isolated store tests.
This module does not enable checkpoint history or import a production caller.
Native APIs load only when a WindowsHistoryFs is constructed without an injected API.
"""

from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass

_MAX_READ = 16 * 1024 * 1024
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset({"CON", "CONIN$", "CONOUT$", "CLOCK$", "PRN", "AUX", "NUL",
                       *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})
_GUID = re.compile(r"\\\\\?\\Volume\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}"
                   r"-[0-9a-fA-F]{12}\}\\\Z")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class WindowsFsRefusal(OSError):
    def __init__(self, reason: str, *,
                 unverified_handles: tuple[HeldHandle | _RawOwner, ...] = ()):
        self.reason = reason
        self.unverified_handles = unverified_handles
        super().__init__(reason)


@dataclass(frozen=True)
class WinFileId:
    volume_serial: bytes
    file_id: bytes

    def __post_init__(self):
        if len(self.volume_serial) != 8 or len(self.file_id) != 16:
            raise WindowsFsRefusal("identity_unavailable")


@dataclass(frozen=True)
class WinStamp:
    identity: WinFileId
    size: int
    links: int
    is_directory: bool
    delete_pending: bool
    last_write_100ns: int
    change_100ns: int
    attributes: int
    reparse_tag: int


class HeldHandle:
    def __init__(self, api, raw: int, stamp: WinStamp, *, drive: str | None = None,
                 guid: str | None = None, components: tuple[str, ...] = ()):
        self._api = api
        self.raw = raw
        self.stamp = stamp
        self.drive = drive
        self.guid = guid
        self.components = components

    def close(self) -> None:
        if self.raw is not None:
            self._api.close(self.raw)
            self.raw = None

    def __enter__(self):
        if self.raw is None:
            raise WindowsFsRefusal("handle_closed")
        return self

    def __exit__(self, _type, error, _traceback):
        _close_owned(self, error)


class _RawOwner:
    """Own an acquired handle until close succeeds or ownership is transferred."""

    def __init__(self, api, raw: int):
        self._api = api
        self.raw = raw

    def close(self) -> None:
        if self.raw is not None:
            self._api.close(self.raw)
            self.raw = None


def _close_owned(owner: HeldHandle | _RawOwner, cause: BaseException | None = None) -> None:
    """Never lose an internal owner when its close result is uncertain."""
    try:
        owner.close()
    except BaseException as close_error:
        prior = cause.unverified_handles if isinstance(cause, WindowsFsRefusal) else ()
        raise WindowsFsRefusal("handle_close_uncertain",
                               unverified_handles=(*prior, owner)) from (
                                   cause if cause is not None else close_error)


def _utf16_bytes(value: str, reason: str) -> bytes:
    try:
        return value.encode("utf-16-le", errors="strict")
    except UnicodeEncodeError:
        raise WindowsFsRefusal(reason) from None


def _component(name: str) -> str:
    if (type(name) is not str or not name or name in {".", ".."}
            or len(name) > 255 or name.endswith((".", " ")) or _BAD_NAME.search(name)
            or "~" in name or name.split(".", 1)[0].upper().translate(
                str.maketrans("¹²³", "123")) in _RESERVED):
        raise WindowsFsRefusal("invalid_name")
    if len(_utf16_bytes(name, "invalid_name")) // 2 > 255:
        raise WindowsFsRefusal("invalid_name")
    return name


def _path(path: str) -> tuple[str, tuple[str, ...]]:
    if type(path) is not str or len(path) > 32760 or len(path) < 4:
        raise WindowsFsRefusal("invalid_path")
    if len(_utf16_bytes(path, "invalid_path")) // 2 > 32760:
        raise WindowsFsRefusal("invalid_path")
    if not re.match(r"\A[A-Za-z]:\\", path) or "/" in path or path.endswith("\\"):
        raise WindowsFsRefusal("invalid_path")
    parts = tuple(_component(part) for part in path[3:].split("\\"))
    return path[0].upper() + ":\\", parts


def _counted_name(name: str) -> tuple[bytes, int, int]:
    _component(name)
    encoded = _utf16_bytes(name, "invalid_name")
    length = len(encoded)
    maximum = length + 2  # Windows WCHAR NUL; UNICODE_STRING.Length excludes it.
    if maximum > 0xFFFF:
        raise WindowsFsRefusal("invalid_name")
    return encoded, length, maximum


def _marshal_counted_name(counted: tuple[bytes, int, int], buffer,
                          unicode_type, pointer):
    encoded, length, maximum = counted
    if (ctypes.sizeof(buffer) != maximum
            or ctypes.string_at(ctypes.addressof(buffer), length) != encoded
            or ctypes.cast(pointer, ctypes.c_void_p).value != ctypes.addressof(buffer)):
        raise WindowsFsRefusal("name_encoding_unavailable")
    # UNICODE_STRING.Buffer is LPWSTR; the caller retains the backing array.
    return unicode_type(length, maximum, ctypes.cast(pointer, ctypes.c_wchar_p))


class WindowsHistoryFs:
    """Fail-closed read facade; an injected API tests control flow off Windows."""

    def __init__(self, api=None):
        self.api = _Win32Api() if api is None else api

    def _check(self, raw: int, *, directory: bool, volume: bytes | None = None) -> WinStamp:
        stamp = self.api.stamp(raw)
        if (stamp.is_directory is not directory or stamp.delete_pending
                or stamp.attributes & _FILE_ATTRIBUTE_REPARSE_POINT or stamp.reparse_tag):
            raise WindowsFsRefusal("reparse_or_type_invalid" if (
                stamp.attributes & _FILE_ATTRIBUTE_REPARSE_POINT or stamp.reparse_tag
            ) else "object_invalid")
        if volume is not None and stamp.identity.volume_serial != volume:
            raise WindowsFsRefusal("different_volume")
        if stamp.links != 1 or stamp.size < 0:
            raise WindowsFsRefusal("object_invalid")
        return stamp

    def _walk(self, drive: str, guid: str, parts: tuple[str, ...]) -> HeldHandle:
        current = _RawOwner(self.api, self.api.open_volume_root(guid))
        owned = [current]
        try:
            fs_name, flags = self.api.volume_info(current.raw)
            if fs_name != "NTFS" or flags & 0x8 == 0:
                raise WindowsFsRefusal("unsupported_volume")
            root = self._check(current.raw, directory=True)
            volume = root.identity.volume_serial
            for part in parts:
                raw_child = self.api.open_child(current.raw, part, True)
                if raw_child is None:
                    raise WindowsFsRefusal("root_missing")
                child = _RawOwner(self.api, raw_child)
                owned.append(child)
                stamp = self._check(child.raw, directory=True, volume=volume)
                current.close()
                owned.remove(current)
                current = child
            result = HeldHandle(self.api, current.raw, stamp if parts else root,
                                drive=drive, guid=guid, components=parts)
            current.raw = None
            return result
        except BaseException as error:
            cleanup_failed = False
            for handle in reversed(owned):
                try:
                    handle.close()
                except BaseException:
                    cleanup_failed = True
            if cleanup_failed:
                unverified = tuple(handle for handle in owned if handle.raw is not None)
                raise WindowsFsRefusal("handle_close_uncertain",
                                       unverified_handles=unverified) from error
            raise

    def open_root(self, path: str) -> HeldHandle:
        drive, parts = _path(path)
        guid = self.api.volume_guid(drive)
        if type(guid) is not str or _GUID.fullmatch(guid) is None:
            raise WindowsFsRefusal("volume_guid_unavailable")
        root = self._walk(drive, guid, parts)
        try:
            self.verify_mount(root)
            return root
        except BaseException as error:
            _close_owned(root, error)
            raise

    def verify_mount(self, root: HeldHandle) -> None:
        if root.raw is None or root.drive is None or root.guid is None:
            raise WindowsFsRefusal("handle_invalid")
        if self.api.volume_guid(root.drive) != root.guid:
            raise WindowsFsRefusal("mount_changed")
        with self._walk(root.drive, root.guid, root.components) as current:
            if current.stamp.identity != root.stamp.identity:
                raise WindowsFsRefusal("mount_changed")
        if self.api.volume_guid(root.drive) != root.guid:
            raise WindowsFsRefusal("mount_changed")

    def open_child(self, parent: HeldHandle, name: str, *, directory: bool) -> HeldHandle | None:
        _component(name)
        if parent.raw is None or not parent.stamp.is_directory:
            raise WindowsFsRefusal("handle_invalid")
        raw = self.api.open_child(parent.raw, name, directory)
        if raw is None:
            return None
        owner = _RawOwner(self.api, raw)
        try:
            stamp = self._check(owner.raw, directory=directory,
                                volume=parent.stamp.identity.volume_serial)
            result = HeldHandle(self.api, owner.raw, stamp, drive=parent.drive,
                                guid=parent.guid,
                                components=(*parent.components, name))
            owner.raw = None
            return result
        except BaseException as error:
            _close_owned(owner, error)
            raise

    def create_private_child(self, parent: HeldHandle, name: str, *,
                             directory: bool) -> HeldHandle | None:
        _component(name)
        if parent.raw is None or not parent.stamp.is_directory:
            raise WindowsFsRefusal("handle_invalid")
        raw = self.api.create_private_child(parent.raw, name, directory)
        if raw is None:
            return None
        owner = _RawOwner(self.api, raw)
        try:
            stamp = self._check(owner.raw, directory=directory,
                                volume=parent.stamp.identity.volume_serial)
            result = HeldHandle(self.api, owner.raw, stamp, drive=parent.drive,
                                guid=parent.guid,
                                components=(*parent.components, name))
            owner.raw = None
            return result
        except BaseException as error:
            _close_owned(owner, error)
            raise

    def open_shared_child(self, parent: HeldHandle, name: str, *,
                          directory: bool) -> HeldHandle | None:
        """Inspect a named node while a lock or SQLite writer also holds it."""
        _component(name)
        if parent.raw is None or not parent.stamp.is_directory:
            raise WindowsFsRefusal("handle_invalid")
        raw = self.api.open_shared_child(parent.raw, name, directory)
        if raw is None:
            return None
        owner = _RawOwner(self.api, raw)
        try:
            stamp = self._check(owner.raw, directory=directory,
                                volume=parent.stamp.identity.volume_serial)
            result = HeldHandle(self.api, owner.raw, stamp, drive=parent.drive,
                                guid=parent.guid,
                                components=(*parent.components, name))
            owner.raw = None
            return result
        except BaseException as error:
            _close_owned(owner, error)
            raise

    def verify_shared_name(self, parent: HeldHandle, name: str,
                           held: HeldHandle) -> WinStamp:
        if held.raw is None:
            raise WindowsFsRefusal("handle_closed")
        current = self.open_shared_child(parent, name,
                                         directory=held.stamp.is_directory)
        if current is None:
            raise WindowsFsRefusal("name_changed")
        with current:
            if current.stamp != held.stamp:
                raise WindowsFsRefusal("name_changed")
            return current.stamp

    def verify_name(self, parent: HeldHandle, name: str, held: HeldHandle) -> WinStamp:
        if held.raw is None:
            raise WindowsFsRefusal("handle_closed")
        current = self.open_child(parent, name, directory=held.stamp.is_directory)
        if current is None:
            raise WindowsFsRefusal("name_changed")
        with current:
            if current.stamp != held.stamp:
                raise WindowsFsRefusal("name_changed")
            return current.stamp

    def read_exact_bounded(self, file: HeldHandle, cap: int) -> bytes:
        if (file.raw is None or file.stamp.is_directory or type(cap) is not int
                or not 0 <= cap <= _MAX_READ):
            raise WindowsFsRefusal("invalid_read")
        before = self._check(file.raw, directory=False,
                             volume=file.stamp.identity.volume_serial)
        if before.links != 1 or before.size > cap:
            raise WindowsFsRefusal("read_too_large")
        data = self.api.read(file.raw, cap + 1)
        after = self._check(file.raw, directory=False,
                            volume=file.stamp.identity.volume_serial)
        if len(data) != before.size or len(data) > cap or after != before:
            raise WindowsFsRefusal("read_changed")
        return data

    def verify_private_acl(self, handle: HeldHandle) -> None:
        if handle.raw is None:
            raise WindowsFsRefusal("handle_closed")
        owner, current, protected, aces = self.api.acl_info(handle.raw)
        allowed = {current, "S-1-5-18", "S-1-5-32-544"}
        if (owner != current or not protected or not aces
                or not any(sid == current and kind == "allow" for sid, kind in aces)
                or any(sid not in allowed or kind != "allow" for sid, kind in aces)):
            raise WindowsFsRefusal("acl_invalid")


class _Win32Api:
    """Explicit ctypes API; no DLL is imported by this module on macOS."""

    def __init__(self):
        if sys.platform != "win32":
            raise WindowsFsRefusal("unsupported_platform")
        from ctypes import wintypes as w

        self.w = w
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.n = ctypes.WinDLL("ntdll", use_last_error=True)
        self.a = ctypes.WinDLL("advapi32", use_last_error=True)

        class FileId128(ctypes.Structure):
            _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

        class FileIdInfo(ctypes.Structure):
            _fields_ = [("VolumeSerialNumber", ctypes.c_uint64), ("FileId", FileId128)]

        class Basic(ctypes.Structure):
            _fields_ = [(x, ctypes.c_int64) for x in ("CreationTime", "LastAccessTime",
                                                       "LastWriteTime", "ChangeTime")] + [
                ("FileAttributes", w.DWORD)]

        class Standard(ctypes.Structure):
            _fields_ = [("AllocationSize", ctypes.c_int64), ("EndOfFile", ctypes.c_int64),
                        ("NumberOfLinks", w.DWORD), ("DeletePending", w.BOOLEAN),
                        ("Directory", w.BOOLEAN)]

        class AttrTag(ctypes.Structure):
            _fields_ = [("FileAttributes", w.DWORD), ("ReparseTag", w.DWORD)]

        class Unicode(ctypes.Structure):
            _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT),
                        ("Buffer", w.LPWSTR)]

        class ObjAttr(ctypes.Structure):
            _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE),
                        ("ObjectName", ctypes.POINTER(Unicode)), ("Attributes", w.ULONG),
                        ("SecurityDescriptor", ctypes.c_void_p),
                        ("SecurityQualityOfService", ctypes.c_void_p)]

        class IoStatus(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_size_t), ("Information", ctypes.c_size_t)]

        class AclSize(ctypes.Structure):
            _fields_ = [("AceCount", w.DWORD), ("AclBytesInUse", w.DWORD),
                        ("AclBytesFree", w.DWORD)]

        class AceHeader(ctypes.Structure):
            _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                        ("AceSize", w.WORD)]

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]

        self.FileIdInfo, self.Basic, self.Standard, self.AttrTag = FileIdInfo, Basic, Standard, AttrTag
        self.Unicode, self.ObjAttr, self.IoStatus = Unicode, ObjAttr, IoStatus
        self.AclSize, self.AceHeader = AclSize, AceHeader
        self.Overlapped = Overlapped
        self.k.GetVolumeNameForVolumeMountPointW.argtypes = (w.LPCWSTR, w.LPWSTR, w.DWORD)
        self.k.GetVolumeNameForVolumeMountPointW.restype = w.BOOL
        self.k.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                       w.DWORD, w.DWORD, w.HANDLE)
        self.k.CreateFileW.restype = w.HANDLE
        self.k.GetVolumeInformationByHandleW.argtypes = (
            w.HANDLE, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD),
            ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD)
        self.k.GetVolumeInformationByHandleW.restype = w.BOOL
        self.k.GetFileInformationByHandleEx.argtypes = (
            w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        self.k.GetFileInformationByHandleEx.restype = w.BOOL
        self.k.ReadFile.argtypes = (w.HANDLE, ctypes.c_void_p, w.DWORD,
                                    ctypes.POINTER(w.DWORD), ctypes.c_void_p)
        self.k.ReadFile.restype = w.BOOL
        self.k.SetFilePointerEx.argtypes = (w.HANDLE, ctypes.c_int64,
                                            ctypes.c_void_p, w.DWORD)
        self.k.SetFilePointerEx.restype = w.BOOL
        self.k.CloseHandle.argtypes = (w.HANDLE,)
        self.k.CloseHandle.restype = w.BOOL
        self.n.NtCreateFile.argtypes = (
            ctypes.POINTER(w.HANDLE), w.DWORD, ctypes.POINTER(ObjAttr),
            ctypes.POINTER(IoStatus), ctypes.c_void_p, w.DWORD, w.DWORD,
            w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD)
        self.n.NtCreateFile.restype = ctypes.c_long
        self.n.RtlNtStatusToDosError.argtypes = (w.ULONG,)
        self.n.RtlNtStatusToDosError.restype = w.ULONG
        self.a.GetSecurityInfo.argtypes = (
            w.HANDLE, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p))
        self.a.GetSecurityInfo.restype = w.DWORD
        self.a.GetSecurityDescriptorControl.argtypes = (
            ctypes.c_void_p, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD))
        self.a.GetSecurityDescriptorControl.restype = w.BOOL
        self.a.GetAclInformation.argtypes = (ctypes.c_void_p, ctypes.c_void_p, w.DWORD, w.DWORD)
        self.a.GetAclInformation.restype = w.BOOL
        self.a.GetAce.argtypes = (ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p))
        self.a.GetAce.restype = w.BOOL
        self.a.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(w.LPWSTR))
        self.a.ConvertSidToStringSidW.restype = w.BOOL
        self.a.IsValidSid.argtypes = (ctypes.c_void_p,)
        self.a.IsValidSid.restype = w.BOOL
        self.a.GetLengthSid.argtypes = (ctypes.c_void_p,)
        self.a.GetLengthSid.restype = w.DWORD
        self.k.LocalFree.argtypes = (ctypes.c_void_p,)
        self.k.LocalFree.restype = ctypes.c_void_p
        self.k.GetCurrentProcess.restype = w.HANDLE
        self.a.OpenProcessToken.argtypes = (w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE))
        self.a.OpenProcessToken.restype = w.BOOL
        self.a.GetTokenInformation.argtypes = (
            w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD))
        self.a.GetTokenInformation.restype = w.BOOL
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.DWORD))
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
        self.k.LockFileEx.argtypes = (w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                                      ctypes.POINTER(Overlapped))
        self.k.LockFileEx.restype = w.BOOL
        self.k.UnlockFileEx.argtypes = (w.HANDLE, w.DWORD, w.DWORD, w.DWORD,
                                        ctypes.POINTER(Overlapped))
        self.k.UnlockFileEx.restype = w.BOOL

    @staticmethod
    def _fail(reason):
        raise WindowsFsRefusal(f"{reason}:{ctypes.get_last_error()}")

    def close(self, handle):
        if not self.k.CloseHandle(handle):
            self._fail("close_failed")

    def volume_guid(self, drive):
        buf = ctypes.create_unicode_buffer(64)
        if not self.k.GetVolumeNameForVolumeMountPointW(drive, buf, len(buf)):
            self._fail("volume_guid_unavailable")
        return buf.value

    def open_volume_root(self, guid):
        # A trailing slash opens the volume root directory, not the volume device.
        handle = self.k.CreateFileW(guid, 0x80 | 0x20000, 0x1 | 0x2 | 0x4, None,
                                    3, 0x02000000 | 0x00200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            self._fail("volume_root_unavailable")
        return handle

    def volume_info(self, handle):
        flags = self.w.DWORD()
        name = ctypes.create_unicode_buffer(64)
        if not self.k.GetVolumeInformationByHandleW(
                handle, None, 0, None, None, ctypes.byref(flags), name, len(name)):
            self._fail("volume_unavailable")
        return name.value, flags.value

    def open_child(self, parent, name, directory):
        counted = _counted_name(name)
        text = ctypes.create_unicode_buffer(name)
        unicode = _marshal_counted_name(counted, text, self.Unicode, text)
        # OBJ_DONT_REPARSE rejects any reparse during a single-component parse.
        attr = self.ObjAttr(ctypes.sizeof(self.ObjAttr), parent, ctypes.pointer(unicode),
                            0x1000 | 0x40, None, None)
        io = self.IoStatus()
        result = self.w.HANDLE()
        access = 0x80 | 0x20000 | 0x100000 | (0x1 if directory else 0x1)
        options = 0x20 | (0x1 if directory else 0x40 | 0x00200000)
        # A read handle denies concurrent writable opens; existing writers
        # cause a sharing refusal rather than an unstable preimage read.
        share = 0x1 | 0x2 | 0x4 if directory else 0x1 | 0x4
        status = self.n.NtCreateFile(ctypes.byref(result), access, ctypes.byref(attr),
                                     ctypes.byref(io), None, 0, share,
                                     1, options, None, 0)
        if status < 0:
            error = int(self.n.RtlNtStatusToDosError(status & 0xFFFFFFFF))
            if error in (2, 3):
                return None
            if status & 0xFFFFFFFF == 0xC000050B:
                raise WindowsFsRefusal("reparse_encountered")
            raise WindowsFsRefusal(f"open_failed:{error}")
        return result.value

    def open_shared_child(self, parent, name, directory):
        counted = _counted_name(name)
        text = ctypes.create_unicode_buffer(name)
        unicode = _marshal_counted_name(counted, text, self.Unicode, text)
        attr = self.ObjAttr(ctypes.sizeof(self.ObjAttr), parent, ctypes.pointer(unicode),
                            0x1000 | 0x40, None, None)
        io = self.IoStatus()
        result = self.w.HANDLE()
        access = 0x80 | 0x20000 | 0x100000 | 0x1
        options = 0x20 | (0x1 if directory else 0x40 | 0x00200000)
        status = self.n.NtCreateFile(ctypes.byref(result), access, ctypes.byref(attr),
                                     ctypes.byref(io), None, 0, 0x1 | 0x2 | 0x4,
                                     1, options, None, 0)
        if status < 0:
            error = int(self.n.RtlNtStatusToDosError(status & 0xFFFFFFFF))
            if error in (2, 3):
                return None
            if status & 0xFFFFFFFF == 0xC000050B:
                raise WindowsFsRefusal("reparse_encountered")
            raise WindowsFsRefusal(f"open_failed:{error}")
        return result.value

    def create_private_child(self, parent, name, directory):
        counted = _counted_name(name)
        text = ctypes.create_unicode_buffer(name)
        unicode = _marshal_counted_name(counted, text, self.Unicode, text)
        sid = self._current_sid()
        sddl = (f"O:{sid}D:P(A;OICI;FA;;;{sid})"
                "(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")
        descriptor = ctypes.c_void_p()
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None):
            self._fail("acl_unavailable")
        try:
            attr = self.ObjAttr(ctypes.sizeof(self.ObjAttr), parent,
                                ctypes.pointer(unicode), 0x1000 | 0x40,
                                descriptor, None)
            io = self.IoStatus()
            result = self.w.HANDLE()
            # Existing names never open through FILE_CREATE. The returned handle
            # can create children of a new private directory or lock a new file.
            access = 0x80 | 0x20000 | 0x100000 | (0x7 if directory else 0x3)
            options = 0x20 | (0x1 if directory else 0x40)
            status = self.n.NtCreateFile(
                ctypes.byref(result), access, ctypes.byref(attr), ctypes.byref(io),
                None, 0, 0x1 | 0x2 | 0x4, 2, options, None, 0)
            if status < 0:
                if status & 0xFFFFFFFF == 0xC0000035:
                    return None
                error = int(self.n.RtlNtStatusToDosError(status & 0xFFFFFFFF))
                raise WindowsFsRefusal(f"create_failed:{error}")
            return result.value
        finally:
            self.k.LocalFree(descriptor)

    def lock_exclusive(self, handle):
        overlap = self.Overlapped()
        if not self.k.LockFileEx(handle, 0x2, 0, 1, 0, ctypes.byref(overlap)):
            self._fail("lock_failed")
        return overlap

    def unlock(self, handle, overlap):
        if not self.k.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlap)):
            self._fail("unlock_failed")

    def _info(self, handle, info_class, kind):
        value = kind()
        if not self.k.GetFileInformationByHandleEx(
                handle, info_class, ctypes.byref(value), ctypes.sizeof(value)):
            self._fail("identity_unavailable")
        return value

    def stamp(self, handle):
        ident = self._info(handle, 18, self.FileIdInfo)
        basic = self._info(handle, 0, self.Basic)
        standard = self._info(handle, 1, self.Standard)
        tag = self._info(handle, 9, self.AttrTag)
        identity = WinFileId(int(ident.VolumeSerialNumber).to_bytes(8, "little"),
                             bytes(ident.FileId.Identifier))
        return WinStamp(identity, int(standard.EndOfFile), int(standard.NumberOfLinks),
                        bool(standard.Directory), bool(standard.DeletePending),
                        int(basic.LastWriteTime), int(basic.ChangeTime),
                        int(tag.FileAttributes), int(tag.ReparseTag))

    def read(self, handle, limit):
        if not self.k.SetFilePointerEx(handle, 0, None, 0):
            self._fail("read_failed")
        chunks = []
        remaining = limit
        while remaining:
            size = min(remaining, 1024 * 1024)
            buf = ctypes.create_string_buffer(size)
            count = self.w.DWORD()
            if not self.k.ReadFile(handle, buf, size, ctypes.byref(count), None):
                self._fail("read_failed")
            if count.value == 0:
                break
            chunks.append(buf.raw[:count.value])
            remaining -= count.value
        return b"".join(chunks)

    def _sid(self, ptr):
        if not ptr or not self.a.IsValidSid(ptr):
            raise WindowsFsRefusal("acl_invalid")
        output = self.w.LPWSTR()
        if not self.a.ConvertSidToStringSidW(ptr, ctypes.byref(output)):
            self._fail("acl_unavailable")
        try:
            return output.value
        finally:
            self.k.LocalFree(ctypes.cast(output, ctypes.c_void_p))

    def _current_sid(self):
        token = self.w.HANDLE()
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(), 0x8, ctypes.byref(token)):
            self._fail("acl_unavailable")
        try:
            needed = self.w.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if needed.value < ctypes.sizeof(ctypes.c_void_p):
                self._fail("acl_unavailable")
            data = ctypes.create_string_buffer(needed.value)
            if not self.a.GetTokenInformation(token, 1, data, needed.value,
                                              ctypes.byref(needed)):
                self._fail("acl_unavailable")
            return self._sid(ctypes.c_void_p.from_buffer(data).value)
        finally:
            self.close(token)

    def acl_info(self, handle, *, allow_inherited=False):
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        code = self.a.GetSecurityInfo(handle, 1, 0x1 | 0x4, ctypes.byref(owner),
                                       None, ctypes.byref(dacl), None,
                                       ctypes.byref(descriptor))
        if code:
            raise WindowsFsRefusal(f"acl_unavailable:{code}")
        try:
            if not owner.value or not dacl.value or not descriptor.value:
                raise WindowsFsRefusal("acl_invalid")
            control, revision = self.w.WORD(), self.w.DWORD()
            if not self.a.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)):
                self._fail("acl_unavailable")
            acl_size = self.AclSize()
            if not self.a.GetAclInformation(dacl, ctypes.byref(acl_size),
                                             ctypes.sizeof(acl_size), 2):
                self._fail("acl_unavailable")
            aces = []
            for index in range(acl_size.AceCount):
                ace = ctypes.c_void_p()
                if not self.a.GetAce(dacl, index, ctypes.byref(ace)):
                    self._fail("acl_unavailable")
                header = ctypes.cast(ace, ctypes.POINTER(self.AceHeader)).contents
                if (header.AceType != 0 or header.AceSize < 16
                        or (header.AceFlags & 0x10 and not allow_inherited)):
                    raise WindowsFsRefusal("acl_invalid")
                if not self.a.IsValidSid(ace.value + 8):
                    raise WindowsFsRefusal("acl_invalid")
                if self.a.GetLengthSid(ace.value + 8) > header.AceSize - 8:
                    raise WindowsFsRefusal("acl_invalid")
                sid = self._sid(ace.value + 8)
                aces.append((sid, "allow"))
            return self._sid(owner), self._current_sid(), bool(control.value & 0x1000), tuple(aces)
        finally:
            self.k.LocalFree(descriptor)
