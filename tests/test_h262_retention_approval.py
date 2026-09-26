"""H262 — a write that deepens what retention deletes waits for a human.

The retention settings (``retention.RETENTION_KEYS``) decide what the lifecycle sweep
deletes for good. A write that would make it delete deeper than the last horizon a human
approved is never applied on one click: the settings route sends it to the approval
queue's irreversible tier (``agents/core/autonomy/irreversible.py``, kind
``settings.retention``, tier 3) and answers 202; an import or an undo that would do it is
refused (409); a reset keeps those keys as they are; ``nerva config set`` refuses it. Only
a human's accept applies it — the values, then the approved snapshot the sweep clamps to,
then an audit row. A queue that cannot take the task (no autonomy, mediation enforce)
means 503 and nothing written.
"""
from __future__ import annotations

import asyncio
import io
import time
from types import SimpleNamespace

import pytest

from agents.core import retention, settings_db
from agents.core.autonomy import irreversible
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
from agents.core.checkpoint import CheckpointManager
from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEvent, SecurityEventType

ADMIN = {"X-Admin-Token": "adm-h262"}
KIND = "settings.retention"


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "checkpoints").mkdir(parents=True)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    cp = CheckpointManager(str(home / "checkpoints" / "checkpoints.db"))
    cp.initialize()
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    orch = SimpleNamespace(autonomy=worker, checkpoints=cp, audit=audit)
    yield SimpleNamespace(home=home, cp=cp, audit=audit, queue=queue, worker=worker, orch=orch, tmp=tmp_path)
    queue.close()
    cp.close()


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import admin

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h262")
    monkeypatch.setattr(admin, "get_orch", lambda: env.orch)
    return TestClient(web.app)


def _value(name):
    cat, key = name.split(".", 1)
    return settings_db.get_value(cat, key)


def _approve(env, **values):
    """Record an approved snapshot of the retention settings as they are, overridden."""
    current = retention.stored_values()
    current.update({k.replace("__", "."): v for k, v in values.items()})
    env.cp.put_state(retention.APPROVED_STATE, {"values": current})


def _pending(env):
    return [t for t in env.queue.pending_decisions() if t.kind == KIND]


def _audit_rows(env):
    return [e for e in env.audit.query(limit=100) if e.event_type == SecurityEventType.SETTINGS_CHANGE]


# ── the gate itself (pure) ────────────────────────────────────────────────────────

def test_the_gate_names_a_write_that_deepens_a_horizon_past_the_approved_one():
    off = {"retention.enabled": False, "retention.conversation_ttl_days": 90, "retention.audit_ttl_days": 365,
           "retention.ingestion_ttl_days": 0, "retention.artifact_ttl_days": 0, "memory.auto_archive_days": 0}
    on = {**off, "retention.enabled": True}
    approved = retention.horizons(on)
    # turning it on with nothing approved deepens audit (365 < forever)
    assert retention.needs_approval({"retention": {"enabled": True}}, off, None) == ["retention.enabled"]
    # a shorter audit TTL than approved deepens; a longer one does not
    assert retention.needs_approval({"retention": {"audit_ttl_days": 30}}, on, approved) == ["retention.audit_ttl_days"]
    assert retention.needs_approval({"retention": {"audit_ttl_days": 900}}, on, approved) == []
    # archiving on while retention is on makes chats deletable: conversations deepen
    assert retention.needs_approval({"memory": {"auto_archive_days": 30}}, on, approved) == ["memory.auto_archive_days"]
    assert retention.needs_approval({"memory": {"auto_archive_days": 30}}, off, None) == []
    # a key outside the retention set is never gated
    assert retention.needs_approval({"retention": {"min_interval_hours": 1}}, on, None) == []
    # re-sending the stored values: only a confirming write (the settings route) asks
    assert retention.needs_approval({"retention": {"enabled": True}}, on, None) == []
    assert retention.needs_approval({"retention": {"enabled": True}}, on, None, confirm=True) == ["retention.enabled"]
    assert retention.needs_approval({"retention": {"enabled": True}}, on, approved, confirm=True) == []
    # a confirming write of a key that has nothing to do with the class that deepens
    assert retention.needs_approval({"memory": {"auto_archive_days": 0}}, on, None, confirm=True) == []


# ── 15. the settings route ────────────────────────────────────────────────────────

def test_a_widening_put_is_queued_and_the_rest_of_the_write_is_applied(env, client):
    resp = client.put("/api/admin/settings/retention", headers=ADMIN,
                      json={"values": {"enabled": True, "audit_ttl_days": 30, "min_interval_hours": 6}})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["gated"] == ["retention.audit_ttl_days", "retention.enabled"]
    assert body["updated"] == 1 and body["category"] == "retention"
    assert _value("retention.enabled") is False and _value("retention.audit_ttl_days") == 365
    assert _value("retention.min_interval_hours") == 6
    [task] = _pending(env)
    assert task.id == body["pending"] and task.status == "blocked" and task.risk_tier == 3
    assert task.payload["values"] == {"retention": {"enabled": True, "audit_ttl_days": 30}}
    assert task.payload["before"]["retention.enabled"] is False
    assert task.payload["reversible"] is False and task.payload["risk_tier"] == 3
    preview = task.payload["preview"]
    assert preview["horizons"]["audit"] == 30 and preview["horizons"]["conversations"] is None
    assert preview["approved"] is None and "audit" in preview["widened"]
    assert env.cp.get_state(retention.APPROVED_STATE) is None


def test_the_card_preview_counts_what_the_new_horizon_would_remove(env, client):
    from datetime import UTC, datetime, timedelta

    for age in (400, 200, 10):
        env.audit.log(SecurityEvent(event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time() - age * 86400,
                                    content_preview=f"row {age}", action_taken="t"))
    old = (datetime.now(UTC) - timedelta(days=500)).isoformat()
    for sid, archived in (("old-chat", True), ("old-open-chat", False)):
        env.cp.create_session_record(sid, "jarvis", {})
        with env.cp._lock:
            env.cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (old, old, sid))
            env.cp._conn.commit()
        env.cp.set_archived(sid, archived)
    settings_db.put_category("retention", {"enabled": True})
    settings_db.put_category("memory", {"auto_archive_days": 30})
    _approve(env, retention__conversation_ttl_days=0, retention__audit_ttl_days=0)
    resp = client.put("/api/admin/settings/retention", headers=ADMIN,
                      json={"values": {"audit_ttl_days": 100, "conversation_ttl_days": 60}})
    assert resp.status_code == 202, resp.text
    preview = env.queue.get(resp.json()["pending"]).payload["preview"]
    assert preview["horizons"]["conversations"] == 60 and preview["horizons"]["audit"] == 100
    assert preview["approved"]["conversations"] is None and sorted(preview["widened"]) == ["audit", "conversations"]
    assert preview["would_delete"] == {"archived_chats": 1, "audit_rows": 2}


def test_a_narrowing_put_is_written_at_once(env, client):
    settings_db.put_category("retention", {"enabled": True})
    _approve(env)
    resp = client.put("/api/admin/settings/retention", headers=ADMIN, json={"values": {"audit_ttl_days": 900}})
    assert resp.status_code == 200, resp.text
    assert _value("retention.audit_ttl_days") == 900 and _pending(env) == []


def test_resending_the_settings_with_nothing_approved_asks_to_confirm_them(env, client):
    """An install that had retention on before H262 deletes nothing until the owner
    confirms once: the HUD re-sends the stored values, which queues them."""
    settings_db.put_category("retention", {"enabled": True})
    resp = client.put("/api/admin/settings/retention", headers=ADMIN, json={"values": {"enabled": True}})
    assert resp.status_code == 202 and resp.json()["gated"] == ["retention.enabled"]
    _approve(env)
    again = client.put("/api/admin/settings/retention", headers=ADMIN, json={"values": {"enabled": True}})
    assert again.status_code == 200


# ── 16. the archive setting is a retention key ────────────────────────────────────

def test_turning_archiving_on_while_retention_is_on_is_a_widening_write(env, client):
    settings_db.put_category("retention", {"enabled": True})
    _approve(env)
    resp = client.put("/api/admin/settings/memory", headers=ADMIN, json={"values": {"auto_archive_days": 30}})
    assert resp.status_code == 202 and resp.json()["gated"] == ["memory.auto_archive_days"]
    assert _value("memory.auto_archive_days") == 0
    assert _pending(env)[0].payload["values"] == {"memory": {"auto_archive_days": 30}}


def test_turning_archiving_on_with_retention_off_is_written_at_once(env, client):
    resp = client.put("/api/admin/settings/memory", headers=ADMIN, json={"values": {"auto_archive_days": 30}})
    assert resp.status_code == 200 and _value("memory.auto_archive_days") == 30 and _pending(env) == []


# ── 17. the executor ──────────────────────────────────────────────────────────────

def _queued(env, client, values, category="retention"):
    resp = client.put(f"/api/admin/settings/{category}", headers=ADMIN, json={"values": values})
    assert resp.status_code == 202, resp.text
    return resp.json()["pending"]


def test_a_human_accept_writes_the_values_the_snapshot_and_an_audit_row(env, client):
    task_id = _queued(env, client, {"enabled": True, "audit_ttl_days": 30})
    task = asyncio.run(env.worker.apply_decision(task_id, "accept", decided_by="admin"))
    result = asyncio.run(irreversible.execute(task, orch=env.orch))
    assert result["status"] == "ok", result
    assert _value("retention.enabled") is True and _value("retention.audit_ttl_days") == 30
    approved = env.cp.get_state(retention.APPROVED_STATE)["value"]
    assert approved["values"] == retention.stored_values()
    assert approved["task_id"] == task_id and approved["approved_by"] == "admin"
    assert retention.approved_horizons(env.cp)["audit"] == 30
    rows = {row.action_taken: row for row in _audit_rows(env)}
    assert set(rows) == {"settings_retention_requested", "settings_retention_approved"}
    assert f"task {task_id}" in rows["settings_retention_requested"].content_preview
    row = rows["settings_retention_approved"]
    assert f"task {task_id}" in row.content_preview and "retention.audit_ttl_days=30" in row.content_preview


@pytest.mark.parametrize("decided_by,decision,reason", [
    ("policy", "accept", "human_decision_required"),
    ("worker", "accept", "human_decision_required"),
    ("", "accept", "human_decision_required"),
    ("admin", "needs-approval", "decision_not_approval"),
    ("admin", "reject", "decision_not_approval"),
])
def test_only_a_human_accept_applies_it(env, client, decided_by, decision, reason):
    task = env.queue.get(_queued(env, client, {"enabled": True}))
    task.decided_by, task.decision = decided_by, decision
    assert asyncio.run(irreversible.execute(task, orch=env.orch)) == {"status": "refused", "reason": reason}
    assert _value("retention.enabled") is False and env.cp.get_state(retention.APPROVED_STATE) is None


def test_a_setting_changed_since_the_request_is_refused(env, client):
    task_id = _queued(env, client, {"enabled": True})
    settings_db.put_category("retention", {"audit_ttl_days": 7})
    task = asyncio.run(env.worker.apply_decision(task_id, "accept", decided_by="admin"))
    result = asyncio.run(irreversible.execute(task, orch=env.orch))
    assert result == {"status": "refused", "reason": "changed_since_request"}
    assert _value("retention.enabled") is False and env.cp.get_state(retention.APPROVED_STATE) is None


def test_an_edited_payload_cannot_carry_another_setting_or_an_invalid_value(env, client):
    task = env.queue.get(_queued(env, client, {"enabled": True}))
    task.decided_by, task.decision = "admin", "edit"
    task.payload = {**task.payload, "values": {"retention": {"enabled": True}, "system": {"log_level": "DEBUG"}}}
    assert asyncio.run(irreversible.execute(task, orch=env.orch))["reason"] == "not_a_retention_setting"
    task.payload = {**task.payload, "values": {"retention": {"audit_ttl_days": -3}}}
    assert asyncio.run(irreversible.execute(task, orch=env.orch))["reason"] == "invalid_settings"
    assert settings_db.get_value("system", "log_level") != "DEBUG"


def test_an_unknown_kind_is_never_queued_or_run():
    assert irreversible.enqueue(SimpleNamespace(autonomy=None), "settings.nope", title="t", payload={},
                                preview={}) == {"refused": "unknown_kind"}
    task = SimpleNamespace(id=1, kind="settings.nope", payload={}, decided_by="admin", decision="accept")
    assert asyncio.run(irreversible.execute(task, orch=None)) == {"status": "refused", "reason": "unknown_kind"}
    assert KIND in irreversible.kinds()


def test_the_executor_routes_the_kind_to_the_helper_not_the_llm():
    from tests.test_web_tools_wiring import _coordinator

    executor = _coordinator({}).build_executor()
    handler = executor.resolve(KIND)
    assert handler is not None and handler is not executor.fallback


def test_the_executor_handler_applies_through_the_helper(env, client, monkeypatch):
    from tests.test_web_tools_wiring import _coordinator

    coordinator = _coordinator({})
    coordinator._orch.checkpoints, coordinator._orch.audit = env.cp, env.audit
    executor = coordinator.build_executor()
    task = asyncio.run(env.worker.apply_decision(_queued(env, client, {"enabled": True}), "accept", decided_by="admin"))
    assert asyncio.run(executor.resolve(KIND)(task))["status"] == "ok"
    assert _value("retention.enabled") is True


# ── 18. a queue that cannot take it ───────────────────────────────────────────────

def test_mediation_enforce_refuses_a_widening_put_and_writes_nothing(env, client, monkeypatch):
    from agents.core.autonomy.mediation_head_store import resolve_task_mediation_mode

    monkeypatch.setenv("JARVIS_TASK_MEDIATION", "enforce")
    queue = TaskQueue(db_path=str(env.tmp / "enforce.db"), mediation_mode=resolve_task_mediation_mode()).initialize()
    env.orch.autonomy = AutonomyWorker(queue, policy=AutonomyPolicy(), budget=InterruptBudget(per_day=4))
    try:
        resp = client.put("/api/admin/settings/retention", headers=ADMIN,
                          json={"values": {"enabled": True, "min_interval_hours": 6}})
    finally:
        queue.close()
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"] == "retention_needs_approval" and resp.json()["reason"] == "approval_queue_refused"
    assert _value("retention.enabled") is False and _value("retention.min_interval_hours") == 24


def test_no_autonomy_refuses_a_widening_put_and_writes_nothing(env, client):
    env.orch.autonomy = None
    resp = client.put("/api/admin/settings/retention", headers=ADMIN,
                      json={"values": {"enabled": True, "min_interval_hours": 6}})
    assert resp.status_code == 503 and resp.json()["reason"] == "approval_queue_unavailable"
    assert _value("retention.enabled") is False and _value("retention.min_interval_hours") == 24


# ── 19. import, reset, undo ───────────────────────────────────────────────────────

def test_a_widening_import_is_refused_with_nothing_applied(env, client):
    doc = {"settings": {"retention": {"enabled": True}, "system": {"log_level": "DEBUG"}}}
    dry = client.post("/api/admin/settings/import", headers=ADMIN, json={**doc, "dry_run": True})
    assert dry.status_code == 200 and dry.json()["retention_needs_approval"] == ["retention.enabled"]
    resp = client.post("/api/admin/settings/import", headers=ADMIN, json=doc)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "retention_needs_approval" and resp.json()["settings"] == ["retention.enabled"]
    assert _value("retention.enabled") is False and settings_db.get_value("system", "log_level") != "DEBUG"
    narrowing = client.post("/api/admin/settings/import", headers=ADMIN,
                            json={"settings": {"retention": {"audit_ttl_days": 900}}})
    assert narrowing.status_code == 200 and _value("retention.audit_ttl_days") == 900


def test_a_reset_keeps_a_retention_key_it_would_deepen(env, client, monkeypatch):
    # With the shipped defaults a reset only ever narrows (enabled goes back to off), so
    # declare a default that deletes: the reset must keep that key as it is.
    monkeypatch.setitem(settings_db._SPEC[("retention", "enabled")], "value", True)
    dry = client.post("/api/admin/settings/retention/reset", headers=ADMIN, json={"dry_run": True}).json()
    assert dry["retention_kept"] == ["retention.enabled"]
    assert "retention.enabled" not in {c["setting"] for c in dry["changes"]}
    settings_db.put_category("retention", {"min_interval_hours": 6})
    done = client.post("/api/admin/settings/retention/reset", headers=ADMIN, json={}).json()
    assert done["retention_kept"] == ["retention.enabled"] and "enabled" not in done["reset"]
    assert _value("retention.enabled") is False and _value("retention.min_interval_hours") == 24
    reseed = client.post("/api/admin/settings/reseed", headers=ADMIN, json={}).json()
    assert reseed["retention_kept"] == ["retention.enabled"] and _value("retention.enabled") is False


def test_a_reset_that_narrows_moves_the_retention_keys_as_before(env, client):
    settings_db.put_category("retention", {"enabled": True, "audit_ttl_days": 30})
    done = client.post("/api/admin/settings/retention/reset", headers=ADMIN, json={}).json()
    assert done["retention_kept"] == [] and _value("retention.enabled") is False


def test_a_widening_undo_is_refused_with_nothing_restored(env, client):
    settings_db.put_category("retention", {"enabled": True, "audit_ttl_days": 30})
    _approve(env, retention__audit_ttl_days=365)
    client.post("/api/admin/settings/retention/reset", headers=ADMIN, json={})
    assert _value("retention.enabled") is False
    resp = client.post("/api/admin/settings/undo", headers=ADMIN, json={})
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "retention_needs_approval"
    assert "retention.enabled" in resp.json()["settings"]
    assert _value("retention.enabled") is False and _value("retention.audit_ttl_days") == 365
    assert settings_db.list_resets()[0]["undone"] is False


def test_an_undo_within_the_approved_horizon_is_restored(env, client):
    settings_db.put_category("retention", {"enabled": True, "audit_ttl_days": 30})
    _approve(env)
    client.post("/api/admin/settings/retention/reset", headers=ADMIN, json={})
    resp = client.post("/api/admin/settings/undo", headers=ADMIN, json={})
    assert resp.status_code == 200 and _value("retention.enabled") is True


# ── 20. nerva config set ──────────────────────────────────────────────────────────

def _cli(*argv):
    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(list(argv), context=ctx), out.getvalue(), err.getvalue()


def test_config_set_refuses_a_widening_write(env):
    code, _out, err = _cli("config", "set", "retention.enabled", "true")
    assert code == 1 and "Settings → Retention" in err and _value("retention.enabled") is False


def test_config_set_writes_a_narrowing_or_approved_one(env):
    code, _out, err = _cli("config", "set", "retention.audit_ttl_days", "900")
    assert code == 0, err
    assert _value("retention.audit_ttl_days") == 900
    settings_db.put_category("retention", {"audit_ttl_days": 365})
    _approve(env, retention__enabled=True)
    code, _out, err = _cli("config", "set", "retention.enabled", "true")
    assert code == 0, err
    assert _value("retention.enabled") is True


def test_config_set_reads_the_snapshot_read_only_and_an_unreadable_one_approves_nothing(env):
    (env.home / "checkpoints" / "checkpoints.db").write_bytes(b"not a database")
    assert retention.approved_horizons_offline() is None
    code, _out, _err = _cli("config", "set", "retention.enabled", "true")
    assert code == 1 and (env.home / "checkpoints" / "checkpoints.db").read_bytes() == b"not a database"


# ── the state route ───────────────────────────────────────────────────────────────

def test_the_retention_state_route_is_admin_only_and_says_what_is_approved(env, client):
    assert client.get("/api/admin/retention").status_code in (401, 403)
    settings_db.put_category("retention", {"enabled": True})
    got = client.get("/api/admin/retention", headers=ADMIN).json()
    assert got["awaiting_approval"] is True and got["approved"] is None
    assert got["current"]["retention.enabled"] is True and got["horizons"]["current"]["audit"] == 365
    assert got["horizons"]["effective"] is None
    _approve(env)
    env.cp.put_state("lifecycle_sweep", {"last_vacuum_at": 5.0, "vacuum_pending": [], "last_report": {"archived": []}})
    got = client.get("/api/admin/retention", headers=ADMIN).json()
    assert got["awaiting_approval"] is False and got["approved"]["values"]["retention.enabled"] is True
    assert got["horizons"]["effective"]["audit"] == 365 and got["sweep"]["last_vacuum_at"] == 5.0
