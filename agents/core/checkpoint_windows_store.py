"""Isolated H011 Windows private store lease; no history caller imports this."""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass

from .checkpoint_windows_fs import (
    HeldHandle,
    WindowsFsRefusal,
    WindowsHistoryFs,
    WinFileId,
    WinStamp,
    _close_owned,
    _component,
)

_lock_state = threading.local()


@dataclass(frozen=True)
class StoreLease:
    fs: WindowsHistoryFs
    store: HeldHandle
    lock: HeldHandle

    def verify_named_child(self, name: str, held: HeldHandle, *, directory: bool):
        if held.stamp.is_directory is not directory:
            raise WindowsFsRefusal("object_invalid")
        return self.fs.verify_shared_name(self.store, name, held)

    def open_or_create_index(self) -> HeldHandle:
        self.fs.verify_mount(self.store)
        name = "history.sqlite3"
        index = self.fs.open_shared_child(self.store, name, directory=False)
        if index is None:
            index = self.fs.create_private_child(self.store, name, directory=False)
        if index is None:
            index = self.fs.open_shared_child(self.store, name, directory=False)
        if index is None:
            raise WindowsFsRefusal("index_unavailable")
        try:
            self.fs.verify_private_acl(index)
            self.verify_named_child(name, index, directory=False)
            return index
        except BaseException as error:
            _close_owned(index, error)
            raise

    def verify_index_identity(self, expected: WinFileId) -> WinStamp:
        self.fs.verify_mount(self.store)
        index = self.fs.open_shared_child(self.store, "history.sqlite3",
                                          directory=False)
        if index is None:
            raise WindowsFsRefusal("index_changed")
        with index:
            self.fs.verify_private_acl(index)
            if index.stamp.identity != expected:
                raise WindowsFsRefusal("index_changed")
            self.verify_named_child("history.sqlite3", index, directory=False)
            return index.stamp

    def verify_sqlite_sidecars(self) -> dict[str, WinFileId]:
        """Check effective restricted access; SQLite children may inherit ACEs."""
        self.fs.verify_mount(self.store)
        found: dict[str, WinFileId] = {}
        for suffix in ("-journal", "-wal", "-shm"):
            name = "history.sqlite3" + suffix
            child = self.fs.open_shared_child(self.store, name, directory=False)
            if child is None:
                continue
            with child:
                owner, current, _protected, aces = self.fs.api.acl_info(
                    child.raw, allow_inherited=True)
                allowed = {current, "S-1-5-18", "S-1-5-32-544"}
                if (owner not in allowed or not aces
                        or not any(sid == current and kind == "allow"
                                   for sid, kind in aces)
                        or any(sid not in allowed or kind != "allow"
                               for sid, kind in aces)):
                    raise WindowsFsRefusal("acl_invalid")
                self.verify_named_child(name, child, directory=False)
                found[name] = child.stamp.identity
        self.fs.verify_mount(self.store)
        return found


class WindowsPrivateStore:
    def __init__(self, fs: WindowsHistoryFs | None = None):
        self.fs = fs if fs is not None else WindowsHistoryFs()

    def open_or_create(self, parent: HeldHandle, name: str) -> HeldHandle:
        _component(name)
        self.fs.verify_mount(parent)
        child = self.fs.open_child(parent, name, directory=True)
        if child is None:
            child = self.fs.create_private_child(parent, name, directory=True)
        if child is None:  # Another process won exclusive creation.
            child = self.fs.open_child(parent, name, directory=True)
        if child is None:
            raise WindowsFsRefusal("store_unavailable")
        try:
            self.fs.verify_private_acl(child)
            self.fs.verify_name(parent, name, child)
            self.fs.verify_mount(child)
            return child
        except BaseException as error:
            _close_owned(child, error)
            raise

    @contextlib.contextmanager
    def locked(self, store: HeldHandle):
        if store.raw is None or not store.stamp.is_directory or store.drive is None:
            raise WindowsFsRefusal("handle_invalid")
        self.fs.verify_mount(store)
        self.fs.verify_private_acl(store)
        spelling = store.drive + "\\".join(store.components)
        key = (spelling, store.stamp.identity)
        held = getattr(_lock_state, "held", None)
        if held is None:
            held = {}
            _lock_state.held = held
        if any(other[0] == spelling and other != key for other in held):
            raise WindowsFsRefusal("history_store_changed")
        if key in held:
            lease, count = held[key]
            self.fs.verify_shared_name(store, "history.lock", lease.lock)
            held[key] = (lease, count + 1)
            try:
                yield lease
            finally:
                held[key] = (lease, held[key][1] - 1)
            return
        lock = self.fs.open_shared_child(store, "history.lock", directory=False)
        if lock is None:
            lock = self.fs.create_private_child(store, "history.lock", directory=False)
        if lock is None:
            lock = self.fs.open_shared_child(store, "history.lock", directory=False)
        if lock is None:
            raise WindowsFsRefusal("history_lock_unavailable")
        with lock:
            self.fs.verify_private_acl(lock)
            self.fs.verify_shared_name(store, "history.lock", lock)
            overlap = self.fs.api.lock_exclusive(lock.raw)
            try:
                self.fs.verify_mount(store)
                self.fs.verify_shared_name(store, "history.lock", lock)
                lease = StoreLease(self.fs, store, lock)
                held[key] = (lease, 1)
                try:
                    yield lease
                finally:
                    held.pop(key, None)
            finally:
                self.fs.api.unlock(lock.raw, overlap)
