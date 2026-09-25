"""H315, the ninth review (review-H315j) — its findings, pinned.

- m1: a start that opened ``.lock`` before a relock could lock the orphaned old file
  afterwards and remove the live directory. ``_owner_alive`` checks that the file it
  locked is still the one at ``.lock``.
- m2: with the manager's fd gone, ``_mount`` closed the dead fd and raised on every
  kernel start. The close tolerates it, and only EBADF from ``fstat`` reads as lost.
- m3: the survivors: ELOOP, a failed relock's staging file, a root that cannot be
  listed, non-ASCII text, bytes counted as ``str()`` spells them.
- nits: separators are counted; a root this user cannot search gives no mount.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

from tests.test_h315g_todo_review import _manager
from tests.test_h315h_todo_review import _key

# ── m2: a gone fd never breaks a start ───────────────────────────────────────────

def test_a_gone_fd_still_gives_a_mount(tmp_path):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    os.close(manager._owner_fd)
    mount = manager._mount(_key())                               # no EBADF out of here
    assert mount and sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_HELD


def test_an_fstat_error_other_than_ebadf_keeps_the_lock(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)

    def fstat(fd):
        raise OSError(errno.ENOMEM, "Cannot allocate memory")

    monkeypatch.setattr(sk.os, "fstat", fstat)
    assert sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_UNKNOWN


def test_eloop_reads_as_lost(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    real = os.stat

    def stat(path, *args, **kwargs):
        if str(path).endswith(os.sep + ".lock"):
            raise OSError(errno.ELOOP, "Too many levels of symbolic links")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(sk.os, "stat", stat)
    assert sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_LOST


# ── m1: an orphaned file says nothing about its owner ────────────────────────────

def test_a_lock_file_replaced_while_it_is_judged_reads_as_alive(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    owner = tmp_path / "p9-0badc0de"
    owner.mkdir()
    (owner / ".lock").write_text("")                             # unheld: the old file
    real = sk._fcntl.flock

    def flock(fd, op):
        # The owner relocks in between: a new, held file is renamed over .lock.
        (owner / ".lock").unlink()
        (owner / ".lock").write_text("")
        return real(fd, op)

    monkeypatch.setattr(sk._fcntl, "flock", flock)
    assert sk._owner_alive(owner) is True


# ── m3: the relock's staging file and the sweep's root ───────────────────────────

def test_a_failed_relock_leaves_no_staging_file(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    owner = tmp_path / "p1-0badc0de"
    owner.mkdir()

    def flock(fd, op):
        raise BlockingIOError(errno.EWOULDBLOCK, "held")

    monkeypatch.setattr(sk._fcntl, "flock", flock)
    assert sk._relock_in_place(owner) is None
    assert list(owner.iterdir()) == []


def test_a_root_that_cannot_be_listed_never_stops_a_start(tmp_path, monkeypatch):
    root = tmp_path / "kernel-rpc"
    root.mkdir()
    real = Path.iterdir

    def iterdir(self):
        if self == root:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    manager = _manager(root)
    assert manager._owner_fd is not None


def test_non_ascii_text_counts_one_per_character():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small("ăîșț" * 1000) is True                     # 4 000 characters, not 24 000


def test_bytes_count_as_str_spells_them():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small(b"\xff" * 3500) is False                   # "\\xff" each: 17 500 encoded


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_separators_are_counted():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small([""] * 4500) is False                       # '"", ' each: 18 000 encoded
    assert rt._small({str(i): "" for i in range(1500)}) is False  # '"i": "", ' each: ~17 800 encoded


def test_a_root_this_user_cannot_search_gives_no_mount(tmp_path, monkeypatch):
    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    owner = root / manager._owner
    (owner / ".lock").unlink()                                   # lost: the next mount relocks
    real = Path.is_symlink

    def is_symlink(self):
        if self == owner:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    mount = manager._mount(_key())                               # no PermissionError out of here
    assert isinstance(mount, dict)
