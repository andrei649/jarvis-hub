"""H667, the second review (review-H667b) — its findings, pinned.

- M1: on Windows ``os.kill(pid, 0)`` is no liveness probe (signal 0 is CTRL_C_EVENT), so
  every record read as alive, and ``release`` unlinked a file it still held open, which
  Windows refuses: the managed cache was never pruned there. Liveness asks the process
  table (OpenProcess / GetExitCodeProcess), and ``release`` closes before it unlinks.
- m1: the owner record overrode a working flock, so a crashed sandbox whose pid came
  back (the hub is pid 1 in a container) kept its directory forever. A record says
  whether its writer held the flock; on the same kernel a free flock is the answer, the
  pid is asked only when there was no flock, and a reused pid is told apart by its start
  time. Another host's record ages out at ten times the limit.
- m2: the tool-RPC path made the run directory again (umask mode, no lock) before the
  sandbox could; the runtime now asks the sandbox first, and a directory that is there
  without its lock or with a wider mode is made right again.
- m3: the managed cache named through a link or a ``..`` was "owner-pointed"; roots
  are compared by identity.
- m4: the surviving mutants pinned; nits 1, 3, 4, 5, 6 and 7.
"""

from __future__ import annotations

import csv
import gc
import os
import shutil
import socket
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import exec_cache
from agents.core.sandbox import Sandbox, _bind_mount

HOUR = 3600
P = exec_cache.PREFIX
posix = pytest.mark.skipif(os.name != "posix", reason="POSIX flock, modes and /proc")


def _age(path: Path, hours: float) -> None:
    then = time.time() - hours * HOUR
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            os.utime(os.path.join(dirpath, name), (then, then), follow_symlinks=False)
    os.utime(path, (then, then))


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(exec_cache, "_date", lambda info: info.st_mtime)
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    return base


def _run_dir(root: Path, name="old", hours=100.0) -> Path:
    path = root / f"{P}{name}"
    path.mkdir(parents=True)
    (path / "script.py").write_text("x")
    _age(path, hours)
    return path


def _lock(root: Path, run: Path, record: str) -> Path:
    lock = root / exec_cache.LOCKS / f"{run.name}.lock"
    lock.parent.mkdir(exist_ok=True)
    lock.write_text(record)
    return lock


def _record(pid, *, flock=1, host=None, boot=None, start=None) -> str:
    host = socket.gethostname() if host is None else host
    boot = exec_cache._boot_id() if boot is None else boot
    start = exec_cache._start_token(pid) if start is None else start
    return f"{host} {pid} flock={flock} boot={boot} start={start}\n"


# ── M1: Windows liveness and release ─────────────────────────────────────────────

class _Kernel32:
    """OpenProcess / GetExitCodeProcess / GetProcessTimes / CloseHandle, faked."""

    def __init__(self, *, handle=7, error=0, exit_code=259, created=1234):
        self.handle, self.error, self.exit_code, self.created = handle, error, exit_code, created
        self.closed = []

    def OpenProcess(self, access, inherit, pid):
        assert access == 0x1000 and not inherit
        return self.handle

    def GetExitCodeProcess(self, handle, ref):
        ref._obj.value = self.exit_code
        return 1

    def GetProcessTimes(self, handle, created, exited, kernel, user):
        created._obj.value = self.created
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(exec_cache, "_WINDOWS", True)
    monkeypatch.setattr(exec_cache, "_fcntl", None)

    def no_kill(*args):
        raise AssertionError("os.kill(pid, 0) is Ctrl+C on Windows")

    monkeypatch.setattr(exec_cache.os, "kill", no_kill)

    def use(kernel):
        monkeypatch.setattr(exec_cache, "_kernel32", lambda: kernel)
        monkeypatch.setattr(exec_cache, "_last_error", lambda: kernel.error)
        return kernel

    return use


@pytest.mark.parametrize("kernel,alive", [
    (_Kernel32(handle=0, error=87), False),               # no such process
    (_Kernel32(handle=0, error=5), True),                 # another user's: alive
    (_Kernel32(exit_code=259), True),                     # STILL_ACTIVE
    (_Kernel32(exit_code=0), False),                      # exited, handle kept by someone
])
def test_windows_asks_the_process_table_never_kill(windows, kernel, alive):
    windows(kernel)
    assert exec_cache._pid_alive(4242) is alive
    if kernel.handle:
        assert kernel.closed == [kernel.handle]


def test_windows_tells_a_reused_pid_by_its_creation_time(windows):
    windows(_Kernel32(created=99))
    assert exec_cache._start_token(4242) == "99"
    assert exec_cache._pid_alive(4242, "99") is True
    assert exec_cache._pid_alive(4242, "98") is False


def test_windows_prunes_a_dead_sandboxs_directory(windows, root):
    windows(_Kernel32(handle=0, error=87))
    old = _run_dir(root)
    _lock(root, old, _record(4242, flock=0, start=""))
    assert exec_cache.prune(root)["deleted"] == [old.name]


def test_release_closes_before_it_unlinks(tmp_path, monkeypatch):
    work = tmp_path / f"{P}x"
    work.mkdir()
    fd = exec_cache.hold(work)
    order = []
    real_close, real_unlink = os.close, Path.unlink

    def close(n):
        order.append("close")
        return real_close(n)

    def unlink(self, *args, **kwargs):
        if self.name.endswith(".lock"):
            order.append("unlink")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(exec_cache.os, "close", close)
    monkeypatch.setattr(Path, "unlink", unlink)
    exec_cache.release(fd, work)
    assert order == ["close", "unlink"]


# ── m1: the flock is the answer where it works ───────────────────────────────────

@posix
@pytest.mark.parametrize("pid", ["self", 1, "parent"])
def test_a_free_flock_beats_a_live_pid(root, pid):
    pid = {"self": os.getpid(), "parent": os.getppid()}.get(pid, pid)
    old = _run_dir(root)
    _lock(root, old, _record(pid))
    assert exec_cache.prune(root)["deleted"] == [old.name]


@posix
def test_a_renamed_host_on_the_same_kernel_is_this_kernel(root):
    old = _run_dir(root)
    _lock(root, old, _record(os.getpid(), host="old-container-id"))
    assert exec_cache.prune(root)["deleted"] == [old.name]


@posix
def test_a_held_flock_still_keeps_the_directory(root):
    import fcntl

    old = _run_dir(root)
    lock = _lock(root, old, _record(999999999))
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert exec_cache.prune(root)["deleted"] == [] and old.exists()
    finally:
        os.close(fd)


def test_without_a_flock_the_pid_is_asked(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    old = _run_dir(root)
    lock = _lock(root, old, _record(os.getpid(), flock=0))
    assert exec_cache.prune(root)["deleted"] == []                        # alive: kept
    lock.write_text(_record(os.getpid(), flock=0, start="another-start"))
    assert exec_cache.prune(root)["deleted"] == [old.name]                # reused pid


@posix
def test_a_record_written_without_a_flock_is_not_freed_by_a_free_flock(root):
    old = _run_dir(root)
    _lock(root, old, _record(os.getpid(), flock=0))
    assert exec_cache.prune(root)["deleted"] == [] and old.exists()


def test_another_hosts_record_ages_out_at_ten_times_the_limit(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    recent = _run_dir(root, "recent", hours=5)
    ancient = _run_dir(root, "ancient", hours=100)
    for run in (recent, ancient):
        _lock(root, run, _record(1, host="far", boot="another-kernel", start="s"))
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [ancient.name]
    locks = root / exec_cache.LOCKS
    orphan = locks / f"{P}gone.lock"
    orphan.write_text(_record(1, host="far", boot="another-kernel", start="s"))
    fresh = locks / f"{P}gone-fresh.lock"
    fresh.write_text(_record(1, host="far", boot="another-kernel", start="s"))
    old = time.time() - 100 * HOUR
    os.utime(orphan, (old, old))
    exec_cache.prune(root, max_age_hours=1)
    assert not orphan.exists() and fresh.exists()


def test_hold_says_whether_it_took_the_flock(tmp_path, monkeypatch):
    work = tmp_path / f"{P}x"
    work.mkdir()
    fd = exec_cache.hold(work)
    record = exec_cache._parse(exec_cache._lock_path(work).read_text())
    assert record["host"] == socket.gethostname() and record["pid"] == str(os.getpid())
    assert record["flock"] == ("1" if os.name == "posix" else "0")
    assert record["start"] == exec_cache._start_token(os.getpid())
    exec_cache.release(fd, work)
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    fd = exec_cache.hold(work)
    assert exec_cache._parse(exec_cache._lock_path(work).read_text())["flock"] == "0"
    exec_cache.release(fd, work)


@posix
def test_this_process_has_a_start_token():
    token = exec_cache._start_token(os.getpid())
    if Path("/proc/self/stat").exists():
        assert token and token == exec_cache._start_token(os.getpid())
    assert exec_cache._start_token(999999999) == ""


# ── m2: the tool-RPC path makes the run directory right ──────────────────────────

def _owner_invocation(server):
    from agents.core import sandbox_invocation

    invocation, _ = sandbox_invocation.bind(
        tools=server.tools(), agent="jarvis",
        principal=SimpleNamespace(admin=True, channel="web"),
        origin="operator", session_id="session_test")
    return invocation


@posix
@pytest.mark.asyncio
async def test_the_tool_rpc_path_makes_a_removed_run_directory_private_and_locked(monkeypatch):
    from agents.core.tool_rpc import ToolRPCServer
    from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox(allow_subprocess=True, allow_wasm=False)
    sandbox._has_docker = False
    lock = exec_cache._lock_path(sandbox.work_dir)
    shutil.rmtree(sandbox.work_dir)
    lock.unlink()
    old = os.umask(0o022)
    try:
        server = ToolRPCServer()
        run = await ToolRPCSandboxRuntime(server, sandbox, invocation=_owner_invocation(server)
                                          ).run_python("print('hi')")
    finally:
        os.umask(old)
    assert run.result.stdout.strip() == "hi"
    assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700
    assert exec_cache._held(lock)


@posix
def test_a_directory_there_without_its_lock_takes_it_again(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    lock = exec_cache._lock_path(sandbox.work_dir)
    lock.unlink()
    os.chmod(sandbox.work_dir, 0o755)
    sandbox.ensure_work_dir()
    assert exec_cache._held(lock)
    assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700


def test_an_explicit_work_dir_keeps_its_mode(tmp_path):
    work = tmp_path / "mine"
    work.mkdir(mode=0o755)
    os.chmod(work, 0o755)
    Sandbox(work_dir=str(work)).ensure_work_dir()
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(work).st_mode) == 0o755
    assert not (tmp_path / exec_cache.LOCKS).exists()


# ── m3: the managed cache by identity ────────────────────────────────────────────

@posix
def test_the_managed_cache_through_a_link_is_the_managed_cache(tmp_path, monkeypatch):
    real = tmp_path / "real"
    (real / "cache" / "exec").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    managed = link / "cache" / "exec"
    monkeypatch.setattr(exec_cache, "managed_root", lambda: managed)
    got = exec_cache.resolve_root({exec_cache.ENV_KEY: str(real / "cache" / "exec")}, lambda *a: "")
    assert got == (managed, True)


def test_the_managed_cache_spelled_with_dotdot_is_the_managed_cache(tmp_path, monkeypatch):
    managed = Path(str(tmp_path / "x" / ".." / "real" / "cache" / "exec"))
    monkeypatch.setattr(exec_cache, "managed_root", lambda: managed)
    got = exec_cache.resolve_root({exec_cache.ENV_KEY: str(managed)}, lambda *a: "")
    assert got == (managed, True)
    other = exec_cache.resolve_root({exec_cache.ENV_KEY: str(tmp_path / "mine")}, lambda *a: "")
    assert other == (tmp_path / "mine", False)


def test_a_relative_data_root_gives_an_absolute_managed_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_HOME", "reldata")
    assert exec_cache.managed_root().is_absolute()


# ── m4: the survivors ────────────────────────────────────────────────────────────

def test_an_empty_record_under_a_free_lock_is_no_owner(root):
    old = _run_dir(root)
    _lock(root, old, "")
    assert exec_cache.prune(root)["deleted"] == [old.name]


def test_a_pid_we_may_not_signal_is_alive(monkeypatch):
    monkeypatch.setattr(exec_cache, "_WINDOWS", False)

    def denied(pid, sig):
        raise PermissionError(1, "not permitted")

    monkeypatch.setattr(exec_cache.os, "kill", denied)
    assert exec_cache._pid_alive(4242) is True


@posix
def test_a_managed_root_owned_by_another_user_or_group_writable(tmp_path, monkeypatch):
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    os.chmod(base, 0o770)
    assert exec_cache.prune(base)["skipped"] == "writable by other users"
    os.chmod(base, 0o700)
    uid = os.getuid()
    monkeypatch.setattr(exec_cache.os, "getuid", lambda: uid + 1)
    assert exec_cache.prune(base)["skipped"] == "owned by another user"


@posix
def test_a_linked_managed_root_is_named_a_link(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert exec_cache.prune(link)["skipped"] == "a link"


@pytest.mark.parametrize("error", [RuntimeError("loop"), ValueError("bad")])
def test_a_root_that_raises_falls_back_unmanaged(monkeypatch, error):
    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(exec_cache, "resolve_root", boom)
    work, managed = exec_cache.new_work_dir()
    try:
        assert managed is False and work.is_dir() and work.is_absolute()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_a_fresh_directorys_lock_is_never_taken_as_an_orphan(root):
    fresh = _run_dir(root, "fresh", hours=0)
    lock = _lock(root, fresh, _record(999999999, flock=0, start=""))
    exec_cache.prune(root)
    assert fresh.exists() and lock.exists()


@posix
def test_a_linked_locks_directory_is_never_emptied(root, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / f"{P}gone.lock"
    victim.write_text("")
    (root / exec_cache.LOCKS).symlink_to(elsewhere, target_is_directory=True)
    exec_cache.prune(root)
    assert victim.exists()


def test_a_backup_keeps_the_rest_of_the_cache(tmp_path, monkeypatch):
    import tarfile

    from agents.core import backup

    src = tmp_path / "data"
    (src / "cache" / "exec" / f"{P}x").mkdir(parents=True)
    (src / "cache" / "exec" / f"{P}x" / "script.py").write_text("secret")
    (src / "cache" / "other").mkdir(parents=True)
    (src / "cache" / "other" / "keep.bin").write_text("keep")
    (src / "mytmp" / f"{P}ab12cd34").mkdir(parents=True)             # nit 3: the owner's root
    (src / "mytmp" / f"{P}ab12cd34" / "script.py").write_text("secret")
    monkeypatch.setenv(exec_cache.ENV_KEY, str(src / "mytmp"))
    backup.create_backup(str(src), out_dir=str(tmp_path / "out"), encrypt=False)
    with tarfile.open(next((tmp_path / "out").glob("*.tar.gz"))) as tar:
        names = tar.getnames()
    assert any(n.endswith("cache/other/keep.bin") for n in names)
    assert not any("script.py" in n for n in names)


def _mount_fields(argv):
    assert argv[0] == "--mount"
    return next(csv.reader([argv[1]], strict=True))


@pytest.mark.parametrize("source", ["/srv/a,b", '/srv/a"b', "/srv/a\nb", "/srv/a\rb", "/srv/plain"])
def test_a_mount_source_is_one_field_whatever_it_holds(source):
    fields = _mount_fields(_bind_mount(source, "/workspace", readonly=True))
    assert fields == ["type=bind", f"src={source}", "dst=/workspace", "readonly"]


@posix
def test_hold_never_writes_through_a_planted_link(tmp_path):
    work = tmp_path / f"{P}x"
    work.mkdir()
    target = tmp_path / "target"
    target.write_text("keep")
    lock = exec_cache._lock_path(work)
    lock.parent.mkdir(mode=0o700)
    lock.symlink_to(target)
    fd = exec_cache.hold(work)
    try:
        assert target.read_text() == "keep"
        assert fd is None or (lock.is_file() and not lock.is_symlink())
    finally:
        exec_cache.release(fd, work)


@posix
def test_the_locks_directory_is_private_whatever_the_umask(tmp_path):
    work = tmp_path / f"{P}x"
    work.mkdir()
    old = os.umask(0)
    try:
        fd = exec_cache.hold(work)
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(tmp_path / exec_cache.LOCKS).st_mode) == 0o700
    exec_cache.release(fd, work)


@posix
def test_a_linked_locks_directory_takes_no_lock(tmp_path):
    work = tmp_path / f"{P}x"
    work.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / exec_cache.LOCKS).symlink_to(elsewhere, target_is_directory=True)
    assert exec_cache.hold(work) is None and list(elsewhere.iterdir()) == []


# ── nits ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["/srv/a\nb", "/srv/a\rb", "/srv/\tx"])
def test_a_control_character_is_no_root(bad):
    from agents.core import settings_db

    assert exec_cache.choice_problem(bad)
    assert exec_cache._as_root(bad) is None
    assert settings_db.validate_category("security", {"sandbox_temp_dir": bad})


def test_a_windows_reparse_point_is_a_link(monkeypatch, tmp_path):
    real = os.lstat(tmp_path)
    fake = SimpleNamespace(st_mode=real.st_mode, st_uid=getattr(real, "st_uid", 0),
                           st_file_attributes=0x400)
    monkeypatch.setattr(exec_cache.os, "lstat", lambda path: fake)
    assert exec_cache._root_problem(tmp_path) == "a link"


def test_the_label_and_the_manual_say_how_to_move_the_cache():
    from agents.core import settings_db

    label = next(d["label"] for d in settings_db.DEFAULTS if d["key"] == "sandbox_temp_dir")
    assert "JARVIS_EXEC_TEMP_DIR" in label
    manual = (Path(__file__).resolve().parent.parent / "docs/test-manual/05-console-panels-b.md"
              ).read_text(encoding="utf-8")
    row = next(line for line in manual.splitlines() if line.startswith("| PNB-167 |"))
    assert "JARVIS_EXEC_TEMP_DIR" in row and "linked" in row


def test_the_production_date_ages_a_real_tree(tmp_path):
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    run = base / f"{P}real"
    run.mkdir()
    (run / "script.py").write_text("x")
    assert exec_cache.prune(base)["deleted"] == []
    assert exec_cache.prune(base, now=time.time() + 100 * HOUR)["deleted"] == [run.name]


def test_the_record_is_written_before_the_lock_has_its_name(tmp_path, monkeypatch):
    work = tmp_path / f"{P}x"
    work.mkdir()
    seen = []
    real = os.replace

    def replace(src, dst, *args, **kwargs):
        seen.append((Path(src).read_text(), Path(dst).exists()))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(exec_cache.os, "replace", replace)
    fd = exec_cache.hold(work)
    assert len(seen) == 1 and seen[0][0].startswith(socket.gethostname() + " ") and not seen[0][1]
    assert [p.name for p in (tmp_path / exec_cache.LOCKS).iterdir()] == [f"{work.name}.lock"]
    exec_cache.release(fd, work)


def test_a_sandbox_gone_releases_its_lock_everywhere(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    lock = exec_cache._lock_path(sandbox.work_dir)
    assert lock.is_file()
    del sandbox
    gc.collect()
    assert not lock.exists()



def test_a_lock_that_is_a_link_to_a_live_record_is_no_lock(root, tmp_path, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    old = _run_dir(root)
    live = tmp_path / "live-record"
    live.write_text(_record(os.getpid(), flock=0))
    lock = root / exec_cache.LOCKS / f"{old.name}.lock"
    lock.parent.mkdir()
    lock.symlink_to(live)
    assert exec_cache.prune(root)["deleted"] == [old.name] and live.exists()


def test_a_long_host_name_is_read_whole(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    host = "h" * 200
    monkeypatch.setattr(exec_cache.socket, "gethostname", lambda: host)
    old = _run_dir(root)
    _lock(root, old, _record(os.getpid(), flock=0, start="another-start"))
    assert exec_cache.prune(root)["deleted"] == [old.name]


def test_a_flock_record_is_not_freed_when_the_probe_took_no_flock(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    old = _run_dir(root)
    _lock(root, old, _record(os.getpid(), flock=1))
    assert exec_cache.prune(root)["deleted"] == [] and old.exists()


@posix
def test_the_start_token_is_the_start_tick():
    if not Path("/proc/self/stat").exists():
        pytest.skip("no /proc")
    text = Path(f"/proc/{os.getpid()}/stat").read_text()
    assert exec_cache._start_token(os.getpid()) == text.rpartition(")")[2].split()[19]
    assert exec_cache._start_token(os.getpid()) != exec_cache._start_token(1)


@posix
def test_a_wide_locks_directory_of_ours_is_made_private(tmp_path):
    work = tmp_path / f"{P}x"
    work.mkdir()
    (tmp_path / exec_cache.LOCKS).mkdir()
    os.chmod(tmp_path / exec_cache.LOCKS, 0o755)
    fd = exec_cache.hold(work)
    assert stat.S_IMODE(os.stat(tmp_path / exec_cache.LOCKS).st_mode) == 0o700
    exec_cache.release(fd, work)


@posix
@pytest.mark.asyncio
async def test_the_mailbox_is_made_inside_a_private_locked_directory(monkeypatch):
    from agents.core import tool_rpc_runtime
    from agents.core.tool_rpc import ToolRPCServer

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox(allow_subprocess=True, allow_wasm=False)
    sandbox._has_docker = False
    lock = exec_cache._lock_path(sandbox.work_dir)
    shutil.rmtree(sandbox.work_dir)
    lock.unlink()
    seen = []
    real = tool_rpc_runtime.FileRPCStore

    def store(root, **kwargs):
        seen.append((sandbox.work_dir.is_dir() and stat.S_IMODE(os.stat(sandbox.work_dir).st_mode),
                     lock.is_file()))
        return real(root, **kwargs)

    monkeypatch.setattr(tool_rpc_runtime, "FileRPCStore", store)
    server = ToolRPCServer()
    await tool_rpc_runtime.ToolRPCSandboxRuntime(
        server, sandbox, invocation=_owner_invocation(server)).run_python("print('hi')")
    assert seen == [(0o700, True)]


def test_a_file_named_like_a_run_directory_is_backed_up(tmp_path):
    import tarfile

    from agents.core import backup

    src = tmp_path / "data"
    (src / "notes").mkdir(parents=True)
    (src / "notes" / f"{P}notes.txt").write_text("keep")
    backup.create_backup(str(src), out_dir=str(tmp_path / "out"), encrypt=False)
    with tarfile.open(next((tmp_path / "out").glob("*.tar.gz"))) as tar:
        assert any(n.endswith(f"notes/{P}notes.txt") for n in tar.getnames())
