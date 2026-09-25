"""H667 — never assume /tmp is real storage; prune only the cache you own.

The sandbox's run directories live under the managed cache (<data root>/cache/exec) or a
root the owner chose, never the system temp root. An hourly prune removes the managed
cache's run directories whose newest file is older than the limit (72 h), keeps any a
live sandbox holds, and never touches a root the owner chose.
"""

from __future__ import annotations

import gc
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import exec_cache
from agents.core.sandbox import Sandbox

HOUR = 3600


def _settings(values):
    return lambda category, key, default=None: values.get(f"{category}.{key}", default)


def _age(path: Path, hours: float) -> None:
    then = time.time() - hours * HOUR
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            os.utime(os.path.join(dirpath, name), (then, then), follow_symlinks=False)
    os.utime(path, (then, then))


def _run_dir(root: Path, name="sandbox-old", hours=100.0, files=("script.py",)) -> Path:
    path = root / name
    path.mkdir(parents=True)
    for file in files:
        (path / file).write_text("x")
    _age(path, hours)
    return path


# ── where run directories go ─────────────────────────────────────────────────────

def test_the_default_is_the_managed_cache_under_the_data_root(monkeypatch):
    from agents.core.paths import data_root

    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    root, managed = exec_cache.resolve_root(get_value=_settings({}))
    assert managed and root == data_root() / "cache" / "exec"


def test_the_environment_wins_then_the_owner_setting(tmp_path):
    env_dir, set_dir = tmp_path / "env", tmp_path / "set"
    both = _settings({"security.sandbox_temp_dir": str(set_dir)})
    assert exec_cache.resolve_root({exec_cache.ENV_KEY: str(env_dir)}, both) == (env_dir, False)
    assert exec_cache.resolve_root({}, both) == (set_dir, False)


def test_a_relative_choice_is_ignored_for_the_next_one(tmp_path, caplog):
    set_dir = tmp_path / "set"
    got = exec_cache.resolve_root({exec_cache.ENV_KEY: "rel/dir"},
                                  _settings({"security.sandbox_temp_dir": str(set_dir)}))
    assert got == (set_dir, False) and "not an absolute path" in caplog.text
    root, managed = exec_cache.resolve_root({}, _settings({"security.sandbox_temp_dir": "rel"}))
    assert managed and root == exec_cache.managed_root()


def test_a_sandbox_makes_its_run_directory_in_the_managed_cache(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    assert sandbox.work_dir.parent == exec_cache.managed_root()
    assert sandbox.work_dir.name.startswith("sandbox-") and sandbox.work_dir_managed is True
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(sandbox.work_dir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(exec_cache.managed_root()).st_mode) & 0o077 == 0


def test_a_sandbox_follows_the_environments_choice(tmp_path, monkeypatch):
    monkeypatch.setenv(exec_cache.ENV_KEY, str(tmp_path / "exec"))
    sandbox = Sandbox()
    assert sandbox.work_dir.parent == tmp_path / "exec" and sandbox.work_dir_managed is False


def test_an_unusable_root_falls_back_to_the_system_temp_unmanaged(tmp_path, monkeypatch, caplog):
    import tempfile

    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv(exec_cache.ENV_KEY, str(blocker / "exec"))       # under a file
    work, managed = exec_cache.new_work_dir()
    assert managed is False and work.parent == Path(tempfile.gettempdir()) and "unusable" in caplog.text
    work.rmdir()


def test_an_explicit_work_dir_is_used_as_given(tmp_path):
    sandbox = Sandbox(work_dir=str(tmp_path))
    assert sandbox.work_dir == tmp_path and sandbox.work_dir_managed is False
    assert not (tmp_path / exec_cache.LOCK_NAME).exists()


# ── the prune ────────────────────────────────────────────────────────────────────

def test_an_idle_run_directory_is_pruned(tmp_path):
    old = _run_dir(tmp_path)
    fresh = _run_dir(tmp_path, "sandbox-fresh", hours=1)
    report = exec_cache.prune(tmp_path)
    assert report["deleted"] == ["sandbox-old"] and not old.exists() and fresh.exists()
    assert list(tmp_path.glob(".pruning-*")) == []


def test_the_newest_file_dates_the_whole_directory(tmp_path):
    group = _run_dir(tmp_path, files=("script.py", "out.pid"))
    (group / ".jarvis_file_rpc").mkdir()
    deep = group / ".jarvis_file_rpc" / "fresh.log"
    deep.write_text("still writing")
    _age(group, 100)                                   # every directory and file old...
    os.utime(deep, None)                               # ...but one file, deep inside
    assert exec_cache.prune(tmp_path)["deleted"] == []
    assert (group / "script.py").exists() and (group / "out.pid").exists()


def test_the_age_limit_is_the_owners(tmp_path):
    _run_dir(tmp_path, hours=10)
    assert exec_cache.prune(tmp_path, max_age_hours=72)["deleted"] == []
    assert exec_cache.prune(tmp_path, max_age_hours=5)["deleted"] == ["sandbox-old"]


@pytest.mark.parametrize("value,hours", [(5, 5.0), ("12", 12.0), (0, 72.0), (-3, 72.0),
                                         ("soon", 72.0), (float("inf"), 72.0), (float("nan"), 72.0),
                                         (None, 72.0)])
def test_the_age_setting_reads_positive_hours_only(value, hours):
    got = exec_cache.max_age_hours(_settings({"security.sandbox_temp_max_age_hours": value}))
    assert got == hours


def test_a_live_sandbox_is_never_pruned_however_old(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    (sandbox.work_dir / "script.py").write_text("x")
    _age(sandbox.work_dir, 500)
    assert exec_cache.prune(exec_cache.managed_root())["deleted"] == []   # its lock is held
    assert sandbox.work_dir.is_dir()


@pytest.mark.skipif(os.name != "posix", reason="flock")
def test_a_lock_that_cannot_be_opened_reads_as_held(tmp_path, monkeypatch):
    old = _run_dir(tmp_path, files=("script.py", exec_cache.LOCK_NAME))
    real = os.open

    def open_(path, flags, *args, **kwargs):
        if str(path).endswith(exec_cache.LOCK_NAME):
            raise PermissionError(13, "denied")
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(exec_cache.os, "open", open_)
    assert exec_cache.prune(tmp_path)["deleted"] == [] and old.exists()


def test_the_live_list_protects_a_directory_without_a_lock(tmp_path):
    old = _run_dir(tmp_path)
    assert exec_cache.prune(tmp_path, live=[old])["deleted"] == [] and old.exists()


@pytest.mark.skipif(os.name != "posix", reason="flock")
def test_a_sandbox_gone_releases_its_directory(monkeypatch):
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    sandbox = Sandbox()
    work = sandbox.work_dir
    _age(work, 500)
    del sandbox
    gc.collect()
    assert work.name in exec_cache.prune(exec_cache.managed_root())["deleted"] and not work.exists()


def test_a_root_the_owner_chose_is_never_pruned(tmp_path):
    old = _run_dir(tmp_path)
    report = exec_cache.prune(tmp_path, managed=False)
    assert report["skipped"] == "owner_pointed" and old.exists()


def test_only_the_caches_own_entries_are_considered(tmp_path):
    other = _run_dir(tmp_path, "owner-notes")
    outside = tmp_path.parent / f"{tmp_path.name}-target"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    link = tmp_path / "sandbox-link"
    link.symlink_to(outside, target_is_directory=True)
    loose = tmp_path / "sandbox-file"
    loose.write_text("x")
    _age(tmp_path, 500)
    _age(outside, 500)                                 # even an old target is not reached
    assert exec_cache.prune(tmp_path)["deleted"] == []
    assert other.exists() and link.is_symlink() and (outside / "keep.txt").exists() and loose.exists()


def test_a_link_inside_a_run_directory_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    root = tmp_path / "root"
    old = _run_dir(root)
    (old / "escape").symlink_to(outside, target_is_directory=True)
    _age(old, 100)
    assert exec_cache.prune(root)["deleted"] == ["sandbox-old"]
    assert (outside / "keep.txt").exists()


def test_a_directory_that_cannot_be_claimed_is_kept_whole(tmp_path, monkeypatch):
    old = _run_dir(tmp_path)
    real = Path.rename

    def rename(self, target):
        if self == old:
            raise PermissionError(13, "in use")       # Windows: a file open inside
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert exec_cache.prune(tmp_path)["deleted"] == [] and (old / "script.py").exists()


def test_an_unfinished_claim_is_finished(tmp_path):
    half = tmp_path / ".pruning-sandbox-x-0000"
    half.mkdir()
    (half / "left.txt").write_text("x")
    exec_cache.prune(tmp_path)
    assert not half.exists()


def test_a_missing_or_unreadable_root_is_a_quiet_no_op(tmp_path, monkeypatch):
    assert exec_cache.prune(tmp_path / "none")["deleted"] == []
    real = Path.iterdir

    def iterdir(self):
        if self == tmp_path:
            raise PermissionError(13, "denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    assert exec_cache.prune(tmp_path)["skipped"].startswith("unreadable")


# ── the schedule ─────────────────────────────────────────────────────────────────

def test_the_prune_runs_hourly_and_keeps_the_hubs_sandbox(monkeypatch, tmp_path):
    import asyncio

    from agents.core.scheduler_service import SchedulerService

    jobs = {}
    scheduler = SimpleNamespace(add_job=lambda fn, trigger, **kw: jobs.update({kw["id"]: (fn, trigger, kw)}))
    live = _run_dir(tmp_path, "sandbox-live")
    orch = SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=scheduler),
                           sandbox=SimpleNamespace(work_dir=live))
    service = SchedulerService(orch)
    service.schedule_exec_cache_prune()
    fn, trigger, kw = jobs["exec-cache-prune"]
    assert trigger == "interval" and kw["hours"] == 1
    old = _run_dir(tmp_path)
    monkeypatch.setattr(exec_cache, "resolve_root", lambda *a, **k: (tmp_path, True))
    monkeypatch.setattr(exec_cache, "max_age_hours", lambda *a, **k: 72.0)
    report = asyncio.run(fn())
    assert report["deleted"] == ["sandbox-old"] and live.exists() and not old.exists()


def test_every_start_registers_the_prune():
    from agents.core.scheduler_service import SchedulerService

    jobs = []
    scheduler = SimpleNamespace(add_job=lambda fn, trigger, **kw: jobs.append(kw["id"]))
    service = SchedulerService(SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=scheduler)))
    for name in dir(SchedulerService):
        if name.startswith("schedule_") and name not in ("schedule_all", "schedule_exec_cache_prune"):
            setattr(service, name, lambda: None)
    service.schedule_all()
    assert jobs == ["exec-cache-prune"]


def test_the_scheduled_prune_leaves_an_owner_root(monkeypatch, tmp_path):
    import asyncio

    from agents.core.scheduler_service import SchedulerService

    old = _run_dir(tmp_path)
    monkeypatch.setattr(exec_cache, "resolve_root", lambda *a, **k: (tmp_path, False))
    orch = SimpleNamespace(heartbeat_scheduler=None, sandbox=None)
    report = asyncio.run(SchedulerService(orch).run_exec_cache_prune())
    assert report["skipped"] == "owner_pointed" and old.exists()


def test_both_settings_are_declared():
    from agents.core import settings_db

    keys = {(d["category"], d["key"]) for d in settings_db.DEFAULTS}
    assert exec_cache.SETTING in keys and exec_cache.AGE_SETTING in keys
