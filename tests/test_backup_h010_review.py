"""H010 review fixes — the in-place restore under real data roots and real supervisors.

Each test pins one finding from the adversarial review of the first H010 cut:

* state DBs named ``*.sqlite`` / ``*.sqlite3`` (channel_routes.sqlite, history.sqlite3)
  are state too: quick snapshots hold them, they are copied through the online backup
  API, the drill integrity-checks them and a restore drops their stale ``-wal``;
* the automatic rollback point covers what the restore overwrites (a full snapshot
  before a full restore), and quick rollback points are pruned;
* a staged archive that changed after it was drilled is refused at apply time;
* a restore killed partway is reported at the next boot as interrupted, never silently;
* the headless coordinator (jarvis-runtime) holds the same DBs open, so a restore defers
  while it runs, and it waits for a restore in progress before it opens them;
* the restore leaves an audit trace outside the DBs it overwrites;
* systemd sees a restart as a reload (RELOADING=1, not STOPPING=1), and the restore keeps
  the watchdog and the start timeout fed while it runs;
* Windows (execv is not same-pid there) is answered "manual", and a raw-uvicorn start
  warns that a staged restore is still waiting.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup as bk
from agents.core import hub_restart, install_identity, sd_notify


def _seed_db(path: Path, rows: int, *, close: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    if close:
        conn.close()
        return None
    return conn


def _rows(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def root(tmp_path):
    data = tmp_path / "data"
    _seed_db(data / "settings.db", 3)
    _seed_db(data / "channel_routes.sqlite", 2)
    _seed_db(data / "checkpoints" / "history.sqlite3", 4)
    (data / "audio").mkdir(parents=True)
    (data / "audio" / "big.wav").write_bytes(b"\0" * 4096)
    (data / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    (data / "plugin.sqlite").write_text("not a database, just a name", encoding="utf-8")
    return data


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    hub_restart.reset()
    monkeypatch.delenv("JARVIS_BACKUP_QUICK_KEEP", raising=False)
    # A stand-in "coordinator" (a live pid that never yields) must not hold a test 60s.
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    yield
    hub_restart.reset()


def _out(root: Path) -> Path:
    return bk.default_backup_dir(root)


# ── finding 1: *.sqlite / *.sqlite3 state DBs ────────────────────────────────

def test_a_quick_snapshot_holds_every_sqlite_state_db_whatever_its_suffix(root):
    quick = bk.create_backup(source_root=str(root), quick=True)
    with tarfile.open(quick["archive"], "r:gz") as tar:
        names = sorted(tar.getnames())
    assert names == ["backup_manifest.json", "channel_routes.sqlite",
                     "checkpoints/history.sqlite3", "settings.db"]
    assert sorted(quick["dbs"]) == ["channel_routes.sqlite", "checkpoints/history.sqlite3",
                                    "settings.db"]


def test_a_live_sqlite_db_is_snapshotted_through_the_backup_api(root):
    # Rows still only in the WAL (no checkpoint, connection open): a byte copy of the
    # main file would not hold them; the online backup API does.
    conn = _seed_db(root / "channel_routes.sqlite", 5, close=False)
    try:
        assert (root / "channel_routes.sqlite-wal").stat().st_size > 0
        arc = bk.create_backup(source_root=str(root), quick=True)
    finally:
        conn.close()
    target = root.parent / "drill"
    bk.restore_backup(arc["archive"], str(target))
    assert _rows(target / "channel_routes.sqlite") == 7


def test_the_drill_integrity_checks_sqlite_suffixed_dbs_but_not_impostors(root):
    report = bk.verify_backup(bk.create_backup(source_root=str(root))["archive"])
    assert report["ok"] is True, report
    assert set(report["dbs"]) == {"settings.db", "channel_routes.sqlite",
                                  "checkpoints/history.sqlite3"}


def test_a_restore_drops_the_stale_wal_beside_a_sqlite_suffixed_db(root):
    snap = bk.create_backup(source_root=str(root), quick=True)
    _seed_db(root / "channel_routes.sqlite", 10)
    (root / "channel_routes.sqlite-wal").write_bytes(b"stale wal that would replay")
    (root / "checkpoints" / "history.sqlite3-shm").write_bytes(b"stale shm")
    res = bk.restore_backup(snap["archive"], str(root), force=True)
    assert res["ok"] is True, res
    assert _rows(root / "channel_routes.sqlite") == 2
    assert not (root / "channel_routes.sqlite-wal").exists()
    assert not (root / "checkpoints" / "history.sqlite3-shm").exists()


# ── finding 2: the rollback covers what the restore overwrites; pruning ─────────

def test_a_full_restore_takes_a_full_rollback_point(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    (root / "notes.json").write_text('{"a": 2}', encoding="utf-8")
    bk.stage_restore(name, source_root=str(root))
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored", result
    assert (root / "notes.json").read_text(encoding="utf-8") == '{"a": 1}'
    rollback = result["rollback"]
    assert not rollback.startswith("jarvis-backup-quick-")
    bk.restore_backup(str(bk.resolve_backup(rollback, out_dir=str(_out(root)))), str(root), force=True)
    assert (root / "notes.json").read_text(encoding="utf-8") == '{"a": 2}'


def test_a_quick_restore_keeps_a_quick_rollback_point(root):
    name = Path(bk.create_backup(source_root=str(root), quick=True)["archive"]).name
    bk.stage_restore(name, source_root=str(root))
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored" and result["rollback"].startswith("jarvis-backup-quick-")


def test_quick_rollback_points_are_pruned_but_never_the_archive_being_restored(root, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_QUICK_KEEP", "2")
    oldest = Path(bk.create_backup(source_root=str(root), quick=True, rollback=True)["archive"]).name
    newer = [Path(bk.create_backup(source_root=str(root), quick=True, rollback=True)["archive"]).name
             for _ in range(3)]
    bk.stage_restore(oldest, source_root=str(root))
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored" and result["ok"] is True, result
    quick = {r["name"] for r in bk.list_backups(str(_out(root))) if r["quick"]}
    # The newest two rollback points (the new one and the newest earlier one) plus the
    # protected archive that was being restored; the two in between are gone, and named.
    assert quick == {result["rollback"], newer[-1], oldest}
    assert sorted(result["pruned"]) == sorted(newer[:2])
    assert bk.restore_history(root)[-1]["pruned"] == result["pruned"]
    assert bk.prune_quick_backups(out_dir=str(_out(root)), keep=1, protect=(oldest,)) != []


# ── finding 3: the staged archive is re-checked when it is applied ──────────────

def test_a_staged_archive_that_changed_since_its_drill_is_refused(root):
    arc = bk.create_backup(source_root=str(root))
    bk.stage_restore(Path(arc["archive"]).name, source_root=str(root))
    _seed_db(root / "settings.db", 4)                       # 7 rows live
    Path(arc["archive"]).write_bytes(Path(arc["archive"]).read_bytes() + b"\0")
    result = bk.apply_pending_restore(root)
    assert result["status"] == "failed" and result["reason"] == "backup_changed"
    assert _rows(root / "settings.db") == 7                  # live state untouched
    assert bk.pending_restore(root) is None


# ── crash safety: an interrupted restore is reported, not silent ────────────────

class _Killed(BaseException):
    """Stands in for SIGKILL: nothing in apply_pending_restore handles it."""


def test_a_restore_killed_partway_is_reported_as_interrupted_at_the_next_boot(root, monkeypatch):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    bk.stage_restore(name, source_root=str(root))
    real = bk.restore_backup

    def _killed(*a, **k):
        raise _Killed()

    monkeypatch.setattr(bk, "restore_backup", _killed)
    with pytest.raises(_Killed):
        bk.apply_pending_restore(root)
    monkeypatch.setattr(bk, "restore_backup", real)
    # The next process (a different pid after the supervisor restarts it).
    journal = _out(root) / "restore-applying.json"
    state = json.loads(journal.read_text(encoding="utf-8"))
    assert state["phase"] == "restoring" and state["rollback"]
    state["pid"] = 999_999_999
    journal.write_text(json.dumps(state), encoding="utf-8")
    assert bk.boot_restore_due(root) is True
    result = bk.apply_pending_restore(root)
    assert result["status"] == "interrupted" and result["ok"] is False
    assert result["name"] == name and result["rollback"] == state["rollback"]
    assert bk.last_restore(root)["status"] == "interrupted"
    assert not journal.exists() and bk.apply_pending_restore(root) is None


def test_serve_reports_an_interrupted_restore_at_boot(root, monkeypatch, capsys):
    import serve

    out = _out(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "restore-applying.json").write_text(json.dumps(
        {"name": "jarvis-backup-x.tar.gz", "phase": "restoring", "pid": 999_999_999,
         "rollback": "jarvis-backup-y.tar.gz"}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(root))
    result = serve.apply_staged_restore()
    assert result["status"] == "interrupted"
    assert "INTERRUPTED" in capsys.readouterr().err


# ── the coordinator holds the same DBs open ───────────────────────────────────

def test_a_restore_defers_while_the_runtime_coordinator_runs(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    _seed_db(root / "settings.db", 1)
    bk.stage_restore(name, source_root=str(root))
    (root / "runtime.pid").write_text(str(os.getppid()), encoding="ascii")   # a live pid
    assert bk.runtime_running_elsewhere(root) is True
    result = bk.apply_pending_restore(root)
    assert result["status"] == "deferred" and "jarvis-runtime" in result["reason"]
    assert _rows(root / "settings.db") == 4 and bk.pending_restore(root) is not None
    assert not (_out(root) / "restore-applying.json").exists()


def test_the_runtime_mark_is_this_processes_own_and_cleared(root):
    bk.mark_runtime(root)
    assert (root / "runtime.pid").read_text(encoding="ascii") == str(os.getpid())
    assert bk.runtime_running_elsewhere(root) is False        # its own mark is not "elsewhere"
    bk.clear_runtime_mark(root)
    assert not (root / "runtime.pid").exists()


def test_the_coordinator_waits_for_a_restore_in_progress(root):
    out = _out(root)
    out.mkdir(parents=True, exist_ok=True)
    journal = out / "restore-applying.json"
    journal.write_text(json.dumps({"name": "x", "phase": "restoring", "pid": os.getppid()}),
                       encoding="utf-8")
    assert bk.restore_in_progress(root) is True
    slept = []

    def _sleep(seconds):
        slept.append(seconds)
        journal.unlink()

    assert bk.wait_while_restoring(root, sleep=_sleep) is True
    assert slept and bk.restore_in_progress(root) is False


def test_the_coordinator_marks_itself_and_waits_before_it_opens_the_stores():
    text = (Path(__file__).resolve().parent.parent / "scripts" / "coordinator.py").read_text(encoding="utf-8")
    run = text[text.index("async def run()"):]
    assert (run.index("mark_runtime(") < run.index("runtime_should_yield(")
            < run.index("_run_marked("))
    assert "clear_runtime_mark(" in run
    marked = text[text.index("async def _run_marked("):]
    assert marked.index("_build_orchestrator()") < marked.index("runtime_should_yield")


# ── audit trace outside the restored DBs ──────────────────────────────────────

def test_an_approved_restore_leaves_an_audit_trace_the_restore_cannot_erase(root, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(root))
    name = Path(bk.create_backup()["archive"]).name
    task = SimpleNamespace(id=17, payload=None, decided_by="admin")
    path = bk.resolve_backup(name)
    st = path.stat()
    task.payload = {"name": name, "bytes": st.st_size, "mtime": st.st_mtime}
    assert asyncio.run(bk.apply_approved(task, None))["status"] == "ok"
    staged = bk.pending_restore(root)
    assert staged["task_id"] == 17 and staged["requested_by"] == "admin"
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored"
    history = bk.restore_history(root)
    assert [h["event"] for h in history] == ["staged", "restored"]
    assert all(h["task_id"] == 17 and h["requested_by"] == "admin" and h["name"] == name
               for h in history)
    assert history[-1]["rollback"] == result["rollback"]
    # The trace lives beside the archives, which no backup holds, so no restore rewrites it.
    with tarfile.open(path, "r:gz") as tar:
        assert not any(n.startswith("backups/") for n in tar.getnames())


# ── systemd: a restart is a reload, and a long restore keeps the unit fed ──────

@pytest.fixture
def notes(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sd_notify, "enabled", lambda: True)
    monkeypatch.setattr(sd_notify, "notify", lambda message: sent.append(message) or True)
    yield sent
    # A requested restart starts the process-wide restart keepalive, which only the execv
    # (or READY=1) ends; left running it would stand in for the next test's own pinger.
    sd_notify.end_restart_keepalive()


def test_a_requested_restart_is_announced_as_reloading_not_stopping(notes, monkeypatch):
    import uvicorn

    async def _noop(self, sockets=None):
        return None

    monkeypatch.setattr(uvicorn.Server, "shutdown", _noop)
    server = sd_notify.NotifyingServer(uvicorn.Config(app=lambda *a: None), lambda: {"ready": True})
    hub_restart.install(lambda: None)
    hub_restart.request("backup.restore")
    asyncio.run(server.shutdown())
    assert notes and not any("STOPPING=1" in m for m in notes)
    assert "RELOADING=1" in notes[0] and "MONOTONIC_USEC=" in notes[0]


def test_a_plain_stop_still_says_stopping(notes, monkeypatch):
    import uvicorn

    async def _noop(self, sockets=None):
        return None

    monkeypatch.setattr(uvicorn.Server, "shutdown", _noop)
    server = sd_notify.NotifyingServer(uvicorn.Config(app=lambda *a: None), lambda: {"ready": True})
    asyncio.run(server.shutdown())
    assert any("STOPPING=1" in m for m in notes) and not any("RELOADING=1" in m for m in notes)


def test_the_boot_restore_feeds_the_watchdog_and_extends_the_timeout(root, notes, monkeypatch):
    import serve

    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    bk.stage_restore(name, source_root=str(root))
    monkeypatch.setenv("JARVIS_HOME", str(root))
    assert serve.apply_staged_restore()["status"] == "restored"
    assert any("WATCHDOG=1" in m and "EXTEND_TIMEOUT_USEC=" in m for m in notes)


def test_keepalive_pings_until_the_block_ends(notes):
    import time

    with sd_notify.keepalive("restoring", interval=0.01):
        time.sleep(0.05)
    count = len(notes)
    assert count >= 2
    time.sleep(0.03)
    assert len(notes) == count                                  # the thread stopped


# ── Windows and raw uvicorn ───────────────────────────────────────────────────

def test_without_a_restart_path_the_restart_is_manual(monkeypatch):
    import serve

    calls = []
    monkeypatch.setattr(serve, "_restart_path", lambda environ=None: None)
    monkeypatch.setattr(serve.os, "execv", lambda exe, argv: calls.append(exe))

    class _Server:
        should_exit = False

        def run(self):
            assert hub_restart.request("backup.restore") is False

    serve.run_server(_Server())
    assert calls == []


def test_a_raw_uvicorn_start_warns_about_a_restore_still_staged(root):
    assert bk.unapplied_restore_warning(root) is None
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    bk.stage_restore(name, source_root=str(root))
    warning = bk.unapplied_restore_warning(root)
    assert name in warning and "serve.py" in warning
    web = (Path(__file__).resolve().parent.parent / "agents" / "web.py").read_text(encoding="utf-8")
    lifespan = web[web.index("async def lifespan("):]
    assert "unapplied_restore_warning(" in lifespan[: lifespan.index("Orchestrator(")]


def test_the_offline_cli_restore_defers_while_the_coordinator_runs(root):
    import io

    from agents.cli.client import HubUnavailable
    from agents.cli.nerva import Context, main

    class _Down:
        base_url = "http://127.0.0.1:8080"

        def post(self, path, body=None):
            raise HubUnavailable("http://127.0.0.1:8080", "connection refused")

    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    _seed_db(root / "settings.db", 1)
    (root / "runtime.pid").write_text(str(os.getppid()), encoding="ascii")
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: _Down())
    code = main(["backup", "restore", name, "--confirm", "RESTORE"], context=ctx)
    assert code == 0, err.getvalue()
    assert "jarvis-runtime" in out.getvalue() and "staged" in out.getvalue()
    assert _rows(root / "settings.db") == 4                    # nothing overwritten under it
    assert bk.pending_restore(root)["name"] == name
