"""H329 approval-backed, replay-safe skill switch writes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.permission_ledger import PermissionLedger
from agents.core.skills import switch_approval, switches
from agents.core.skills.signing import source_snapshot
from tests.test_h329_skill_switches import _skill


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)


def test_redundant_disable_advances_durable_revision(tmp_path):
    skill = _skill(tmp_path, "weather", "Weather Intel")
    first = switch_approval.disable([skill], channel="", actor="admin")
    revision = switch_approval.revision()
    second = switch_approval.disable([skill], channel="", actor="admin")
    assert first["changed"] == ["Weather Intel"]
    assert second["unchanged"] == ["Weather Intel"]
    assert switch_approval.revision() > revision


def test_deleted_switch_row_after_restart_remains_fail_closed(tmp_path, monkeypatch):
    skill = _skill(tmp_path, "weather", "Weather Intel")
    switch_approval.disable([skill])
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='skills' AND key='disabled'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(settings_db, "_initialized", False)
    assert switches.off_reason(skill) == "switches unavailable"
    with pytest.raises(settings_db.SettingsUnreadable):
        switch_approval.disable([skill])


def test_first_switch_read_marks_store_against_later_row_loss(tmp_path, monkeypatch):
    skill = _skill(tmp_path, "weather", "Weather Intel")
    assert switches.state() == {"disabled": [], "channel_disabled": {}}
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='skills' AND key='disabled'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(settings_db, "_initialized", False)
    assert switches.off_reason(skill) == "switches unavailable"


def test_legacy_store_without_bridge_marker_can_seed_new_switch_rows(tmp_path):
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='skills' AND key='disabled'")
        conn.commit()
    finally:
        conn.close()
    settings_db._initialized = False
    assert switches.state() == {"disabled": [], "channel_disabled": {}}


def _approval_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(switch_approval, "kernel_enabled", lambda: True)
    monkeypatch.setattr("agents.core.permission_ledger._kernel_on", lambda: True)
    skill = _skill(tmp_path, "weather", "Weather Intel")
    skill.source_fingerprint = source_snapshot(skill.path).fingerprint
    queued = []

    def enqueue(**kwargs):
        queued.append(kwargs)
        return len(queued)

    ledger = PermissionLedger(tmp_path / "permissions.db", enabled=True,
                              authorizer=lambda action: SimpleNamespace(verdict="queue"))
    orch = SimpleNamespace(permission_ledger=ledger, autonomy=SimpleNamespace(govern_enqueue=enqueue))
    loader = SimpleNamespace(skills={skill.name: skill})
    return skill, orch, loader, queued


def _task(queued, *, approved=True, task_id=1):
    return SimpleNamespace(id=task_id, kind="permission.grant", payload=dict(queued[task_id - 1]["payload"]),
                           title=queued[task_id - 1]["title"], agent="jarvis",
                           decision="accept" if approved else "reject",
                           decided_by="alice" if approved else "policy",
                           human_decision={"action": "accept", "by": "alice"} if approved else None)


def test_approval_applies_once_with_canonical_event(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    request = switch_approval.request_enable(orch, [skill])
    assert request["status"] == "pending" and switches.off_reason(skill) == "everywhere"
    task = _task(queued)
    applied = asyncio.run(switch_approval.apply_approved(task, ledger=orch.permission_ledger, loader=loader))
    assert applied["status"] == "ok" and switches.off_reason(skill) == ""
    grant = orch.permission_ledger.list_grants(include_inactive=True)[0]
    assert grant.status == "consumed"
    conn = settings_db.get_conn()
    try:
        event = conn.execute("SELECT * FROM skill_switch_events WHERE action='enable'").fetchone()
        assert event["task_id"] == 1 and event["approver"] == "alice"
        assert conn.execute("SELECT count(*) FROM skill_switch_receipts").fetchone()[0] == 1
    finally:
        conn.close()
    assert asyncio.run(switch_approval.apply_approved(task, ledger=orch.permission_ledger,
                                                       loader=loader))["status"] == "refused"


def test_redundant_disable_invalidates_pending_approval(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill])
    switch_approval.disable([skill])
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "stale_switch_request"}
    assert switches.off_reason(skill) == "everywhere"


def test_request_snapshot_cannot_absorb_concurrent_disable(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    original = switch_approval._target_record

    def concurrent_disable(skills):
        switch_approval.disable([skill])  # WAL writer between state and revision reads
        return original(skills)

    monkeypatch.setattr(switch_approval, "_target_record", concurrent_disable)
    request = switch_approval.request_enable(orch, [skill])
    assert request["status"] == "pending"
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "stale_switch_request"}
    assert switches.off_reason(skill) == "everywhere"


def test_kernel_off_before_approval_refuses(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill])
    monkeypatch.setattr(switch_approval, "kernel_enabled", lambda: False)
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "kernel_unavailable"}
    assert switches.off_reason(skill) == "everywhere"


def test_double_click_reuses_pending_task(tmp_path, monkeypatch):
    skill, orch, _loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    first = switch_approval.request_enable(orch, [skill])
    second = switch_approval.request_enable(orch, [skill])
    assert first["task_id"] == second["task_id"] == 1 and len(queued) == 1


def test_kernel_denial_never_reaches_skill_approval_inbox(tmp_path, monkeypatch):
    from agents.core.kernel import Verdict
    from agents.core.permission_ledger import PermissionRequestError

    skill, orch, _loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    orch.permission_ledger._authorizer = lambda _action: SimpleNamespace(verdict=Verdict.DENY,
                                                                          reason="owner gate")
    with pytest.raises(PermissionRequestError, match="kernel_denied"):
        switch_approval.request_enable(orch, [skill])
    assert queued == [] and switches.off_reason(skill) == "everywhere"


@pytest.mark.parametrize("missing", ["kernel", "authorizer", "worker"])
def test_missing_governed_authority_refuses_without_enqueuing(tmp_path, monkeypatch, missing):
    from agents.core.permission_ledger import PermissionRequestError

    skill, orch, _loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    if missing == "kernel":
        monkeypatch.setattr(switch_approval, "kernel_enabled", lambda: False)
    elif missing == "authorizer":
        orch.permission_ledger._authorizer = None
    else:
        orch.autonomy = None
    with pytest.raises(PermissionRequestError, match="unavailable"):
        switch_approval.request_enable(orch, [skill])
    assert queued == [] and switches.off_reason(skill) == "everywhere"


def test_already_enabled_request_is_noop_even_with_kernel_off(tmp_path, monkeypatch):
    skill, orch, _loader, queued = _approval_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(switch_approval, "kernel_enabled", lambda: False)
    out = switch_approval.request_enable(orch, [skill])
    assert out["status"] == "unchanged" and queued == []


def test_request_persistence_failure_leaves_unbound_task(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    conn = settings_db.get_conn()
    try:
        conn.execute("CREATE TRIGGER refuse_request BEFORE INSERT ON skill_switch_requests "
                     "BEGIN SELECT RAISE(ABORT, 'disk refusal'); END")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(Exception, match="disk refusal"):
        switch_approval.request_enable(orch, [skill])
    assert len(queued) == 1
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "task_binding_mismatch"}
    assert switches.off_reason(skill) == "everywhere"


def test_canonical_audit_failure_rolls_back_enable_and_receipt(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill])
    conn = settings_db.get_conn()
    try:
        conn.execute("CREATE TRIGGER refuse_enable_audit BEFORE INSERT ON skill_switch_events "
                     "WHEN NEW.action='enable' BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
        conn.commit()
    finally:
        conn.close()
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "failed", "reason": "switch_store_unavailable"}
    assert switches.off_reason(skill) == "everywhere"
    conn = settings_db.get_conn()
    try:
        assert conn.execute("SELECT count(*) FROM skill_switch_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_category_membership_change_refuses_approved_set(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    skill.manifest["hermes"] = {"category": "info"}
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill], category="info")
    newcomer = _skill(tmp_path, "news", "News", category="info")
    newcomer.source_fingerprint = source_snapshot(newcomer.path).fingerprint
    loader.skills[newcomer.name] = newcomer
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "stale_skill_category"}
    assert switches.off_reason(skill) == "everywhere"


def test_approved_category_enables_exact_members(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    skill.manifest["hermes"] = {"category": "info"}
    news = _skill(tmp_path, "news", "News", category="info")
    news.source_fingerprint = source_snapshot(news.path).fingerprint
    loader.skills[news.name] = news
    switch_approval.disable([skill, news])
    request = switch_approval.request_enable(orch, [skill, news], category="info")
    assert request["pending"] == ["Weather Intel", "News"]
    assert "Weather Intel" in queued[0]["title"] and "News" in queued[0]["title"]
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out["status"] == "ok" and set(out["changed"]) == {"Weather Intel", "News"}
    assert switches.off_reason(skill) == switches.off_reason(news) == ""


def test_real_governed_queue_human_decision_pipeline(tmp_path, monkeypatch):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker

    skill, orch, loader, _queued = _approval_fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200))
        orch.autonomy = worker
        switch_approval.disable([skill])
        settings_db.put_category("skills", {"channel_disabled": {"web": ["Weather Intel"]}})
        pending = switch_approval.request_enable(orch, [skill], channel="web")
        task = queue.get(pending["task_id"])
        assert task.status == "blocked" and task.payload["scope"] == "once"
        assert switches.off_reason(skill, "web") == "everywhere"
        approved = asyncio.run(worker.apply_decision(task.id, "accept", decided_by="alice"))
        out = asyncio.run(switch_approval.apply_approved(approved, ledger=orch.permission_ledger,
                                                         loader=loader))
        assert out["status"] == "ok" and switches.off_reason(skill, "web") == "everywhere"
        assert switches.state()["channel_disabled"] == {}  # global off remains
        denied = switch_approval.request_enable(orch, [skill])
        rejected = asyncio.run(worker.apply_decision(denied["task_id"], "reject", decided_by="alice"))
        assert asyncio.run(switch_approval.apply_approved(rejected, ledger=orch.permission_ledger,
                                                          loader=loader))["status"] == "refused"
        assert switches.off_reason(skill) == "everywhere"
        retried = switch_approval.request_enable(orch, [skill])
        assert retried["task_id"] != denied["task_id"]
    finally:
        queue.close()


def test_machine_decision_and_source_change_do_not_enable(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill])
    out = asyncio.run(switch_approval.apply_approved(_task(queued, approved=False),
                                                     ledger=orch.permission_ledger, loader=loader))
    assert out["status"] == "refused" and switches.off_reason(skill) == "everywhere"
    (skill.path / "SKILL.md").write_text("# changed\n", encoding="utf-8")
    out = asyncio.run(switch_approval.apply_approved(_task(queued), ledger=orch.permission_ledger,
                                                     loader=loader))
    assert out == {"status": "refused", "reason": "stale_skill_source"}
    assert switches.off_reason(skill) == "everywhere"


def test_approved_task_payload_or_title_edits_cannot_widen(tmp_path, monkeypatch):
    skill, orch, loader, queued = _approval_fixture(tmp_path, monkeypatch)
    switch_approval.disable([skill])
    switch_approval.request_enable(orch, [skill])
    task = _task(queued)
    task.payload["reason"] = "approve a different skill"
    assert asyncio.run(switch_approval.apply_approved(task, ledger=orch.permission_ledger,
                                                      loader=loader))["reason"] == "task_binding_mismatch"
    task = _task(queued)
    task.title = "Switch on everything"
    assert asyncio.run(switch_approval.apply_approved(task, ledger=orch.permission_ledger,
                                                      loader=loader))["reason"] == "task_binding_mismatch"
    assert switches.off_reason(skill) == "everywhere"
