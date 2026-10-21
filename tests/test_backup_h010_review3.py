"""H010 review round 3 — the coordinator really lets go of the data root for a restore.

Round 2 had the jarvis-runtime coordinator stop its orchestrator, drop its mark and rebuild
in the same process once the restore was over. Run against the REAL orchestrator that left
WAL connections open on missions.db, permissions.db, work_runs.db, autonomy/jobs.db,
analytics.db … through the restore, and the rebuilt process kept writing to the unlinked
pre-restore inodes (module-global stores such as analytics_store._db are never reopened).

Each test pins one finding of the third review:

* a real supervisor + coordinator (real ``_build_orchestrator``, fake LLM) holds no file
  under the data root once it has yielded, the restore completes, and every DB the
  respawned coordinator then has open is the restored file on disk (no "(deleted)" inode);
* a yield never rebuilds in the same process: the coordinator exits with
  ``RESTORE_YIELD_EXIT`` and the supervisor respawns it at once, without backoff;
* a process that still holds a SQLite file (DB, -wal, -shm, -journal) under the root never
  drops its mark (it exits instead);
* an exited coordinator its parent has not reaped yet (a zombie) does not hold the root;
* a stage nobody applies stops the runtime only for a bounded grace period, after which the
  coordinator resumes, says so in the restore history, and yields again when the apply runs.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess  # nosec B404 - the test runs this interpreter on fixed scripts
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.core import backup as bk
from agents.core import hub_restart

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import coordinator, runtime_supervisor  # noqa: E402

_LINUX_PROC = sys.platform.startswith("linux") and Path("/proc/self/fd").is_dir()


def _seed(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def _rows(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def _wait_for(predicate, timeout: float = 90.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} not reached in {timeout:g}s")
        time.sleep(0.1)


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data / "h010probe.db", 1)
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.delenv("JARVIS_RESTORE_STAGE_TTL_HOURS", raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", raising=False)
    hub_restart.reset()
    yield data
    hub_restart.reset()


# ── /proc helpers ────────────────────────────────────────────────────────────────

def _children(pid: int) -> list[int]:
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text(encoding="ascii", errors="replace")
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) > 1 and fields[1] == str(pid) and fields[0] != "Z":
            found.append(int(entry))
    return found


def _root_fds(pid: int, root: Path) -> dict[str, str]:
    """fd number -> target, for every fd of *pid* under *root* (deleted ones included)."""
    prefix = os.path.realpath(root) + os.sep
    out = {}
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return out
    for fd in fds:
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith(prefix):
            out[fd] = target
    return out


def _db_fds(pid: int, root: Path) -> dict[str, str]:
    return {fd: t for fd, t in _root_fds(pid, root).items()
            if t.removesuffix(" (deleted)").endswith((".db", ".db-wal", ".db-shm"))}


def _events(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")]


# ── 1. the real coordinator releases the root and reopens the restored files ─────

@pytest.mark.skipif(not _LINUX_PROC, reason="reads open files from /proc")
def test_the_real_coordinator_holds_nothing_under_the_root_and_reopens_the_restored_files(
        root, tmp_path):
    run_log = tmp_path / "runtime.jsonl"
    env = {**os.environ, "JARVIS_HOME": str(root), "JARVIS_RUNTIME_FAKE_LLM": "1",
           "JARVIS_RUNTIME_RESTORE_POLL": "0.2", "JARVIS_RUNTIME_LOG": str(run_log),
           "JARVIS_RUNTIME_STATE": str(tmp_path / "state.json"),
           "JARVIS_RUNTIME_RESPAWN_DELAY": "5"}
    sup = subprocess.Popen(  # nosec B603 - this interpreter on the repo's supervisor
        [sys.executable, str(REPO / "scripts" / "runtime_supervisor.py")],
        env=env, cwd=str(tmp_path))
    try:
        # The real orchestrator is up: its stores hold the root's DBs open.
        _wait_for(lambda: len(_children(sup.pid)) == 1 and _db_fds(_children(sup.pid)[0], root),
                  what="the coordinator opening its stores")
        first = _children(sup.pid)[0]
        assert bk.runtime_running_elsewhere(root) is True
        name = Path(bk.create_backup(source_root=str(root))["archive"]).name
        _seed(root / "h010probe.db", 2)                                  # 3 rows live
        assert bk.stage_restore(name, source_root=str(root))["ok"]

        # The coordinator yields: no live process marks the root any more ...
        _wait_for(lambda: not bk.runtime_running_elsewhere(root), what="the yield")
        # ... and no coordinator process holds anything under it (round 2 kept ~7 DBs open).
        for pid in [first, *_children(sup.pid)]:
            assert _root_fds(pid, root) == {}, f"pid {pid} still holds files under the root"

        result = bk.apply_pending_restore(root, runtime_wait=30)
        assert result["status"] == "restored" and result["ok"] is True, result
        assert _rows(root / "h010probe.db") == 1

        # A fresh process rebuilds the orchestrator on the restored files.
        _wait_for(lambda: len(_children(sup.pid)) == 1 and _children(sup.pid)[0] != first
                  and _db_fds(_children(sup.pid)[0], root), what="the respawned coordinator")
        second = _children(sup.pid)[0]
        assert not Path(f"/proc/{first}").exists()                      # the old one is gone
        fds = _root_fds(second, root)
        assert not [t for t in fds.values() if t.endswith("(deleted)")], fds
        for fd, target in fds.items():
            # Every open file IS the file on disk now: writes land in the restored root.
            assert os.stat(f"/proc/{second}/fd/{fd}").st_ino == os.stat(target).st_ino, target
        kinds = [(e.get("supervisor_event"), e.get("exit_code")) for e in _events(run_log)]
        assert ("child_exited", coordinator.RESTORE_YIELD_EXIT) in kinds, kinds
        assert ("respawned", None) in kinds
        assert bk.runtime_running_elsewhere(root) is True               # re-marked by the new pid
    finally:
        sup.send_signal(signal.SIGTERM)
        sup.wait(timeout=60)


_WRITER = """
import asyncio, os, sys
sys.path.insert(0, {repo!r})
sys.path.insert(0, {agents!r})
from scripts import coordinator

_real = coordinator._build_orchestrator
_tasks = []

async def _build():
    orch = await _real()
    from agents.core import analytics_store

    async def _write():
        while True:
            analytics_store.record_event("h010.probe", props={{"pid": os.getpid()}})
            await asyncio.sleep(0.2)

    _tasks.append(asyncio.get_running_loop().create_task(_write()))
    return orch

coordinator._build_orchestrator = _build
coordinator.main()
"""


def _probe_pids(db: Path) -> set[int]:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return set()
    try:
        rows = conn.execute("SELECT props_json FROM events WHERE name = 'h010.probe'").fetchall()
    except sqlite3.Error:
        return set()
    finally:
        conn.close()
    return {json.loads(r[0]).get("pid") for r in rows}


@pytest.mark.skipif(not _LINUX_PROC, reason="reads open files from /proc")
def test_an_analytics_write_after_the_restore_lands_in_the_restored_file(root, tmp_path):
    """The module-global analytics connection (analytics_store._db) is the one round 2 never
    reopened: every analytics write after the restore went to the unlinked pre-restore
    inode. Here the real orchestrator writes an analytics event every 0.2 s, and the
    events the coordinator writes after the restore are in the restored analytics.db."""
    wrapper = tmp_path / "coordinator_writer.py"
    wrapper.write_text(_WRITER.format(repo=str(REPO), agents=str(REPO / "agents")),
                       encoding="utf-8")
    src = (REPO / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = src.replace('_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
                          f"_COORDINATOR = {str(wrapper)!r}")
    assert patched != src
    sup_script = tmp_path / "runtime_supervisor.py"
    sup_script.write_text(patched, encoding="utf-8")
    env = {**os.environ, "JARVIS_HOME": str(root), "JARVIS_RUNTIME_FAKE_LLM": "1",
           "JARVIS_RUNTIME_RESTORE_POLL": "0.2", "JARVIS_RUNTIME_LOG": str(tmp_path / "rt.jsonl"),
           "JARVIS_RUNTIME_STATE": str(tmp_path / "state.json")}
    analytics_db = root / "analytics.db"
    sup = subprocess.Popen([sys.executable, str(sup_script)], env=env,  # nosec B603
                           cwd=str(tmp_path))
    try:
        _wait_for(lambda: len(_children(sup.pid)) == 1
                  and _children(sup.pid)[0] in _probe_pids(analytics_db),
                  what="the coordinator writing analytics events")
        first = _children(sup.pid)[0]
        name = Path(bk.create_backup(source_root=str(root))["archive"]).name
        assert bk.stage_restore(name, source_root=str(root))["ok"]
        _wait_for(lambda: not bk.runtime_running_elsewhere(root), what="the yield")
        assert bk.apply_pending_restore(root, runtime_wait=30)["status"] == "restored"
        # The writes made after the restore are in the file on disk, read by a fresh reader.
        _wait_for(lambda: any(p not in (first, None) for p in _probe_pids(analytics_db)),
                  what="a post-restore analytics write in the restored analytics.db")
        second = _children(sup.pid)[0]
        assert second != first and second in _probe_pids(analytics_db)
        held = [fd for fd, t in _db_fds(second, root).items() if t.endswith("analytics.db")]
        restored_ino = analytics_db.stat().st_ino
        assert held and all(os.stat(f"/proc/{second}/fd/{fd}").st_ino == restored_ino
                            for fd in held)
    finally:
        sup.send_signal(signal.SIGTERM)
        sup.wait(timeout=60)


# ── 2. a yield exits; it never rebuilds in the same process ──────────────────────

class _Orch:
    runtime_log = None

    def __init__(self, log):
        self._runtime_settings = {}
        self._log = log

    async def start_channels(self):
        self._log.append("start")

    async def stop_channels(self):
        self._log.append("stop")

    async def aclose(self):
        self._log.append("aclose")


class _Exited(Exception):
    pass


def _patch_coordinator(monkeypatch, log, *, open_files=()):
    async def _build():
        log.append("build")
        return _Orch(log)

    def _exit(code):
        log.append(("exit", code))
        raise _Exited(code)

    monkeypatch.setattr(coordinator, "_build_orchestrator", _build)
    monkeypatch.setattr(coordinator, "_exit_process", _exit)
    monkeypatch.setattr(coordinator, "_open_root_files", lambda: list(open_files))
    monkeypatch.setenv("JARVIS_RUNTIME_RESTORE_POLL", "0.05")


def test_a_yield_exits_with_the_restore_code_and_never_rebuilds(root, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "r.jsonl"))
    monkeypatch.setenv("JARVIS_RUNTIME_STATE", str(tmp_path / "s.json"))
    log: list = []
    _patch_coordinator(monkeypatch, log)
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        for _ in range(200):
            if "start" in log:
                break
            await asyncio.sleep(0.01)
        bk.stage_restore(name, source_root=str(root))
        with pytest.raises(_Exited):
            await asyncio.wait_for(task, 10)

    asyncio.run(_scenario())
    assert log.count("build") == 1
    assert log[-1] == ("exit", coordinator.RESTORE_YIELD_EXIT)
    assert log.index("stop") < log.index(("exit", coordinator.RESTORE_YIELD_EXIT))
    # The mark stays until the process is gone: a dead pid is what releases the root.
    assert (root / "runtime.pid").read_text().strip() == str(os.getpid())


def test_a_process_still_holding_root_files_exits_instead_of_dropping_its_mark(root, monkeypatch):
    log: list = []
    _patch_coordinator(monkeypatch, log, open_files=[str(root / "missions.db")])
    bk.stage_restore(Path(bk.create_backup(source_root=str(root))["archive"]).name,
                     source_root=str(root))
    with pytest.raises(_Exited):
        asyncio.run(coordinator.run())
    assert log == [("exit", coordinator.RESTORE_YIELD_EXIT)]
    assert (root / "runtime.pid").exists()           # never cleared while files are open


def test_a_fresh_process_waits_without_building_and_builds_once_after(root, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "r.jsonl"))
    monkeypatch.setenv("JARVIS_RUNTIME_STATE", str(tmp_path / "s.json"))
    log: list = []
    _patch_coordinator(monkeypatch, log)
    bk.stage_restore(Path(bk.create_backup(source_root=str(root))["archive"]).name,
                     source_root=str(root))

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        await asyncio.sleep(0.3)
        assert log == [] and not (root / "runtime.pid").exists()
        bk.cancel_staged_restore(root)
        for _ in range(200):
            if "start" in log:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())
    assert log.count("build") == 1


def _yielding_child(tmp_path: Path, count: Path, *, uptime: float) -> Path:
    child = tmp_path / "fake_coordinator.py"
    child.write_text(
        "import sys, pathlib, time\n"
        f"p = pathlib.Path({str(count)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        f"time.sleep({uptime})\n"
        f"sys.exit({coordinator.RESTORE_YIELD_EXIT} if n < 4 else 0)\n", encoding="utf-8")
    return child


def _patched_supervisor(tmp_path: Path, child: Path) -> Path:
    src = (REPO / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = src.replace('_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
                          f"_COORDINATOR = {str(child)!r}")
    assert patched != src
    script = tmp_path / "runtime_supervisor.py"
    script.write_text(patched, encoding="utf-8")
    return script


def test_a_restore_yield_that_ran_nothing_still_backs_off(tmp_path):
    """A child exiting 75 at once (it never ran an orchestrator) cannot make the loop spin."""
    count = tmp_path / "count"
    script = _patched_supervisor(tmp_path, _yielding_child(tmp_path, count, uptime=0.0))
    log = tmp_path / "runtime.jsonl"
    env = {**os.environ, "JARVIS_RUNTIME_LOG": str(log), "JARVIS_RUNTIME_RESPAWN_DELAY": "2"}
    sup = subprocess.Popen([sys.executable, str(script)], env=env)  # nosec B603
    try:
        time.sleep(3.0)
        assert int(count.read_text()) <= 2               # 2 s, then 4 s between spawns
    finally:
        sup.send_signal(signal.SIGTERM)
        sup.wait(timeout=30)
    assert not [e for e in _events(log) if e.get("restore_yield")]


def test_the_supervisor_respawns_a_restore_yield_at_once(tmp_path):
    count = tmp_path / "count"
    child = _yielding_child(tmp_path, count, uptime=runtime_supervisor.YIELD_MIN_UPTIME_SECONDS + 0.1)
    src = (REPO / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = src.replace('_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
                          f"_COORDINATOR = {str(child)!r}")
    assert patched != src
    script = tmp_path / "runtime_supervisor.py"
    script.write_text(patched, encoding="utf-8")
    log = tmp_path / "runtime.jsonl"
    env = {**os.environ, "JARVIS_RUNTIME_LOG": str(log), "JARVIS_RUNTIME_RESPAWN_DELAY": "3"}
    sup = subprocess.Popen([sys.executable, str(script)], env=env)  # nosec B603
    try:
        _wait_for(lambda: count.exists() and count.read_text() == "5", timeout=15.0,
                  what="five spawns")                # a 3 s backoff would need 3+6+12+24 s
    finally:
        sup.send_signal(signal.SIGTERM)
        sup.wait(timeout=30)
    yields = [e for e in _events(log) if e.get("supervisor_event") == "child_exited"
              and e.get("exit_code") == coordinator.RESTORE_YIELD_EXIT]
    assert len(yields) == 4 and all(e.get("restore_yield") is True for e in yields)
    assert runtime_supervisor.RESTORE_YIELD_EXIT == coordinator.RESTORE_YIELD_EXIT


# ── 3. a stage nobody applies stops the runtime only for a grace period ──────────

def _age_stage(root: Path, seconds: float) -> None:
    marker = bk.default_backup_dir(root) / "pending-restore.json"
    staged = json.loads(marker.read_text(encoding="utf-8"))
    staged["staged_at"] = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    marker.write_text(json.dumps(staged), encoding="utf-8")


def test_the_runtime_yields_to_a_fresh_stage_but_resumes_after_the_grace(root, monkeypatch):
    monkeypatch.setenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", "600")
    assert bk.runtime_should_yield(root) is False
    bk.stage_restore(Path(bk.create_backup(source_root=str(root))["archive"]).name,
                     source_root=str(root))
    assert bk.runtime_should_yield(root) is True
    _age_stage(root, 601)
    assert bk.runtime_should_yield(root) is False     # unapplied for too long: run again
    assert bk.restore_wanted(root) is True            # the stage itself still stands
    # The apply begins (a live journal by another process): the runtime yields again.
    journal = bk.default_backup_dir(root) / "restore-applying.json"
    helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # nosec B603
    try:
        journal.write_text(json.dumps({"phase": "checking", "pid": helper.pid}), encoding="utf-8")
        assert bk.runtime_should_yield(root) is True
    finally:
        helper.kill()
        helper.wait()
        journal.unlink()


def test_the_resumed_runtime_is_recorded_once_in_the_history(root, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "r.jsonl"))
    monkeypatch.setenv("JARVIS_RUNTIME_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", "600")
    log: list = []
    _patch_coordinator(monkeypatch, log)
    bk.stage_restore(Path(bk.create_backup(source_root=str(root))["archive"]).name,
                     source_root=str(root))
    _age_stage(root, 601)

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        for _ in range(200):
            if "start" in log:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)                       # several polls while resumed
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())
    assert log.count("build") == 1                      # it runs instead of waiting
    events = [h["event"] for h in bk.restore_history(root)]
    assert events.count("runtime_resumed") == 1
    view = bk.staged_restore_view(root)
    assert view["runtime_resumed_at"]


def test_the_grace_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", "42")
    assert bk.runtime_restore_grace_seconds() == 42.0
    monkeypatch.delenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS")
    assert bk.runtime_restore_grace_seconds() == bk.RUNTIME_RESTORE_GRACE_DEFAULT


@pytest.mark.skipif(not _LINUX_PROC, reason="reads the process state from /proc")
def test_an_exited_coordinator_not_yet_reaped_no_longer_holds_the_root(root):
    """The yield leaves the mark to a pid that is dead; before its parent reaps it the pid
    is a zombie, which holds no file, so the restore must not wait for it."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])  # nosec B603
    (root / "runtime.pid").write_text(str(child.pid), encoding="ascii")
    try:
        _wait_for(lambda: Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[-1].split()[0]
                  == "Z", timeout=10, what="the zombie state")
        assert bk.runtime_running_elsewhere(root) is False
    finally:
        child.wait()
