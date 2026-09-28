"""H315, the seventh review (review-H315h) — its findings, pinned.

- m1: one failed ``stat`` of the owner lock (ESTALE) made the manager close the fd that
  held it, over live mounts the next start then removed. Only a lock file that is gone or
  replaced reads as lost, and a directory that still stands is locked again in place.
- m2: one scan worker, not four: the scan holds the GIL, so more workers bought no
  throughput and only made the loop wait.
- m3: the survivors — the fork hook, a mount with no ``flock``, ``bytes`` sizes, a raising
  tool that is not a script, a K2 cell's inflated count, a failed lock's staging
  directory, ``_`` at a slice end, a dotless name, dict keys and scalars in the walk.
- nits: the size walk is bounded and counts what encodes large; K2's own refusals open no
  revision and a cell with no mailbox made no calls; a dotted directory leaves nothing.
- Pre-existing: an answer too deep to encode is flagged, never raised out of the broker.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

import pytest

from tests.test_h315g_todo_review import _host_sandbox, _manager


def _key(session="s"):
    from agents.core import session_kernels as sk

    return sk.KernelKey(agent="a", principal="p", session_id=session, data_scope="d")


# ── m1: a lock that was never lost is never given up ─────────────────────────────

def test_one_failed_stat_keeps_the_lock_and_the_live_mount(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    first = manager._owner
    live = manager._mount(_key("a"))["rpc_dir"]
    real, failed = os.stat, []

    def stat(path, *args, **kwargs):
        if str(path).endswith(os.sep + ".lock") and not failed:
            failed.append(path)
            raise OSError(errno.ESTALE, "Stale file handle")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(sk.os, "stat", stat)
    assert manager._mount(_key("b"))
    monkeypatch.setattr(sk.os, "stat", real)
    assert failed and manager._owner == first
    _manager(root)                                        # another process's start sweeps
    assert os.path.isdir(live) and sk._owner_alive(root / first) is True


@pytest.mark.parametrize("error", [PermissionError(errno.EACCES, "denied"), OSError(errno.ENOMEM, "no memory")])
def test_an_error_that_says_nothing_about_the_lock_reads_as_unknown(tmp_path, monkeypatch, error):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)

    def stat(*args, **kwargs):
        raise error

    monkeypatch.setattr(sk.os, "stat", stat)
    assert sk._lock_state(root / manager._owner, manager._owner_fd) == sk.LOCK_UNKNOWN


@pytest.mark.parametrize("how", ["replaced", "deleted"])
def test_a_lock_file_that_went_is_held_again_where_the_mounts_live(tmp_path, how):
    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    first = manager._owner
    live = manager._mount(_key("a"))["rpc_dir"]
    lock = root / first / ".lock"
    lock.unlink()
    if how == "replaced":
        lock.write_text("")                               # same name, a lock nobody holds
    assert manager._mount(_key("b"))["rpc_dir"].startswith(str(root / first))
    assert manager._owner == first and sk._owner_alive(root / first) is True
    _manager(root)
    assert os.path.isdir(live)


def test_a_lock_file_replaced_while_it_is_being_locked_is_not_taken(tmp_path, monkeypatch):
    """Between the rename into place and the re-check another file takes the name: the
    fd locks a file that is no longer at the path, which holds nothing up."""
    from agents.core import session_kernels as sk

    owner = tmp_path / "p1-0badc0de"
    owner.mkdir()
    real = os.replace

    def replace(src, dst):
        real(src, dst)
        Path(dst).unlink()
        Path(dst).write_text("")

    monkeypatch.setattr(sk.os, "replace", replace)
    assert sk._relock_in_place(owner) is None


def test_a_lock_someone_else_holds_takes_a_new_directory(tmp_path):
    import fcntl

    from agents.core import session_kernels as sk

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    first = manager._owner
    lock = root / first / ".lock"
    lock.unlink()
    other = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mount = manager._mount(_key())
        assert manager._owner != first and mount["rpc_dir"].startswith(str(root / manager._owner))
    finally:
        os.close(other)


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="counts open fds through /proc")
def test_switching_locks_leaks_no_fd(tmp_path):
    import shutil

    root = tmp_path / "kernel-rpc"
    manager = _manager(root)
    manager._mount(_key())
    before = len(os.listdir("/proc/self/fd"))
    for turn in range(20):
        owner = root / manager._owner
        if turn % 2:
            shutil.rmtree(owner)                          # a new directory
        else:
            (owner / ".lock").unlink()                    # held again in place
            (owner / ".lock").write_text("")
        assert manager._mount(_key(f"s{turn}"))
    assert len(os.listdir("/proc/self/fd")) == before


def test_with_no_flock_a_kernel_still_gets_a_mount(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    monkeypatch.setattr(sk, "_fcntl", None)
    manager = _manager(tmp_path / "kernel-rpc")
    assert manager._owner_fd is None
    assert os.path.isdir(manager._mount(_key())["rpc_dir"])


def test_a_failed_lock_leaves_no_staging_directory(tmp_path, monkeypatch):
    from agents.core import session_kernels as sk

    def flock(fd, op):
        raise BlockingIOError(errno.EWOULDBLOCK, "held")

    monkeypatch.setattr(sk._fcntl, "flock", flock)
    root = tmp_path / "kernel-rpc"
    assert sk._hold_owner_lock(root / "p1-0badc0de") is None
    assert list(root.iterdir()) == []


# ── m2 and the fork hook ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork")
def test_a_forked_child_scans_a_large_answer():
    """The hook itself, not the function it calls: a child that inherits a pool whose
    thread went with the fork hangs on its first large scan (review-H315h H59)."""
    import asyncio
    import signal
    import time
    import warnings

    from agents.core import tool_rpc_runtime as rt

    assert rt._SCAN_WORKERS == 1
    assert rt._SCAN_POOL.submit(lambda: 1).result(5) == 1  # the pool has its thread, idle
    answer = {"ok": True, "result": {"text": "x" * 40_000}}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        pid = os.fork()
    if pid == 0:                                          # the child
        code = 3
        try:
            signal.alarm(10)
            code = 0 if asyncio.run(rt._scan(answer)) is False else 1
        finally:
            os._exit(code)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        pytest.fail("the forked child's scan hung")
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0


# ── the size walk (n1, H54, H55, H56) ────────────────────────────────────────────

def test_bytes_count_as_they_encode():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small(b"x" * 1000) is True
    assert rt._small(b"\x00" * 4000) is False            # spelt "\\x00" each: over 16 KiB


def test_a_long_dict_key_counts():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small({"k" * 20_000: 1}) is False


def test_scalars_count():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small([1] * 100) is True
    assert rt._small([1] * 1000) is False


def test_a_container_wider_than_the_budget_is_refused_before_it_is_listed():
    from agents.core import tool_rpc_runtime as rt

    class Wide(list):
        def __iter__(self):
            raise AssertionError("listed")

    assert rt._small(Wide([0] * 20_000)) is False


@pytest.mark.parametrize("value", [10 ** 4000, object(), ["\x00" * 3000]], ids=["huge-int", "object", "control"])
def test_what_encodes_large_or_unknown_is_not_small(value):
    from agents.core import tool_rpc_runtime as rt

    assert rt._small(value) is False


def test_printable_text_under_the_bound_is_small():
    from agents.core import tool_rpc_runtime as rt

    assert rt._small({"text": "a" * 3000, "n": 12, "f": 1.5, "b": True, "z": None}) is True


def test_an_answer_too_deep_to_encode_is_flagged():
    import asyncio

    from agents.core import tool_rpc_runtime as rt

    deep: list = []
    for _ in range(100_000):
        deep = [deep]
    assert rt._flagged(deep) is True
    assert asyncio.run(rt._scan({"ok": True, "result": deep})) is True


def test_an_underscore_at_a_slice_end_is_inside_the_word():
    from agents.core import tool_rpc_runtime as rt

    prefix = len('{"ok": true, "result": {"page": "')
    room = rt._SCAN_CHUNK + rt._SCAN_OVERLAP - prefix - len("you are now")
    page = ("x " * (room // 2 + 1))[:room] + "you are now_here to be seen"
    assert rt._flagged({"ok": True, "result": {"page": page}}) is False


# ── revisions (n2, H44, H31) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["estop_engaged", "authority_expired", "cell_denied",
                                    "kernel_unavailable", "cell_refused", "cell_too_long"])
def test_the_kernels_own_refusals_open_no_revision(reason):
    from agents.core.agent_runtime import _script_revision_due

    assert _script_revision_due("execute_code", {"ok": True, "result": {"ok": False, "reason": reason}}) is False


def test_a_teardown_that_was_not_confirmed_still_opens_one():
    from agents.core.agent_runtime import _script_revision_due

    result = {"ok": True, "result": {"ok": False, "reason": "teardown_unconfirmed"}}
    assert _script_revision_due("execute_code", result) is True


def test_the_kernels_refusals_are_its_own_names():
    from agents.core import agent_runtime, code_tools
    from agents.core import session_kernels as sk

    assert {sk.ESTOP_ENGAGED, sk.AUTHORITY_EXPIRED, code_tools.SESSION_DENIED, sk.KERNEL_UNAVAILABLE,
            sk.CELL_REFUSED, sk.CELL_TOO_LONG} < agent_runtime._SCRIPT_REFUSALS
    assert sk.TEARDOWN_UNCONFIRMED not in agent_runtime._SCRIPT_REFUSALS


def test_a_raising_tool_that_is_not_a_script_opens_no_revision():
    from agents.core.agent_runtime import _script_revision_due

    assert _script_revision_due("fetch", {"ok": False, "reason": "tool_error", "tool": "fetch"}) is False


@pytest.mark.asyncio
async def test_a_k2_cell_that_inflates_its_count_opens_no_revision(tmp_path):
    from agents.core.todo_tool import TodoStore
    from tests.test_h315c_todo_review import _fetching_server, _tool_messages, _turn
    from tests.test_h315d_todo_review import _k2

    store = TodoStore()
    runtime, kernels = _k2(_fetching_server(store), tmp_path)
    script = [
        ("todo", {"todos": [{"id": "1", "content": "step one"}]}),
        ("todo", {}),
        ("todo", {}),
        ("execute_code", {"code": 'jarvis_tool_call.__globals__["CELL"]["calls"] = 7\nprint("ok")'}),
        ("todo", {}),
    ]
    try:
        backend, _events, _origin, _reply = await _turn(runtime, script)
    finally:
        await kernels.shutdown()
    assert "repeated_call" in _tool_messages(backend)[-1]


@pytest.mark.asyncio
async def test_a_cell_with_no_mailbox_made_no_calls(tmp_path):
    from agents.core.session_kernels import WORKER_SOURCE, PipeKernelBackend, SessionKernelManager

    kernels = SessionKernelManager(
        PipeKernelBackend(lambda key, token, rpc_dir="": [sys.executable, "-c", WORKER_SOURCE], name="local"),
        cell_timeout_seconds=20, rpc_root=str(tmp_path / "kernel-rpc"))
    record = await kernels._acquire(_key())
    try:
        payload = await kernels._run_serviced(
            record, 'jarvis_tool_call.__globals__["CELL"]["calls"] = 7', None, "", broker=None)
    finally:
        await kernels.shutdown()
    assert payload["tool_calls"] == 0


# ── the per-run file name (n4, H03) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_dotted_directory_leaves_nothing_per_run(tmp_path):
    sandbox = _host_sandbox(tmp_path)
    for _ in range(3):
        result = await sandbox.execute_python("import os, sys\nprint(os.path.basename(sys.argv[0]))",
                                              filename="a.d/run")
        assert result.stdout.strip().startswith("run-")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.d"]


@pytest.mark.asyncio
async def test_a_dotfile_keeps_its_name(tmp_path):
    sandbox = _host_sandbox(tmp_path)
    result = await sandbox.execute_python("import os, sys\nprint(os.path.basename(sys.argv[0]))",
                                          filename=".hidden")
    assert result.stdout.strip().startswith(".hidden-")
