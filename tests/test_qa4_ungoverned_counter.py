"""QA4 observational detection of tasks without authenticated intake evidence."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

from agents.core.autonomy.mediation import (
    MAX_INTAKE_EVIDENCE_AGE_MS,
    DetachedHMACSigner,
    issue_intake_evidence,
    verify_intake_evidence,
)
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.kernel.metrics import KERNEL_METRICS

_KEY = b"qa4-stable-owner-held-test-key"
_NOW_MS = 1_786_662_000_000


class _ActPolicy:
    def decide(self, _action):
        return type("Decision", (), {"outcome": "act", "tier": 1, "reason": "ok"})()


def test_truthy_legacy_kernel_mediation_marker_cannot_suppress_qa4_breach(tmp_path):
    observed = []

    async def execute(task):
        observed.append(task.id)
        return {"status": "ok"}

    KERNEL_METRICS.reset()
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, policy=_ActPolicy(), executor=execute)

    task = asyncio.run(
        worker.submit(
            "jarvis",
            "draft_email",
            "Draft update",
            payload={"body": "hello", "kernel_mediation": True},
        )
    )

    summary = asyncio.run(worker.tick())

    assert summary["done"] == 1
    assert observed == [task.id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}


def test_editing_live_task_fields_invalidates_intake_evidence_without_blocking_dispatch(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    mutations = {
        "payload": json.dumps({"body": "edited"}),
        "title": "Edited update",
        "kind": "draft_sms",
        "agent": "attacker",
        "origin": "manual",
    }

    for field, value in mutations.items():
        observed = []

        async def execute(task, observed=observed):
            observed.append(task.id)
            return {"status": "ok"}

        def signer(data):
            return hmac.new(_KEY, data, hashlib.sha256).hexdigest()
        queue = TaskQueue(str(tmp_path / f"{field}.db")).initialize()
        worker = AutonomyWorker(
            queue,
            policy=_ActPolicy(),
            executor=execute,
            kernel=MediationKernelBridge(
                lambda _action: Decision(Verdict.GRANT, reason="accepted", tier=1)
            ),
            mediation_signer=DetachedHMACSigner(signer),
            mediation_clock_ms=lambda: _NOW_MS,
        )
        task = asyncio.run(
            worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
        )
        assert task.kernel_intake_evidence is not None

        queue._conn.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task.id))
        queue._conn.commit()
        KERNEL_METRICS.reset()

        summary = asyncio.run(worker.tick())

        assert summary["done"] == 1
        assert observed == [task.id]
        expected_kind = str(value) if field == "kind" else "draft_email"
        assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {expected_kind: 1}


def test_one_bridge_decision_cannot_bless_two_qa4_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    calls = []

    def kernel(_action):
        calls.append(1)
        verdict = Verdict.GRANT if len(calls) == 1 else Verdict.DENY
        return Decision(verdict, reason="kernel", tier=1)

    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    bridge = MediationKernelBridge(kernel)
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        kernel=bridge,
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )

    bridge(worker._kernel_action("jarvis", "draft_email", "Draft one", {"body": "one"}, "generated"))
    first_id = worker.govern_enqueue("jarvis", "draft_email", "Draft one", {"body": "one"})
    second_id = worker.govern_enqueue("jarvis", "draft_email", "Draft two", {"body": "two"})

    first = queue.get(first_id)
    second = queue.get(second_id)
    assert first.kernel_intake_evidence is not None
    assert second.kernel_intake_evidence is None
    assert calls == [1, 1]


def test_valid_qa4_evidence_survives_restart_with_a_stable_signer(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    path = tmp_path / "tasks.db"
    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(path)).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        kernel=MediationKernelBridge(
            lambda _action: Decision(Verdict.GRANT, reason="accepted", tier=1)
        ),
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )
    task = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )
    queue.close()

    observed = []

    async def execute(reloaded_task):
        observed.append(reloaded_task.id)
        return {"status": "ok"}

    KERNEL_METRICS.reset()
    reopened = TaskQueue(str(path)).initialize()
    restarted = AutonomyWorker(
        reopened,
        policy=_ActPolicy(),
        executor=execute,
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )

    summary = asyncio.run(restarted.tick())

    assert summary["done"] == 1
    assert observed == [task.id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {}


def test_malformed_forged_and_stale_evidence_count_without_blocking_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )

    for case in ("malformed", "forged", "stale"):
        observed = []

        async def execute(task, observed=observed):
            observed.append(task.id)
            return {"status": "ok"}

        queue = TaskQueue(str(tmp_path / f"{case}.db")).initialize()
        worker = AutonomyWorker(
            queue,
            policy=_ActPolicy(),
            executor=execute,
            kernel=MediationKernelBridge(
                lambda _action: Decision(Verdict.GRANT, reason="accepted", tier=1)
            ),
            mediation_signer=signer,
            mediation_clock_ms=lambda: _NOW_MS,
        )
        task = asyncio.run(
            worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
        )
        if case == "malformed":
            evidence = "{"
        elif case == "forged":
            forged = dict(task.kernel_intake_evidence)
            forged["signature"] = "0" * 64
            evidence = json.dumps(forged)
        else:
            stale = issue_intake_evidence(
                signer,
                intake_id="d68257bc-7ec5-4fd4-9128-4db7d5597469",
                agent=task.agent,
                kind=task.kind,
                title=task.title,
                origin=task.origin,
                payload=task.payload,
                verdict="grant",
                tier=task.risk_tier,
                task_tier=task.risk_tier,
                issued_at_ms=_NOW_MS - MAX_INTAKE_EVIDENCE_AGE_MS - 1,
                task_id=task.id,
            )
            assert stale is not None
            evidence = json.dumps(stale.to_dict())
        queue._conn.execute(
            "UPDATE tasks SET kernel_intake_evidence=? WHERE id=?", (evidence, task.id)
        )
        queue._conn.commit()
        KERNEL_METRICS.reset()

        summary = asyncio.run(worker.tick())

        assert summary["done"] == 1
        assert observed == [task.id]
        assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}


def test_worker_uses_the_bridge_intake_take_after_direct_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")

    class _RecordingBridge(MediationKernelBridge):
        def __init__(self):
            super().__init__(lambda _action: Decision(Verdict.GRANT, reason="accepted", tier=1))
            self.intake_takes = 0

        def take_intake_evidence(self, **kwargs):
            self.intake_takes += 1
            return super().take_intake_evidence(**kwargs)

    bridge = _RecordingBridge()
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        kernel=bridge,
        mediation_signer=DetachedHMACSigner(
            lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
        ),
        mediation_clock_ms=lambda: _NOW_MS,
    )

    task = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )

    assert task.kernel_intake_evidence is not None
    assert bridge.intake_takes == 2


def test_intake_evidence_binds_kernel_tier_not_policy_task_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        kernel=MediationKernelBridge(
            lambda _action: Decision(Verdict.GRANT, reason="kernel tier", tier=3)
        ),
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )

    task = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )
    evidence = task.kernel_intake_evidence

    assert task.risk_tier == 1
    assert evidence["tier"] == 3
    assert not verify_intake_evidence(
        signer,
        evidence,
        agent=task.agent,
        kind=task.kind,
        title=task.title,
        origin=task.origin,
        payload=task.payload,
        tier=task.risk_tier,
        now_ms=_NOW_MS,
        task_id=task.id,
    )


def test_forged_b7_shaped_fields_do_not_exempt_qa4_observation(tmp_path):
    observed = []

    async def execute(task):
        observed.append(task.id)
        return {"status": "ok"}

    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    task_id = queue.enqueue("jarvis", "draft_email", "Draft update", {"body": "hello"})
    queue.transition(task_id, "approved")
    queue._conn.execute(
        """UPDATE tasks
              SET mediation_enqueue_id=?, mediation_receipt=?
            WHERE id=?""",
        (
            "f65c2e0d-d339-4e3d-8039-f2dd752d1c7e",
            json.dumps({"receipt_id": "forged", "signature": "0" * 64}),
            task_id,
        ),
    )
    queue._conn.commit()
    worker = AutonomyWorker(queue, executor=execute)
    KERNEL_METRICS.reset()

    summary = asyncio.run(worker.tick())

    assert summary["done"] == 1
    assert observed == [task_id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}


def test_copied_evidence_with_a_cleared_intake_id_cannot_bless_a_second_task(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )
    observed = []

    async def execute(task):
        observed.append(task.id)
        return {"status": "ok"}

    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        executor=execute,
        kernel=MediationKernelBridge(
            lambda _action: Decision(Verdict.GRANT, reason="accepted", tier=1)
        ),
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )
    first = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )
    queue.transition(first.id, "blocked")
    second_id = queue.enqueue("jarvis", "draft_email", "Draft update", {"body": "hello"})
    queue.transition(second_id, "approved")
    queue._conn.execute("UPDATE tasks SET kernel_intake_id=NULL WHERE id=?", (first.id,))
    queue._conn.execute(
        "UPDATE tasks SET kernel_intake_evidence=? WHERE id=?",
        (json.dumps(first.kernel_intake_evidence), second_id),
    )
    queue._conn.commit()
    KERNEL_METRICS.reset()

    summary = asyncio.run(worker.tick())

    assert summary["done"] == 1
    assert observed == [second_id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}


def test_direct_queue_enqueue_strips_the_legacy_kernel_mediation_marker(tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()

    task_id = queue.enqueue(
        "jarvis",
        "draft_email",
        "Draft update",
        {"body": "hello", "kernel_mediation": True},
    )

    assert queue.get(task_id).payload == {"body": "hello"}


def test_final_task_tier_mutation_invalidates_qa4_evidence_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    observed = []

    class _TierThreePolicy:
        def decide(self, _action):
            return type("Decision", (), {"outcome": "act", "tier": 3, "reason": "high"})()

    async def execute(task):
        observed.append(task.id)
        return {"status": "ok"}

    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_TierThreePolicy(),
        executor=execute,
        kernel=MediationKernelBridge(
            lambda _action: Decision(Verdict.GRANT, reason="kernel", tier=1)
        ),
        mediation_signer=DetachedHMACSigner(
            lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
        ),
        mediation_clock_ms=lambda: _NOW_MS,
    )
    task = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )

    assert task.kernel_intake_evidence["tier"] == 1
    assert task.kernel_intake_evidence["task_tier"] == 3
    queue._conn.execute("UPDATE tasks SET risk_tier=1 WHERE id=?", (task.id,))
    queue._conn.commit()
    KERNEL_METRICS.reset()

    summary = asyncio.run(worker.tick())

    assert summary["done"] == 1
    assert observed == [task.id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}


def test_tampered_persisted_kernel_tier_invalidates_qa4_evidence_without_blocking(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    observed = []

    async def execute(task):
        observed.append(task.id)
        return {"status": "ok"}

    signer = DetachedHMACSigner(
        lambda data: hmac.new(_KEY, data, hashlib.sha256).hexdigest()
    )
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=_ActPolicy(),
        executor=execute,
        kernel=MediationKernelBridge(
            lambda _action: Decision(Verdict.GRANT, reason="kernel tier", tier=3)
        ),
        mediation_signer=signer,
        mediation_clock_ms=lambda: _NOW_MS,
    )
    task = asyncio.run(
        worker.submit("jarvis", "draft_email", "Draft update", payload={"body": "hello"})
    )
    tampered = dict(task.kernel_intake_evidence)
    tampered["tier"] = 0
    queue._conn.execute(
        "UPDATE tasks SET kernel_intake_evidence=? WHERE id=?",
        (json.dumps(tampered), task.id),
    )
    queue._conn.commit()

    assert not verify_intake_evidence(
        signer,
        tampered,
        agent=task.agent,
        kind=task.kind,
        title=task.title,
        origin=task.origin,
        payload=task.payload,
        tier=3,
        task_tier=task.risk_tier,
        now_ms=_NOW_MS,
        task_id=task.id,
    )
    KERNEL_METRICS.reset()

    summary = asyncio.run(worker.tick())

    assert summary["done"] == 1
    assert observed == [task.id]
    assert KERNEL_METRICS.snapshot()["ungoverned_by_kind"] == {"draft_email": 1}
