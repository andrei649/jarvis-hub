"""H464d — approval-wait credit is the wait the owner imposed, whoever was looking.

H487 credits a company run the time it spent blocked on the owner's answer (at most
360 s per block, never past the ask's own deadline, only while the task is still the
one that was asked). Since H464c the report routes are read-only, and nothing on the
tick path looks at a blocked run: the scheduler skips it as ``blocked`` and the
reconciler only reads answers. The credit of an answer is the answer's own durable
timestamp, so it never needed anyone to look. A wait that ended WITHOUT an answer —
the owner stopped the run, or resumed it by hand — was closed at the last time
somebody happened to observe it, which after H464c is nobody: the owner's wait was
credited as zero.

These pin the credit a run ends up with, for each way a wait ends, with the HUD
polling every report route through the wait, with the scheduler sweeping through it,
and with nobody looking: the same number, and it is the wait the owner imposed.

Hermetic: a real task queue and ledger under tmp_path on one hand-driven clock, the
real company runtime with a spy intake, and the company routes on a TestClient.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import pytest

from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.company_supervisor import Action
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.schedule_runtime import ScheduleConfig
from agents.core.autonomy.work_runs import Budget, WorkRunLedger

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0
WAIT = 100.0          # how long the owner kept the run waiting
POLL = 10.0           # how often the HUD (or the scheduler) looked, when it did


@pytest.fixture
def world(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    q = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    ledger = WorkRunLedger(tmp_path / "work.db", clock=lambda: clock[0])
    yield types.SimpleNamespace(clock=clock, q=q, ledger=ledger)
    ledger.close()
    q.close()


class _Orch:
    """The names the shipped orchestrator has; the intake ends as the real one does
    for an ask: a durable row, blocked on the owner (optionally with a deadline)."""

    def __init__(self, world, *, deadline: float | None = None):
        self.work_runs = world.ledger
        self.company_runtime = None
        q = world.q

        def govern_enqueue(**kwargs):
            stamp = datetime.fromtimestamp(deadline, UTC).isoformat() if deadline else None
            tid = q.enqueue(kwargs["agent"], kwargs["kind"], kwargs["title"],
                            dict(kwargs.get("payload") or {}), approval_deadline_at=stamp)
            q.transition(tid, TaskStatus.BLOCKED)
            return tid

        self.autonomy_queue = types.SimpleNamespace(get=q.get)
        self.autonomy = types.SimpleNamespace(govern_enqueue=govern_enqueue)


def _one_ask():
    asked: list[int] = []

    def plan(_context):
        if asked:
            return None
        asked.append(1)
        return Action(kind="research", summary="ask the owner",
                      task={"agent": "jarvis", "kind": "research.collect",
                            "title": "Ask the owner", "payload": {"q": 1}})

    return plan


def _client(ledger, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.routers import company as company_routes
    from agents.core.routers._deps import user_guard

    async def _get():
        return ledger

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    app = FastAPI()
    app.include_router(company_routes.router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


async def _sweep(runtime):
    runtime.parts.scheduler._last.clear()      # the interval is not what is under test
    return await runtime.sweep()


def _poll_the_hud(client, ledger, run_id):
    """Every report route the HUD reads — and they write nothing (H464c)."""
    before = ledger._conn.total_changes
    assert client.get("/api/company/runs").status_code == 200
    assert client.get(f"/api/company/runs/{run_id}").status_code == 200
    assert client.get("/api/company/waiting").status_code == 200
    assert ledger._conn.total_changes == before


async def _blocked_run(world, monkeypatch, *, deadline=None):
    runtime = build_company_runtime(_Orch(world, deadline=deadline), planner=_one_ask(),
                                    config=ScheduleConfig(enabled=True))
    run = world.ledger.open_run(
        types.SimpleNamespace(goal_id="g", title="Ask and wait", approved_by="receipt:1"),
        budget=Budget(max_seconds=3_600),
    )
    await _sweep(runtime)
    (step,) = world.ledger.outstanding_asks(run.id)
    assert world.ledger.get(run.id).status == "blocked"
    return runtime, run, step, _client(world.ledger, monkeypatch)


async def _wait(world, runtime, client, run_id, seconds, polling):
    """Let ``seconds`` pass while the HUD polls, the scheduler sweeps, or nobody looks."""
    elapsed = 0.0
    while elapsed < seconds:
        step = min(POLL, seconds - elapsed)
        world.clock[0] += step
        elapsed += step
        if polling == "hud":
            _poll_the_hud(client, world.ledger, run_id)
        elif polling == "sweeps":
            await _sweep(runtime)


def _end_the_wait(world, client, run_id, task_id, how):
    q = world.q
    if how == "accept":
        q.transition(task_id, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                     human_reason=None)
    elif how == "reject":
        q.transition(task_id, TaskStatus.REJECTED, decided_by="owner", decision="reject",
                     human_reason=None)
    elif how == "expired":
        assert [t.id for t in q.expire_pending_approvals().tasks] == [task_id]
        assert q.get(task_id).status == "expired"
    elif how == "stopped":
        assert client.post(f"/api/company/runs/{run_id}/stop").status_code == 200
    elif how == "resumed":
        world.ledger.resume(run_id)
    else:  # pragma: no cover - a typo in the parametrisation
        raise AssertionError(how)


def _credit(ledger, run_id) -> float:
    settled = ledger.budget_state(run_id)["human_wait_seconds"]
    report = ledger.budget_state(run_id, settle=False)["human_wait_seconds"]
    assert settled == report          # the report reads the number the tick path settles
    return settled


@pytest.mark.parametrize("polling", ["none", "hud", "sweeps"])
@pytest.mark.parametrize("how", ["accept", "reject", "expired", "stopped", "resumed"])
async def test_the_credit_is_the_owner_s_wait_whoever_was_looking(world, monkeypatch,
                                                                   how, polling):
    deadline = T0 + WAIT if how == "expired" else None
    runtime, run, step, client = await _blocked_run(world, monkeypatch, deadline=deadline)
    await _wait(world, runtime, client, run.id, WAIT, polling)
    _end_the_wait(world, client, run.id, step.task_id, how)
    world.clock[0] += 30
    await _sweep(runtime)             # the reconciler reads the answer, if there is one
    world.clock[0] += 30
    assert _credit(world.ledger, run.id) == WAIT
    if how in {"accept", "reject", "expired"}:
        assert world.ledger.get(run.id).status == "working"
    elif how == "stopped":
        assert world.ledger.get(run.id).status in {"stopping", "stopped"}


@pytest.mark.parametrize("polling", ["none", "hud"])
async def test_a_stop_after_the_cap_credits_the_cap_and_no_more(world, monkeypatch, polling):
    """The 360 s epoch cap holds when the wait is closed by a stop."""
    runtime, run, _step, client = await _blocked_run(world, monkeypatch)
    await _wait(world, runtime, client, run.id, 500.0, polling)
    _end_the_wait(world, client, run.id, _step.task_id, "stopped")
    world.clock[0] += 60
    assert _credit(world.ledger, run.id) == 360.0


@pytest.mark.parametrize("polling", ["none", "hud"])
async def test_a_stop_past_the_ask_s_deadline_credits_up_to_the_deadline(world, monkeypatch,
                                                                         polling):
    """No expiry pass ran, so the task still reads ``blocked``: its own deadline still
    bounds the credit a stop closes."""
    runtime, run, step, client = await _blocked_run(world, monkeypatch, deadline=T0 + 50)
    await _wait(world, runtime, client, run.id, WAIT, polling)
    assert world.q.get(step.task_id).status == "blocked"
    _end_the_wait(world, client, run.id, step.task_id, "stopped")
    world.clock[0] += 60
    assert _credit(world.ledger, run.id) == 50.0


@pytest.mark.parametrize("polling", ["none", "hud"])
async def test_a_stop_after_the_ask_was_edited_credits_nothing_it_cannot_prove(
    world, monkeypatch, polling
):
    """The identity rule: once the task no longer says what was asked, a stop credits
    only what was proven before the edit — which, with nobody observing, is nothing.
    Closing a wait on a stop never widens what H487 allows."""
    runtime, run, step, client = await _blocked_run(world, monkeypatch)
    await _wait(world, runtime, client, run.id, 30.0, polling)
    world.q.update_payload(step.task_id, {"q": "something else"})
    await _wait(world, runtime, client, run.id, WAIT - 30.0, polling)
    _end_the_wait(world, client, run.id, step.task_id, "stopped")
    world.clock[0] += 60
    assert _credit(world.ledger, run.id) == 0.0


async def test_a_stop_whose_ask_cannot_be_read_credits_only_what_was_proven(world,
                                                                            monkeypatch):
    """A queue that cannot be read at the moment of the stop proves nothing new: the
    wait closes where it was last proven (fail closed, never a guess)."""
    runtime, run, step, client = await _blocked_run(world, monkeypatch)
    world.clock[0] += WAIT

    def _locked(_task_id):
        raise OSError("database is locked")

    world.ledger.bind_approval_task_reader(_locked)
    _end_the_wait(world, client, run.id, step.task_id, "stopped")
    world.ledger.bind_approval_task_reader(world.q.get)
    world.clock[0] += 60
    assert _credit(world.ledger, run.id) == 0.0


async def test_the_owner_s_answer_after_a_stop_does_not_add_to_the_credit(world,
                                                                          monkeypatch):
    """The stop ends the wait; an answer that lands later is not more waiting."""
    runtime, run, step, client = await _blocked_run(world, monkeypatch)
    world.clock[0] += 40
    _end_the_wait(world, client, run.id, step.task_id, "stopped")
    world.clock[0] += 60
    _end_the_wait(world, client, run.id, step.task_id, "accept")
    await _sweep(runtime)
    world.clock[0] += 60
    assert _credit(world.ledger, run.id) == 40.0
