"""H010 review round 5 — the hub restarts itself on Windows too, and says so when it cannot.

Each test pins one finding of the fifth review:

* Windows under the NSSM service (``NERVA_SERVICE_WRAPPER=nssm``, set by
  ``deploy/windows/install-service.ps1``): the hub installs its stopper, an approved restore
  answers ``restart: "requested"``, and after the drain the hub releases ``hub.lock`` and
  exits ``RESTART_EXIT_CODE`` (75), which NSSM's ``AppExit Default Restart`` relaunches;
* Windows in an interactive session (the packaged nerva.exe, ``python serve.py`` in a
  terminal): the hub releases the lock, then spawns a successor with its own command line in
  a new console and process group, and the successor waits for the old pid to be gone
  before it applies the stage (until then hub.lock still names a live pid and the apply
  would defer);
* where no self-restart exists (a Windows service without the marker, raw uvicorn) the
  accept, the stage, ``nerva backup list``, ``nerva approvals accept`` and
  ``nerva backup restore`` all say the owner must restart the hub, never that it restarts
  itself.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sqlite3
import subprocess  # nosec B404 - the test starts this interpreter on a fixed script
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup as bk
from agents.core import hub_restart, install_identity

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


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
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.delenv("JARVIS_RESTORE_STAGE_TTL_HOURS", raising=False)
    monkeypatch.delenv("NERVA_SERVICE_WRAPPER", raising=False)
    monkeypatch.delenv("NERVA_RESTART_PREDECESSOR", raising=False)
    hub_restart.reset()
    yield data
    hub_restart.reset()


def _approved_task(name: str, task_id: int = 7):
    st = bk.resolve_backup(name).stat()
    return SimpleNamespace(id=task_id, decided_by="admin",
                           payload={"name": name, "bytes": st.st_size, "mtime": st.st_mtime})


class _AcceptingServer:
    """A server whose run() is the human's accept arriving while the hub serves."""

    def __init__(self, task):
        self.task, self.should_exit, self.result = task, False, None

    def run(self):
        self.result = asyncio.run(bk.apply_approved(self.task, None))


@pytest.fixture()
def no_exec(monkeypatch):
    import serve

    calls = []
    monkeypatch.setattr(serve.os, "execv", lambda exe, argv: calls.append(exe))
    return calls


# ── 1. Windows under the NSSM service: exit 75, NSSM relaunches ──────────────────

def test_windows_under_nssm_requests_a_restart_and_exits_75_after_the_drain(root, monkeypatch, no_exec):
    import serve

    monkeypatch.setattr(serve, "_OS_NAME", "nt")
    monkeypatch.setenv("NERVA_SERVICE_WRAPPER", "nssm")
    events = []
    monkeypatch.setattr(install_identity, "release_hub_lock", lambda: events.append("released"))
    monkeypatch.setattr(serve, "_spawn_successor", lambda: events.append("spawned"))
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    server = _AcceptingServer(_approved_task(name))
    with pytest.raises(SystemExit) as exited:
        serve.run_server(server)
    assert exited.value.code == serve.RESTART_EXIT_CODE == 75
    assert server.result["restart"] == "requested" and "action_needed" not in server.result
    assert server.should_exit is True                      # the stopper drained uvicorn
    assert events == ["released"] and no_exec == []         # lock released; no spawn, no exec
    assert bk.pending_restore(root)["name"] == name and "restart" not in bk.pending_restore(root)


def test_the_service_script_marks_nssm_and_restarts_only_on_a_non_zero_exit():
    script = (REPO / "deploy" / "windows" / "install-service.ps1").read_text(encoding="utf-8")
    assert '"NERVA_SERVICE_WRAPPER=nssm"' in script
    assert "AppExit Default Restart" in script and "AppExit 0 Exit" in script
    env_block = script[script.index("$ServiceName AppEnvironmentExtra"):script.index("$ServiceName AppStopMethodConsole")]
    assert "NERVA_SERVICE_WRAPPER=nssm" in env_block


# ── 2. Windows, interactive (packaged nerva.exe / a terminal): spawn, then exit ──

def _spawn_recorder(monkeypatch, events):
    def _popen(argv, **kwargs):
        events.append(("spawned", list(argv), kwargs))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(subprocess, "Popen", _popen)       # serve imports it at the spawn


def test_windows_interactive_releases_the_lock_then_spawns_a_successor_with_its_argv(
        root, monkeypatch, no_exec):
    import serve

    monkeypatch.setattr(serve, "_OS_NAME", "nt")
    monkeypatch.setattr(serve, "_windows_session_id", lambda: 1)
    events = []
    monkeypatch.setattr(install_identity, "release_hub_lock", lambda: events.append(("released",)))
    _spawn_recorder(monkeypatch, events)
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    server = _AcceptingServer(_approved_task(name))
    serve.run_server(server)                                # returns: the process then exits
    assert server.result["restart"] == "requested"
    assert [e[0] for e in events] == ["released", "spawned"]
    _, argv, kwargs = events[1]
    assert argv == [sys.executable, *sys.orig_argv[1:]]
    assert kwargs["env"]["NERVA_RESTART_PREDECESSOR"] == str(os.getpid())
    assert kwargs["close_fds"] is True
    assert kwargs["creationflags"] & 0x10 and kwargs["creationflags"] & 0x200   # new console + group
    assert no_exec == []


def test_the_packaged_exe_successor_is_the_exe_with_its_own_arguments(monkeypatch):
    import serve

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", [r"C:\Program Files\Nerva\nerva.exe", "--safe-mode"])
    assert serve._successor_argv() == [sys.executable, "--safe-mode"]


def test_a_failed_spawn_tells_the_owner_to_start_nerva_again(root, monkeypatch, no_exec, capsys):
    import serve

    monkeypatch.setattr(serve, "_OS_NAME", "nt")
    monkeypatch.setattr(serve, "_windows_session_id", lambda: 2)
    monkeypatch.setattr(install_identity, "release_hub_lock", lambda: None)

    def _boom():
        raise OSError("no console")

    monkeypatch.setattr(serve, "_spawn_successor", _boom)

    class _Server:
        should_exit = False

        def run(self):
            assert hub_restart.request("backup.restore") is True

    serve.run_server(_Server())
    assert "start Nerva again yourself" in capsys.readouterr().err


def test_the_successor_waits_for_its_predecessor_before_the_apply(root, tmp_path):
    """The predecessor released hub.lock but its pid is still in the file until it exits;
    applied before then the stage defers. The successor's boot wait closes that gap."""
    import serve

    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    _seed(root / "settings.db", 4)
    old_hub = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])  # nosec B603
    reaper = threading.Thread(target=old_hub.wait, daemon=True)   # no zombie left behind
    reaper.start()
    (root / install_identity.HUB_LOCK_FILE).write_text(str(old_hub.pid), encoding="ascii")
    bk.stage_restore(name, source_root=str(root))
    # Without the wait the apply defers (the old hub still "holds" the root) ...
    early = bk.apply_pending_restore(root)
    assert early["status"] == "deferred" and "another hub" in early["reason"]
    assert _rows(root / "settings.db") == 5
    # ... the successor's boot waits for the pid, then the same stage applies.
    env = {"NERVA_RESTART_PREDECESSOR": str(old_hub.pid)}
    assert serve.wait_for_predecessor(env, timeout=30) is True
    assert "NERVA_RESTART_PREDECESSOR" not in env            # not inherited by a later restart
    assert old_hub.poll() is not None
    assert bk.apply_pending_restore(root)["status"] == "restored"
    assert _rows(root / "settings.db") == 1


def test_the_predecessor_wait_is_bounded():
    import serve

    slept = []
    env = {"NERVA_RESTART_PREDECESSOR": "123456"}
    assert serve.wait_for_predecessor(env, alive=lambda pid: True, timeout=1.0, poll=0.5,
                                      sleep=slept.append) is False
    assert slept == [0.5, 0.5]
    assert serve.wait_for_predecessor({}, alive=lambda pid: True) is True   # no predecessor


def test_serve_waits_for_the_predecessor_before_it_applies_a_stage():
    text = (REPO / "serve.py").read_text(encoding="utf-8")
    assert text.index("\nwait_for_predecessor()\n") < text.index("\napply_staged_restore()\n")
    assert text.index("\napply_staged_restore()\n") < text.index("from agents.web import app")


# ── 3. no self-restart: every surface says so ────────────────────────────────────

def test_a_windows_service_without_the_marker_is_manual_and_says_what_to_do(root, monkeypatch, no_exec):
    import serve

    monkeypatch.setattr(serve, "_OS_NAME", "nt")
    monkeypatch.setattr(serve, "_windows_session_id", lambda: 0)      # session 0: a service
    spawned = []
    monkeypatch.setattr(serve, "_spawn_successor", lambda: spawned.append(True))
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    server = _AcceptingServer(_approved_task(name))
    serve.run_server(server)
    result = server.result
    staged = bk.pending_restore(root)
    assert result["restart"] == "manual" and server.should_exit is False
    assert result["action_needed"] == bk.manual_restart_hint(staged["expires_at"])
    assert f"before {staged['expires_at']}" in result["action_needed"]
    assert staged["restart"] == "manual"
    view = bk.staged_restore_view(root)
    assert view["state"] == "waiting" and view["action_needed"] == result["action_needed"]
    assert spawned == [] and no_exec == []


def test_an_expired_manual_stage_asks_for_nothing(root, monkeypatch):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    asyncio.run(bk.apply_approved(_approved_task(name), None))       # no stopper: manual
    assert bk.staged_restore_view(root)["action_needed"]
    marker = bk.default_backup_dir(root) / bk._PENDING_RESTORE
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["expires_at"] = "2000-01-01T00:00:00+00:00"
    marker.write_text(json.dumps(data), encoding="utf-8")
    view = bk.staged_restore_view(root)
    assert view["state"] == "expired" and "action_needed" not in view


class _Hub:
    def __init__(self, routes=None):
        self.routes, self.calls = dict(routes or {}), []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body=None):
        self.calls.append(("POST", path, body))
        return self.routes[f"POST {path}"]

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.routes[f"GET {path}"]


def _nerva(argv, root, hub=None):
    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: hub or _Hub())
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


@pytest.mark.parametrize("reply", [{"pending": 42, "restart": "manual"}, {"pending": 42}])
def test_nerva_backup_restore_does_not_promise_a_restart_the_hub_cannot_do(root, reply):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    code, out, err = _nerva(["backup", "restore", name], root,
                            hub=_Hub({"POST /api/admin/backup/restore": reply}))
    assert code == 0, err
    assert "restarts itself" not in out
    assert "cannot restart itself" in out and "restart the hub/service yourself" in out
    assert "python serve.py" in out and "expires 24 h after the accept" in out
    assert "nerva approvals accept 42" in out


def test_nerva_backup_restore_names_the_self_restart_when_the_hub_has_one(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    code, out, _ = _nerva(["backup", "restore", name], root,
                          hub=_Hub({"POST /api/admin/backup/restore": {"pending": 9, "restart": "self"}}))
    assert code == 0
    assert "restarts itself and restores before any store opens" in out
    assert "cannot restart itself" not in out


def test_nerva_backup_list_flags_a_stage_that_needs_a_manual_restart(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    asyncio.run(bk.apply_approved(_approved_task(name), None))
    expires = bk.pending_restore(root)["expires_at"]
    code, out, _ = _nerva(["backup", "list"], root)
    assert code == 0
    assert "ACTION NEEDED" in out and f"apply it before {expires}" in out
    code, out, _ = _nerva(["backup", "list", "--json"], root)
    view = json.loads(out)["pending_restore"]
    assert view["restart"] == "manual" and expires in view["action_needed"]


def test_nerva_approvals_accept_says_a_manual_restore_is_not_applied_yet(root):
    hint = bk.manual_restart_hint("2026-10-22T10:00:00+00:00")
    task = {"id": 5, "kind": "backup.restore", "status": "done",
            "result": {"status": "ok", "staged": "jarvis-backup-x.tar.gz", "restart": "manual",
                       "action_needed": hint}}
    hub = _Hub({"POST /autonomy/tasks/5/decision": {"ok": True, "task": task}})
    code, out, _ = _nerva(["approvals", "accept", "5"], root, hub=hub)
    assert code == 0
    assert "NOT applied yet" in out and "before 2026-10-22T10:00:00+00:00" in out
    task["result"]["restart"] = "requested"
    code, out, _ = _nerva(["approvals", "accept", "5"], root, hub=hub)
    assert "NOT applied" not in out


# ── the restore route tells the CLI which it is ──────────────────────────────────

ADMIN = {"X-Admin-Token": "adm-h010r5"}


@pytest.fixture()
def client(root, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
    from agents.core.routers import backup as backup_router

    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    queue = TaskQueue(db_path=str(tmp_path / "autonomy-q.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h010r5")
    monkeypatch.setattr(backup_router, "get_orch", lambda: SimpleNamespace(autonomy=worker))
    yield TestClient(web.app)
    queue.close()


def test_the_restore_route_says_whether_this_hub_restarts_itself(root, client):
    name = Path(bk.create_backup()["archive"]).name
    first = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert first.status_code == 202 and first.json()["restart"] == "manual"
    hub_restart.install(lambda: None)
    again = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert again.status_code == 202
    assert again.json() == {"pending": first.json()["pending"], "existing": True, "restart": "self"}
