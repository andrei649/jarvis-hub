"""H329 switch-on reaches the registered coordinator handler on a real worker tick."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import permission_ledger, settings_db
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.security.capability import KillSwitch
from agents.core.skills import switch_approval, switches
from agents.core.skills.signing import source_snapshot
from tests.test_h329_skill_switches import _skill
from tests.test_web_tools_wiring import _coordinator


@pytest.mark.asyncio
async def test_approved_skill_switch_executes_via_real_worker_and_cannot_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TASK_MEDIATION", "off")
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    real_ledger = permission_ledger.PermissionLedger

    def isolated_ledger(**kwargs):
        return real_ledger(tmp_path / "permissions.db", enabled=True, **kwargs)

    monkeypatch.setattr(permission_ledger, "PermissionLedger", isolated_ledger)
    skill = _skill(tmp_path, "weather", "Weather Intel")
    skill.source_fingerprint = source_snapshot(skill.path).fingerprint
    queue = TaskQueue(str(tmp_path / "tasks.db"), mediation_mode="off").initialize()
    try:
        worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200))
        coordinator = _coordinator({})
        orch = coordinator._orch
        orch.autonomy = worker
        orch.autonomy_queue = queue
        orch.kill_switch = KillSwitch(tmp_path / "halt.json")
        orch.skills = SimpleNamespace(skills={skill.name: skill})
        orch.skill_usage = None
        executor = coordinator.build_executor()
        worker.executor = executor.execute
        ledger = orch.permission_ledger
        assert ledger is not None and ledger._authorizer is not None

        switch_approval.disable([skill])
        request = switch_approval.request_enable(orch, [skill])
        task_id = request["task_id"]
        assert request["status"] == "pending" and queue.get(task_id).status == "blocked"
        assert switches.off_reason(skill) == "everywhere"
        await worker.apply_decision(task_id, "accept", decided_by="alice")
        assert switches.off_reason(skill) == "everywhere"
        await worker.tick(task_id=task_id)
        completed = queue.get(task_id)
        assert completed.status == "done" and completed.result["status"] == "ok"
        assert switches.off_reason(skill) == ""
        conn = settings_db.get_conn()
        try:
            event = conn.execute("SELECT task_id,approver FROM skill_switch_events WHERE action='enable'").fetchone()
            assert event["task_id"] == task_id and event["approver"] == "alice"
        finally:
            conn.close()

        switch_approval.disable([skill])
        replay = await executor.resolve("permission.grant")(completed)
        assert replay["status"] == "refused" and switches.off_reason(skill) == "everywhere"
    finally:
        queue.close()
