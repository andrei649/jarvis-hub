"""H010 review round 2 — the in-place restore with the documented deployment running.

Each test pins one finding from the second adversarial review:

* the jarvis-runtime coordinator gives the data root up when a restore is staged, so the
  approved restore completes at the hub's restart with the runtime unit still running
  (a real coordinator process, its pid live, yields; since review r3 it exits and a
  fresh process rebuilds — tests/test_backup_h010_review3.py runs the real orchestrator);
* every deferral is recorded (last-restore.json, restore-history.jsonl once per process
  and reason) and ``nerva backup list`` / ``GET /api/admin/backup`` say "deferred";
* a staged restore expires and can be cancelled (CLI and admin route), and neither an
  expired nor a cancelled stage ever overwrites data written after it was staged;
* process marks (runtime.pid, hub.lock) are never archived or restored;
* a restore prunes only its own automatic rollback points, never an owner's quick backup;
* systemd's watchdog is fed from RELOADING=1 through the drain, the re-exec and the slow
  boot up to READY=1;
* two processes applying at the same moment cannot both restore.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import socket
import sqlite3
import subprocess  # nosec B404 - the test runs this interpreter on a fixed script
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import pytest

from agents.core import backup as bk
from agents.core import hub_restart, sd_notify

REPO = Path(__file__).resolve().parent.parent
ADMIN = {"X-Admin-Token": "adm-h010r2"}


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


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data / "settings.db", 1)
    (data / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.delenv("JARVIS_BACKUP_QUICK_KEEP", raising=False)
    monkeypatch.delenv("JARVIS_RESTORE_STAGE_TTL_HOURS", raising=False)
    hub_restart.reset()
    yield data
    hub_restart.reset()


def _out(root: Path) -> Path:
    return bk.default_backup_dir(root)


def _name(made: dict) -> str:
    return Path(made["archive"]).name


def _events(root: Path) -> list[str]:
    return [h["event"] for h in bk.restore_history(root)]


def _wait_for(predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.05)


# ── 1. the coordinator yields the root: the restore completes on its own ─────────

_CHILD = """
import asyncio, os, sys
sys.path.insert(0, {repo!r})
from scripts import coordinator

builds = {builds!r}

class _Orch:
    runtime_log = None
    _runtime_settings = {{}}
    async def start_channels(self):
        with open(builds, "a") as fh:
            fh.write("start\\n")
    async def stop_channels(self):
        with open(builds, "a") as fh:
            fh.write("stop\\n")
    async def aclose(self):
        pass

async def _build():
    return _Orch()

coordinator._build_orchestrator = _build
asyncio.run(coordinator.run())
"""


def test_a_running_coordinator_yields_and_the_staged_restore_completes(root, tmp_path):
    name = _name(bk.create_backup(source_root=str(root)))       # settings.db: 1 row
    builds = tmp_path / "builds.log"
    script = tmp_path / "child.py"
    script.write_text(_CHILD.format(repo=str(REPO), builds=str(builds)), encoding="utf-8")
    env = {**os.environ, "JARVIS_HOME": str(root), "JARVIS_RUNTIME_RESTORE_POLL": "0.1",
           "JARVIS_RUNTIME_LOG": str(tmp_path / "run.jsonl"),
           "JARVIS_RUNTIME_STATE": str(tmp_path / "state.json")}
    child = subprocess.Popen([sys.executable, str(script)], env=env, cwd=str(tmp_path))  # nosec B603
    mark = root / "runtime.pid"
    try:
        _wait_for(lambda: mark.exists() and mark.read_text().strip() == str(child.pid)
                  and builds.exists() and builds.read_text().count("start") == 1)
        assert bk.runtime_running_elsewhere(root) is True
        _seed(root / "settings.db", 2)                           # 3 rows live
        assert bk.stage_restore(name, source_root=str(root))["ok"]
        # What the re-exec'd hub does at boot: no operator touches jarvis-runtime.
        result = bk.apply_pending_restore(root, runtime_wait=30)
        assert result["status"] == "restored" and result["ok"] is True, result
        assert _rows(root / "settings.db") == 1
        assert "stop" in builds.read_text()
        assert _events(root)[-2:] == ["staged", "restored"]
        # H010 review r3: it never rebuilds in the same process (its stores' handles would
        # point at the replaced files); it exited for the supervisor to start a fresh one.
        assert child.wait(timeout=30) == coordinator_exit_code()
        assert builds.read_text().count("start") == 1
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=30)
    # A fresh process (what the supervisor spawns) builds once on the restored root.
    fresh = subprocess.Popen([sys.executable, str(script)], env=env, cwd=str(tmp_path))  # nosec B603
    try:
        _wait_for(lambda: builds.read_text().count("start") == 2
                  and mark.exists() and mark.read_text().strip() == str(fresh.pid))
    finally:
        fresh.send_signal(signal.SIGTERM)
        fresh.wait(timeout=30)
    assert fresh.returncode == 0
    # H010 review r4: a coordinator that built an orchestrator leaves its mark on a stop
    # too; its dead pid is what releases the root.
    assert mark.read_text().strip() == str(fresh.pid)
    assert bk.runtime_running_elsewhere(root) is False


def coordinator_exit_code() -> int:
    sys.path.insert(0, str(REPO))
    from scripts.coordinator import RESTORE_YIELD_EXIT

    return RESTORE_YIELD_EXIT


def test_the_coordinator_watches_for_a_live_stage_but_not_an_expired_one(root):
    assert bk.restore_wanted(root) is False
    bk.stage_restore(_name(bk.create_backup(source_root=str(root))), source_root=str(root))
    assert bk.restore_wanted(root) is True
    marker = _out(root) / "pending-restore.json"
    staged = json.loads(marker.read_text(encoding="utf-8"))
    staged["expires_at"] = "2000-01-01T00:00:00+00:00"
    marker.write_text(json.dumps(staged), encoding="utf-8")
    assert bk.restore_wanted(root) is False


# ── 2. every deferral leaves a trace ────────────────────────────────────────────

def test_a_deferral_is_recorded_once_per_process_and_reason(root):
    name = _name(bk.create_backup(source_root=str(root)))
    bk.stage_restore(name, source_root=str(root))
    (root / "runtime.pid").write_text(str(os.getppid()), encoding="ascii")   # never yields
    first = bk.apply_pending_restore(root)
    second = bk.apply_pending_restore(root)
    assert first["status"] == second["status"] == "deferred"
    last = bk.last_restore(root)
    assert last["status"] == "deferred" and "jarvis-runtime" in last["reason"]
    assert last["name"] == name and last["staged_at"] == bk.pending_restore(root)["staged_at"]
    assert _events(root) == ["staged", "deferred"]                 # rate-limited
    view = bk.staged_restore_view(root)
    assert view["state"] == "deferred" and view["deferred_reason"] == last["reason"]


def test_nerva_backup_list_says_deferred_not_applied_at_the_next_start(root):
    from agents.cli.nerva import Context, main

    bk.stage_restore(_name(bk.create_backup(source_root=str(root))), source_root=str(root))
    out = io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=io.StringIO(), inp=io.StringIO(""))
    assert main(["backup", "list"], context=ctx) == 0
    assert "applied at the next hub start" in out.getvalue()
    (root / "runtime.pid").write_text(str(os.getppid()), encoding="ascii")
    bk.apply_pending_restore(root)
    out = io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=io.StringIO(), inp=io.StringIO(""))
    assert main(["backup", "list"], context=ctx) == 0
    assert "deferred: the jarvis-runtime coordinator" in out.getvalue()
    assert "applied at the next hub start" not in out.getvalue()


@pytest.fixture
def client(root, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h010r2")
    return TestClient(web.app)


def test_the_admin_listing_reports_the_deferral(root, client):
    bk.stage_restore(_name(bk.create_backup(source_root=str(root))), source_root=str(root))
    (root / "runtime.pid").write_text(str(os.getppid()), encoding="ascii")
    bk.apply_pending_restore(root)
    body = client.get("/api/admin/backup", headers=ADMIN).json()
    assert body["pending_restore"]["state"] == "deferred"
    assert "jarvis-runtime" in body["pending_restore"]["deferred_reason"]
    assert body["last_restore"]["status"] == "deferred"


# ── 3. a stage expires and can be cancelled; neither overwrites later data ───────

def test_an_expired_stage_is_discarded_and_never_overwrites_later_data(root):
    name = _name(bk.create_backup(source_root=str(root)))
    staged = bk.stage_restore(name, source_root=str(root))
    assert staged["expires_at"] > staged["staged_at"]
    _seed(root / "settings.db", 5)                               # written after staging
    marker = _out(root) / "pending-restore.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["expires_at"] = "2000-01-01T00:00:00+00:00"
    marker.write_text(json.dumps(data), encoding="utf-8")
    assert bk.staged_restore_view(root)["state"] == "expired"
    result = bk.apply_pending_restore(root)
    assert result["status"] == "failed" and result["reason"] == "stage_expired"
    assert _rows(root / "settings.db") == 6 and not marker.exists()
    assert "rollback" not in result and _events(root) == ["staged", "failed"]
    assert bk.apply_pending_restore(root) is None


def test_a_stage_from_before_the_expiry_existed_expires_after_the_ttl(root, monkeypatch):
    monkeypatch.setenv("JARVIS_RESTORE_STAGE_TTL_HOURS", "1")
    old = {"name": "x", "staged_at": "2000-01-01T00:00:00+00:00"}
    assert bk.stage_expired(old) is True
    assert bk.stage_expired({"name": "x", "staged_at": bk._now_iso()}) is False
    assert bk.stage_expired({"name": "x"}) is True                # cannot be dated


def test_the_ttl_comes_from_the_environment(root, monkeypatch):
    monkeypatch.setenv("JARVIS_RESTORE_STAGE_TTL_HOURS", "2")
    staged = bk.stage_restore(_name(bk.create_backup(source_root=str(root))), source_root=str(root))
    span = bk._parse_iso(staged["expires_at"]) - bk._parse_iso(staged["staged_at"])
    assert abs(span - 7200) < 1


def test_nerva_backup_cancel_withdraws_the_stage_and_later_data_survives(root):
    from agents.cli.nerva import Context, main

    name = _name(bk.create_backup(source_root=str(root)))
    bk.stage_restore(name, source_root=str(root))
    _seed(root / "settings.db", 4)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(""))
    assert main(["backup", "cancel"], context=ctx) == 0, err.getvalue()
    assert name in out.getvalue()
    assert bk.pending_restore(root) is None and bk.apply_pending_restore(root) is None
    assert _rows(root / "settings.db") == 5
    history = bk.restore_history(root)
    assert [h["event"] for h in history] == ["staged", "cancelled"]
    assert history[-1]["cancelled_by"] == "nerva-cli"
    err = io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=io.StringIO(), err=err, inp=io.StringIO(""))
    assert main(["backup", "cancel"], context=ctx) == 1
    assert "no staged restore" in err.getvalue()


def test_the_admin_route_cancels_a_staged_restore(root, client):
    assert client.delete("/api/admin/backup/restore").status_code in (401, 403)
    assert client.delete("/api/admin/backup/restore", headers=ADMIN).status_code == 404
    name = _name(bk.create_backup(source_root=str(root)))
    bk.stage_restore(name, source_root=str(root))
    resp = client.delete("/api/admin/backup/restore", headers=ADMIN)
    assert resp.status_code == 200 and resp.json()["cancelled"] == name
    assert bk.pending_restore(root) is None
    assert bk.restore_history(root)[-1]["cancelled_by"] == "api.admin"


def test_a_stage_cancelled_while_the_restore_waits_for_the_coordinator_is_not_applied(root):
    name = _name(bk.create_backup(source_root=str(root)))
    bk.stage_restore(name, source_root=str(root))
    _seed(root / "settings.db", 2)
    mark = root / "runtime.pid"
    mark.write_text(str(os.getppid()), encoding="ascii")

    def _sleep(_seconds):
        assert bk.cancel_staged_restore(root)["ok"] is True   # the owner withdraws it
        mark.unlink()                                          # then the coordinator yields

    result = bk.apply_pending_restore(root, runtime_wait=5, sleep=_sleep)
    assert result["status"] == "cancelled"
    assert _rows(root / "settings.db") == 3
    assert not (_out(root) / "restore-applying.json").exists()


def test_a_restore_being_applied_cannot_be_cancelled(root):
    out = _out(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "restore-applying.json").write_text(json.dumps(
        {"name": "x", "phase": "restoring", "pid": os.getppid()}), encoding="utf-8")
    assert bk.cancel_staged_restore(root) == {"ok": False, "reason": "applying"}


# ── 4. process marks are never archived or restored ─────────────────────────────

def test_process_marks_are_never_archived_or_restored(root):
    live = str(os.getppid())
    (root / "runtime.pid").write_text(live, encoding="ascii")
    (root / "hub.lock").write_text(live, encoding="ascii")
    made = bk.create_backup(source_root=str(root))
    with tarfile.open(made["archive"], "r:gz") as tar:
        names = tar.getnames()
    assert "runtime.pid" not in names and "hub.lock" not in names
    # The operator stops what had the root open, then restores.
    (root / "runtime.pid").unlink()
    (root / "hub.lock").unlink()
    bk.stage_restore(_name(made), source_root=str(root))
    assert bk.apply_pending_restore(root)["status"] == "restored"
    assert not (root / "runtime.pid").exists() and not (root / "hub.lock").exists()
    # A later restore is not deferred by a mark the first one planted.
    bk.stage_restore(_name(made), source_root=str(root))
    assert bk.apply_pending_restore(root)["status"] == "restored"


def test_an_old_archive_carrying_a_mark_cannot_plant_it(root, tmp_path):
    # An archive made before the marks were left out: runtime.pid and hub.lock inside.
    src = tmp_path / "old-root"
    _seed(src / "settings.db", 1)
    stale = str(os.getppid())
    (src / "runtime.pid").write_text(stale, encoding="ascii")
    (src / "hub.lock").write_text(stale, encoding="ascii")
    arc = tmp_path / "old.tar.gz"
    manifest = tmp_path / "backup_manifest.json"
    manifest.write_text(json.dumps({"file_count": 3, "mode": "full"}), encoding="utf-8")
    with tarfile.open(arc, "w:gz") as tar:
        for rel in ("settings.db", "runtime.pid", "hub.lock"):
            tar.add(src / rel, arcname=rel)
        tar.add(manifest, arcname="backup_manifest.json")
    (root / "hub.lock").write_text("", encoding="ascii")          # the live hub's (empty) lock
    res = bk.restore_backup(str(arc), str(root), force=True)
    assert res["ok"] is True, res
    assert not (root / "runtime.pid").exists()
    assert (root / "hub.lock").read_text(encoding="ascii") == ""
    assert bk.runtime_running_elsewhere(root) is False


# ── 5. a restore prunes only its own rollback points ────────────────────────────

@pytest.mark.parametrize("quick_restore", [False, True])
def test_a_restore_never_prunes_an_owners_quick_backups(root, quick_restore):
    owner = [_name(bk.create_backup(source_root=str(root), quick=True)) for _ in range(7)]
    target = _name(bk.create_backup(source_root=str(root), quick=quick_restore))
    bk.stage_restore(target, source_root=str(root))
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored", result
    names = {r["name"] for r in bk.list_backups(str(_out(root)))}
    assert set(owner) <= names
    assert result["pruned"] == []
    rows = {r["name"]: r for r in bk.list_backups(str(_out(root)))}
    assert rows[result["rollback"]]["rollback"] is True
    assert not any(rows[n]["rollback"] for n in owner)


# ── 6. the watchdog is fed across the whole self-restart ────────────────────────

@pytest.fixture
def notify_socket(monkeypatch):
    folder = tempfile.mkdtemp(prefix="sdn-")
    path = os.path.join(folder, "n.sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(0.05)
    received: list[tuple[float, str]] = []
    stop = threading.Event()

    def _read():
        while not stop.is_set():
            try:
                data = sock.recv(4096)
            except TimeoutError:
                continue
            received.append((time.monotonic(), data.decode()))

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    monkeypatch.setenv("WATCHDOG_USEC", "200000")                # WatchdogSec = 0.2s
    monkeypatch.setenv("WATCHDOG_PID", str(os.getpid()))
    monkeypatch.delenv(sd_notify.RESTART_ENV, raising=False)
    yield received
    stop.set()
    reader.join(timeout=1)
    sd_notify.end_restart_keepalive()
    sock.close()
    os.unlink(path)
    os.rmdir(folder)


def test_no_watchdog_gap_from_reloading_to_ready_across_a_slow_reexec(notify_socket, monkeypatch):
    import uvicorn

    async def _slow_drain(self, sockets=None):
        await asyncio.sleep(0.35)                                # lifespan teardown

    monkeypatch.setattr(uvicorn.Server, "shutdown", _slow_drain)
    server = sd_notify.NotifyingServer(uvicorn.Config(app=lambda *a: None), lambda: {"ready": True})
    hub_restart.install(lambda: None)
    hub_restart.request("backup.restore")
    asyncio.run(server.shutdown())
    # run_server's execv: the old image (and its thread) ends, the new one starts with the flag.
    os.environ[sd_notify.RESTART_ENV] = "1"
    sd_notify.end_restart_keepalive()
    assert sd_notify.continue_restart_keepalive() is True        # serve.py's first lines
    assert sd_notify.RESTART_ENV not in os.environ               # consumed, not inherited
    time.sleep(0.5)                                              # a slow boot: imports, lifespan

    async def _ready():
        notifier = sd_notify.Notifier()
        assert notifier.ready({"ready": True}) is True
        await notifier.stopping()

    asyncio.run(_ready())
    time.sleep(0.05)
    messages = list(notify_socket)
    texts = [m for _, m in messages]
    start = next(i for i, m in enumerate(texts) if "RELOADING=1" in m)
    end = next(i for i, m in enumerate(texts) if "READY=1" in m)
    stamps = [t for t, _ in messages[start:end + 1]]
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert gaps and max(gaps) < 0.15, gaps                       # well inside WatchdogSec
    assert all("WATCHDOG=1" in m for m in texts[start + 1:end])
    assert sd_notify._restart_pinger is None                     # READY=1 ended it


def test_a_restart_keepalive_is_bounded_when_ready_never_comes(notify_socket):
    os.environ[sd_notify.RESTART_ENV] = "1"
    assert sd_notify.continue_restart_keepalive(interval=0.02, max_seconds=0.1) is True
    time.sleep(0.3)
    count = len(notify_socket)
    time.sleep(0.1)
    assert len(notify_socket) == count                           # stopped: a hang is caught


def test_without_the_flag_a_plain_boot_starts_no_keepalive(notify_socket):
    assert sd_notify.continue_restart_keepalive() is False
    assert sd_notify._restart_pinger is None


def test_run_server_flags_the_reexec_and_serve_resumes_the_keepalive_first(monkeypatch):
    import serve

    seen = []
    monkeypatch.setattr(serve, "_SAME_PID_REEXEC", True)
    monkeypatch.setattr(serve.os, "execv",
                        lambda exe, argv: seen.append(os.environ.get(sd_notify.RESTART_ENV)))
    monkeypatch.delenv(sd_notify.RESTART_ENV, raising=False)

    class _Server:
        should_exit = False

        def run(self):
            hub_restart.request("backup.restore")

    serve.run_server(_Server())
    os.environ.pop(sd_notify.RESTART_ENV, None)
    assert seen == ["1"]
    text = (REPO / "serve.py").read_text(encoding="utf-8")
    assert text.index("continue_restart_keepalive()") < text.index("from agents.web import app")
    assert text.index("continue_restart_keepalive()") < text.index("apply_staged_restore()\n")


# ── 7. two processes applying at once ───────────────────────────────────────────

def test_a_second_concurrent_apply_defers_instead_of_restoring_twice(root):
    from agents.core import install_identity

    bk.stage_restore(_name(bk.create_backup(source_root=str(root))), source_root=str(root))
    _out(root).mkdir(parents=True, exist_ok=True)
    with open(_out(root) / "restore.lock", "a+b") as held:     # the other booting hub
        install_identity._file_lock(held, blocking=False)
        result = bk.apply_pending_restore(root)
        install_identity._file_unlock(held)
    assert result["status"] == "deferred" and "applying" in result["reason"]
    assert bk.pending_restore(root) is not None
    assert bk.apply_pending_restore(root)["status"] == "restored"
