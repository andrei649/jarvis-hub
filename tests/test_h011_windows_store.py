"""Isolated H011 Windows private-store lease tests; native probes use temp NTFS."""

from __future__ import annotations

import ctypes
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.core.checkpoint_windows_fs as windows_fs
from agents.core.checkpoint_windows_fs import (
    WindowsFsRefusal,
    WindowsHistoryFs,
    WinFileId,
    WinStamp,
)
from agents.core.checkpoint_windows_store import WindowsPrivateStore


def _stamp(number: int, *, directory: bool) -> WinStamp:
    return WinStamp(WinFileId((1).to_bytes(8, "little"), number.to_bytes(16, "little")),
                    0, 1, directory, False, 10, 11, 0x10 if directory else 0x20, 0)


class FakeStoreApi:
    def __init__(self):
        self.guid = "\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\"
        self.children = {(1, "project", True): 2}
        self.stamps = {1: _stamp(1, directory=True), 2: _stamp(2, directory=True)}
        self.acls = {}
        self.next_raw = 3
        self.calls = []
        self.closed = []
        self.active_lock = set()

    def volume_guid(self, drive):
        return self.guid

    def open_volume_root(self, guid):
        return 1

    def volume_info(self, handle):
        return "NTFS", 0x8

    def open_child(self, parent, name, directory):
        self.calls.append(("open", parent, name, directory))
        if name == "history.lock" and self.active_lock:
            raise WindowsFsRefusal("open_failed:32")
        return self.children.get((parent, name, directory))

    def open_shared_child(self, parent, name, directory):
        self.calls.append(("open_shared", parent, name, directory))
        return self.children.get((parent, name, directory))

    def create_private_child(self, parent, name, directory):
        self.calls.append(("create", parent, name, directory))
        if (parent, name, directory) in self.children:
            return None
        raw = self.next_raw
        self.next_raw += 1
        self.children[(parent, name, directory)] = raw
        self.stamps[raw] = _stamp(raw, directory=directory)
        self.acls[raw] = ("owner", "owner", True, (("owner", "allow"),))
        return raw

    def stamp(self, handle):
        return self.stamps[handle]

    def acl_info(self, handle, *, allow_inherited=False):
        return self.acls[handle]

    def lock_exclusive(self, handle):
        self.calls.append(("lock", handle))
        self.active_lock.add(handle)
        return object()

    def unlock(self, handle, overlap):
        self.calls.append(("unlock", handle))
        self.active_lock.remove(handle)

    def close(self, handle):
        self.closed.append(handle)


def test_fake_typed_native_create_keeps_full_name_and_private_descriptor(monkeypatch):
    """Use fixed Windows field widths even on hosts with four-byte wchar_t."""
    class Unicode(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_uint16), ("MaximumLength", ctypes.c_uint16),
                    ("Buffer", ctypes.c_wchar_p)]

    class ObjAttr(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_uint32), ("RootDirectory", ctypes.c_void_p),
                    ("ObjectName", ctypes.POINTER(Unicode)),
                    ("Attributes", ctypes.c_uint32),
                    ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_size_t), ("Information", ctypes.c_size_t)]

    observed = {}

    def convert(sddl, revision, target, _size):
        observed["sddl"] = sddl
        assert revision == 1
        ctypes.cast(target, ctypes.POINTER(ctypes.c_void_p)).contents.value = 0x1234
        return 1

    def create(result, access, attr_ptr, _io, _allocation, _attributes,
               share, disposition, options, _ea, _ea_length):
        attr = ctypes.cast(attr_ptr, ctypes.POINTER(ObjAttr)).contents
        counted = attr.ObjectName.contents
        pointer = ctypes.c_void_p.from_address(
            ctypes.addressof(counted) + Unicode.Buffer.offset).value
        assert (counted.Length, counted.MaximumLength) == (8, 10)
        assert ctypes.string_at(pointer, 10) == "A😀B".encode("utf-16-le") + b"\0\0"
        assert attr.RootDirectory == 44 and attr.SecurityDescriptor == 0x1234
        assert attr.Attributes & 0x1000 and share == 7 and disposition == 2
        assert access & 0x2 and options & 0x40
        ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p)).contents.value = 55
        return 0

    def free(pointer):
        observed["freed"] = pointer.value

    def utf16_buffer(name):
        encoded = name.encode("utf-16-le") + b"\0\0"
        return (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)

    monkeypatch.setattr(windows_fs.ctypes, "create_unicode_buffer", utf16_buffer)
    api = windows_fs._Win32Api.__new__(windows_fs._Win32Api)
    api._current_sid = lambda: "S-1-5-21-1234"
    api.Unicode, api.ObjAttr, api.IoStatus = Unicode, ObjAttr, IoStatus
    api.w = SimpleNamespace(HANDLE=ctypes.c_void_p)
    api.a = SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=convert)
    api.n = SimpleNamespace(NtCreateFile=create)
    api.k = SimpleNamespace(LocalFree=free)
    assert api.create_private_child(44, "A😀B", False) == 55
    assert observed["sddl"].startswith("O:S-1-5-21-1234D:P")
    assert "(A;OICI;FA;;;SY)" in observed["sddl"]
    assert "(A;OICI;FA;;;BA)" in observed["sddl"]
    assert observed["freed"] == 0x1234


@contextmanager
def _fixture():
    api = FakeStoreApi()
    fs = WindowsHistoryFs(api)
    store = WindowsPrivateStore(fs)
    with fs.open_root(r"C:\project") as parent:
        yield api, fs, store, parent


def test_fake_private_store_creation_and_lock_hold_verified_handles():
    with _fixture() as (api, fs, store, parent):
        with store.open_or_create(parent, "h011-private") as held:
            fs.verify_private_acl(held)
            with store.locked(held) as lease:
                assert lease.store is held
                assert lease.lock.raw == 4
                assert ("lock", 4) in api.calls
            assert ("unlock", 4) in api.calls
        assert 3 in api.closed and 4 in api.closed
        assert ("create", 2, "h011-private", True) in api.calls
        assert ("create", 3, "history.lock", False) in api.calls


def test_fake_broad_existing_store_refuses_before_lock_creation():
    with _fixture() as (api, _fs, store, parent):
        api.children[(2, "h011-private", True)] = 3
        api.stamps[3] = _stamp(3, directory=True)
        api.acls[3] = ("owner", "owner", False, (("owner", "allow"),))
        with pytest.raises(WindowsFsRefusal, match="acl_invalid"):
            store.open_or_create(parent, "h011-private")
        assert 3 in api.closed
        assert not any(call[0] == "lock" for call in api.calls)


@pytest.mark.parametrize("failure,expected", [
    ("wrong_owner", "acl_invalid"),
    ("inherited", "acl_invalid"),
    ("everyone", "acl_invalid"),
    ("reparse", "reparse_or_type_invalid"),
    ("volume", "different_volume"),
])
def test_fake_new_store_fences_refuse_unsafe_created_node(failure, expected):
    with _fixture() as (api, _fs, store, parent):
        original_create = api.create_private_child

        def unsafe_create(parent_raw, name, directory):
            raw = original_create(parent_raw, name, directory)
            if failure == "wrong_owner":
                api.acls[raw] = ("other", "owner", True, (("owner", "allow"),))
            elif failure == "inherited":
                api.acls[raw] = ("owner", "owner", False, (("owner", "allow"),))
            elif failure == "everyone":
                api.acls[raw] = ("owner", "owner", True,
                                 (("owner", "allow"), ("S-1-1-0", "allow")))
            elif failure == "reparse":
                old = api.stamps[raw]
                api.stamps[raw] = WinStamp(old.identity, old.size, old.links,
                                           True, False, 10, 11, 0x400, 0xA000000C)
            else:
                old = api.stamps[raw]
                api.stamps[raw] = WinStamp(
                    WinFileId((2).to_bytes(8, "little"), old.identity.file_id),
                    old.size, old.links, True, False, 10, 11, 0x10, 0)
            return raw

        api.create_private_child = unsafe_create
        with pytest.raises(WindowsFsRefusal, match=expected):
            store.open_or_create(parent, "h011-private")
        assert 3 in api.closed


def test_fake_failed_create_cleanup_exposes_unverified_handle():
    with _fixture() as (api, _fs, store, parent):
        original_create, original_close = api.create_private_child, api.close

        def unsafe_create(parent_raw, name, directory):
            raw = original_create(parent_raw, name, directory)
            api.stamps[raw] = _stamp(raw, directory=False)
            return raw

        def fail_created_close(raw):
            if raw == 3:
                raise WindowsFsRefusal("close_failed:synthetic")
            original_close(raw)

        api.create_private_child = unsafe_create
        api.close = fail_created_close
        with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
            store.open_or_create(parent, "h011-private")
        assert len(caught.value.unverified_handles) == 1
        assert caught.value.unverified_handles[0].raw == 3
        api.close = original_close
        caught.value.unverified_handles[0].close()
        assert 3 in api.closed


def test_fake_lock_failure_closes_new_lock_without_yielding_lease():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held):
        def fail_lock(_raw):
            raise WindowsFsRefusal("lock_failed:synthetic")

        api.lock_exclusive = fail_lock
        with (pytest.raises(WindowsFsRefusal, match="lock_failed"),
              store.locked(held)):
            pytest.fail("lease was admitted")
        assert 4 in api.closed


def test_fake_index_is_created_exclusively_and_verified_under_lease():
    with (_fixture() as (api, fs, store, parent),
          store.open_or_create(parent, "h011-private") as held,
          store.locked(held) as lease):
        with lease.open_or_create_index() as index:
            assert index.stamp.identity == _stamp(5, directory=False).identity
            fs.verify_private_acl(index)
            assert lease.verify_named_child("history.sqlite3", index,
                                            directory=False) == index.stamp
        with lease.open_or_create_index() as reopened:
            assert reopened.stamp.identity == index.stamp.identity
        assert api.calls.count(("create", 3, "history.sqlite3", False)) == 1


def test_fake_same_thread_reentry_reuses_one_os_lock():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held,
          store.locked(held) as outer,
          store.locked(held) as inner):
        assert inner is outer
        assert [call for call in api.calls if call[0] == "lock"] == [("lock", 4)]
    assert [call for call in api.calls if call[0] == "unlock"] == [("unlock", 4)]


def test_fake_same_spelling_changed_store_identity_refuses_reentry():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held,
          store.locked(held)):
        api.children[(2, "h011-private", True)] = 5
        api.stamps[5] = _stamp(5, directory=True)
        api.acls[5] = ("owner", "owner", True, (("owner", "allow"),))
        with (store.open_or_create(parent, "h011-private") as changed,
              pytest.raises(WindowsFsRefusal, match="history_store_changed"),
              store.locked(changed)):
            pytest.fail("changed store was admitted")


def test_fake_index_substitution_refuses_before_sqlite_connect():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held,
          store.locked(held) as lease,
          lease.open_or_create_index() as index):
        expected_id = index.stamp.identity
        api.children[(3, "history.sqlite3", False)] = 6
        api.stamps[6] = _stamp(6, directory=False)
        api.acls[6] = ("owner", "owner", True, (("owner", "allow"),))
        with pytest.raises(WindowsFsRefusal, match="index_changed"):
            lease.verify_index_identity(expected_id)


def test_fake_sidecar_with_outside_access_refuses_without_rejecting_inheritance():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held,
          store.locked(held) as lease):
        api.children[(3, "history.sqlite3-journal", False)] = 5
        api.stamps[5] = _stamp(5, directory=False)
        api.acls[5] = ("owner", "owner", False, (("owner", "allow"),))
        assert lease.verify_sqlite_sidecars() == {
            "history.sqlite3-journal": _stamp(5, directory=False).identity}
        api.acls[5] = ("owner", "owner", False,
                       (("owner", "allow"), ("S-1-1-0", "allow")))
        with pytest.raises(WindowsFsRefusal, match="acl_invalid"):
            lease.verify_sqlite_sidecars()


def test_fake_post_lock_name_change_refuses_and_releases_lock():
    with (_fixture() as (api, _fs, store, parent),
          store.open_or_create(parent, "h011-private") as held):
        original_lock = api.lock_exclusive

        def swap_after_lock(handle):
            overlap = original_lock(handle)
            api.children[(3, "history.lock", False)] = 5
            api.stamps[5] = _stamp(5, directory=False)
            return overlap

        api.lock_exclusive = swap_after_lock
        with (pytest.raises(WindowsFsRefusal, match="name_changed"),
              store.locked(held)):
            pytest.fail("changed lock was admitted")
        assert ("unlock", 4) in api.calls and 4 in api.closed


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_generic_existing_store_refuses_without_rewriting_acl(tmp_path):
    generic = tmp_path / "h011-private"
    generic.mkdir()
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    with (fs.open_root(str(tmp_path)) as parent,
          pytest.raises(WindowsFsRefusal, match="acl_invalid")):
        store.open_or_create(parent, generic.name)
    assert generic.is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_private_store_and_lock_are_owner_only(tmp_path):
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, "h011-private") as held):
        fs.verify_private_acl(held)
        print("private store", sys.getwindowsversion(), sys.version,
              fs.api.volume_info(held.raw), held.stamp.identity,
              fs.api.acl_info(held.raw))
        with store.locked(held) as lease:
            fs.verify_private_acl(lease.lock)
            print("private lock", lease.lock.stamp.identity,
                  fs.api.acl_info(lease.lock.raw))
            assert fs.verify_name(held, "history.lock", lease.lock).identity == (
                lease.lock.stamp.identity)
        with store.open_or_create(parent, "h011-private") as reopened:
            assert reopened.stamp.identity == held.stamp.identity


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_ordinary_sqlite_claim_and_sidecar_privacy(tmp_path):
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    db_path = path / "history.sqlite3"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held,
          store.locked(held) as lease):
        with lease.open_or_create_index() as index:
            expected_id = index.stamp.identity
        assert lease.verify_index_identity(expected_id).identity == expected_id
        with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            print("sqlite journal", db.execute("PRAGMA journal_mode").fetchone()[0],
                  "index", expected_id)
            db.execute("PRAGMA synchronous=FULL")
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            db.execute("CREATE TABLE ops (key TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, payload TEXT)")
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO ops VALUES ('one', 'running')")
            db.commit()  # Claim is durable before the synthetic effect.
            assert db_path.exists() and not (path / "effect.marker").exists()
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO entries VALUES (1, 'selected')")
            sidecar = fs.open_shared_child(held, "history.sqlite3-journal",
                                           directory=False)
            assert sidecar is not None
            with sidecar:
                owner, current, _protected, aces = fs.api.acl_info(
                    sidecar.raw, allow_inherited=True)
                allowed = {current, "S-1-5-18", "S-1-5-32-544"}
                assert owner in allowed
                assert aces and (current, "allow") in aces
                assert all(sid in allowed and kind == "allow" for sid, kind in aces)
                print("sqlite sidecar", sidecar.stamp.identity,
                      (owner, current, _protected, aces))
                lease.verify_named_child("history.sqlite3-journal", sidecar,
                                         directory=False)
            assert "history.sqlite3-journal" in lease.verify_sqlite_sidecars()
            db.commit()
            assert lease.verify_index_identity(expected_id).identity == expected_id
            db.execute("BEGIN IMMEDIATE")
            assert db.execute("SELECT id,payload FROM entries").fetchall() == [
                (1, "selected")]
            with (closing(sqlite3.connect(db_path, timeout=0)) as peer,
                  pytest.raises(sqlite3.OperationalError)):
                peer.execute("INSERT INTO entries VALUES (2, 'late')")
            (path / "effect.marker").write_bytes(b"synthetic")
            db.execute("UPDATE ops SET state='completed' WHERE key='one'")
            db.commit()
        with fs.open_shared_child(held, "history.sqlite3", directory=False) as index:
            assert index.stamp.identity == expected_id
            fs.verify_private_acl(index)
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro",
                                     uri=True, timeout=0)) as reader:
            reader.execute("PRAGMA query_only=ON")
            assert reader.execute("SELECT key,state FROM ops").fetchall() == [
                ("one", "completed")]
            assert reader.execute("SELECT id,payload FROM entries").fetchall() == [
                (1, "selected")]
        assert (path / "effect.marker").read_bytes() == b"synthetic"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_lock_contention_releases_after_holder_death(tmp_path):
    script = """
import pathlib
import sys
from agents.core.checkpoint_windows_fs import WindowsHistoryFs
from agents.core.checkpoint_windows_store import WindowsPrivateStore
fs = WindowsHistoryFs()
store = WindowsPrivateStore(fs)
pathlib.Path(sys.argv[2]).write_text('started')
with fs.open_root(sys.argv[1]) as parent:
    with store.open_or_create(parent, 'h011-private') as held:
        with store.locked(held):
            pathlib.Path(sys.argv[3]).write_text('acquired')
            sys.stdin.read()
"""

    def wait_for(path: Path) -> bool:
        until = time.monotonic() + 6
        while time.monotonic() < until:
            if path.exists():
                return True
            time.sleep(0.02)
        return False

    def start(prefix: str):
        return subprocess.Popen([sys.executable, "-c", script, str(tmp_path),
                                 str(tmp_path / f"{prefix}.started"),
                                 str(tmp_path / f"{prefix}.acquired")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    first = start("first")
    second = None
    third = None
    try:
        assert wait_for(tmp_path / "first.acquired"), first.poll()
        second = start("second")
        assert wait_for(tmp_path / "second.started"), second.poll()
        time.sleep(0.2)
        assert not (tmp_path / "second.acquired").exists()
        first.kill()
        first.communicate(timeout=5)
        assert wait_for(tmp_path / "second.acquired"), second.poll()
        assert second.stdin is not None
        second.stdin.close()
        second.wait(timeout=5)
        assert second.returncode == 0, second.stderr.read() if second.stderr else ""
        third = start("third")
        assert wait_for(tmp_path / "third.acquired"), third.poll()
        assert third.stdin is not None
        third.stdin.close()
        third.wait(timeout=5)
        assert third.returncode == 0, third.stderr.read() if third.stderr else ""
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=5)
        if second is not None and second.poll() is None:
            second.kill()
            second.communicate(timeout=5)
        if third is not None and third.poll() is None:
            third.kill()
            third.communicate(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_unsafe_index_and_sidecar_hardlinks_refuse_before_connect(tmp_path):
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    db_path = path / "history.sqlite3"
    parked = path / "parked-index"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held,
          store.locked(held) as lease):
        with lease.open_or_create_index() as index:
            expected_id = index.stamp.identity
        os.replace(db_path, parked)
        os.link(outside, db_path)
        with pytest.raises(WindowsFsRefusal, match="object_invalid"):
            lease.verify_index_identity(expected_id)
        assert outside.read_bytes() == b"outside-sentinel"
        os.unlink(db_path)
        os.replace(parked, db_path)
        os.link(outside, path / "history.sqlite3-journal")
        with pytest.raises(WindowsFsRefusal, match="object_invalid"):
            lease.verify_sqlite_sidecars()
        assert outside.read_bytes() == b"outside-sentinel"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_store_and_post_lock_name_substitution_refuse(tmp_path):
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held):
        os.replace(path, tmp_path / "parked-store")
        with (pytest.raises(WindowsFsRefusal, match="root_missing|mount_changed"),
              store.locked(held)):
            pytest.fail("renamed store was admitted")
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held):
        original_lock = fs.api.lock_exclusive

        def swap_after_lock(handle):
            overlap = original_lock(handle)
            os.replace(path / "history.lock", path / "parked-lock")
            os.link(outside, path / "history.lock")
            return overlap

        fs.api.lock_exclusive = swap_after_lock
        with (pytest.raises(WindowsFsRefusal, match="object_invalid|name_changed"),
              store.locked(held)):
            pytest.fail("changed lock was admitted")
    assert outside.read_bytes() == b"outside-sentinel"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_post_claim_index_substitution_keeps_running_claim(tmp_path):
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    db_path = path / "history.sqlite3"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held,
          store.locked(held) as lease):
        with lease.open_or_create_index() as index:
            expected_id = index.stamp.identity
        with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE ops (key TEXT PRIMARY KEY, state TEXT)")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO ops VALUES ('swap', 'running')")
        os.replace(db_path, path / "parked-index")
        os.link(outside, db_path)
        with pytest.raises(WindowsFsRefusal, match="object_invalid"):
            lease.verify_index_identity(expected_id)
        assert outside.read_bytes() == b"outside-sentinel"
        assert not (path / "effect.marker").exists()
        with closing(sqlite3.connect(path / "parked-index", timeout=0)) as saved:
            assert saved.execute("SELECT key,state FROM ops").fetchall() == [
                ("swap", "running")]


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_guard_sidecar_substitution_refuses_before_effect(tmp_path):
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    db_path = path / "history.sqlite3"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held,
          store.locked(held) as lease):
        with lease.open_or_create_index():
            pass
        with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE ops (key TEXT PRIMARY KEY, state TEXT)")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO ops VALUES ('guard', 'running')")
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            os.link(outside, path / "history.sqlite3-journal")
            with pytest.raises(WindowsFsRefusal, match="object_invalid"):
                lease.verify_sqlite_sidecars()
            db.rollback()
        assert outside.read_bytes() == b"outside-sentinel"
        assert not (path / "effect.marker").exists()
        with closing(sqlite3.connect(db_path, timeout=0)) as saved:
            assert saved.execute("SELECT key,state FROM ops").fetchall() == [
                ("guard", "running")]


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_committed_claim_survives_crash_without_replay(tmp_path):
    script = """
import os
import pathlib
import sqlite3
import sys
from contextlib import closing
from agents.core.checkpoint_windows_fs import WindowsHistoryFs
from agents.core.checkpoint_windows_store import WindowsPrivateStore
root = pathlib.Path(sys.argv[1])
fs = WindowsHistoryFs()
store = WindowsPrivateStore(fs)
with fs.open_root(str(root)) as parent:
    with store.open_or_create(parent, 'h011-private') as held:
        with store.locked(held) as lease:
            with lease.open_or_create_index():
                pass
            with closing(sqlite3.connect(root / 'h011-private' / 'history.sqlite3')) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE ops (key TEXT PRIMARY KEY, state TEXT)')
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                db.execute("INSERT INTO ops VALUES ('crash', 'running')")
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                db.execute("INSERT INTO ops VALUES ('uncommitted', 'running')")
                os._exit(77)
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                           capture_output=True, text=True, check=False, timeout=10)
    assert child.returncode == 77, child.stderr
    fs = WindowsHistoryFs()
    store = WindowsPrivateStore(fs)
    path = tmp_path / "h011-private"
    with (fs.open_root(str(tmp_path)) as parent,
          store.open_or_create(parent, path.name) as held,
          store.locked(held) as lease):
        with lease.open_or_create_index() as index:
            lease.verify_index_identity(index.stamp.identity)
        assert "history.sqlite3-journal" in lease.verify_sqlite_sidecars()
        with closing(sqlite3.connect(path / "history.sqlite3", timeout=0)) as recovery:
            assert recovery.execute("SELECT key,state FROM ops").fetchall() == [
                ("crash", "running")]
            print("sqlite recovery", recovery.execute(
                "SELECT key,state FROM ops").fetchall())
        with closing(sqlite3.connect(f"file:{(path / 'history.sqlite3').as_posix()}"
                                     "?mode=ro", uri=True, timeout=0)) as reader:
            assert reader.execute("SELECT key,state FROM ops").fetchall() == [
                ("crash", "running")]
        assert not (path / "effect.marker").exists()
