"""An update card crosses the signed Kernel queue and the hub execution guard."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core import hub_restart, hub_update, hub_update_apply
from agents.core.autonomy import irreversible
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Action, Decision, Verdict, authorize, revalidate
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.kernel.registry import Mediation, classify, known_broker_action_kinds
from agents.core.update_commands import update_command
from tests.test_h084_update_command import _admissible_plan, _ctx
from tests.test_task_mediation_evidence import NOW_MS, _head_anchor, _signer


def _rig(tmp_path, monkeypatch, *, mode="enforce", verdict=Verdict.GRANT,
         kernel_available=True, signer_available=True):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    monkeypatch.setattr(hub_update_apply, "state_dir", lambda: tmp_path / "update")
    monkeypatch.setattr(hub_update_apply, "plan", lambda *_a, **_kw: _admissible_plan())
    monkeypatch.setattr(hub_update_apply, "_audit", lambda *_a, **_kw: None)
    monkeypatch.setattr(hub_restart, "available", lambda: True)
    path = tmp_path / "queue.db"
    signer = _signer() if signer_available else None
    queue = TaskQueue(str(path), mediation_mode=mode, mediation_signer=signer,
                      mediation_head_anchor=_head_anchor(path), mediation_scope="global",
                      mediation_policy_revision="update-test", mediation_clock_ms=lambda: NOW_MS).initialize()
    calls = []
    effect = {"verdict": Verdict.GRANT}

    def authorize(action, **_kw):
        calls.append(action)
        return Decision(verdict, reason="test decision", tier=0)

    def revalidate_effect(action, capability=None, *, approval_check=None):
        if not callable(approval_check) or approval_check(action) is not True:
            return Decision(Verdict.DENY, reason="task is not current")
        return Decision(effect["verdict"], reason="current test effect", tier=3)

    authorize.revalidate = revalidate_effect
    bridge = MediationKernelBridge(authorize) if kernel_available else None
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="ask"), kernel=bridge,
                            mediation_signer=signer, mediation_clock_ms=lambda: NOW_MS)
    orch = SimpleNamespace(autonomy=worker, autonomy_queue=queue, audit=None, intent_log=None)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)

    async def execute(task):
        return await irreversible.execute(task, orch=orch)

    executor.register(hub_update_apply.APPROVAL_KIND, execute)
    worker.executor = executor.execute
    return SimpleNamespace(queue=queue, worker=worker, orch=orch, executor=executor, calls=calls,
                           effect=effect)


def _request(rig):
    return hub_update_apply.request_apply(rig.orch, None, "refuse", requested_by="owner (chat /update)")


def test_exact_update_kind_is_registered_without_wildcard():
    assert classify("hub.update") is Mediation.KERNEL
    assert "hub.update" in known_broker_action_kinds()
    assert classify("hub.update_trust") is None
    assert classify("hub.update_rollback") is None
    assert classify("hub.arbitrary") is None


def test_real_kernel_revalidates_only_exact_human_receipt():
    policy = AutonomyPolicy(mode="auto")
    action = Action(kind="hub.update", agent="owner", title="Update", scope="global", origin="manual",
                    payload={"risk_tier": 3, "reversible": False, "approved_task_id": 7})
    def check(actual):
        return actual == action
    assert revalidate(action, policy=policy, approval_check=check).verdict is Verdict.GRANT
    assert revalidate(action, policy=policy).verdict is Verdict.QUEUE
    assert revalidate(action, policy=policy, approval_check=lambda _actual: False).verdict is Verdict.QUEUE
    for kind in ("hub.update_trust", "hub.update_rollback", "hub.other"):
        sibling = Action(kind=kind, agent="owner", title="Update", scope="global", origin="manual",
                         payload=action.payload)
        assert revalidate(sibling, policy=policy, approval_check=lambda _actual: True).verdict is not Verdict.GRANT
    external = Action(kind="hub.update", agent="owner", title="Update", scope="global", origin="external",
                      payload=action.payload)
    assert revalidate(external, policy=policy, approval_check=lambda _actual: True).verdict is Verdict.QUEUE
    policy.mode = "ask"
    assert revalidate(action, policy=policy, approval_check=check).verdict is not Verdict.GRANT
    policy.mode = "off"
    assert revalidate(action, policy=policy, approval_check=check).verdict is not Verdict.GRANT
    policy.mode = "unknown"
    assert revalidate(action, policy=policy, approval_check=check).verdict is not Verdict.GRANT
    policy.mode = "auto"
    halted = SimpleNamespace(is_halted=lambda *_a: True)
    assert revalidate(action, policy=policy, kill_switch=halted, approval_check=check).verdict is Verdict.DENY


@pytest.mark.parametrize("mode,verdict,kernel_available,signer_available", [
    ("hold", Verdict.GRANT, True, True),
    ("enforce", Verdict.DENY, True, True),
    ("enforce", None, False, True),
    ("enforce", Verdict.GRANT, True, False),
])
def test_strict_refusal_never_records_update_card(tmp_path, monkeypatch, mode, verdict,
                                                   kernel_available, signer_available):
    rig = _rig(tmp_path, monkeypatch, mode=mode, verdict=verdict,
               kernel_available=kernel_available, signer_available=signer_available)
    try:
        with pytest.raises(hub_update_apply.UpdateRefused):
            _request(rig)
        assert rig.queue.list() == []
        assert not (tmp_path / "update" / "pending.json").exists()
    finally:
        rig.queue.close()


def test_strict_intake_refuses_when_kernel_switch_is_off(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    try:
        monkeypatch.delenv("JARVIS_ACTION_KERNEL")
        with pytest.raises(hub_update_apply.UpdateRefused):
            _request(rig)
        assert rig.queue.list() == []
        assert not (tmp_path / "update" / "pending.json").exists()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [Verdict.GRANT, Verdict.QUEUE])
async def test_real_strict_request_is_signed_and_human_approved_before_mocked_apply(tmp_path, monkeypatch,
                                                                                     verdict):
    rig = _rig(tmp_path, monkeypatch, verdict=verdict)
    applied = []
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "current", lambda: None)
    monkeypatch.setattr(hub_update, "_new_action", lambda _kind: {"id": "local-test", "lines": []})
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline",
                        lambda payload, _by, task_id, _record, **_kw: applied.append((payload, task_id))
                        or {"id": "mock-receipt", "result": "refused", "reason": "mocked_no_update"})
    try:
        result = _request(rig)
        task_id = result["pending"]
        task = rig.queue.get(task_id)
        assert task.status == "blocked" and task.risk_tier == 3 and task.autonomy_level == "ask"
        assert task.mediation_receipt["verdict"] == verdict.value
        assert task.mediation_receipt["effective_tier"] == 3
        assert task.payload["to"] == "b" * 40
        assert rig.calls and rig.calls[-1].kind == "hub.update"
        assert not applied
        await rig.worker.tick()
        assert not applied
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert not applied
        await rig.worker.tick()
        assert len(applied) == 1 and applied[0][1] == task_id
        assert applied[0][0]["to"] == "b" * 40
        assert rig.queue.verified_mediation_stats()["valid"]
        assert rig.queue.get(task_id).result["reason"] == "mocked_no_update"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_owner_web_chat_command_uses_real_signed_strict_intake(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        reply = await update_command(_ctx(orch=rig.orch))
        tasks = rig.queue.list()
        assert len(tasks) == 1 and str(tasks[0].id) in reply
        assert tasks[0].kind == "hub.update" and tasks[0].status == "blocked"
        assert tasks[0].mediation_receipt["verdict"] == "grant"
        assert tasks[0].risk_tier == 3
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ask", "auto"])
async def test_real_kernel_and_signed_worker_reach_only_mocked_physical_effects(
        tmp_path, monkeypatch, mode):
    rig = _rig(tmp_path, monkeypatch)
    rig.worker.policy.mode = mode

    def kernel(action, **_kw):
        return authorize(action, policy=rig.worker.policy)

    def current_kernel(action, capability=None, *, approval_check=None):
        return revalidate(action, policy=rig.worker.policy, approval_check=approval_check)

    kernel.revalidate = current_kernel
    rig.worker._mediation_kernel = MediationKernelBridge(kernel)
    checkout = {"head": "a" * 40}
    effects = []
    monkeypatch.setattr(hub_update_apply, "head", lambda: checkout["head"])
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: "b" * 40 if value == "b" * 40 else None)
    monkeypatch.setattr(hub_update_apply, "verify_target",
                        lambda *_a: {"trusted": True, "how": "pinned", "signer": None})
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: False)
    monkeypatch.setattr(hub_update_apply, "_backup",
                        lambda *_a: effects.append("backup") or {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "install_dependencies",
                        lambda *_a: pytest.fail("dependency install ran"))

    def git(*args, **_kw):
        assert args == ("merge", "--ff-only", "--no-edit", "--no-verify-signatures", "b" * 40)
        effects.append("merge")
        checkout["head"] = "b" * 40
        return 0, "", ""

    monkeypatch.setattr(hub_update_apply, "_git", git)
    monkeypatch.setattr(hub_restart, "request", lambda *_a: effects.append("restart") or True)
    monkeypatch.setattr(hub_update, "_new_action", lambda _kind: {"id": "local-test", "lines": []})
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)
    try:
        task_id = _request(rig)["pending"]
        task = rig.queue.get(task_id)
        assert task.status == "blocked" and task.mediation_receipt["verdict"] == "queue"
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert effects == []
        await rig.worker.tick()
        if mode == "auto":
            assert effects == ["backup", "merge", "restart"]
            assert rig.queue.get(task_id).result["status"] == "ok"
            assert hub_update_apply.current()["phase"] == "restarting"
        else:
            assert effects == []
            assert rig.queue.get(task_id).result["reason"] == "authority_changed"
            assert hub_update_apply.current() is None
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_signed_but_unrecorded_update_card_cannot_apply(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        payload = hub_update_apply._plan_payload(_admissible_plan())
        task_id = rig.worker.govern_enqueue(
            "owner", "hub.update", "Unrecorded update",
            payload={**payload, "risk_tier": 3, "reversible": False, "preview": {}},
            risk_tier=3, autonomy_level="ask", origin="manual",
        )
        assert rig.queue.get(task_id).mediation_receipt["verdict"] == "grant"
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        await rig.worker.tick()
        assert rig.queue.get(task_id).result["reason"] == "not_requested"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_human_edit_is_not_acceptance_of_update_card(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        rig.queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner", decision="edit",
                             human_reason=None)
        await rig.worker.tick()
        assert rig.queue.get(task_id).result["reason"] == "edit_not_supported"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["receipt", "scope", "policy", "halt"])
async def test_stale_execution_evidence_never_reaches_pipeline(tmp_path, monkeypatch, revocation):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        if revocation == "receipt":
            rig.queue._conn.execute("UPDATE tasks SET mediation_receipt=? WHERE id=?", ("{}", task_id))
            rig.queue._conn.commit()
        elif revocation == "scope":
            rig.queue._mediation_scope = "different-scope"
        elif revocation == "policy":
            rig.queue._mediation_policy_revision = "new-policy"
        else:
            rig.worker._kill_switch = SimpleNamespace(is_halted=lambda *_a: True)
        await rig.worker.tick()
        assert rig.queue.get(task_id).status != "done"
        assert (tmp_path / "update" / "pending.json").exists()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("decider", ["policy", "system", "kernel", "worker"])
async def test_machine_decision_never_reaches_pipeline(tmp_path, monkeypatch, decider):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by=decider)
        await rig.worker.tick()
        assert rig.queue.get(task_id).result["reason"] == "human_decision_required"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_nonhub_worker_leaves_approved_card_unclaimed(tmp_path, monkeypatch):
    from agents.core import hub_restart, install_identity

    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_restart, "available", lambda: False)
    monkeypatch.setattr(install_identity, "hub_lock_held_elsewhere", lambda: True)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert irreversible.held_here(rig.queue.get(task_id))
        await rig.worker.tick()
        assert rig.queue.get(task_id).status == "approved"
        assert (tmp_path / "update" / "pending.json").exists()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("probe_error", [False, True])
async def test_nonhub_without_visible_hub_still_cannot_claim_update(tmp_path, monkeypatch, probe_error):
    from agents.core import hub_restart, install_identity

    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_restart, "available", lambda: False)

    def probe():
        if probe_error:
            raise OSError("lock state unavailable")
        return False

    monkeypatch.setattr(install_identity, "hub_lock_held_elsewhere", probe)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        assert irreversible.held_here(rig.queue.get(task_id)) == "hub_applies_update"
        await rig.worker.tick()
        assert rig.queue.get(task_id).status == "approved"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_direct_executor_dispatch_cannot_bypass_worker_claim(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        result = await rig.executor.execute(rig.queue.get(task_id))
        assert result == {"status": "refused", "reason": "mediation_execution_context_required"}
    finally:
        rig.queue.close()


@pytest.mark.asyncio
async def test_changed_recorded_payload_refuses_before_pipeline(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "held_here", lambda _task: None)
    monkeypatch.setattr(hub_update_apply, "_run_pipeline", lambda *_a: pytest.fail("update ran"))
    try:
        task_id = _request(rig)["pending"]
        saved = rig.queue.get(task_id)
        changed = SimpleNamespace(id=task_id, kind="hub.update", decision="accept",
                                  decided_by="owner", payload={**saved.payload, "to": "c" * 40})
        result = await hub_update_apply.apply_approved(changed, rig.orch)
        assert result == {"status": "refused", "reason": "payload_changed"}
        assert (tmp_path / "update" / "pending.json").exists()
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", ["policy", "scope", "receipt", "kernel", "halt", "host"])
@pytest.mark.parametrize("stash", [False, True])
async def test_backup_wait_rechecks_live_authority_before_git(tmp_path, monkeypatch, revoke, stash):
    rig = _rig(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()
    if stash:
        def planned(*_a, **_kw):
            value = _admissible_plan()
            value.update(dirty=True, dirty_policy="stash")
            return value
        monkeypatch.setattr(hub_update_apply, "plan", planned)

    def backup(_log, _label):
        started.set()
        if not release.wait(5):
            raise TimeoutError("test backup was not released")
        return {"name": "mocked-backup", "ok": True}

    monkeypatch.setattr(hub_update_apply, "head", lambda: "a" * 40)
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: "b" * 40 if value == "b" * 40 else None)
    monkeypatch.setattr(hub_update_apply, "verify_target",
                        lambda *_a: {"trusted": True, "how": "pinned", "signer": None})
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: stash)
    monkeypatch.setattr(hub_update_apply, "_backup", backup)
    monkeypatch.setattr(hub_update_apply, "_git", lambda *_a, **_kw: pytest.fail("Git ran after revocation"))
    monkeypatch.setattr(hub_update, "_new_action", lambda _kind: {"id": "local-test", "lines": []})
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        tick = asyncio.create_task(rig.worker.tick())
        assert await asyncio.to_thread(started.wait, 3)
        if revoke == "policy":
            rig.queue._mediation_policy_revision = "changed"
        elif revoke == "scope":
            rig.queue._mediation_scope = "changed"
        elif revoke == "receipt":
            rig.queue._conn.execute("UPDATE tasks SET mediation_receipt=? WHERE id=?", ("{}", task_id))
            rig.queue._conn.commit()
        elif revoke == "kernel":
            rig.effect["verdict"] = Verdict.DENY
        elif revoke == "halt":
            rig.worker._kill_switch = SimpleNamespace(is_halted=lambda *_a: True)
        else:
            monkeypatch.setattr(hub_restart, "available", lambda: False)
        release.set()
        await tick
        assert rig.queue.get(task_id).result["reason"] == "authority_changed"
        assert hub_update_apply.current() is None
    finally:
        release.set()
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replace", ["queue_off", "worker_missing"])
async def test_signed_task_cannot_downgrade_checker_before_pipeline(tmp_path, monkeypatch, replace):
    rig = _rig(tmp_path, monkeypatch)
    monkeypatch.setattr(hub_update_apply, "head", lambda: "a" * 40)
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: "b" * 40 if value == "b" * 40 else None)
    monkeypatch.setattr(hub_update_apply, "verify_target",
                        lambda *_a: {"trusted": True, "how": "pinned", "signer": None})
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: False)
    monkeypatch.setattr(hub_update_apply, "_backup", lambda *_a: {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "_git", lambda *_a, **_kw: pytest.fail("Git ran"))
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)

    def action(_kind):
        if replace == "queue_off":
            rig.queue.mediation_mode = "off"
        else:
            rig.orch.autonomy = None
        return {"id": "local-test", "lines": []}

    monkeypatch.setattr(hub_update, "_new_action", action)
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        await rig.worker.tick()
        assert rig.queue.get(task_id).result["reason"] == "authority_changed"
        assert hub_update_apply.current() is None
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", ["host", "mode", "queue"])
async def test_legacy_off_mode_rechecks_bound_authority_after_backup(tmp_path, monkeypatch, revoked):
    rig = _rig(tmp_path, monkeypatch, mode="off")

    class QueueView:
        def __getattr__(self, name):
            return getattr(rig.queue, name)

    def backup(*_args):
        if revoked == "host":
            monkeypatch.setattr(hub_restart, "available", lambda: False)
        elif revoked == "mode":
            rig.queue.mediation_mode = "enforce"
        else:
            rig.worker.queue = QueueView()
        return {"name": "mocked-backup", "ok": True}

    monkeypatch.setattr(hub_update_apply, "head", lambda: "a" * 40)
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: "b" * 40 if value == "b" * 40 else None)
    monkeypatch.setattr(hub_update_apply, "verify_target",
                        lambda *_a: {"trusted": True, "how": "pinned", "signer": None})
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: False)
    monkeypatch.setattr(hub_update_apply, "_backup", backup)
    monkeypatch.setattr(hub_update_apply, "_git", lambda *_a, **_kw: pytest.fail("Git ran"))
    monkeypatch.setattr(hub_update, "_new_action", lambda _kind: {"id": "local-test", "lines": []})
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        await rig.worker.tick()
        assert hub_update_apply.receipts(limit=1)[-1]["reason"] == "authority_changed"
    finally:
        rig.queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked_at,reset_ok", [
    ("after_merge", True), ("during_dependencies", True), ("before_restart", True),
    ("after_merge", False),
])
async def test_revocation_after_merge_uses_bounded_rollback_before_restart(
        tmp_path, monkeypatch, revoked_at, reset_ok):
    rig = _rig(tmp_path, monkeypatch)

    def planned(*_a, **_kw):
        value = _admissible_plan()
        value["dependencies"] = {"changed": True, "command": "mocked"}
        return value

    monkeypatch.setattr(hub_update_apply, "plan", planned)
    checkout = {"head": "a" * 40}
    git_calls, installs = [], []
    monkeypatch.setattr(hub_update_apply, "head", lambda: checkout["head"])
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: "b" * 40 if value == "b" * 40 else None)
    monkeypatch.setattr(hub_update_apply, "verify_target",
                        lambda *_a: {"trusted": True, "how": "pinned", "signer": None})
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: False)
    monkeypatch.setattr(hub_update_apply, "_backup", lambda *_a: {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "_file_at", lambda *_a: None)
    monkeypatch.setattr(hub_restart, "request", lambda *_a: pytest.fail("restart ran after revocation"))
    monkeypatch.setattr(hub_update, "_new_action", lambda _kind: {"id": "local-test", "lines": []})
    monkeypatch.setattr(hub_update, "_finish", lambda *_a, **_kw: None)
    append_receipt = hub_update_apply._append_receipt

    def append(record):
        if revoked_at == "before_restart" and record.get("result") is None:
            rig.queue._mediation_policy_revision = "changed"
        append_receipt(record)

    monkeypatch.setattr(hub_update_apply, "_append_receipt", append)

    def git(*args, **_kw):
        git_calls.append(args)
        if args[:1] == ("merge",):
            checkout["head"] = "b" * 40
            if revoked_at == "after_merge":
                rig.queue._mediation_policy_revision = "changed"
            return 0, "", ""
        assert args == ("reset", "--keep", "a" * 40)
        if reset_ok:
            checkout["head"] = "a" * 40
        return (0 if reset_ok else 1), "", "mocked reset failure"

    def install(_log):
        installs.append(True)
        if revoked_at == "during_dependencies" and len(installs) == 1:
            rig.queue._mediation_policy_revision = "changed"
        return True

    monkeypatch.setattr(hub_update_apply, "_git", git)
    monkeypatch.setattr(hub_update_apply, "install_dependencies", install)
    try:
        task_id = _request(rig)["pending"]
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        await rig.worker.tick()
        result = rig.queue.get(task_id).result
        assert result["reason"] == "authority_changed"
        assert result["status"] == ("refused" if reset_ok else "failed")
        assert result["result"] == ("refused" if reset_ok else "rollback_incomplete")
        assert git_calls == [
            ("merge", "--ff-only", "--no-edit", "--no-verify-signatures", "b" * 40),
            ("reset", "--keep", "a" * 40),
        ]
        assert len(installs) == (2 if revoked_at in {"during_dependencies", "before_restart"} else 0)
        assert checkout["head"] == ("a" * 40 if reset_ok else "b" * 40)
        assert hub_update_apply.current() is None
    finally:
        rig.queue.close()


def test_manifest_exposes_exact_human_and_update_limitations():
    from agents.core.capability_manifests import manifest_for_action

    manifest = manifest_for_action("hub.update")
    assert manifest is not None
    assert manifest.risk == "irreversible_or_money" and manifest.confidence == 0.0
    assert {"action-kernel", "human-approval", "recorded-request", "trusted-target"} <= set(manifest.requires)
    assert set(hub_update_apply._APPLY_KEYS) <= set(manifest.inputs["required"])
    assert manifest.implementation == "agents.core.hub_update_apply:apply_approved"
    assert "rollback" in manifest.rollback.description.lower()
    assert "cannot" in manifest.rollback.limitations.lower()
