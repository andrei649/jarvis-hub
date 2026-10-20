"""H010 — back up and restore the whole install, Hermes-parity.

Three gaps closed on top of H23.8's backup/verify/restore:

* a **quick** snapshot (``create_backup(quick=True)``, ``nerva backup create --quick``):
  only the state SQLite DBs, each through the online backup API — the small, fast
  rollback point Hermes' ``backup --quick`` is;
* restore reachable from the ``nerva`` CLI and the admin API, routed through the
  approval queue's irreversible tier (``backup.restore``, tier 3, a human's accept);
* an **in-place** restore the hub performs itself: an approved restore is *staged*
  (drilled, then a marker under ``backups/``), the hub is asked to restart, and
  ``serve.py`` applies the staged restore at the next boot — before ``agents.web`` is
  imported, so no store has the live DBs open — after a rollback snapshot.
"""
from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup as bk
from agents.core import hub_restart, install_identity


def _seed_db(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
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
def root(tmp_path):
    data = tmp_path / "data"
    _seed_db(data / "settings.db", 3)
    _seed_db(data / "nested" / "autonomy.db", 5)
    (data / "audio").mkdir(parents=True)
    (data / "audio" / "big.wav").write_bytes(b"\0" * 4096)
    (data / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    return data


@pytest.fixture(autouse=True)
def _no_restart_hook():
    hub_restart.reset()
    yield
    hub_restart.reset()


# ── quick snapshot ────────────────────────────────────────────────────────────

def test_quick_backup_holds_only_the_state_dbs(root):
    full = bk.create_backup(source_root=str(root))
    quick = bk.create_backup(source_root=str(root), quick=True)
    with tarfile.open(quick["archive"], "r:gz") as tar:
        names = sorted(tar.getnames())
    assert names == ["backup_manifest.json", "nested/autonomy.db", "settings.db"]
    assert quick["mode"] == "quick" and full["mode"] == "full"
    assert sorted(quick["dbs"]) == ["nested/autonomy.db", "settings.db"]
    assert quick["file_count"] == 2
    assert quick["bytes"] < full["bytes"]
    assert Path(quick["archive"]).name.startswith("jarvis-backup-quick-")
    listing = bk.list_backups(out_dir=str(bk.default_backup_dir(root)))
    assert {r["name"]: r["quick"] for r in listing} == {
        Path(quick["archive"]).name: True, Path(full["archive"]).name: False}
    assert bk.verify_backup(quick["archive"])["ok"] is True


def test_restoring_a_quick_snapshot_rolls_the_dbs_back_and_drops_stale_wal(root):
    snap = bk.create_backup(source_root=str(root), quick=True)
    _seed_db(root / "settings.db", 10)                    # state moves on: 13 rows
    (root / "notes.json").write_text('{"a": 2}', encoding="utf-8")
    (root / "settings.db-wal").write_bytes(b"stale wal that would replay over the snapshot")
    (root / "settings.db-shm").write_bytes(b"stale shm")
    res = bk.restore_backup(snap["archive"], str(root), force=True)
    assert res["ok"] is True, res
    assert _rows(root / "settings.db") == 3
    assert not (root / "settings.db-wal").exists() and not (root / "settings.db-shm").exists()
    assert (root / "notes.json").read_text(encoding="utf-8") == '{"a": 2}'  # not in a quick snapshot
    assert (root / "audio" / "big.wav").exists()


# ── staged in-place restore ───────────────────────────────────────────────────

def test_stage_restore_drills_the_archive_and_writes_a_marker(root):
    arc = bk.create_backup(source_root=str(root))
    name = Path(arc["archive"]).name
    staged = bk.stage_restore(name, source_root=str(root))
    assert staged["ok"] is True and staged["name"] == name
    assert bk.pending_restore(root)["name"] == name
    # Staging touches no live data.
    assert _rows(root / "settings.db") == 3


def test_stage_restore_refuses_an_unknown_or_broken_archive(root):
    with pytest.raises(FileNotFoundError):
        bk.stage_restore("jarvis-backup-nope.tar.gz", source_root=str(root))
    out = bk.default_backup_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    bad = out / "jarvis-backup-broken.tar.gz"
    bad.write_bytes(b"not a tar")
    staged = bk.stage_restore(bad.name, source_root=str(root))
    assert staged["ok"] is False and staged["problem"]
    assert bk.pending_restore(root) is None


def test_apply_pending_restore_restores_in_place_after_a_rollback_snapshot(root):
    arc = bk.create_backup(source_root=str(root))
    name = Path(arc["archive"]).name
    _seed_db(root / "settings.db", 7)                      # 10 rows live
    bk.stage_restore(name, source_root=str(root))
    result = bk.apply_pending_restore(root)
    assert result["status"] == "restored", result
    assert result["name"] == name and result["ok"] is True
    assert _rows(root / "settings.db") == 3                # the archive's state
    assert bk.pending_restore(root) is None                # one attempt, never a boot loop
    rollback = result["rollback"]
    # A full restore gets a full rollback point (H010 review): it overwrites more than DBs.
    assert rollback.startswith("jarvis-backup-") and not rollback.startswith("jarvis-backup-quick-")
    # The rollback point holds the pre-restore state and restores it back.
    path = bk.resolve_backup(rollback, out_dir=str(bk.default_backup_dir(root)))
    bk.restore_backup(str(path), str(root), force=True)
    assert _rows(root / "settings.db") == 10
    assert bk.last_restore(root)["name"] == name


def test_apply_pending_restore_is_a_noop_without_a_marker(root):
    assert bk.apply_pending_restore(root) is None
    assert bk.last_restore(root) is None


def test_apply_pending_restore_defers_while_another_hub_holds_the_root(root, monkeypatch):
    arc = bk.create_backup(source_root=str(root))
    bk.stage_restore(Path(arc["archive"]).name, source_root=str(root))
    monkeypatch.setattr(install_identity, "hub_lock_held_elsewhere", lambda root=None: True)
    result = bk.apply_pending_restore(root)
    assert result["status"] == "deferred"
    assert bk.pending_restore(root) is not None            # still staged for the next boot


def test_a_staged_restore_whose_archive_vanished_fails_once_and_clears(root):
    arc = bk.create_backup(source_root=str(root))
    bk.stage_restore(Path(arc["archive"]).name, source_root=str(root))
    Path(arc["archive"]).unlink()
    result = bk.apply_pending_restore(root)
    assert result["status"] == "failed" and result["reason"] == "backup_missing"
    assert bk.pending_restore(root) is None
    assert bk.last_restore(root)["status"] == "failed"
    assert _rows(root / "settings.db") == 3


# ── the hub restarts itself ───────────────────────────────────────────────────

def test_a_restart_request_without_a_running_server_says_so():
    assert hub_restart.request("backup.restore") is False
    assert hub_restart.requested() is None


def test_a_restart_request_stops_the_server_and_is_remembered():
    stopped = []
    hub_restart.install(lambda: stopped.append(True))
    assert hub_restart.request("backup.restore") is True
    assert stopped == [True] and hub_restart.requested() == "backup.restore"


def test_serve_reexecs_itself_when_a_restart_was_requested(monkeypatch):
    import serve

    calls = []
    released = []
    monkeypatch.setattr(serve.os, "execv", lambda exe, argv: calls.append((exe, list(argv))))
    monkeypatch.setattr(install_identity, "release_hub_lock", lambda: released.append(True))

    class _Server:
        should_exit = False

        def run(self):
            assert hub_restart.request("backup.restore") is True
            assert self.should_exit is True

    serve.run_server(_Server())
    assert released == [True]
    assert calls == [(sys.executable, list(sys.orig_argv))]


def test_serve_does_not_reexec_on_a_plain_stop(monkeypatch):
    import serve

    calls = []
    monkeypatch.setattr(serve.os, "execv", lambda exe, argv: calls.append(exe))

    class _Server:
        should_exit = False

        def run(self):
            return None

    serve.run_server(_Server())
    assert calls == [] and hub_restart.requested() is None


def test_serve_applies_a_staged_restore_before_the_hub_opens_its_stores(root, monkeypatch, capsys):
    import serve

    arc = bk.create_backup(source_root=str(root))
    _seed_db(root / "settings.db", 4)
    bk.stage_restore(Path(arc["archive"]).name, source_root=str(root))
    monkeypatch.setenv("JARVIS_HOME", str(root))
    result = serve.apply_staged_restore()
    assert result["status"] == "restored"
    assert _rows(root / "settings.db") == 3
    assert "Restored backup" in capsys.readouterr().out
    assert serve.apply_staged_restore() is None
    # The boot hook runs before the hub module is imported (stores open at import).
    text = Path(serve.__file__).read_text(encoding="utf-8")
    assert text.index("apply_staged_restore()\n") < text.index("from agents.web import app")


# ── the irreversible tier: route + approved apply ─────────────────────────────

ADMIN = {"X-Admin-Token": "adm-h010"}


@pytest.fixture
def env(tmp_path, monkeypatch, root):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget

    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    queue = TaskQueue(db_path=str(tmp_path / "autonomy-q.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    orch = SimpleNamespace(autonomy=worker)
    yield SimpleNamespace(root=root, queue=queue, worker=worker, orch=orch)
    queue.close()


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import backup as backup_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h010")
    monkeypatch.setattr(backup_router, "get_orch", lambda: env.orch)
    return TestClient(web.app)


def test_the_restore_route_queues_a_tier_three_card_and_stages_nothing(env, client):
    arc = bk.create_backup()
    name = Path(arc["archive"]).name
    resp = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    task = env.queue.get(body["pending"])
    assert task.kind == "backup.restore" and task.risk_tier == 3 and task.status == "blocked"
    assert task.payload["name"] == name and task.payload["reversible"] is False
    assert task.payload["preview"]["verify"]["ok"] is True
    assert bk.pending_restore(env.root) is None
    again = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name})
    assert again.status_code == 202 and again.json() == {"pending": body["pending"], "existing": True}


def test_the_restore_route_refuses_unknown_names_and_needs_admin(env, client):
    assert client.post("/api/admin/backup/restore", headers=ADMIN,
                       json={"name": "jarvis-backup-nope.tar.gz"}).status_code == 404
    assert client.post("/api/admin/backup/restore", headers=ADMIN, json={}).status_code == 400
    assert client.post("/api/admin/backup/restore", json={"name": "x"}).status_code in (401, 403)


def test_a_human_accept_stages_the_restore_and_asks_the_hub_to_restart(env, client):
    from agents.core.autonomy import irreversible

    stopped = []
    hub_restart.install(lambda: stopped.append(True))
    name = Path(bk.create_backup()["archive"]).name
    task_id = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name}).json()["pending"]
    machine = SimpleNamespace(id=task_id, kind="backup.restore", payload=env.queue.get(task_id).payload,
                              decided_by="policy", decision="accept")
    assert asyncio.run(irreversible.execute(machine, orch=env.orch))["reason"] == "human_decision_required"
    assert bk.pending_restore(env.root) is None and stopped == []
    task = asyncio.run(env.worker.apply_decision(task_id, "accept", decided_by="admin"))
    result = asyncio.run(irreversible.execute(task, orch=env.orch))
    staged = bk.pending_restore(env.root)
    assert result == {"status": "ok", "kind": "backup.restore", "staged": name, "restart": "requested",
                      "expires_at": staged["expires_at"]}
    assert staged["name"] == name
    assert stopped == [True]


def test_an_accept_after_the_archive_changed_is_refused(env, client):
    from agents.core.autonomy import irreversible

    arc = bk.create_backup()
    name = Path(arc["archive"]).name
    task_id = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name}).json()["pending"]
    Path(arc["archive"]).write_bytes(Path(arc["archive"]).read_bytes() + b"\0")
    task = asyncio.run(env.worker.apply_decision(task_id, "accept", decided_by="admin"))
    assert asyncio.run(irreversible.execute(task, orch=env.orch)) == {
        "status": "refused", "reason": "backup_changed"}
    assert bk.pending_restore(env.root) is None


def test_the_backup_listing_names_a_pending_and_the_last_restore(env, client):
    name = Path(bk.create_backup()["archive"]).name
    bk.stage_restore(name)
    body = client.get("/api/admin/backup", headers=ADMIN).json()
    assert body["pending_restore"]["name"] == name and body["last_restore"] is None


# ── the `nerva backup` verbs ──────────────────────────────────────────────────

class _Hub:
    def __init__(self, routes=None, raise_with=None):
        self.routes, self.raise_with, self.calls = dict(routes or {}), raise_with, []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body=None):
        self.calls.append(("POST", path, body))
        if self.raise_with is not None:
            raise self.raise_with
        return self.routes[f"POST {path}"]

    def get(self, path):
        self.calls.append(("GET", path, None))
        if self.raise_with is not None:
            raise self.raise_with
        return self.routes[f"GET {path}"]


def _nerva(argv, root, hub=None, stdin=""):
    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    hub = hub or _Hub()
    ctx = Context(environ={"JARVIS_HOME": str(root)}, out=out, err=err, inp=io.StringIO(stdin),
                  client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), hub


def test_nerva_backup_create_quick_list_and_verify_offline(root):
    code, out, err, hub = _nerva(["backup", "create", "--quick", "--json"], root)
    assert code == 0, err
    made = json.loads(out)
    assert made["mode"] == "quick" and made["file_count"] == 2
    code, out, _, _ = _nerva(["backup", "list", "--json"], root)
    listing = json.loads(out)
    assert [r["name"] for r in listing["backups"]] == [Path(made["archive"]).name]
    assert listing["pending_restore"] is None
    code, out, _, _ = _nerva(["backup", "verify"], root)
    assert code == 0 and "ok" in out
    assert hub.calls == []                                 # offline: the hub was never asked


def test_nerva_backup_restore_asks_the_running_hub_for_an_approval(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    hub = _Hub({"POST /api/admin/backup/restore": {"pending": 42}})
    code, out, err, _ = _nerva(["backup", "restore", name], root, hub=hub)
    assert code == 0, err
    assert hub.calls == [("POST", "/api/admin/backup/restore", {"name": name})]
    assert "#42" in out and "nerva approvals accept 42" in out
    assert bk.pending_restore(root) is None


def test_nerva_backup_restore_offline_needs_the_irreversible_confirmation(root):
    from agents.cli.client import HubUnavailable
    from agents.cli.nerva import EXIT_USAGE

    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    _seed_db(root / "settings.db", 2)
    down = _Hub(raise_with=HubUnavailable("http://127.0.0.1:8080", "connection refused"))
    code, _, err, _ = _nerva(["backup", "restore", name], root, hub=down)
    assert code == EXIT_USAGE and "IRREVERSIBLE" in err and "--confirm RESTORE" in err
    assert _rows(root / "settings.db") == 5 and bk.pending_restore(root) is None
    code, out, err, _ = _nerva(["backup", "restore", name, "--confirm", "RESTORE"], root, hub=down)
    assert code == 0, err
    assert _rows(root / "settings.db") == 3
    assert "rollback" in out


def test_nerva_backup_restore_offline_refuses_an_unknown_name(root):
    from agents.cli.client import HubUnavailable

    down = _Hub(raise_with=HubUnavailable("http://127.0.0.1:8080", "connection refused"))
    code, _, err, _ = _nerva(["backup", "restore", "jarvis-backup-nope.tar.gz", "--confirm", "RESTORE"],
                             root, hub=down)
    assert code == 1 and "no such backup" in err


# ── governance: the in-place path has exactly these callers ───────────────────

def test_the_in_place_restore_is_reached_only_from_the_boot_hook_and_the_offline_cli():
    repo = Path(__file__).resolve().parent.parent
    callers = set()
    for path in [*sorted((repo / "agents").rglob("*.py")), *sorted(repo.glob("*.py"))]:
        rel = path.relative_to(repo).as_posix()
        if rel == "agents/core/backup.py":
            continue
        if "apply_pending_restore" in path.read_text(encoding="utf-8", errors="replace"):
            callers.add(rel)
    assert callers == {"serve.py", "agents/cli/nerva.py"}
