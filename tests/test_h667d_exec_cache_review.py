"""H667, the third review (review-H667c) — its findings, pinned.

- m1: on a filesystem that refuses flock (ENOLCK, EOPNOTSUPP), every probe error read
  as "busy", so a dead owner's record was never read. Only EWOULDBLOCK is busy now; any
  other error reads the record.
- m2: backups dropped any directory whose name starts with the prefix, anywhere in the
  data root. Only a run directory exactly as mkdtemp names it, in the managed cache or
  directly under the root the owner chose, is left out.
- m3: the real survivors pinned (a free flock on another kernel, a reboot, a failed
  GetExitCodeProcess, a cache that does not exist yet, nested run files, an owner-root
  directory made again, a staged record on the error path, a root we do not own).
- nits: a record from before a reboot, or from before the flag, under a free flock is
  free (1); a pid from another namespace is never read here (2); staged records are
  cleaned and an interrupt leaks nothing (3); an odd pid never stops the sweep (4); a
  first lock that failed is taken later (5); only a junction or symlink reparse point is
  a link (7); the label says what JARVIS_EXEC_TEMP_DIR does (8).
"""

from __future__ import annotations

import errno
import os
import shutil
import socket
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import exec_cache
from agents.core.sandbox import Sandbox

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


def _record(pid, *, flock=1, host=None, boot=None, start=None, ns=None) -> str:
    host = socket.gethostname() if host is None else host
    boot = exec_cache._boot_id() if boot is None else boot
    start = exec_cache._start_token(pid) if start is None else start
    ns = exec_cache._pid_ns() if ns is None else ns
    return f"{host} {pid} flock={flock} boot={boot} start={start} ns={ns}\n"


class _RefusingFcntl:
    LOCK_EX, LOCK_NB = 2, 4

    def __init__(self, err):
        self.err = err

    def flock(self, fd, op):
        raise OSError(self.err, os.strerror(self.err))


# ── m1: a filesystem that refuses flock ──────────────────────────────────────────

@pytest.mark.parametrize("err", [errno.ENOLCK, errno.EOPNOTSUPP, errno.EINVAL])
def test_a_refused_flock_reads_the_record(root, monkeypatch, err):
    monkeypatch.setattr(exec_cache, "_fcntl", _RefusingFcntl(err))
    dead = _run_dir(root, "dead")
    _lock(root, dead, _record(999_999, flock=0, start=""))
    live = _run_dir(root, "live")
    _lock(root, live, _record(os.getpid(), flock=0))
    flocked = _run_dir(root, "flocked")
    _lock(root, flocked, _record(os.getpid(), flock=1))
    assert exec_cache.prune(root)["deleted"] == [dead.name]
    assert live.exists() and flocked.exists()


def test_only_a_busy_flock_is_held(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", _RefusingFcntl(errno.EWOULDBLOCK))
    dead = _run_dir(root, "dead")
    _lock(root, dead, _record(999_999, flock=0, start=""))
    assert exec_cache.prune(root)["deleted"] == []


# ── m2: backups ──────────────────────────────────────────────────────────────────

def _archived(src: Path, out: Path) -> list[str]:
    import tarfile

    from agents.core import backup

    backup.create_backup(str(src), out_dir=str(out), encrypt=False)
    with tarfile.open(next(out.glob("*.tar.gz"))) as tar:
        return tar.getnames()


def test_an_owner_folder_named_like_the_prefix_is_backed_up(tmp_path, monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    src = tmp_path / "data"
    for rel in ("workspace/nerva-sandbox-plans/roadmap.md", "skills/nerva-sandbox-helper/SKILL.md",
                "workspace/nerva-sandbox-abcd1234/notes.md"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("keep")
    names = _archived(src, tmp_path / "out")
    for rel in ("roadmap.md", "SKILL.md", "notes.md"):
        assert any(n.endswith(rel) for n in names), rel


def test_nested_run_files_under_the_owner_root_are_left_out(tmp_path, monkeypatch):
    src = tmp_path / "data"
    run = src / "mine" / f"{P}ab12cd34"
    (run / ".jarvis_file_rpc" / "r1").mkdir(parents=True)
    (run / ".jarvis_file_rpc" / "r1" / "req_000001.json").write_text("{}")
    (src / "mine" / "keep.txt").write_text("keep")
    monkeypatch.setenv(exec_cache.ENV_KEY, str(src / "mine"))
    names = _archived(src, tmp_path / "out")
    assert not any("req_000001" in n for n in names) and any(n.endswith("keep.txt") for n in names)


# ── m3: the survivors ────────────────────────────────────────────────────────────

@posix
def test_a_free_flock_never_frees_another_kernels_record(root):
    run = _run_dir(root, "far", hours=5)
    _lock(root, run, _record(1, host="far-host", boot="another-kernel", start="s"))
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [] and run.exists()


@posix
def test_a_record_from_before_a_reboot_under_a_free_flock_is_free(root):
    run = _run_dir(root)
    _lock(root, run, _record(os.getpid(), boot="the-boot-before"))
    assert exec_cache.prune(root)["deleted"] == [run.name]


def test_a_failed_exit_code_query_reads_alive(monkeypatch):
    class Kernel:
        def OpenProcess(self, access, inherit, pid):
            return 7

        def GetExitCodeProcess(self, handle, ref):
            return 0

        def GetProcessTimes(self, *args):
            return 0

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(exec_cache, "_WINDOWS", True)
    monkeypatch.setattr(exec_cache, "_kernel32", lambda: Kernel())
    assert exec_cache._pid_alive(4242) is True


@posix
def test_a_cache_that_does_not_exist_yet_is_matched_through_a_link(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    managed = link / "cache" / "exec"                       # neither side exists yet
    monkeypatch.setattr(exec_cache, "managed_root", lambda: managed)
    got = exec_cache.resolve_root({exec_cache.ENV_KEY: str(real / "cache" / "exec")}, lambda *a: "")
    assert got == (managed, True)


@posix
def test_an_owner_root_run_directory_comes_back_private(tmp_path, monkeypatch):
    monkeypatch.setenv(exec_cache.ENV_KEY, str(tmp_path / "mine"))
    sandbox = Sandbox()
    assert sandbox.work_dir_managed is False
    shutil.rmtree(sandbox.work_dir)
    old = os.umask(0o022)
    try:
        sandbox.ensure_work_dir()
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700


def test_a_failed_replace_leaves_no_staged_record(tmp_path, monkeypatch):
    work = tmp_path / f"{P}x"
    work.mkdir()

    def refuse(src, dst):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(exec_cache.os, "replace", refuse)
    assert exec_cache.hold(work) is None
    assert list((tmp_path / exec_cache.LOCKS).iterdir()) == []


@posix
def test_a_root_we_do_not_own_keeps_its_mode(tmp_path, monkeypatch):
    base = tmp_path / "exec"
    base.mkdir()
    os.chmod(base, 0o755)
    uid = os.getuid()
    monkeypatch.setattr(exec_cache.os, "getuid", lambda: uid + 1)
    exec_cache._secure_managed(base)
    assert stat.S_IMODE(os.stat(base).st_mode) == 0o755


# ── nits ─────────────────────────────────────────────────────────────────────────

@posix
@pytest.mark.parametrize("pid", ["self", 1])
def test_a_record_from_before_the_flag_under_a_free_flock_is_free(root, pid):
    pid = os.getpid() if pid == "self" else pid
    run = _run_dir(root)
    _lock(root, run, f"{socket.gethostname()} {pid}\n")
    assert exec_cache.prune(root)["deleted"] == [run.name]


def test_a_pid_from_another_namespace_is_never_read_here(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    monkeypatch.setattr(exec_cache, "_pid_ns", lambda: "4026531836")
    run = _run_dir(root, "container", hours=5)
    _lock(root, run, _record(999_999, flock=0, start="", ns="4026532999"))
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == []
    _age(run, 100)
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [run.name]


@pytest.mark.parametrize("pid", ["²", "99999999999999999999", "-1"])
def test_an_odd_pid_never_stops_the_sweep(root, monkeypatch, pid):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    odd = _run_dir(root, "odd", hours=5)
    _lock(root, odd, f"{socket.gethostname()} {pid} flock=0\n")
    plain = _run_dir(root, "plain", hours=5)
    _lock(root, plain, _record(999_999, flock=0, start=""))
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [plain.name] and odd.exists()


def test_a_lock_that_cannot_be_judged_is_kept_and_the_sweep_goes_on(root, monkeypatch):
    first = _run_dir(root, "a")
    second = _run_dir(root, "b")
    real = exec_cache._held
    seen = []

    def held(lock, **kwargs):
        seen.append(lock.name)
        if len(seen) == 1:
            raise RuntimeError("surprise")
        return real(lock, **kwargs)

    monkeypatch.setattr(exec_cache, "_held", held)
    deleted = exec_cache.prune(root)["deleted"]
    assert len(deleted) == 1 and {first.name, second.name} - set(deleted)


def test_a_stale_staged_record_is_cleaned_and_a_fresh_one_kept(root):
    locks = root / exec_cache.LOCKS
    locks.mkdir()
    stale = locks / f".{P}x.deadbeef.tmp"
    stale.write_text("")
    old = time.time() - 2 * HOUR
    os.utime(stale, (old, old))
    fresh = locks / f".{P}y.cafebabe.tmp"
    fresh.write_text("")
    exec_cache.prune(root)
    assert not stale.exists() and fresh.exists()


def test_an_interrupt_during_hold_leaks_nothing(tmp_path, monkeypatch):
    work = tmp_path / f"{P}x"
    work.mkdir()
    closed = []
    real_close = os.close

    def interrupted(fd, data):
        raise KeyboardInterrupt

    monkeypatch.setattr(exec_cache.os, "write", interrupted)
    monkeypatch.setattr(exec_cache.os, "close", lambda fd: closed.append(fd) or real_close(fd))
    with pytest.raises(KeyboardInterrupt):
        exec_cache.hold(work)
    assert closed and list((tmp_path / exec_cache.LOCKS).iterdir()) == []


@posix
def test_a_first_lock_that_failed_is_taken_later(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    real = exec_cache.hold
    calls = []

    def flaky(work_dir):
        calls.append(work_dir)
        return None if len(calls) == 1 else real(work_dir)

    monkeypatch.setattr(exec_cache, "hold", flaky)
    sandbox = Sandbox()
    assert sandbox._work_lock is None and sandbox.work_dir_managed
    sandbox.ensure_work_dir()
    assert sandbox._work_lock is not None and exec_cache._held(exec_cache._lock_path(sandbox.work_dir))


@pytest.mark.parametrize("tag,link", [(0xA0000003, True), (0xA000000C, True), (0x9000001A, False)])
def test_only_a_junction_or_symlink_reparse_point_is_a_link(monkeypatch, tmp_path, tag, link):
    real = os.lstat(tmp_path)
    fake = SimpleNamespace(st_mode=real.st_mode, st_uid=getattr(real, "st_uid", 0),
                           st_file_attributes=0x400, st_reparse_tag=tag)
    monkeypatch.setattr(exec_cache.os, "lstat", lambda path: fake)
    assert (exec_cache._root_problem(tmp_path) == "a link") is link


def test_the_label_says_what_the_environment_choice_does():
    from agents.core import settings_db

    label = next(d["label"] for d in settings_db.DEFAULTS if d["key"] == "sandbox_temp_dir")
    assert "JARVIS_HOME" in label and "never pruned" in label
    manual = (Path(__file__).resolve().parent.parent / "docs/test-manual/05-console-panels-b.md"
              ).read_text(encoding="utf-8")
    row = next(line for line in manual.splitlines() if line.startswith("| PNB-167 |"))
    assert "JARVIS_HOME" in row and "never pruned" in row


def test_an_odd_pid_ages_out_like_a_foreign_record(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    odd = _run_dir(root, "odd", hours=100)
    _lock(root, odd, f"{socket.gethostname()} ² flock=0\n")
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [odd.name]


def test_another_hosts_record_is_never_read_by_its_pid_here(root, monkeypatch):
    monkeypatch.setattr(exec_cache, "_fcntl", None)
    run = _run_dir(root, "far", hours=5)
    _lock(root, run, _record(999_999, flock=0, host="far-host", boot="another-kernel", start=""))
    assert exec_cache.prune(root, max_age_hours=1)["deleted"] == [] and run.exists()


def test_under_the_owner_root_only_a_mkdtemp_name_is_left_out(tmp_path, monkeypatch):
    src = tmp_path / "data"
    (src / "mine" / f"{P}plans").mkdir(parents=True)
    (src / "mine" / f"{P}plans" / "roadmap.md").write_text("keep")
    monkeypatch.setenv(exec_cache.ENV_KEY, str(src / "mine"))
    assert any(n.endswith("roadmap.md") for n in _archived(src, tmp_path / "out"))
