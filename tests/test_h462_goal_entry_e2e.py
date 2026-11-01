"""H462 — a goal said in the conversation (or posted by the HUD) becomes a run, end to end.

Through the physical governed path, nothing stubbed between the entry point and the
ledger: the ``/goal`` chat command (and ``POST /api/company/goals``) → goal_intake →
``goal_contract.propose`` → the Action Kernel (``goal.approve`` is
``Mediation.KERNEL``) → the worker's governed intake on a mediated, signed queue →
the owner's accept on the decision card → the worker's tick → the coordinator's own
``goal.approve`` handler → a run opened in the work-run ledger, pinned to what the
owner approved — and the shipped runtime then reads its checklist back and queues
its first step for approval.

The properties pinned:

  · proposing grants nothing: the card lands BLOCKED in the inbox, the kernel saw
    ``goal.approve``, and no run exists until the owner accepts;
  · a kernel DENY refuses the goal before the inbox ever sees a card;
  · a policy decision on the card opens nothing (``not_decided_by_a_human``);
  · ``/subgoal`` then narrows the running goal without resetting it, and the
    verifier will not pass the run until that criterion holds.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from agents.core import kernel  # noqa: E402
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor  # noqa: E402
from agents.core.autonomy.policy import AutonomyPolicy  # noqa: E402
from agents.core.autonomy.queue import TaskQueue  # noqa: E402
from agents.core.autonomy.work_runs import WorkRunLedger  # noqa: E402
from agents.core.autonomy.worker import AutonomyWorker  # noqa: E402
from agents.core.commands import Principal, build_default_registry  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.security.capability import KillSwitch  # noqa: E402
from tests.test_web_tools_wiring import _coordinator  # noqa: E402

OWNER = Principal(channel="telegram", sender="42", admin=True)

GOAL = (
    "Prepare the quarterly brief\n"
    "verify: the brief is in docs/\n"
    "scope: research, write\n"
    "step: research: read the Q3 figures\n"
    "step: write: draft the brief\n"
    "must not: touch the ledger\n"
    "stop when: the figures are missing"
)


class _IntentLog:
    def __init__(self, key: bytes):
        self.key = key

    def sign_detached(self, body: bytes) -> str:
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def record(self, *_args, **_kwargs) -> None:
        pass


@pytest.fixture
def governed(tmp_path, monkeypatch):
    """The session-command kernel fixture's shape: a mediated queue in enforce mode, a
    real worker, the kernel on, and the coordinator's own executor."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    monkeypatch.setattr("agents.core.autonomy.work_runs.data_path",
                        lambda _name: tmp_path / "work_runs.db")
    monkeypatch.setattr("agents.core.permission_ledger.data_path",
                        lambda _name: tmp_path / "permissions.db")
    intent = _IntentLog(b"h462 local synthetic signer")
    signer = DetachedHMACSigner(intent.sign_detached)
    head = [None]

    def compare_and_set(before, after):
        if head[0] != before:
            return False
        head[0] = after
        return True

    queue = TaskQueue(
        str(tmp_path / "tasks.db"),
        mediation_mode="enforce",
        mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], compare_and_set),
        mediation_scope="global",
    ).initialize()
    kill = KillSwitch(tmp_path / "kill.json")
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"),
                            kill_switch=kill, mediation_signer=signer)
    coordinator = _coordinator({})
    orch = coordinator._orch
    orch.autonomy = worker
    orch.autonomy_queue = queue
    orch.kill_switch = kill
    orch.intent_log = intent
    orch.commands = build_default_registry()
    kernel_calls = []
    physical_authorize = kernel.authorize

    def observed_authorize(action, *args, **kwargs):
        verdict = physical_authorize(action, *args, **kwargs)
        kernel_calls.append((action, verdict))
        return verdict

    monkeypatch.setattr(kernel, "authorize", observed_authorize)
    executor = coordinator.build_executor()
    worker.executor = executor.execute
    ledger = orch.work_runs
    assert isinstance(ledger, WorkRunLedger)
    try:
        yield orch, queue, worker, ledger, kernel_calls
    finally:
        queue.close()
        ledger.close()
        if getattr(orch, "permission_ledger", None) is not None:
            orch.permission_ledger.close()


def _task_id(reply: str) -> int:
    marker = "as task "
    assert marker in reply, reply
    return int(reply.split(marker, 1)[1].split(" ", 1)[0])


async def _approve_and_run(worker, queue, task_id, decided_by="owner-42"):
    approved = await worker.apply_decision(task_id, "accept", decided_by=decided_by)
    assert approved.status == "approved"
    assert (await worker.tick(task_id=task_id))["done"] == 1
    return queue.get(task_id).result


async def test_goal_in_chat_becomes_an_opened_run_only_after_the_owner_accepts(governed):
    orch, queue, worker, ledger, kernel_calls = governed

    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    assert outcome.status == "answered", outcome.reply
    task_id = _task_id(outcome.reply)
    assert "nothing runs until you accept it there" in outcome.reply

    # Proposed, not granted: a blocked, signed card in the inbox, and no run.
    task = queue.get(task_id)
    assert task.kind == "goal.approve" and task.status == "blocked"
    assert task.mediation_receipt is not None
    assert task.payload["title"] == "Prepare the quarterly brief"
    assert task.payload["scope_kinds"] == ["research", "write"]
    assert [row["summary"] for row in task.payload["plan"]] == [
        "read the Q3 figures", "draft the brief"]
    assert task.payload["budget"]["max_steps"] == 20
    assert task.payload["requested_by"] == "telegram:42"
    assert {a.kind for a, _v in kernel_calls} == {"goal.approve"}
    assert all(v.verdict in {Verdict.GRANT, Verdict.QUEUE} for _a, v in kernel_calls)
    assert ledger.list_runs() == []
    assert (await worker.tick(task_id=task_id))["done"] == 0
    assert ledger.list_runs() == []

    # The owner accepts the card: the coordinator's goal.approve handler opens the run.
    result = await _approve_and_run(worker, queue, task_id)
    assert result["status"] == "ok" and result["kind"] == "goal.approve"
    run = ledger.get(result["run_id"])
    assert run is not None and run.status == "planning"
    assert run.title == "Prepare the quarterly brief"
    assert run.approved_by == f"task:{task_id}:owner-42"
    assert run.approved_fingerprint == task.payload["fingerprint"]
    assert run.budget.max_steps == 20

    # The shipped runtime reads the approved checklist back from the card and queues
    # the plan's first row through the same governed intake, for approval.
    from agents.core.autonomy.company_runtime import build_company_runtime

    runtime = build_company_runtime(orch)
    assert runtime is not None
    await runtime.parts.supervisor.tick(run.id)
    steps = ledger.steps(run.id)
    assert [(s.kind, s.summary, s.outcome) for s in steps] == [
        ("research", "read the Q3 figures", "queued")]
    first = queue.get(steps[0].task_id)
    assert first.kind == "research" and first.status == "blocked"


async def test_subgoal_narrows_the_running_goal_without_resetting_it(governed):
    orch, queue, worker, ledger, _kernel_calls = governed
    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    result = await _approve_and_run(worker, queue, _task_id(outcome.reply))
    run_id = result["run_id"]
    before = ledger.get(run_id)

    added = await orch.commands.dispatch("/subgoal the brief has a one-page summary",
                                         orch=orch, principal=OWNER)
    assert added.status == "answered" and "subgoal:1" in added.reply, added.reply
    after = ledger.get(run_id)
    assert (after.status, after.steps_used, after.fingerprint, after.updated_at) == (
        before.status, before.steps_used, before.fingerprint, before.updated_at)
    assert ledger.tampered(run_id) is False
    assert [s["describe"] for s in ledger.subgoals(run_id)] == ["the brief has a one-page summary"]

    # The verifier folds it in: every approved check probed and holding is not enough.
    from agents.core.autonomy.goal_contract import approve_from_task
    from agents.core.autonomy.work_verifier import Check, WorkVerifier

    ledger.record_step(run_id, kind="research", summary="read the Q3 figures",
                       outcome="ok", task_id=999)
    goal = approve_from_task(queue.get(int(after.approved_by.split(":")[1])))
    checks = goal.verifier_checks()
    approved_only = [Check(id=c.id, describe=c.describe, probe=lambda: True) for c in checks]
    report = await WorkVerifier(ledger).verify(run_id, approved_only, record=False)
    assert report.passed is False
    assert "subgoal:1" in report.reason
    probed = [*approved_only, Check(id="subgoal:1", describe="summary", probe=lambda: True)]
    assert (await WorkVerifier(ledger).verify(run_id, probed, record=False)).passed is True


async def test_a_kernel_deny_refuses_the_goal_before_the_inbox_sees_a_card(governed, monkeypatch):
    orch, queue, _worker, ledger, _kernel_calls = governed
    monkeypatch.setattr(kernel, "authorize",
                        lambda action, *a, **k: Decision(Verdict.DENY, reason="kill_switch"))
    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    assert outcome.reply.startswith("Not proposed: the Action Kernel refused")
    assert "kill_switch" in outcome.reply
    assert queue.list(kind="goal.approve") == []
    assert ledger.list_runs() == []


async def test_a_policy_decision_on_the_card_opens_no_run(governed):
    orch, queue, worker, ledger, _kernel_calls = governed
    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    task_id = _task_id(outcome.reply)
    await worker.apply_decision(task_id, "accept", decided_by="policy")
    await worker.tick(task_id=task_id)
    result = queue.get(task_id).result or {}
    assert result.get("status") == "refused"
    assert result.get("reason") == "not_decided_by_a_human"
    assert ledger.list_runs() == []


async def test_the_route_reaches_the_same_front_door(governed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.routers import company as company_routes
    from agents.core.routers._deps import admin_guard

    orch, queue, worker, ledger, kernel_calls = governed
    monkeypatch.setattr(company_routes, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(company_routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    reply = TestClient(app).post("/api/company/goals", json={"text": GOAL})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["ok"] is True and "payload" not in body
    task = queue.get(body["task_id"])
    assert task.kind == "goal.approve" and task.status == "blocked"
    assert task.payload["requested_by"] == "owner:api"
    assert ledger.list_runs() == []
    assert any(a.kind == "goal.approve" for a, _v in kernel_calls)
    result = await _approve_and_run(worker, queue, body["task_id"])
    assert ledger.get(result["run_id"]).title == "Prepare the quarterly brief"
