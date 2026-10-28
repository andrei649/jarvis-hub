"""Timestamp helpers for controlled, non-concurrently-mutated test fixtures."""
import os
import stat
import time
from pathlib import Path


def _windows_kernel():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                  ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    kernel.SetFileTime.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _windows_error():
    import ctypes

    return ctypes.WinError(ctypes.get_last_error())


def _stamp_windows_link(path: Path, timestamp: float) -> None:
    import ctypes
    from ctypes import wintypes

    ticks = int(timestamp * 10_000_000) + 116444736000000000
    if not 0 <= ticks <= 0xFFFFFFFFFFFFFFFF:
        raise OverflowError("fixture timestamp is outside FILETIME range")
    value = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
    kernel = _windows_kernel()
    # WRITE_ATTRIBUTES; shared read/write/delete; OPEN_EXISTING; open the reparse
    # point itself, with directory handles permitted. Never open its target.
    handle = kernel.CreateFileW(str(path), 0x100, 7, None, 3, 0x02200000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise _windows_error()
    try:
        if not kernel.SetFileTime(handle, None, ctypes.byref(value), ctypes.byref(value)):
            raise _windows_error()
    finally:
        if not kernel.CloseHandle(handle):
            raise _windows_error()


def _stamp_link(path: Path, timestamp: float) -> None:
    if os.name == "nt":
        _stamp_windows_link(path, timestamp)
    else:
        os.utime(path, (timestamp, timestamp), follow_symlinks=False)


def age_tree(path: Path, hours: float) -> None:
    """Age owned fixture entries and link metadata, refusing a linked root.

    This path-based helper is not a runtime security primitive. Call it only while
    the test owns the tree and no concurrent process or thread can change it.
    """
    def linked(entry: Path) -> bool:
        info = entry.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse)

    path = Path(path)
    if linked(path):
        raise ValueError("timestamp fixture root is a link or reparse point")
    entries = []
    links = []
    for directory, dirnames, filenames in os.walk(path, followlinks=False):
        owned_dirs = []
        for name in dirnames:
            entry = Path(directory) / name
            if linked(entry):
                links.append(entry)
            else:
                owned_dirs.append(name)
                entries.append(entry)
        dirnames[:] = owned_dirs
        for name in filenames:
            entry = Path(directory) / name
            (links if linked(entry) else entries).append(entry)
    entries.append(path)

    then = time.time() - hours * 3600
    for entry in links:
        _stamp_link(entry, then)
    for entry in entries:
        os.utime(entry, (then, then))
