"""H315, the eighth review (review-H315i) — its findings, pinned.

- m1: ``_small`` charged a string six times its length for one newline, so multi-line
  answers of a few KiB queued behind large scans again. It counts the exact encoding.
- m2: the relock made ``.lock`` and only then locked it; a start in between took the
  unheld file and removed the live mounts. The new lock is made and locked under a
  staging name, then renamed over ``.lock``.
- m3: another OS user's owner directory (umask 077) made ``_owner_alive`` raise, and the
  hub could not start. It reads as alive, and one unreadable entry never stops a sweep.
- m4: the survivors: a stat error that persists, no lock at start, the walk's early
  exits, an owner directory replaced by a link, a huge negative int.
- nits: an owner path that is no longer a directory, or an fd that is gone, reads as
  lost; an empty file name runs as the default one.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from tests.test_h315g_todo_review import _host_sandbox, _manager
from tests.test_h315h_todo_review import _key

# ── m1: counted as it encodes ────────────────────────────────────────────────────

def test_a_multi_line_answer_of_a_few_kib_is_small():
    from agents.core import tool_rpc_runtime as rt

    log = "2026-09-25 INFO line of a log\n" * 140                 # 4.2 KB, 140 newlines
    assert rt._small({"ok": True, "result": {"text": log}}) is True


def test_quotes_and_backslashes_count_as_they_encode():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small('"' * 9000) is False                         # 18 002 encoded
    assert rt._small("\\" * 9000) is False
    assert rt._small("a" * 9000) is True


def test_a_string_over_the_budget_is_refused_before_it_is_encoded(monkeypatch):
    from agents.core import tool_rpc_runtime as rt

    class Refusing:
        @staticmethod
        def dumps(*args, **kwargs):
            raise AssertionError("encoded")

    monkeypatch.setattr(rt, "json", Refusing)
    assert rt._small("x" * (rt._SCAN_INLINE_BYTES + 1)) is False


def test_a_wide_dict_is_refused_before_it_is_listed():
    from agents.core import tool_rpc_runtime as rt

    class Wide(dict):
        def keys(self):
            raise AssertionError("listed")

    assert rt._small(Wide((i, i) for i in range(20_000))) is False


def test_a_huge_negative_int_is_not_small():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small(-(10 ** 4000)) is False


# ── m2: the name never holds a lock nobody has taken ─────────────────────────────

def test_a_start_during_the_relock_leaves_the_live_mounts(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    live = manager._mount(_key("a"))["rpc_dir"]
    (root / manager._owner / ".lock").unlink()                  # lost: relocked at the next mount
    real, starts = sk._fcntl.flock, []

    def flock(fd, op):
        if not starts:
            starts.append(True)
            _manager(root)                                      # another process's start, in the gap
        return real(fd, op)

    monkeypatch.setattr(sk._fcntl, "flock", flock)
    assert manager._mount(_key("b"))
    monkeypatch.setattr(sk._fcntl, "flock", real)
    assert starts and os.path.isdir(live)
    assert sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_HELD


# ── m3: another user's directory never stops a start ─────────────────────────────

def test_a_directory_that_cannot_be_looked_into_reads_as_alive(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    owner = tmp_path / "p9-0badc0de"
    owner.mkdir()
    real = Path.is_symlink

    def is_symlink(self):
        if self.name == ".lock":
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    assert sk._owner_alive(owner) is True


def test_one_unreadable_entry_never_stops_the_sweep_or_the_start(tmp_path, monkeypatch):
    import time

    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    stale = root / "p8-0ddba11a"
    stale.mkdir(parents=True)
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    blocked = root / "p9-0badc0de"
    blocked.mkdir()
    real = sk._owner_alive

    def owner_alive(path):
        if path.name == blocked.name:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path)

    monkeypatch.setattr(sk, "_owner_alive", owner_alive)
    manager = _manager(root)                                     # starts
    assert blocked.is_dir() and not stale.exists()               # left, and the sweep went on
    assert manager._mount(_key())


# ── m4 (I10, I02, I06): the lock's other states ──────────────────────────────────

def test_a_stat_that_keeps_failing_keeps_the_lock(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    first = manager._owner
    live = manager._mount(_key("a"))["rpc_dir"]
    real = os.stat

    def stat(path, *args, **kwargs):
        if str(path).endswith(os.sep + ".lock"):
            raise OSError(errno.ESTALE, "Stale file handle")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(sk.os, "stat", stat)
    for session in ("b", "c", "d"):
        assert manager._mount(_key(session))
    monkeypatch.setattr(sk.os, "stat", real)
    assert manager._owner == first
    _manager(root)
    assert os.path.isdir(live) and sk._owner_alive(root / first) is True


def test_with_no_lock_at_start_there_is_no_mount(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    monkeypatch.setattr(sk, "_hold_owner_lock", lambda owner: None)     # ENOLCK at start
    manager = _manager(tmp_path / "kernel-rpc")
    assert manager._owner_fd is None
    assert manager._mount(_key()) == {}


def test_an_owner_directory_replaced_by_a_link_is_not_followed(tmp_path):
    import shutil

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    first = manager._owner
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.rmtree(root / first)
    (root / first).symlink_to(elsewhere, target_is_directory=True)
    mount = manager._mount(_key())
    assert manager._owner != first and not mount["rpc_dir"].startswith(str(root / first))
    assert list(elsewhere.iterdir()) == []


# ── n1: states that are lost, not unknown ────────────────────────────────────────

def test_an_owner_path_that_is_a_file_reads_as_lost(tmp_path):
    import shutil

    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    owner = root / manager._owner
    shutil.rmtree(owner)
    owner.write_text("")
    assert sk._lock_state(owner, manager._owner_fd) == sk.LOCK_LOST
    assert manager._mount(_key())                                 # a new directory, not no mount forever


def test_an_fd_that_is_gone_reads_as_lost(tmp_path):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    os.close(manager._owner_fd)
    assert sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_LOST


# ── n3: an empty file name runs as the default ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["", ".", "/"])
async def test_an_empty_file_name_runs_as_the_default(tmp_path, filename):
    sandbox = _host_sandbox(tmp_path)
    result = await sandbox.execute_python("import os, sys\nprint(os.path.basename(sys.argv[0]))",
                                          filename=filename)
    assert result.stdout.strip().startswith("script-") and list(tmp_path.glob("*.py")) == []
