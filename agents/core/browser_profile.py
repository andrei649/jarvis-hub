"""Ownership checks for disposable browser profiles."""

from __future__ import annotations

import ctypes
import os
import re
import secrets
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PREFIX = "nerva-browser-"
_NAME = re.compile(r"nerva-browser-[0-9a-f]{32}\Z")


def _root() -> Path:
    path = Path(tempfile.gettempdir()).absolute()
    if os.name == "nt":
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetLongPathNameW.argtypes = (w.LPCWSTR, w.LPWSTR, w.DWORD)
        kernel.GetLongPathNameW.restype = w.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetLongPathNameW(str(path), buffer, len(buffer))
        if not length or length >= len(buffer):
            raise OSError("temp root unavailable")
        return Path(buffer.value)
    return path


def _entry(raw: str | Path) -> Path | None:
    path = Path(raw)
    root = _root()
    valid_name = (_NAME.fullmatch(path.name) is not None if os.name == "nt" else
                  path.name.startswith(PREFIX) and re.fullmatch(r"[A-Za-z0-9_-]+", path.name))
    if not path.is_absolute() or path.parent != root or not valid_name:
        return None
    return path


def _windows_identity(path: Path) -> dict[str, str]:
    from agents.core.checkpoint_windows_fs import WindowsFsRefusal, WindowsHistoryFs
    from agents.core.persistence.private_file import _verify_windows_acl

    fs = WindowsHistoryFs()
    with fs.open_root(str(path.parent)) as root:
        child = fs.open_child(root, path.name, directory=True)
        if child is None:
            raise WindowsFsRefusal("profile_missing")
        with child:
            _verify_windows_acl(fs.api.acl_info(child.raw))
            fs.verify_name(root, path.name, child)
            ident = child.stamp.identity
            return {"volume": ident.volume_serial.hex(), "file_id": ident.file_id.hex(),
                    "root_volume": root.stamp.identity.volume_serial.hex(),
                    "root_file_id": root.stamp.identity.file_id.hex()}


def profile_identity(raw: str | Path) -> dict:
    """Capture a present, direct child profile's stable filesystem identity."""
    path = _entry(raw)
    if path is None:
        raise ValueError("profile_owner_unverified")
    if os.name == "nt":
        return _windows_identity(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("profile_owner_unverified")
    root = path.parent.lstat()
    if not stat.S_ISDIR(root.st_mode):
        raise ValueError("profile_owner_unverified")
    return {"dev": info.st_dev, "ino": info.st_ino,
            "root_dev": root.st_dev, "root_ino": root.st_ino}


def validated_owned_profile(raw: str | Path, identity: dict | None = None) -> Path | None:
    """Return only a live profile whose directory is the recorded object."""
    path = _entry(raw)
    if path is None or (os.name == "nt" and not isinstance(identity, dict)):
        return None
    try:
        current = profile_identity(path)
    except (OSError, ValueError, TypeError):
        return None
    if identity is not None and current != identity:
        return None
    return path


def profile_absent(raw: str | Path, identity: dict | None = None) -> bool:
    """Confirm a valid profile name is absent below the unredirected temp root."""
    path = _entry(raw)
    if path is None or (os.name == "nt" and not isinstance(identity, dict)):
        return False
    try:
        if os.name == "nt":
            from agents.core.checkpoint_windows_fs import WindowsHistoryFs

            fs = WindowsHistoryFs()
            with fs.open_root(str(path.parent)) as root:
                if (root.stamp.identity.volume_serial.hex() != identity.get("root_volume") or
                        root.stamp.identity.file_id.hex() != identity.get("root_file_id")):
                    return False
                child = fs.open_child(root, path.name, directory=True)
                if child is not None:
                    child.close()
                return child is None
        root_info = path.parent.lstat()
        if not stat.S_ISDIR(root_info.st_mode):
            return False
        path.lstat()
        return False
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _create_windows(path: Path) -> None:
    from ctypes import wintypes as w

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", w.BOOL)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD))
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    kernel.CreateDirectoryW.argtypes = (w.LPCWSTR, ctypes.POINTER(SecurityAttributes))
    kernel.CreateDirectoryW.restype = w.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    from agents.core.checkpoint_windows_fs import WindowsHistoryFs

    descriptor = ctypes.c_void_p()
    sid = WindowsHistoryFs().api._current_sid()
    # Protected inheritable DACL: Chrome's descendants stay private too.
    sddl = f"O:{sid}D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{sid})"
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attrs)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def create_owned_profile() -> tuple[Path, dict]:
    """Create a random profile directly below the trusted system temp directory."""
    root = _root()
    if os.name == "nt":
        from agents.core.checkpoint_windows_fs import WindowsHistoryFs

        with WindowsHistoryFs().open_root(str(root)):
            pass
    for _ in range(10):
        path = root / (PREFIX + secrets.token_hex(16))
        try:
            if os.name == "nt":
                _create_windows(path)
            else:
                path.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("profile allocation exhausted")
    # shortcut: identity failure leaves a private temp directory, revisit if failures recur.
    return path, profile_identity(path)


def _no_redirections(path: Path) -> bool:
    """Refuse a profile with links or junctions anywhere inside it."""
    with os.scandir(path) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if (stat.S_ISLNK(info.st_mode) or
                    getattr(info, "st_file_attributes", 0) & 0x400 or
                    getattr(entry, "is_junction", lambda: False)()):
                return False
            if stat.S_ISDIR(info.st_mode) and not _no_redirections(Path(entry.path)):
                return False
    return True


def _guard_handle(path: Path, *, delete_access: bool = False) -> int:
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                    w.DWORD, w.DWORD, w.HANDLE)
    kernel.CreateFileW.restype = w.HANDLE
    access = 0x80 | 0x20000 | (0x10000 if delete_access else 0)
    handle = kernel.CreateFileW(str(path), access, 0x1 | 0x2,
                                None, 3, 0x02000000 | 0x00200000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "profile guard unavailable")
    return handle


@contextmanager
def guard_owned_profile(raw: str | Path, identity: dict | None = None) -> Iterator[Path | None]:
    """Pin the recorded Windows root and profile during process recovery."""
    path = _entry(raw)
    if path is None or (os.name == "nt" and not isinstance(identity, dict)):
        raise ValueError("profile_owner_unverified")
    if profile_absent(path, identity):
        yield None
        return
    if os.name != "nt":
        if validated_owned_profile(path, identity) is None:
            raise ValueError("profile_owner_unverified")
        yield path
        return
    from agents.core.checkpoint_windows_fs import WindowsHistoryFs

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    root_handle = _guard_handle(path.parent)
    try:
        profile_handle = _guard_handle(path, delete_access=True)
        try:
            fs = WindowsHistoryFs()
            root_stamp = fs.api.stamp(root_handle)
            profile_stamp = fs.api.stamp(profile_handle)
            if (not root_stamp.is_directory or root_stamp.attributes & 0x400 or
                    not profile_stamp.is_directory or profile_stamp.attributes & 0x400 or
                    root_stamp.identity.volume_serial.hex() != identity.get("root_volume") or
                    root_stamp.identity.file_id.hex() != identity.get("root_file_id") or
                    profile_stamp.identity.volume_serial.hex() != identity.get("volume") or
                    profile_stamp.identity.file_id.hex() != identity.get("file_id") or
                    validated_owned_profile(path, identity) is None):
                raise ValueError("profile_owner_unverified")
            yield path
        finally:
            if not kernel.CloseHandle(profile_handle):
                raise OSError("profile guard close unverified")
    finally:
        if not kernel.CloseHandle(root_handle):
            raise OSError("profile root guard close unverified")


def _remove_windows(path: Path, identity: dict) -> bool:
    from agents.core.browser_windows_journal import _Native
    from agents.core.checkpoint_windows_fs import HeldHandle, WindowsHistoryFs

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    fs = WindowsHistoryFs()
    native = _Native(fs)

    def delete_children(directory: HeldHandle, directory_path: Path) -> None:
        for name in native.names(directory):
            # Path metadata selects the type only. Open and deletion are relative to
            # the held directory, and the native open refuses any reparse point.
            info = (directory_path / name).lstat()
            is_directory = stat.S_ISDIR(info.st_mode)
            raw = native.open(directory, name, directory=is_directory,
                              share_delete=False)
            if raw is None:
                raise OSError("profile child disappeared")
            try:
                stamp = fs.verified_stamp(raw, directory=is_directory,
                                  volume=directory.stamp.identity.volume_serial)
                child = HeldHandle(fs.api, raw, stamp)
                raw = None
                with child:
                    if is_directory:
                        delete_children(child, directory_path / name)
                    native.delete(child.raw)
            finally:
                if raw is not None:
                    fs.api.close(raw)

    # Denying delete sharing pins both names until handle-based removal.
    root_handle = _guard_handle(path.parent)
    try:
        root_stamp = fs.api.stamp(root_handle)
        if (not root_stamp.is_directory or root_stamp.attributes & 0x400 or
                root_stamp.identity.volume_serial.hex() != identity["root_volume"] or
                root_stamp.identity.file_id.hex() != identity["root_file_id"] or
                validated_owned_profile(path, identity) is None):
            return False
        root = HeldHandle(fs.api, root_handle, root_stamp)
        raw = native.open(root, path.name, directory=True, share_delete=False)
        if raw is None:
            return False
        try:
            stamp = fs.verified_stamp(raw, directory=True,
                              volume=root_stamp.identity.volume_serial)
            if (stamp.identity.volume_serial.hex() != identity["volume"] or
                    stamp.identity.file_id.hex() != identity["file_id"]):
                return False
            profile = HeldHandle(fs.api, raw, stamp)
            raw = None
            with profile:
                delete_children(profile, path)
                native.delete(profile.raw)
            return True
        finally:
            if raw is not None:
                fs.api.close(raw)
    finally:
        if not kernel.CloseHandle(root_handle):
            raise ctypes.WinError(ctypes.get_last_error())


def remove_owned_profile(raw: str | Path, identity: dict | None = None) -> bool:
    """Remove the exact recorded profile; absence is an idempotent success."""
    path = _entry(raw)
    if path is None or (os.name == "nt" and not isinstance(identity, dict)):
        return False
    try:
        path.lstat()
    except FileNotFoundError:
        return profile_absent(path, identity)
    except OSError:
        return False
    if validated_owned_profile(path, identity) is None:
        return False
    try:
        if os.name == "nt":
            import time

            for attempt in range(20):
                try:
                    return _remove_windows(path, identity)
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32, 145) or attempt == 19:
                        return False
                    time.sleep(0.05)
        shutil.rmtree(path)
        return True
    except OSError:
        return False
