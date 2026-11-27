"""Private, incremental FTS5 index for the currently selected vault."""

import os
import sqlite3
from contextlib import contextmanager, suppress
from pathlib import Path


def _private_file(path):
    if os.name != "nt":
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise PermissionError("vault index must be private") from None
        else:
            os.close(fd)
        return
    import ctypes
    from ctypes import wintypes as w

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", w.BOOL)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.OpenProcessToken.argtypes = (w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE))
    adv.OpenProcessToken.restype = w.BOOL
    adv.GetTokenInformation.argtypes = (w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD))
    adv.GetTokenInformation.restype = w.BOOL
    adv.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(w.LPWSTR))
    adv.ConvertSidToStringSidW.restype = w.BOOL
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD))
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    adv.SetFileSecurityW.argtypes = (w.LPCWSTR, w.DWORD, ctypes.c_void_p)
    adv.SetFileSecurityW.restype = w.BOOL
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    token = w.HANDLE()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        needed = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token, 1, buf, needed.value, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_ptr = ctypes.c_void_p.from_buffer(buf).value
        out = w.LPWSTR()
        if not adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = out.value
        finally:
            kernel.LocalFree(ctypes.cast(out, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)
    descriptor = ctypes.c_void_p()
    exists = path.exists()
    sddl = (f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{sid})"
            if exists else f"O:{sid}D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{sid})")
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if path.is_symlink():
            raise PermissionError("vault index must be a plain file")
        if exists:
            if not adv.SetFileSecurityW(str(path), 4, descriptor):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            kernel.CreateFileW.argtypes = (
                w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(SecurityAttributes),
                w.DWORD, w.DWORD, w.HANDLE)
            kernel.CreateFileW.restype = w.HANDLE
            handle = kernel.CreateFileW(str(path), 0x40000000, 0x3, ctypes.byref(attrs),
                                        1, 0x80, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(handle)
    finally:
        kernel.LocalFree(descriptor)


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    _private_file(path)
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA secure_delete=ON")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS notes (
        path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
        title TEXT NOT NULL, tags TEXT NOT NULL, body TEXT NOT NULL,
        links TEXT NOT NULL DEFAULT '[]', digest TEXT NOT NULL DEFAULT '')""")
    if "links" not in {row[1] for row in db.execute("PRAGMA table_info(notes)")}:
        db.execute("ALTER TABLE notes ADD COLUMN links TEXT NOT NULL DEFAULT '[]'")
    if "digest" not in {row[1] for row in db.execute("PRAGMA table_info(notes)")}:
        db.execute("ALTER TABLE notes ADD COLUMN digest TEXT NOT NULL DEFAULT ''")
    db.execute("""CREATE TABLE IF NOT EXISTS hidden (
        path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL)""")
    old_fts = db.execute("SELECT sql FROM sqlite_master WHERE name='search'").fetchone()
    if old_fts and "path UNINDEXED" in old_fts[0]:
        db.execute("DROP TABLE search")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
        path, title, tags, body, tokenize='unicode61 remove_diacritics 2')""")
    with suppress(sqlite3.Error):
        db.execute("INSERT INTO search(search, rank) VALUES('secure-delete', 1)")
    try:
        with db:
            yield db
    finally:
        db.close()


def clear(db):
    db.execute("DELETE FROM search")
    db.execute("DELETE FROM notes")
    db.execute("DELETE FROM hidden")


def put(db, path, mtime_ns, size, title, tags, body, links, digest):
    db.execute("DELETE FROM search WHERE path=?", (path,))
    db.execute("DELETE FROM hidden WHERE path=?", (path,))
    db.execute("""INSERT INTO notes(path, mtime_ns, size, title, tags, body, links, digest)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(path) DO UPDATE SET mtime_ns=excluded.mtime_ns,
                  size=excluded.size, title=excluded.title, tags=excluded.tags, body=excluded.body,
                  links=excluded.links, digest=excluded.digest""",
               (path, mtime_ns, size, title, tags, body, links, digest))
    db.execute("INSERT INTO search(path, title, tags, body) VALUES (?, ?, ?, ?)",
               (path, title, tags, body))


def remove(db, path):
    db.execute("DELETE FROM search WHERE path=?", (path,))
    db.execute("DELETE FROM notes WHERE path=?", (path,))
    db.execute("DELETE FROM hidden WHERE path=?", (path,))


def hide(db, path, mtime_ns, size):
    remove(db, path)
    db.execute("INSERT INTO hidden VALUES (?, ?, ?)", (path, mtime_ns, size))


def ranked_paths(db, terms, limit=100):
    words = [word.replace('"', '') for word in terms if word]
    if not words:
        return []
    query = " OR ".join('"' + word + '"' for word in sorted(words))
    return [row[0] for row in db.execute(
        "SELECT path FROM search WHERE search MATCH ? ORDER BY bm25(search, 3, 6, 3, 1) LIMIT ?",
        (query, limit))]
