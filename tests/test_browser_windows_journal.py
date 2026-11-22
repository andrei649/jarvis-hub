"""Native NTFS checks for browser ownership records."""

import os
import subprocess
import sys

import pytest

from agents.core.browser_windows_journal import WindowsJournal
from agents.core.checkpoint_windows_fs import WindowsHistoryFs

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="native Windows NTFS only")
SID = "a" * 32


def _private(path, *, directory):
    fs = WindowsHistoryFs()
    with fs.open_root(str(path.parent)) as parent, fs.open_child(
            parent, path.name, directory=directory) as held:
        fs.verify_private_acl(held)


def test_missing_root_and_private_atomic_round_trip(tmp_path):
    root = tmp_path / "journal"
    journal = WindowsJournal(root)
    assert journal.entries() == []
    assert not root.exists()
    assert WindowsJournal(tmp_path / "missing-parent" / "journal").entries() == []
    journal.write(SID, {"profile": "owned", "native": None})
    path = journal._file(SID)
    assert journal.entries() == [path]
    assert journal.read(path) == {"native": None, "profile": "owned"}
    _private(root, directory=True)
    _private(path, directory=False)
    journal.write(SID, {"profile": "updated", "native": [1, 2]})
    assert journal.read(path)["profile"] == "updated"
    assert journal.entries() == [path]
    journal.remove(SID)
    journal.remove(SID)
    assert journal.entries() == []


def test_invalid_and_ambiguous_records_refuse(tmp_path):
    journal = WindowsJournal(tmp_path / "journal")
    with pytest.raises(ValueError):
        journal.write("../wrong", {})
    with pytest.raises(ValueError):
        journal.write(SID, {"large": "x" * 4096})
    assert journal.entries() == []
    journal.write(SID, {"ok": True})
    path = journal._file(SID)
    for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{'):
        path.write_bytes(payload)
        with pytest.raises((OSError, ValueError)):
            journal.read(path)
    with pytest.raises(ValueError):
        journal.read(tmp_path / "outside.json")


def test_transient_rename_conflict_retries_and_failed_write_preserves_old_record(tmp_path, monkeypatch):
    journal = WindowsJournal(tmp_path / "journal")
    journal.write(SID, {"version": 1})
    path = journal._file(SID)
    native_rename = journal.native.rename
    attempts = 0

    def sharing_once(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        native_rename(*args)

    monkeypatch.setattr(journal.native, "rename", sharing_once)
    journal.write(SID, {"version": 2})
    assert attempts == 2
    assert journal.read(path) == {"version": 2}
    old_bytes = path.read_bytes()

    def failed_write(*_args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(journal.native, "write", failed_write)
    with pytest.raises(OSError, match="simulated write failure"):
        journal.write(SID, {"version": 3})
    assert path.read_bytes() == old_bytes
    assert journal.entries() == [path]


def test_concurrent_root_creation_reopens_private_winner(tmp_path, monkeypatch):
    journal = WindowsJournal(tmp_path / "journal")
    native_open = journal.native.open

    def raced_open(parent, name, *, create=False, directory=False):
        if create and directory:
            raw = native_open(parent, name, create=True, directory=True)
            journal.fs.api.close(raw)
            error = FileExistsError("another writer created the root")
            error.winerror = 183
            raise error
        return native_open(parent, name, create=create, directory=directory)

    monkeypatch.setattr(journal.native, "open", raced_open)
    journal.write(SID, {"winner": True})
    assert journal.read(journal._file(SID)) == {"winner": True}


def test_exact_crash_scratch_is_ignored_but_other_entries_are_reported(tmp_path):
    journal = WindowsJournal(tmp_path / "journal")
    journal.write(SID, {})
    scratch = journal.root / ("." + SID + "." + "f" * 16)
    scratch.write_bytes(b"incomplete")
    unexpected = journal.root / "unexpected.txt"
    unexpected.write_bytes(b"unknown")
    assert set(journal.entries()) == {journal._file(SID), unexpected}


def test_open_write_handle_refuses_post_publish_swap(tmp_path, monkeypatch):
    journal = WindowsJournal(tmp_path / "journal")
    other = "b" * 32
    journal.write(other, {"unrelated": True})
    native_rename = journal.native.rename

    def swapped_publish(handle, root, name):
        native_rename(handle, root, name)
        os.replace(journal._file(other), journal._file(SID))

    monkeypatch.setattr(journal.native, "rename", swapped_publish)
    with pytest.raises(OSError):
        journal.write(SID, {"intended": True})
    assert journal.read(journal._file(other)) == {"unrelated": True}


def test_refuses_hard_link_and_unintended_acl_without_removing_data(tmp_path):
    journal = WindowsJournal(tmp_path / "journal")
    journal.write(SID, {"ok": True})
    path = journal._file(SID)
    linked = tmp_path / "linked.json"
    os.link(path, linked)
    before = path.read_bytes()
    with pytest.raises(OSError):
        journal.read(path)
    with pytest.raises(OSError):
        journal.remove(SID)
    assert path.read_bytes() == linked.read_bytes() == before
    linked.unlink()
    result = subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:R"],
                            capture_output=True, text=True, check=True)
    assert result.returncode == 0
    with pytest.raises(OSError, match="acl_invalid"):
        journal.read(path)
    with pytest.raises(OSError, match="acl_invalid"):
        journal.write(SID, {"changed": True})
    assert path.read_bytes() == before


def test_refuses_root_junction_and_ancestor_junction(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "journal"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(root), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    journal = WindowsJournal(root)
    for action in (journal.entries, lambda: journal.write(SID, {}),
                   lambda: journal.read(journal._file(SID)), lambda: journal.remove(SID)):
        with pytest.raises(OSError, match="reparse"):
            action()
    assert list(outside.iterdir()) == []
    ancestor = tmp_path / "ancestor"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(ancestor), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with pytest.raises(OSError, match="reparse"):
        WindowsJournal(ancestor / "journal").entries()


def test_refuses_shared_root_acl(tmp_path):
    journal = WindowsJournal(tmp_path / "journal")
    journal.write(SID, {"ok": True})
    subprocess.run(["icacls", str(journal.root), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
                   capture_output=True, text=True, check=True)
    with pytest.raises(OSError, match="acl_invalid"):
        journal.entries()
    with pytest.raises(OSError, match="acl_invalid"):
        journal.write(SID, {"changed": True})
