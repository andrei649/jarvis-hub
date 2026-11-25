"""Empty private scratch files for atomic writes and local editor handoffs."""

from __future__ import annotations

import os
import secrets
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


def _verify_windows_acl(info: tuple) -> None:
    from agents.core.checkpoint_windows_fs import WindowsFsRefusal

    owner, current, protected, aces = info
    allowed = {current, "S-1-3-4", "S-1-5-18", "S-1-5-32-544"}
    if (owner != current or not protected or not aces
            or not any(sid in {current, "S-1-3-4"} and kind == "allow" for sid, kind in aces)
            or any(sid not in allowed or kind != "allow" for sid, kind in aces)):
        raise WindowsFsRefusal("acl_invalid")


@lru_cache(maxsize=1)
def _windows_native():
    import ctypes
    from ctypes import wintypes as w

    from agents.core.checkpoint_windows_fs import WindowsHistoryFs

    fs = WindowsHistoryFs()

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", w.BOOL)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD))
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    kernel.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD,
                                    ctypes.POINTER(SecurityAttributes), w.DWORD, w.DWORD, w.HANDLE)
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    return fs.api, advapi, kernel, SecurityAttributes


def _create_windows_private(path: Path) -> int:
    import ctypes

    api, advapi, kernel, SecurityAttributes = _windows_native()
    descriptor = ctypes.c_void_p()
    sddl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;OW)"
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    created = False
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = kernel.CreateFileW(str(path), 0x40000000 | 0x20000, 0x3,
                                    ctypes.byref(attrs), 1, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        created = True
        _verify_windows_acl(api.acl_info(handle))
        return handle
    except BaseException:
        if created:
            kernel.CloseHandle(handle)
            path.unlink(missing_ok=True)
        raise
    finally:
        kernel.LocalFree(descriptor)


def _allocate(target: Path) -> tuple[Path, int | None]:
    target = Path(target)
    if os.name == "nt":
        for _ in range(10):
            stage = target.with_name(f".{target.stem}.{secrets.token_hex(12)}{target.suffix}")
            try:
                return stage, _create_windows_private(stage)
            except FileExistsError:
                continue
        raise FileExistsError("could not allocate private scratch file")
    fd, name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=target.suffix,
                                 dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        raise
    os.close(fd)
    return Path(name), None


def _close_windows_handle(handle: int | None) -> None:
    if handle is not None:
        import ctypes
        if not _windows_native()[2].CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def private_staging_path(target: Path) -> Iterator[Path]:
    """Yield an empty, private scratch path; remove it on exit."""
    stage, handle = _allocate(Path(target))
    try:
        _close_windows_handle(handle)
        yield stage
    finally:
        stage.unlink(missing_ok=True)


def atomic_private_write(target: Path, write, *, exclusive: bool = False) -> None:
    """Keep a verified private file open while writing, then publish it atomically."""
    stage, handle = _allocate(target)
    try:
        try:
            write(stage)
        finally:
            _close_windows_handle(handle)
        if exclusive:
            if os.name == "nt":
                os.rename(stage, target)  # Windows refuses an existing target.
            else:
                os.link(stage, target)  # POSIX rename would overwrite it.
        else:
            for attempt in range(10):
                try:
                    os.replace(stage, target)
                    break
                except PermissionError as error:
                    if os.name != "nt" or error.winerror not in (5, 32) or attempt == 9:
                        raise
                    time.sleep(0.01)
    finally:
        stage.unlink(missing_ok=True)
