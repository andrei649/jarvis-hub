"""H010 review round 6 — an accepted restore is applied by the process that can restart the hub.

Each test pins one finding of the sixth review:

* the hub and jarvis-runtime (``scripts/coordinator.py``) both run the autonomy loop over one
  queue and both register ``backup.restore``. A worker with no stopper while a live hub holds
  ``hub.lock`` (jarvis-runtime) must leave the accepted task APPROVED, unclaimed, for the
  hub's worker — which stages it with ``restart: "self"`` and restarts. A "manual" stage after
  a 202 that said "self" never happens. With no hub at all the worker that has the task
  still applies it and says the restart is manual.
* ``nerva approvals accept`` on a restore: the decision route answers ``approved`` with no
  result (the loop runs the accept later), so the CLI waits a bounded few seconds on
  ``GET /api/admin/backup`` for the stage and then says what it is — NOT applied yet when
  the hub cannot restart itself — or points at ``nerva backup list``.
"""
from __future__ import annotations

import asyncio
import io
import os
import sqlite3
import subprocess  # nosec B404 - the test starts this interpreter as a live "hub" pid
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.cli.client import HubUnavailable
from agents.core import backup as bk
from agents.core import hub_restart, install_identity

ADMIN = {"X-Admin-Token": "adm-h010r6"}


def _seed(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data / "settings.db", 1)
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.delenv("JARVIS_RESTORE_STAGE_TTL_HOURS", raising=False)
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    hub_restart.reset()
    yield data
    hub_restart.reset()


@pytest.fixture()
def live_hub(root):
    """Another live process whose pid sits in hub.lock — the hub, as jarvis-runtime sees it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # nosec B603
    (root / install_identity.HUB_LOCK_FILE).write_text(str(proc.pid), encoding="ascii")
    yield proc
    proc.kill()
    proc.wait()


def _worker(db: Path):
    """One process's autonomy worker on the shared queue DB, wired as the coordinator wires it."""
    from agents.core.autonomy import irreversible
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget

    queue = TaskQueue(db_path=str(db)).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    orch = SimpleNamespace(autonomy=worker)

    async def execute(task):
        if task.kind in irreversible.kinds():
            return await irreversible.execute(task, orch=orch)
        raise AssertionError(f"{task.kind} reached the fallback")

    worker.executor = execute
    return SimpleNamespace(queue=queue, worker=worker, orch=orch)


@pytest.fixture()
def two_processes(root, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import backup as backup_router

    db = tmp_path / "autonomy-q.db"
    hub, runtime = _worker(db), _worker(db)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h010r6")
    monkeypatch.setattr(backup_router, "get_orch", lambda: hub.orch)
    yield SimpleNamespace(hub=hub, runtime=runtime, client=TestClient(web.app))
    hub.queue.close()
    runtime.queue.close()


def _as_runtime(monkeypatch):
    """jarvis-runtime: no stopper (only serve.py installs one), no hold on hub.lock."""
    hub_restart.reset()
    monkeypatch.setattr(install_identity, "_hub_handle", None)


def _as_hub(monkeypatch, stopped):
    """The hub serve.py runs: it holds hub.lock itself and can restart itself."""
    hub_restart.install(lambda: stopped.append(True))
    monkeypatch.setattr(install_identity, "_hub_handle", object())


def test_the_runtime_leaves_an_accepted_restore_for_the_hub_that_said_self(
        two_processes, live_hub, monkeypatch):
    env, stopped = two_processes, []
    _as_hub(monkeypatch, stopped)
    name = Path(bk.create_backup()["archive"]).name
    reply = env.client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert reply.status_code == 202 and reply.json()["restart"] == "self"
    task_id = reply.json()["pending"]
    asyncio.run(env.hub.worker.apply_decision(task_id, "accept", decided_by="admin"))

    # The runtime's loop ticks first and would claim the approved task: it must not.
    _as_runtime(monkeypatch)
    assert install_identity.hub_lock_held_elsewhere() is True
    summary = asyncio.run(env.runtime.worker.tick())
    assert summary["ran"] == 0 and summary["held"] == 1
    task = env.runtime.queue.get(task_id)
    assert task.status == "approved" and task.attempts == 0 and task.result is None
    assert bk.pending_restore() is None                      # nothing staged, no "manual" stage

    # The hub's loop claims it, stages it with restart "self" and restarts itself.
    _as_hub(monkeypatch, stopped)
    summary = asyncio.run(env.hub.worker.tick())
    assert summary["done"] == 1
    task = env.hub.queue.get(task_id)
    assert task.status == "done" and task.result["restart"] == "requested"
    staged = bk.staged_restore_view()
    assert staged["name"] == name and staged["restart"] == "self" and staged["task_id"] == task_id
    assert "action_needed" not in staged
    assert stopped == [True]


def test_the_runtime_applies_a_restore_when_no_hub_holds_the_root(two_processes, monkeypatch):
    env = two_processes
    _as_runtime(monkeypatch)
    name = Path(bk.create_backup()["archive"]).name
    reply = env.client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert reply.json()["restart"] == "manual"
    task_id = reply.json()["pending"]
    asyncio.run(env.runtime.worker.apply_decision(task_id, "accept", decided_by="admin"))
    assert install_identity.hub_lock_held_elsewhere() is False
    summary = asyncio.run(env.runtime.worker.tick())
    assert summary["done"] == 1
    assert env.runtime.queue.get(task_id).result["restart"] == "manual"
    staged = bk.staged_restore_view()
    assert staged["restart"] == "manual" and "restart the hub/service" in staged["action_needed"]


def test_a_hub_that_appears_between_the_hold_and_the_apply_stops_the_stage(
        root, live_hub, monkeypatch):
    """The apply rechecks: it never stages a restore a live hub (that can restart) must take."""
    from agents.core.autonomy import irreversible

    _as_runtime(monkeypatch)
    name = Path(bk.create_backup()["archive"]).name
    st = bk.resolve_backup(name).stat()
    task = SimpleNamespace(id=9, kind="backup.restore", decided_by="admin", decision="accept",
                           payload={"name": name, "bytes": st.st_size, "mtime": st.st_mtime})
    assert irreversible.held_here(task) == "hub_applies_restore"
    assert asyncio.run(irreversible.execute(task, orch=None)) == {
        "status": "refused", "reason": "hub_applies_restore"}
    assert bk.pending_restore() is None


def test_the_hold_is_only_for_the_restore_kind(root, live_hub, monkeypatch):
    from agents.core.autonomy import irreversible

    _as_runtime(monkeypatch)
    assert irreversible.held_here(SimpleNamespace(kind="settings.retention")) is None
    hub_restart.install(lambda: None)                     # a process that can restart: no hold
    assert irreversible.held_here(SimpleNamespace(kind="backup.restore")) is None


def test_the_manual_stage_is_born_manual(root, monkeypatch):
    """No reader sees a stage of an approved restore without its restart mode (r6)."""
    _as_runtime(monkeypatch)
    name = Path(bk.create_backup()["archive"]).name
    seen = []
    real = bk._write_json

    def spy(path, data):
        if Path(path).name == bk._PENDING_RESTORE:
            seen.append(dict(data))
        return real(path, data)

    monkeypatch.setattr(bk, "_write_json", spy)
    st = bk.resolve_backup(name).stat()
    task = SimpleNamespace(id=4, decided_by="admin",
                           payload={"name": name, "bytes": st.st_size, "mtime": st.st_mtime})
    result = asyncio.run(bk.apply_approved(task, None))
    assert result["restart"] == "manual"
    assert seen and all(row.get("restart") == "manual" for row in seen)


# ── nerva approvals accept follows the accepted restore ─────────────────────────

class _Hub:
    """The hub as the CLI sees it: the real decision reply, then the backup listing."""

    def __init__(self, listings):
        self.listings, self.calls = list(listings), []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body=None):
        self.calls.append(("POST", path))
        # routers/autonomy.py autonomy_decide: the task right after apply_decision.
        return {"ok": True, "task": {"id": 5, "kind": "backup.restore", "status": "approved",
                                     "result": None}}

    def get(self, path):
        self.calls.append(("GET", path))
        assert path == "/api/admin/backup"
        item = self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]
        if isinstance(item, Exception):
            raise item
        return item


def _nerva(argv, root, hub, monkeypatch):
    from agents.cli import nerva
    from agents.cli.nerva import Context, main

    monkeypatch.setattr(nerva, "RESTORE_FOLLOW_SECONDS", 0.3)
    monkeypatch.setattr(nerva, "RESTORE_FOLLOW_POLL_SECONDS", 0.01)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def _listing(stage=None, last=None):
    return {"backups": [], "pending_restore": stage, "last_restore": last}


def test_accept_waits_for_the_stage_and_says_a_manual_restore_is_not_applied_yet(root, monkeypatch):
    hint = bk.manual_restart_hint("2026-10-22T10:00:00+00:00")
    manual = {"name": "jarvis-backup-x.tar.gz", "task_id": 5, "state": "waiting",
              "restart": "manual", "action_needed": hint}
    hub = _Hub([_listing(), _listing(), _listing(manual)])
    code, out, _ = _nerva(["approvals", "accept", "5"], root, hub, monkeypatch)
    assert code == 0
    assert "#5 accepted → approved" in out
    assert "NOT applied yet" in out and "before 2026-10-22T10:00:00+00:00" in out
    assert [c for c in hub.calls if c[0] == "GET"] == [("GET", "/api/admin/backup")] * 3


def test_accept_says_the_hub_restarts_itself_only_when_the_stage_says_self(root, monkeypatch):
    self_stage = {"name": "jarvis-backup-x.tar.gz", "task_id": 5, "state": "waiting",
                  "restart": "self"}
    code, out, _ = _nerva(["approvals", "accept", "5"], root, _Hub([_listing(self_stage)]),
                          monkeypatch)
    assert code == 0 and "the hub restarts itself to apply it" in out and "NOT applied" not in out
    other = {**self_stage, "task_id": 99, "restart": "manual", "action_needed": "x"}
    code, out, _ = _nerva(["approvals", "accept", "5"], root, _Hub([_listing(other)]), monkeypatch)
    assert "NOT applied" not in out and "restarts itself" not in out
    assert "not staged yet" in out and "nerva backup list" in out


def test_accept_with_a_hub_gone_quiet_or_a_finished_restore(root, monkeypatch):
    code, out, _ = _nerva(["approvals", "accept", "5"], root,
                          _Hub([_listing(), HubUnavailable("http://127.0.0.1:8080", "refused")]),
                          monkeypatch)
    assert code == 0 and "stopped answering" in out and "nerva backup list" in out
    done = {"name": "jarvis-backup-x.tar.gz", "task_id": 5, "status": "restored"}
    code, out, _ = _nerva(["approvals", "accept", "5"], root, _Hub([_listing(last=done)]),
                          monkeypatch)
    assert "restore of jarvis-backup-x.tar.gz: restored" in out


def test_accept_of_another_kind_does_not_poll(root, monkeypatch):
    class _Other(_Hub):
        def post(self, path, body=None):
            return {"ok": True, "task": {"id": 5, "kind": "settings.retention",
                                         "status": "approved", "result": None}}

    hub = _Other([_listing()])
    code, out, _ = _nerva(["approvals", "accept", "5"], root, hub, monkeypatch)
    assert code == 0 and hub.calls == [] and out.strip() == "#5 accepted → approved"


def test_the_coordinator_process_wires_the_hold_through_the_shared_worker():
    """jarvis-runtime and the hub run one worker class: the hold sits in its claim loop."""
    src = (Path(__file__).resolve().parent.parent / "agents" / "core" / "autonomy" /
           "worker.py").read_text(encoding="utf-8")
    loop = src[src.index("async def _run_runnable"):src.index("async def _run_consent")]
    assert loop.index("irreversible.held_here(task)") < loop.index("TaskStatus.RUNNING")
    assert os.path.exists(Path(__file__).resolve().parent.parent / "scripts" / "coordinator.py")
