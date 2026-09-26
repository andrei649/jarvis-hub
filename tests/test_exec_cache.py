"""H667 — never assume /tmp is real storage; prune only the cache you own.

The sandbox's run directories live under the managed cache (<data root>/cache/exec) or a
root the owner chose, never the system temp root. An hourly prune removes the managed
cache's run directories whose newest file is older than the limit (72 h), keeps any a
live sandbox holds, and never touches a root the owner chose.
"""

from __future__ import annotations

import asyncio
import gc
import os
import socket
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import exec_cache
from agents.core.sandbox import Sandbox

HOUR = 3600
P = exec_cache.PREFIX


def _settings(values):
    return lambda category, key, default=None: values.get(f"{category}.{key}", default)


def _age(path: Path, hours: float) -> None:
    then = time.time() - hours * HOUR
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            os.utime(os.path.join(dirpath, name), (then, then), follow_symlinks=False)
    os.utime(path, (then, then))


def _ctime_old(monkeypatch, hours=100.0):
    """Date by mtime alone: utime cannot move the ctime back, so a test that ages a tree
    stands in for a tree that really is that old."""
    monkeypatch.setattr(exec_cache, "_date", lambda info: info.st_mtime)


def _run_dir(root: Path, name="old", hours=100.0, files=("script.py",)) -> Path:
    path = root / f"{P}{name}"
    path.mkdir(parents=True)
    for file in files:
        (path / file).write_text("x")
    _age(path, hours)
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    _ctime_old(monkeypatch)
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    return base


@pytest.fixture
def managed(tmp_path, monkeypatch):
    base = tmp_path / "data" / "cache" / "exec"
    monkeypatch.setattr(exec_cache, "managed_root", lambda: base)
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    return base


# ── where run directories go ─────────────────────────────────────────────────────

def test_the_default_is_the_managed_cache_under_the_data_root(monkeypatch):
    from agents.core.paths import data_root

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    root, managed = exec_cache.resolve_root(get_value=_settings({}))
    assert managed and root == (data_root() / "cache" / "exec").absolute()


def test_the_environment_wins_then_the_owner_setting(tmp_path):
    env_dir, set_dir = tmp_path / "env", tmp_path / "set"
    both = _settings({"security.sandbox_temp_dir": str(set_dir)})
    assert exec_cache.resolve_root({exec_cache.ENV_KEY: str(env_dir)}, both) == (env_dir, False)
    assert exec_cache.resolve_root({exec_cache.ENV_KEY: f"  {env_dir}  "}, both) == (env_dir, False)
    assert exec_cache.resolve_root({}, both) == (set_dir, False)


def test_a_home_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert exec_cache.resolve_root({exec_cache.ENV_KEY: "~/exec"}, _settings({})) == (tmp_path / "exec", False)


@pytest.mark.parametrize("bad", ["rel/dir", "~nosuchuser_h667/exec", "/srv/a\x00b"])
def test_a_value_that_is_not_an_absolute_path_is_skipped(tmp_path, caplog, bad):
    set_dir = tmp_path / "set"
    got = exec_cache.resolve_root({exec_cache.ENV_KEY: bad},
                                  _settings({"security.sandbox_temp_dir": str(set_dir)}))
    assert got == (set_dir, False) and "not an absolute path" in caplog.text
    root, managed = exec_cache.resolve_root({}, _settings({"security.sandbox_temp_dir": bad}))
    assert managed and root == exec_cache.managed_root()


@pytest.mark.parametrize("bad", ["~nosuchuser_h667/exec", "/srv/a\x00b"])
def test_a_bad_stored_root_never_stops_a_sandbox(monkeypatch, bad):
    from agents.core import settings_db

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    monkeypatch.setattr(settings_db, "get_value",
                        lambda c, k, d=None: bad if (c, k) == exec_cache.SETTING else d)
    sandbox = Sandbox()                                   # no RuntimeError, no ValueError
    assert sandbox.work_dir.parent == exec_cache.managed_root()


def test_the_setting_is_validated_on_write():
    from agents.core import settings_db

    for bad in ("rel", "~nosuchuser_h667/x", "/a\x00b", 5):
        assert settings_db.validate_category("security", {"sandbox_temp_dir": bad})
    for good in ("", "/srv/nerva-exec"):
        assert settings_db.validate_category("security", {"sandbox_temp_dir": good}) == []
    for bad in (0, -1, 0.5, 9000, float("nan"), True):
        assert settings_db.validate_category("security", {"sandbox_temp_max_age_hours": bad})
    for good in (1, 72, 8760, 1.5):
        assert settings_db.validate_category("security", {"sandbox_temp_max_age_hours": good}) == []


def test_the_managed_root_is_the_managed_cache_whoever_names_it(managed):
    assert exec_cache.resolve_root({exec_cache.ENV_KEY: str(managed)}, _settings({})) == (managed, True)


def test_a_relative_data_root_gives_an_absolute_run_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_HOME", "reldata")
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    assert sandbox.work_dir.is_absolute()
    assert sandbox.work_dir.parent == tmp_path / "reldata" / "cache" / "exec"


def test_a_sandbox_makes_its_run_directory_in_the_managed_cache(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    assert sandbox.work_dir.parent == exec_cache.managed_root()
    assert sandbox.work_dir.name.startswith(P) and sandbox.work_dir_managed is True
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(exec_cache.managed_root()).st_mode) & 0o077 == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_wide_managed_root_of_ours_is_made_private(managed):
    managed.mkdir(parents=True, mode=0o777)
    os.chmod(managed, 0o777)
    exec_cache.new_work_dir({}, _settings({}))
    assert stat.S_IMODE(os.stat(managed).st_mode) == 0o700


def test_a_sandbox_follows_the_environments_choice(tmp_path, monkeypatch):
    monkeypatch.setenv(exec_cache.ENV_KEY, str(tmp_path / "exec"))
    sandbox = Sandbox()
    assert sandbox.work_dir.parent == tmp_path / "exec" and sandbox.work_dir_managed is False
    assert sandbox._work_lock is None and not (tmp_path / "exec" / exec_cache.LOCKS).exists()


def test_an_unusable_root_falls_back_to_the_system_temp_unmanaged(tmp_path, monkeypatch, caplog):
    import tempfile

    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv(exec_cache.ENV_KEY, str(blocker / "exec"))       # under a file
    work, managed = exec_cache.new_work_dir()
    assert managed is False and work.parent == Path(tempfile.gettempdir()).absolute()
    assert "unusable" in caplog.text
    work.rmdir()


def test_an_explicit_work_dir_is_used_as_given(tmp_path):
    sandbox = Sandbox(work_dir=str(tmp_path))
    assert sandbox.work_dir == tmp_path and sandbox.work_dir_managed is False
    assert sandbox._work_lock is None


# ── the lock ─────────────────────────────────────────────────────────────────────

def test_the_lock_lives_outside_the_run_directory_and_names_its_owner(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    lock = sandbox.work_dir.parent / exec_cache.LOCKS / f"{sandbox.work_dir.name}.lock"
    assert lock.is_file() and list(sandbox.work_dir.iterdir()) == []
    assert lock.read_text().split()[:2] == [socket.gethostname(), str(os.getpid())]


@pytest.mark.skipif(os.name != "posix", reason="flock")
def test_a_live_sandbox_is_never_pruned_however_old(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    _ctime_old(monkeypatch)
    sandbox = Sandbox()
    (sandbox.work_dir / "script.py").write_text("x")
    _age(sandbox.work_dir, 500)
    assert sandbox.work_dir.name not in exec_cache.prune(exec_cache.managed_root())["deleted"]
    assert sandbox.work_dir.is_dir()


def test_without_flock_the_owner_record_keeps_a_live_sandbox(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    _ctime_old(monkeypatch)
    monkeypatch.setattr(exec_cache, "_fcntl", None)       # flock a no-op, or missing
    sandbox = Sandbox()
    _age(sandbox.work_dir, 500)
    assert sandbox.work_dir.name not in exec_cache.prune(exec_cache.managed_root())["deleted"]
    assert sandbox.work_dir.is_dir()


def test_a_dead_owner_or_another_host_in_the_record(root):
    old = _run_dir(root)
    lock = root / exec_cache.LOCKS / f"{old.name}.lock"
    lock.parent.mkdir()
    lock.write_text("otherhost 1\n")
    assert exec_cache.prune(root)["deleted"] == []                        # another host: kept
    lock.write_text(f"{socket.gethostname()} 999999999\n")
    assert exec_cache.prune(root)["deleted"] == [old.name] and not lock.exists()


@pytest.mark.skipif(os.name != "posix", reason="flock")
def test_a_lock_that_cannot_be_opened_reads_as_held(root, monkeypatch):
    old = _run_dir(root)
    lock = root / exec_cache.LOCKS / f"{old.name}.lock"
    lock.parent.mkdir()
    lock.write_text("")
    real = os.open

    def open_(path, flags, *args, **kwargs):
        if str(path) == str(lock):
            raise PermissionError(13, "denied")
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(exec_cache.os, "open", open_)
    assert exec_cache.prune(root)["deleted"] == [] and old.exists()


@pytest.mark.parametrize("kind", ["dir", "link", "fifo"])
def test_a_lock_that_is_not_a_file_is_no_lock(root, kind):
    old = _run_dir(root)
    lock = root / exec_cache.LOCKS / f"{old.name}.lock"
    lock.parent.mkdir()
    if kind == "dir":
        lock.mkdir()
    elif kind == "link":
        lock.symlink_to(root / "elsewhere")
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("POSIX named pipes")
        os.mkfifo(lock)
    assert exec_cache.prune(root)["deleted"] == [old.name]


@pytest.mark.skipif(os.name != "posix", reason="fds")
def test_the_probe_leaves_no_descriptor_open(root):
    old = _run_dir(root)
    lock = root / exec_cache.LOCKS / f"{old.name}.lock"
    lock.parent.mkdir()
    lock.write_text("otherhost 1\n")
    before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
    for _ in range(20):
        exec_cache._held(lock)
    if before is not None:
        assert len(os.listdir("/proc/self/fd")) == before


@pytest.mark.skipif(os.name != "posix", reason="flock")
def test_a_sandbox_gone_releases_its_directory(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    _ctime_old(monkeypatch)
    sandbox = Sandbox()
    work = sandbox.work_dir
    lock = work.parent / exec_cache.LOCKS / f"{work.name}.lock"
    _age(work, 500)
    del sandbox
    gc.collect()
    assert not lock.exists()
    assert work.name in exec_cache.prune(exec_cache.managed_root())["deleted"] and not work.exists()


@pytest.mark.asyncio
async def test_a_run_directory_removed_under_a_live_sandbox_comes_back_private(monkeypatch, tmp_path):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox(allow_subprocess=True, allow_wasm=False)
    sandbox._has_docker = False
    import shutil

    shutil.rmtree(sandbox.work_dir)
    result = await sandbox.execute_python("print('hi')")
    assert result.stdout.strip() == "hi"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700
        lock = sandbox.work_dir.parent / exec_cache.LOCKS / f"{sandbox.work_dir.name}.lock"
        assert exec_cache._held(lock)


# ── the prune ────────────────────────────────────────────────────────────────────

def test_an_idle_run_directory_is_pruned(root):
    old = _run_dir(root)
    fresh = _run_dir(root, "fresh", hours=1)
    report = exec_cache.prune(root)
    assert report["deleted"] == [old.name] and not old.exists() and fresh.exists()
    assert list(root.glob(f"{exec_cache.CLAIM}*")) == []


def test_the_newest_file_dates_the_whole_directory(root):
    group = _run_dir(root, files=("script.py", "out.pid"))
    (group / ".jarvis_file_rpc").mkdir()
    deep = group / ".jarvis_file_rpc" / "fresh.log"
    deep.write_text("still writing")
    _age(group, 100)                                   # every directory and file old...
    os.utime(deep, None)                               # ...but one file, deep inside
    assert exec_cache.prune(root)["deleted"] == []


def test_a_fresh_subdirectory_dates_the_group(root):
    group = _run_dir(root)
    sub = group / "sub"
    sub.mkdir()
    _age(group, 100)
    os.utime(sub, None)
    assert exec_cache.prune(root)["deleted"] == []


def test_the_directory_itself_dates_the_group(root):
    group = _run_dir(root)
    os.utime(group, None)                              # a file was just removed from it
    assert exec_cache.prune(root)["deleted"] == []


def test_an_mtime_in_the_future_does_not_keep_a_directory_forever(tmp_path):
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    group = _run_dir(base)
    future = time.time() + 100 * 365 * 24 * HOUR
    os.utime(group / "script.py", (future, future))
    info = os.lstat(group / "script.py")
    assert exec_cache._date(info) == min(info.st_mtime, info.st_ctime) < future


def test_the_age_limit_is_the_owners_with_an_hour_floor(root):
    _run_dir(root, hours=10)
    assert exec_cache.prune(root, max_age_hours=72)["deleted"] == []
    assert exec_cache.prune(root, max_age_hours=5)["deleted"] == [f"{P}old"]
    _run_dir(root, "recent", hours=0.5)
    assert exec_cache.prune(root, max_age_hours=0.01)["deleted"] == []           # never under an hour


@pytest.mark.parametrize("value,hours", [(5, 5.0), ("12", 12.0), (0, 72.0), (-3, 72.0),
                                         ("soon", 72.0), (float("inf"), 72.0), (float("nan"), 72.0),
                                         (None, 72.0)])
def test_the_age_setting_reads_positive_hours_only(value, hours):
    got = exec_cache.max_age_hours(_settings({"security.sandbox_temp_max_age_hours": value}))
    assert got == hours


def test_the_live_list_protects_a_directory_without_a_lock(root):
    old = _run_dir(root)
    assert exec_cache.prune(root, live=[old])["deleted"] == [] and old.exists()


def test_a_root_the_owner_chose_is_never_pruned(root):
    old = _run_dir(root)
    report = exec_cache.prune(root, managed=False)
    assert report["skipped"] == "owner_pointed" and report["_scheduler_status"] == "skipped"
    assert old.exists()


def test_only_the_caches_own_entries_are_considered(root, tmp_path):
    other = root / "owner-notes"
    other.mkdir()
    plain = root / "sandbox-other-program"
    plain.mkdir()
    outside = tmp_path / "target"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    link = root / f"{P}link"
    link.symlink_to(outside, target_is_directory=True)
    loose = root / f"{P}file"
    loose.write_text("x")
    _age(root, 500)
    _age(outside, 500)                                 # even an old target is not reached
    assert exec_cache.prune(root)["deleted"] == []
    assert other.exists() and plain.exists() and link.is_symlink()
    assert (outside / "keep.txt").exists() and loose.exists()


def test_a_link_inside_a_run_directory_is_not_followed(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    old = _run_dir(root)
    (old / "escape").symlink_to(outside, target_is_directory=True)
    _age(old, 100)
    assert exec_cache.prune(root)["deleted"] == [old.name]
    assert (outside / "keep.txt").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes")
@pytest.mark.parametrize("problem", ["link", "wide"])
def test_a_root_that_is_not_ours_alone_is_not_swept(tmp_path, monkeypatch, problem):
    _ctime_old(monkeypatch)
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    old = _run_dir(real)
    root = real
    if problem == "link":
        root = tmp_path / "linked"
        root.symlink_to(real, target_is_directory=True)
    else:
        os.chmod(real, 0o777)
    report = exec_cache.prune(root)
    assert report["deleted"] == [] and report["_scheduler_status"] == "failed" and old.exists()


def test_a_directory_swapped_for_a_link_is_not_counted_or_followed(root, tmp_path, monkeypatch):
    outside = tmp_path / "victim"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    old = _run_dir(root)
    real = Path.rename

    def rename(self, target):
        if self == old:                                # swapped between the checks and the claim
            import shutil

            shutil.rmtree(old)
            old.symlink_to(outside, target_is_directory=True)
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert exec_cache.prune(root)["deleted"] == []
    assert (outside / "keep.txt").exists() and list(root.glob(f"{exec_cache.CLAIM}*")) == []


def test_a_directory_that_cannot_be_claimed_is_kept_whole(root, monkeypatch):
    old = _run_dir(root)
    real = Path.rename

    def rename(self, target):
        if self == old:
            raise PermissionError(13, "in use")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert exec_cache.prune(root)["deleted"] == [] and (old / "script.py").exists()


def test_an_unfinished_claim_is_finished(root, tmp_path):
    half = root / f"{exec_cache.CLAIM}{P}x-0000"
    half.mkdir()
    (half / "left.txt").write_text("x")
    target = tmp_path / "t"
    target.mkdir()
    (target / "keep").write_text("x")
    stale_link = root / f"{exec_cache.CLAIM}{P}y-0000"
    stale_link.symlink_to(target, target_is_directory=True)
    exec_cache.prune(root)
    assert not half.exists() and not stale_link.is_symlink() and (target / "keep").exists()


def test_a_missing_or_unreadable_root(tmp_path, monkeypatch):
    assert exec_cache.prune(tmp_path / "none")["deleted"] == []
    base = tmp_path / "exec"
    base.mkdir(mode=0o700)
    real = Path.iterdir

    def iterdir(self):
        if self == base:
            raise PermissionError(13, "denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    report = exec_cache.prune(base)
    assert report["skipped"].startswith("unreadable") and report["_scheduler_status"] == "failed"


# ── the schedule ─────────────────────────────────────────────────────────────────

def _service(live=None):
    from agents.core.scheduler_service import SchedulerService

    jobs = {}
    scheduler = SimpleNamespace(add_job=lambda fn, trigger, **kw: jobs.update({kw["id"]: (fn, trigger, kw)}))
    orch = SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=scheduler),
                           sandbox=SimpleNamespace(work_dir=live) if live else None)
    return SchedulerService(orch), jobs


def test_the_prune_runs_hourly_off_the_loop_and_keeps_the_hubs_sandbox(managed, monkeypatch):
    from agents.core import settings_db

    _ctime_old(monkeypatch)
    managed.mkdir(parents=True, mode=0o700)
    live = _run_dir(managed, "live")
    old = _run_dir(managed, hours=10)
    monkeypatch.setattr(settings_db, "get_value",
                        lambda c, k, d=None: 5 if (c, k) == exec_cache.AGE_SETTING else d)
    threads, real = [], exec_cache.prune

    def prune(*args, **kwargs):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(*args, **kwargs)

    monkeypatch.setattr(exec_cache, "prune", prune)
    service, jobs = _service(live)
    service.schedule_exec_cache_prune()
    fn, trigger, kw = jobs["exec-cache-prune"]
    assert trigger == "interval" and kw["hours"] == 1
    report = asyncio.run(fn())
    assert report["deleted"] == [old.name] and live.exists()     # 10 h old, the owner's 5 h limit
    assert threads == [False]                                    # off the event loop's thread


def test_the_managed_cache_is_pruned_whatever_root_is_chosen_now(managed, tmp_path, monkeypatch):
    _ctime_old(monkeypatch)
    managed.mkdir(parents=True, mode=0o700)
    stranded = _run_dir(managed)
    owner = tmp_path / "owner"
    mine = _run_dir(owner)
    monkeypatch.setenv(exec_cache.ENV_KEY, str(owner))
    report = asyncio.run(_service()[0].run_exec_cache_prune())
    assert report["deleted"] == [stranded.name] and mine.exists()


def test_the_prune_never_raises_into_the_scheduler(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(exec_cache, "prune", boom)
    assert asyncio.run(_service()[0].run_exec_cache_prune()) == {"_scheduler_status": "failed"}


def test_every_start_registers_the_prune():
    from agents.core.scheduler_service import SchedulerService

    service, jobs = _service()
    for name in dir(SchedulerService):
        if name.startswith("schedule_") and name not in ("schedule_all", "schedule_exec_cache_prune"):
            setattr(service, name, lambda: None)
    service.schedule_all()
    assert list(jobs) == ["exec-cache-prune"]


def test_both_settings_are_declared():
    from agents.core import settings_db

    keys = {(d["category"], d["key"]) for d in settings_db.DEFAULTS}
    assert exec_cache.SETTING in keys and exec_cache.AGE_SETTING in keys


# ── backups and the CLI ──────────────────────────────────────────────────────────

def test_a_backup_leaves_the_exec_cache_out(tmp_path, monkeypatch):
    import tarfile

    from agents.core import backup

    src = tmp_path / "data"
    run = src / "cache" / "exec" / f"{P}x"
    run.mkdir(parents=True)
    (run / "script-abc.py").write_text("print('secret')")
    (src / "notes.txt").write_text("keep")
    manifest = backup.create_backup(str(src), out_dir=str(tmp_path / "out"), encrypt=False)
    archive = next((tmp_path / "out").glob("*.tar.gz"))
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(n.endswith("notes.txt") for n in names)
    assert not any("cache/exec" in n for n in names) and manifest["file_count"] >= 1


def test_nerva_config_set_says_the_root_needs_a_restart(monkeypatch):
    import io

    from agents.cli import nerva

    assert ("security", "sandbox_temp_dir") in nerva._RESTART_SETTINGS
    assert ("security", "sandbox_temp_max_age_hours") not in nerva._RESTART_SETTINGS


def test_a_lock_left_without_its_directory_is_removed(root):
    locks = root / exec_cache.LOCKS
    locks.mkdir()
    orphan = locks / f"{P}gone.lock"
    orphan.write_text(f"{socket.gethostname()} 999999999\n")
    held = locks / f"{P}far.lock"
    held.write_text("otherhost 1\n")
    exec_cache.prune(root)
    assert not orphan.exists() and held.exists()


@pytest.mark.asyncio
async def test_the_docker_path_makes_a_removed_run_directory_again(monkeypatch):
    import shutil

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox(timeout=5)
    sandbox._has_docker = True
    shutil.rmtree(sandbox.work_dir)

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

        def kill(self):
            return None

        async def wait(self):
            return None

    async def fake_exec(*cmd, stdout=None, stderr=None):
        return _Proc()

    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", fake_exec)
    result = await sandbox.execute_python("print('ok')")
    assert result.success and sandbox.work_dir.is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700
