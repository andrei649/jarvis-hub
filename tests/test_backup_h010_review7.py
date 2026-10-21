"""H010 review round 7 — ``nerva approvals accept`` says what happens to a restore without
waiting for the hub's autonomy tick.

Each test pins one finding of the seventh review:

* only the hub's worker stages an accepted restore (r6), and it does so on its next
  ``AutonomyCoordinator.loop`` tick — ``max(15, system.autonomy_tick)`` seconds, 60 by
  default — long after the CLI's 8 s follow window. The accept must therefore not depend on
  catching the stage: ``GET /api/admin/backup`` reports the hub's restart mode and its tick,
  and the CLI says "NOT applied yet" for a hub that cannot restart itself right away.
* an accept the apply refuses (``backup_changed``, ``backup_failed_verify``, the
  ``hub_applies_restore`` race …) wrote no stage and no outcome, so the CLI said "not staged
  yet" forever. The refusal is now recorded in ``restore-history.jsonl`` and reported by the
  listing (``refused_restore``), and the CLI tells the owner to request the restore again.
"""
from __future__ import annotations

import asyncio
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup as bk
from agents.core import hub_restart, install_identity

ADMIN = {"X-Admin-Token": "adm-h010r7"}


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
    hub_restart.reset()
    yield data
    hub_restart.reset()


class _Orch:
    """The orchestrator as the router and the coordinator loop read it: live settings."""

    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)


@pytest.fixture()
def api(root, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import backup as backup_router

    orch = _Orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h010r7")
    monkeypatch.setattr(backup_router, "get_orch", lambda: orch)
    return SimpleNamespace(client=TestClient(web.app), orch=orch)


# ── the listing says how and when the hub applies an accepted restore ─────────────

def test_the_listing_reports_the_restart_mode_and_the_tick_the_stage_waits_for(api):
    reply = api.client.get("/api/admin/backup", headers=ADMIN).json()
    assert reply["restart"] == "manual"                  # no stopper installed
    assert reply["stage_within_seconds"] == 60           # settings_db default tick
    api.orch.settings["system.autonomy_tick"] = 300
    assert api.client.get("/api/admin/backup", headers=ADMIN).json()["stage_within_seconds"] == 300
    api.orch.settings["system.autonomy_tick"] = 5        # the loop never ticks faster than 15 s
    assert api.client.get("/api/admin/backup", headers=ADMIN).json()["stage_within_seconds"] == 15
    hub_restart.install(lambda: None)
    assert api.client.get("/api/admin/backup", headers=ADMIN).json()["restart"] == "self"


def test_the_coordinator_loop_sleeps_exactly_the_tick_the_listing_reports(monkeypatch):
    """The real ``AutonomyCoordinator.loop`` with the default setting: the interval the
    listing announces is the one the hub's worker waits before it can stage the accept."""
    from agents.core import autonomy_coordinator as ac

    slept = []

    class _Stop(Exception):
        pass

    async def fake_sleep(seconds):
        slept.append(seconds)
        raise _Stop

    monkeypatch.setattr(ac.asyncio, "sleep", fake_sleep)
    orch = _Orch()
    with pytest.raises(_Stop):
        asyncio.run(ac.AutonomyCoordinator(orch).loop())
    assert slept == [60] == [ac.autonomy_tick_seconds(orch)]
    orch.settings["system.autonomy_tick"] = 1
    assert ac.autonomy_tick_seconds(orch) == 15


# ── nerva approvals accept answers without waiting for the tick ─────────────────

class _Hub:
    """The hub as the CLI sees it: the real decision reply, then the backup listing."""

    def __init__(self, listings):
        self.listings, self.calls = list(listings), []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body=None):
        self.calls.append(("POST", path))
        return {"ok": True, "task": {"id": 5, "kind": "backup.restore", "status": "approved",
                                     "result": None}}

    def get(self, path):
        self.calls.append(("GET", path))
        assert path == "/api/admin/backup"
        return self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]


def _nerva(argv, root, hub, monkeypatch):
    from agents.cli import nerva
    from agents.cli.nerva import Context, main

    monkeypatch.setattr(nerva, "RESTORE_FOLLOW_SECONDS", 0.2)
    monkeypatch.setattr(nerva, "RESTORE_FOLLOW_POLL_SECONDS", 0.01)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def _listing(restart, stage=None, last=None, refused=None, tick=60):
    return {"backups": [], "pending_restore": stage, "last_restore": last,
            "refused_restore": refused, "restart": restart, "stage_within_seconds": tick}


def test_a_manual_hub_accept_says_not_applied_yet_even_when_the_stage_is_a_tick_away(
        root, monkeypatch):
    """Default tick (60 s): the stage never shows up inside the follow window."""
    hub = _Hub([_listing("manual")])
    code, out, _ = _nerva(["approvals", "accept", "5"], root, hub, monkeypatch)
    assert code == 0
    assert "#5 accepted → approved" in out
    assert "NOT applied yet" in out and "within ~60 s" in out
    assert "restart the hub/service yourself" in out
    assert "restarts itself" not in out


def test_a_self_restarting_hub_accept_says_so_before_the_stage(root, monkeypatch):
    code, out, _ = _nerva(["approvals", "accept", "5"], root,
                          _Hub([_listing("self", tick=300)]), monkeypatch)
    assert code == 0
    assert "restarts itself to apply it" in out and "within ~300 s" in out
    assert "NOT applied" not in out


def test_a_stage_that_does_appear_still_adds_its_deadline(root, monkeypatch):
    hint = bk.manual_restart_hint("2026-10-22T10:00:00+00:00")
    stage = {"name": "jarvis-backup-x.tar.gz", "task_id": 5, "state": "waiting",
             "restart": "manual", "action_needed": hint}
    code, out, _ = _nerva(["approvals", "accept", "5"], root,
                          _Hub([_listing("manual"), _listing("manual", stage=stage)]),
                          monkeypatch)
    assert code == 0 and "before 2026-10-22T10:00:00+00:00" in out


def test_a_refused_accept_is_reported_and_asks_for_a_new_request(root, monkeypatch):
    refused = {"event": "refused", "task_id": 5, "name": "jarvis-backup-x.tar.gz",
               "reason": "backup_changed"}
    code, out, _ = _nerva(["approvals", "accept", "5"], root,
                          _Hub([_listing("manual"), _listing("manual", refused=refused)]),
                          monkeypatch)
    assert code == 0
    assert "refused (backup_changed)" in out and "nerva backup restore" in out
    assert "not staged yet" not in out
    other = {**refused, "task_id": 77}
    code, out, _ = _nerva(["approvals", "accept", "5"], root,
                          _Hub([_listing("manual", refused=other)]), monkeypatch)
    assert "refused" not in out


# ── a refused apply leaves a trace the listing reports ──────────────────────────

def _task(name, task_id=5, **over):
    st = bk.resolve_backup(name).stat()
    payload = {"name": name, "bytes": st.st_size, "mtime": st.st_mtime, **over}
    return SimpleNamespace(id=task_id, kind="backup.restore", decided_by="admin",
                           decision="accept", payload=payload)


def test_a_refused_apply_is_recorded_and_listed(root, api, monkeypatch):
    name = Path(bk.create_backup()["archive"]).name
    result = asyncio.run(bk.apply_approved(_task(name, bytes=1), None))
    assert result == {"status": "refused", "reason": "backup_changed"}
    assert bk.pending_restore() is None
    refused = bk.last_refused_restore()
    assert refused["event"] == "refused" and refused["task_id"] == 5
    assert refused["reason"] == "backup_changed" and refused["name"] == name
    listed = api.client.get("/api/admin/backup", headers=ADMIN).json()["refused_restore"]
    assert listed["task_id"] == 5 and listed["reason"] == "backup_changed"


def test_the_hub_race_refusal_is_recorded_too(root, monkeypatch):
    import subprocess  # nosec B404 - the test starts this interpreter as a live "hub" pid
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # nosec B603
    try:
        (root / install_identity.HUB_LOCK_FILE).write_text(str(proc.pid), encoding="ascii")
        monkeypatch.setattr(install_identity, "_hub_handle", None)
        name = Path(bk.create_backup()["archive"]).name
        result = asyncio.run(bk.apply_approved(_task(name, task_id=8), None))
    finally:
        proc.kill()
        proc.wait()
    assert result == {"status": "refused", "reason": "hub_applies_restore"}
    assert bk.last_refused_restore()["task_id"] == 8


def test_a_later_stage_hides_an_older_refusal(root):
    """Only a refusal newer than the last stage is reported: a re-request that staged wins."""
    name = Path(bk.create_backup()["archive"]).name
    asyncio.run(bk.apply_approved(_task(name, bytes=1), None))
    assert bk.last_refused_restore() is not None
    assert bk.stage_restore(name, requested_by="admin", task_id=6, restart="manual")["ok"]
    assert bk.last_refused_restore() is None


def test_backup_list_shows_the_refused_restore(root, monkeypatch):
    from agents.cli.nerva import Context, main

    name = Path(bk.create_backup()["archive"]).name
    asyncio.run(bk.apply_approved(_task(name, bytes=1), None))
    out = io.StringIO()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=io.StringIO(),
                  inp=io.StringIO(""), client_factory=lambda env: None)
    assert main(["backup", "list"], context=ctx) == 0
    assert f"refused restore: {name} (backup_changed)" in out.getvalue()
    assert "nerva backup restore" in out.getvalue()
