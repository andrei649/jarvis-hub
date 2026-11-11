"""Windows DACL facts that ``st_mode`` cannot express.

POSIX ``st_mode`` is the permission contract. On Windows, CPython sets
``S_IWOTH`` for every file that is not read-only, so a mode of ``0o600`` is
not something ``os.stat`` can report. The contract there is Everyone's
(``S-1-1-0``) access mask.

Write rights are decided per bit. A DENY ACE for DELETE does not cancel an
ALLOW of ``FILE_WRITE_DATA``. At one precedence, deny wins over allow. Explicit
ACEs outrank inherited ones. ``INHERIT_ONLY`` ACEs do not apply to the object
they are attached to, and an inherited ACE that names only the other object
kind (a file ACE on a directory, or a directory ACE on a file) does not apply.
A NULL DACL, an unreadable DACL, or an Everyone ACE whose type this reader
cannot interpret is treated as granting the right (fail closed).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# File and standard rights. GENERIC_* are expanded through the file mapping
# before a bit is tested, so an allow of GENERIC_WRITE is FILE_WRITE_DATA.
FILE_READ_DATA = 0x1
FILE_WRITE_DATA = 0x2
FILE_APPEND_DATA = 0x4
FILE_READ_EA = 0x8
FILE_WRITE_EA = 0x10
FILE_EXECUTE = 0x20
FILE_DELETE_CHILD = 0x40
FILE_READ_ATTRIBUTES = 0x80
FILE_WRITE_ATTRIBUTES = 0x100
DELETE = 0x10000
WRITE_DAC = 0x40000
WRITE_OWNER = 0x80000
GENERIC_ALL = 0x10000000
GENERIC_EXECUTE = 0x20000000
GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000

_FILE_ALL_ACCESS = 0x1F01FF
_FILE_GENERIC_WRITE = 0x120116
_FILE_GENERIC_READ = 0x120089
_FILE_GENERIC_EXECUTE = 0x1200A0

_OBJECT_INHERIT = 0x1
_CONTAINER_INHERIT = 0x2
_INHERIT_ONLY = 0x8
_INHERITED = 0x10

_ACCESS_ALLOWED = 0
_ACCESS_DENIED = 1
# Audit and alarm ACEs do not grant or deny access.
_NON_ACCESS_TYPES = frozenset({2, 3, 7, 8})

_WRITE_BITS = (
    FILE_WRITE_DATA, FILE_APPEND_DATA, FILE_WRITE_EA, FILE_WRITE_ATTRIBUTES,
    FILE_DELETE_CHILD, DELETE, WRITE_DAC, WRITE_OWNER,
)
_READ_BITS = (FILE_READ_DATA, FILE_READ_EA, FILE_READ_ATTRIBUTES, FILE_EXECUTE)


class _Unreadable(Exception):
    """The DACL could not be interpreted. Callers fail closed."""


def _expand(mask: int) -> int:
    specific = mask
    if mask & GENERIC_ALL:
        specific |= _FILE_ALL_ACCESS
    if mask & GENERIC_WRITE:
        specific |= _FILE_GENERIC_WRITE
    if mask & GENERIC_READ:
        specific |= _FILE_GENERIC_READ
    if mask & GENERIC_EXECUTE:
        specific |= _FILE_GENERIC_EXECUTE
    return specific


def _applies(flags: int, *, directory: bool) -> bool:
    """Whether this ACE controls the object itself, not only its children."""
    if flags & _INHERIT_ONLY:
        return False
    if flags & _INHERITED:
        to_files = bool(flags & _OBJECT_INHERIT)
        to_dirs = bool(flags & _CONTAINER_INHERIT)
        if to_files != to_dirs:
            if directory and not to_dirs:
                return False
            if not directory and not to_files:
                return False
    return True


def everyone_write_effective(aces: list[tuple[int, int, int]], *, directory: bool) -> bool:
    """Whether Everyone's ACEs leave any write bit allowed.

    Each item is ``(ace_type, ace_flags, mask)`` and is already known to name
    Everyone. An access ACE this function cannot interpret is writable.
    """
    tracked: list[tuple[int, int, int]] = []
    for ace_type, flags, mask in aces:
        if not _applies(flags, directory=directory):
            continue
        if ace_type in _NON_ACCESS_TYPES:
            continue
        if ace_type not in (_ACCESS_ALLOWED, _ACCESS_DENIED):
            return True
        tracked.append((ace_type, flags, _expand(mask)))
    return any(_bit_allowed(bit, tracked) for bit in _WRITE_BITS)


def everyone_read_effective(aces: list[tuple[int, int, int]], *, directory: bool) -> bool:
    """Same precedence as :func:`everyone_write_effective`, for read bits."""
    tracked: list[tuple[int, int, int]] = []
    for ace_type, flags, mask in aces:
        if not _applies(flags, directory=directory):
            continue
        if ace_type in _NON_ACCESS_TYPES:
            continue
        if ace_type not in (_ACCESS_ALLOWED, _ACCESS_DENIED):
            return True
        tracked.append((ace_type, flags, _expand(mask)))
    return any(_bit_allowed(bit, tracked) for bit in _READ_BITS)


def _bit_allowed(bit: int, aces: list[tuple[int, int, int]]) -> bool:
    """Explicit deny, then explicit allow, then inherited deny, then inherited allow.

    Deny wins over allow at the same precedence even when the allow ACE is
    earlier in the DACL.
    """
    explicit_deny = explicit_allow = inherited_deny = inherited_allow = False
    for ace_type, flags, mask in aces:
        if not mask & bit:
            continue
        inherited = bool(flags & _INHERITED)
        denied = ace_type == _ACCESS_DENIED
        if not inherited and denied:
            explicit_deny = True
        elif not inherited and not denied:
            explicit_allow = True
        elif inherited and denied:
            inherited_deny = True
        else:
            inherited_allow = True
    if explicit_deny:
        return False
    if explicit_allow:
        return True
    if inherited_deny:
        return False
    return inherited_allow


def everyone_rights(path: Path | str) -> frozenset[str]:
    """``read`` and/or ``write`` when Everyone has that access.

    On POSIX this is ``S_IROTH`` / ``S_IWOTH``. On Windows it is the DACL.
    Unreadable metadata reports both rights.
    """
    if os.name != "nt":
        try:
            mode = os.stat(path).st_mode
        except OSError:
            return frozenset({"read", "write"})
        rights: set[str] = set()
        if mode & stat.S_IROTH:
            rights.add("read")
        if mode & stat.S_IWOTH:
            rights.add("write")
        return frozenset(rights)
    try:
        aces, directory = _windows_everyone_aces(Path(path))
    except _Unreadable:
        return frozenset({"read", "write"})
    rights = set()
    if everyone_read_effective(aces, directory=directory):
        rights.add("read")
    if everyone_write_effective(aces, directory=directory):
        rights.add("write")
    return frozenset(rights)


def _windows_everyone_aces(path: Path) -> tuple[list[tuple[int, int, int]], bool]:
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p))
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetAclInformation.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD)
    adv.GetAclInformation.restype = wintypes.BOOL
    adv.GetAce.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    adv.GetAce.restype = wintypes.BOOL
    adv.ConvertStringSidToSidW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
    adv.ConvertStringSidToSidW.restype = wintypes.BOOL
    adv.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    adv.EqualSid.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p

    class AclSize(ctypes.Structure):
        _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD),
                    ("AclBytesFree", wintypes.DWORD)]

    class AceHead(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", wintypes.WORD)]

    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    everyone = ctypes.c_void_p()
    try:
        code = adv.GetNamedSecurityInfoW(
            os.fspath(path), 1, 0x4, ctypes.byref(owner), ctypes.byref(group),
            ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(descriptor))
        if code != 0 or not descriptor.value or not dacl.value:
            raise _Unreadable()
        if not adv.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(everyone)):
            raise _Unreadable()
        info = AclSize()
        if not adv.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            raise _Unreadable()
        aces: list[tuple[int, int, int]] = []
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not adv.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                raise _Unreadable()
            head = ctypes.cast(ace, ctypes.POINTER(AceHead)).contents
            if head.AceType in _NON_ACCESS_TYPES:
                continue
            # Object and callback ACEs put the SID at a flag-dependent offset.
            # Guessing it could skip an Everyone allow, so an ACE this reader
            # cannot interpret fails closed (the file is treated as writable).
            if head.AceType not in (_ACCESS_ALLOWED, _ACCESS_DENIED) or head.AceSize < 16:
                raise _Unreadable()
            mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD)).contents.value
            if not adv.EqualSid(everyone, ace.value + 8):
                continue
            aces.append((head.AceType, head.AceFlags, int(mask)))
        try:
            directory = path.is_dir()
        except OSError:
            raise _Unreadable() from None
        return aces, directory
    except _Unreadable:
        raise
    except (OSError, ctypes.ArgumentError, ValueError):
        raise _Unreadable() from None
    finally:
        if everyone.value:
            kernel.LocalFree(everyone)
        if descriptor.value:
            kernel.LocalFree(descriptor)
