"""The wiring that makes company mode actually run — and refuse to.

Every other piece of the chain is a component with its own tests. This is the
part that decides whether any of them are built, so the tests are about the
answers to that:

  · off means NOTHING is constructed — a supervisor that exists is a supervisor
    something can call;
  · turning it OFF takes effect at the very next tick; turning it ON needs a
    restart. Stopping should always be easy, starting always deliberate;
  · the planner is the checklist the owner READ ON THE CARD, not a model. "Let a
    model decide what to do all night" is the thing that must be opted into;
  · a goal with no plan proposes NOTHING — "you approved a goal with no plan, so
    nothing happened" beats a model improvising from a one-line title;
  · a goal that cannot be read yields an EMPTY plan, never an unrestricted one;
  · a sweep never raises into the scheduler, because one bad run must not kill
    the job that would have recovered it.

Hermetic: a fake orchestrator, an on-disk ledger under tmp_path, an injected
clock. Nothing sleeps and no scheduler is started.
"""

from __future__ import annotations

import types

import pytest

from agents.core.autonomy.company_planner import ChecklistPlanner
from agents.core.autonomy.company_runtime import (
    CompanyRuntime,
    RuntimeParts,
    build_company_runtime,
)
from agents.core.autonomy.goal_contract import GoalDraft, SuccessCheck
from agents.core.autonomy.schedule_runtime import ScheduleConfig
from agents.core.autonomy.work_runs import Budget, WorkRunLedger

pytestmark = pytest.mark.asyncio

DAY = 86_400.0


@pytest.fixture
def ledger(tmp_path):
    store = WorkRunLedger(tmp_path / "runs.db", clock=lambda: 1_000.0)
    yield store
    store.close()


class _Orch:
    def __init__(self, ledger, *, queue=True, intake=True):
        self.work_runs = ledger
        self.company_runtime = None
        if queue:
            self.task_queue = types.SimpleNamespace(get=lambda tid: None)
        if intake:
            self.govern_enqueue = lambda **kw: 1


def _goal_obj(goal_id="g1"):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="ship the thing",
        approved_by=types.SimpleNamespace(key="owner:accept:7"),
        deadline_at=0.0,
    )


def _draft(plan=(), scope=("research", "write")):
    return GoalDraft(
        title="Prepare the brief",
        scope_kinds=tuple(scope),
        budget=Budget(),
        deadline_at=9_999_999_999.0,
        stop_conditions=("the source data changes",),
        checks=(SuccessCheck(id="c1", describe="a brief exists", probe_ref="p:x"),),
        deliverable="one brief",
        plan=tuple(plan),
    )


def _approved(draft):
    from agents.core.autonomy.goal_contract import ApprovedGoal

    return ApprovedGoal(
        goal_id="g1", title=draft.title, approved_by="owner:accept:7",
        deadline_at=draft.deadline_at, draft=draft, approved_at=0.0,
    )


# ── off means nothing is built ───────────────────────────────────────────────

async def test_nothing_is_built_with_the_flag_off(ledger, monkeypatch):
    """Not "built but inert": a supervisor that exists is one something can call."""
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    assert build_company_runtime(_Orch(ledger)) is None


async def test_nothing_is_built_without_a_ledger(monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    assert build_company_runtime(types.SimpleNamespace(work_runs=None)) is None


async def test_nothing_is_built_without_a_governed_intake(ledger, monkeypatch):
    """Without an intake a run could only take ungoverned steps, which is the one
    thing this whole chain exists to prevent."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    assert build_company_runtime(_Orch(ledger, intake=False)) is None


async def test_a_missing_task_queue_is_named_rather_than_discovered_at_3am(ledger, monkeypatch):
    """Without a queue reader an approved task can never unblock its run, so the
    first ask would block the night forever. It builds — reading past runs is
    still useful — but it says so."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger, queue=False))
    assert runtime is not None
    assert any("can never be resumed" in r for r in runtime.parts.reasons)
    assert runtime.parts.reconciler is None


# ── stopping is easy, starting is deliberate ─────────────────────────────────

async def test_clearing_the_flag_stops_work_at_the_very_next_tick(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger))
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    result = await runtime.sweep()
    assert result["swept"] == 0
    assert result["reason"] == "company mode is off"


async def test_the_flag_is_re_read_every_sweep_not_cached(ledger, monkeypatch):
    """Caching it at construction would mean "off" needs a restart too, and the
    asymmetry only works if stopping is the easy direction."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger))
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    assert (await runtime.sweep())["swept"] == 0
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    assert (await runtime.sweep()).get("reason") != "company mode is off"


# ── the planner is the approved checklist ────────────────────────────────────

async def test_the_planner_walks_the_plan_the_owner_approved(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    goal = _approved(_draft(plan=[
        {"kind": "research", "summary": "collect the figures"},
        {"kind": "write", "summary": "draft the brief"},
    ]))
    run = ledger.open_run(_goal_obj())
    runtime = build_company_runtime(_Orch(ledger), goals=lambda _gid: goal)

    result = await runtime.sweep()
    assert result["swept"] == 1
    steps = ledger.steps(run.id)
    assert [s.summary for s in steps] == ["collect the figures"]


async def test_the_second_tick_takes_the_second_step(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    goal = _approved(_draft(plan=[
        {"kind": "research", "summary": "collect the figures"},
        {"kind": "write", "summary": "draft the brief"},
    ]))
    run = ledger.open_run(_goal_obj())
    runtime = build_company_runtime(_Orch(ledger), goals=lambda _gid: goal)
    await runtime.sweep()
    # the first step queued and blocked the run; resolve it as the owner would
    ledger.resolve_step(run.id, ledger.outstanding_asks(run.id)[0].seq, outcome="ok")
    ledger.resume(run.id)
    runtime.parts.scheduler._last.clear()      # the interval is not what is under test
    await runtime.sweep()
    assert [s.summary for s in ledger.steps(run.id)] == [
        "collect the figures", "draft the brief"
    ]


async def test_a_goal_with_no_plan_proposes_nothing(ledger, monkeypatch):
    """"You approved a goal with no plan, so nothing happened" is a better outcome
    than a model improvising a night's work from a one-line title."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    goal = _approved(_draft(plan=[]))
    run = ledger.open_run(_goal_obj())
    runtime = build_company_runtime(_Orch(ledger), goals=lambda _gid: goal)
    await runtime.sweep()
    assert [s for s in ledger.steps(run.id) if s.outcome == "queued"] == []


async def test_an_unreadable_goal_yields_an_empty_plan_never_an_open_one(ledger, monkeypatch):
    """A planner that proposes nothing wastes a night. A planner that proposes
    anything because it could not read its limits is the failure this prevents."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")

    def _boom(_goal_id):
        raise RuntimeError("the goal store is gone")

    run = ledger.open_run(_goal_obj())
    runtime = build_company_runtime(_Orch(ledger), goals=_boom)
    await runtime.sweep()
    assert [s for s in ledger.steps(run.id) if s.outcome == "queued"] == []


async def test_a_supplied_planner_is_recorded_as_a_deviation(ledger, monkeypatch):
    """A model planner is allowed and must be visible: "the approved checklist is
    not in use" is a fact the owner is owed."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")

    async def _planner(_context):
        return None

    runtime = build_company_runtime(_Orch(ledger), planner=_planner)
    assert any("not in use" in r for r in runtime.parts.reasons)


async def test_a_plan_step_outside_the_goal_scope_is_refused_when_the_card_is_built():
    """Refused where the owner can see it, not at 3am inside a run."""
    from agents.core.autonomy.goal_contract import GoalContractError

    with pytest.raises(GoalContractError) as exc:
        _draft(plan=[{"kind": "payment", "summary": "buy the thing"}], scope=("research",))
    assert exc.value.reason == "plan_step_out_of_scope"


@pytest.mark.parametrize(
    "row",
    [{"kind": "", "summary": "x"}, {"kind": "research", "summary": ""}, "not a mapping"],
)
async def test_an_unreadable_plan_step_makes_the_plan_unapprovable(row):
    from agents.core.autonomy.goal_contract import GoalContractError

    with pytest.raises(GoalContractError) as exc:
        _draft(plan=[row])
    assert exc.value.reason == "invalid_plan_step"


async def test_the_plan_is_inside_the_fingerprint():
    """Editing the plan after the card was shown invalidates the approval,
    exactly like editing the budget would."""
    a = _draft(plan=[{"kind": "research", "summary": "collect the figures"}])
    b = _draft(plan=[{"kind": "research", "summary": "collect different figures"}])
    assert a.fingerprint() != b.fingerprint()


async def test_the_approved_plan_becomes_planner_steps():
    goal = _approved(_draft(plan=[{"kind": "write", "summary": "draft it"}]))
    steps = goal.plan_steps()
    assert [(s.kind, s.summary) for s in steps] == [("write", "draft it")]
    # and it really is what ChecklistPlanner takes
    assert ChecklistPlanner(steps, scope_kinds=goal.scope_kinds) is not None


# ── the sweep never raises ───────────────────────────────────────────────────

async def test_a_failing_sweep_is_reported_not_raised(ledger, monkeypatch):
    """One bad run must not silently unregister the job that would recover it."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger))

    class _Broken:
        async def sweep(self):
            raise RuntimeError("boom")

        def snapshot(self):
            raise RuntimeError("boom")

    runtime.parts.scheduler = _Broken()
    result = await runtime.sweep()
    assert result == {"ok": False, "swept": 0, "reason": "RuntimeError"}
    # and the status surface degrades rather than raising too
    assert runtime.snapshot()["enabled"] is True


async def test_a_sweep_over_nothing_is_a_clean_zero(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    result = await build_company_runtime(_Orch(ledger)).sweep()
    assert result["ok"] is True
    assert result["swept"] == 0


async def test_the_snapshot_says_whether_it_is_enabled(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger))
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    snapshot = runtime.snapshot()
    assert snapshot["enabled"] is False
    # the scheduler's own config is a DIFFERENT fact and keeps its own key: these
    # two shared one until the shadowing was found, and the gate lost
    assert snapshot["scheduler_enabled"] is True


async def test_runtime_parts_report_what_was_built(ledger):
    parts = RuntimeParts(ledger=ledger, supervisor=None, scheduler=None, reconciler=None)
    assert parts.as_dict()["built"] is True


async def test_a_runtime_with_an_injected_gate_never_reads_the_environment(ledger):
    """The gate is injectable so a test — and a caller with its own switch — does
    not have to mutate process state to prove the off path."""
    runtime = CompanyRuntime(
        RuntimeParts(ledger=ledger, supervisor=None, scheduler=None, reconciler=None),
        enabled=lambda: False,
    )
    assert (await runtime.sweep())["reason"] == "company mode is off"


# ── registration: off at boot means no job at all ────────────────────────────

class _Sched:
    def __init__(self):
        self.jobs = []

    def add_job(self, fn, trigger, **kw):
        self.jobs.append((getattr(fn, "__name__", str(fn)), trigger, kw.get("id")))
        self.seconds = kw.get("seconds")


def _service(ledger, sched):
    from agents.core.scheduler_service import SchedulerService

    orch = _Orch(ledger)
    orch.heartbeat_scheduler = types.SimpleNamespace(scheduler=sched)
    orch.get_setting = lambda key, default=None: default
    return SchedulerService(orch), orch


async def test_no_job_is_registered_with_the_flag_off_at_boot(ledger, monkeypatch):
    """Starting a night of autonomous work should never happen because a config
    file changed while nobody was looking. It takes a restart."""
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    service, orch = _service(ledger, sched)
    service.schedule_company_mode()
    assert sched.jobs == []
    assert orch.company_runtime is None


async def test_the_job_is_registered_when_the_flag_is_set_at_boot(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    service, orch = _service(ledger, sched)
    service.schedule_company_mode()
    assert [job[2] for job in sched.jobs] == ["company-mode-sweep"]
    assert orch.company_runtime is not None


async def test_no_job_is_registered_when_the_runtime_refuses_to_build(monkeypatch):
    """Registering a job that can only no-op would report a working night shift."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    orch = types.SimpleNamespace(
        work_runs=None, company_runtime=None,
        heartbeat_scheduler=types.SimpleNamespace(scheduler=sched),
        get_setting=lambda key, default=None: default,
    )
    from agents.core.scheduler_service import SchedulerService

    SchedulerService(orch).schedule_company_mode()
    assert sched.jobs == []


async def test_the_tick_interval_never_drops_below_a_minute(ledger, monkeypatch):
    """A work run is measured in hours; a tighter loop only buys wasted calls
    against an approval that has not arrived."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    sched = _Sched()
    from agents.core.scheduler_service import SchedulerService

    orch = _Orch(ledger)
    orch.heartbeat_scheduler = types.SimpleNamespace(scheduler=sched)
    orch.get_setting = lambda key, default=None: 1 if "company_tick" in key else default
    SchedulerService(orch).schedule_company_mode()
    assert sched.seconds == 60


# ── H464: one barrier check, shared by the scheduler and the supervisor ──────

async def test_a_parked_run_is_skipped_by_the_built_chain(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    runtime = build_company_runtime(_Orch(ledger), goals=lambda _gid: None)
    barriers = runtime.parts.barriers
    assert barriers is not None
    run = ledger.open_run(_goal_obj())
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 600}},
                     source="planner")
    result = await runtime.sweep()
    assert result["skipped"] == {run.id: "waiting"}
    assert (await runtime.parts.supervisor.tick(run.id)).outcome == "waiting"
    assert ledger.get(run.id).steps_used == 0


async def test_the_judge_wait_probe_is_passed_through(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    asked = []

    async def _grader(_rid):
        return types.SimpleNamespace(passed=False, reason="not yet")

    runtime = build_company_runtime(
        _Orch(ledger), goals=lambda _gid: None, verify=_grader, judge=_grader,
        judge_wait=lambda rid: asked.append(rid) or {"kind": "deadline",
                                                     "target": {"in_seconds": 60}},
    )
    run = ledger.open_run(_goal_obj())
    assert (await runtime.parts.supervisor.tick(run.id)).outcome == "waiting"
    assert asked == [run.id]
    assert ledger.get(run.id).barrier["source"] == "judge"


# ── H464b C2: built from the names the real orchestrator actually has ────────

def _intake(calls, queue=None):
    """The governed intake as a spy. With a real queue it does what the real one
    ends in for an ``ask`` task: a durable row, blocked on the owner's decision."""

    def govern_enqueue(**kwargs):
        calls.append(dict(kwargs))
        if queue is None:
            return len(calls)
        from agents.core.autonomy.queue import TaskStatus

        tid = queue.enqueue(kwargs["agent"], kwargs["kind"], kwargs["title"],
                            dict(kwargs.get("payload") or {}))
        queue.transition(tid, TaskStatus.BLOCKED)
        return tid

    return govern_enqueue


class _RealOrch:
    """Shaped like the shipped orchestrator and nothing more: the queue is
    ``autonomy_queue`` (orchestrator.py) and the governed intake is
    ``autonomy.govern_enqueue`` (worker.py). No ``task_queue``, ``queue`` or
    ``govern_enqueue`` attribute exists on the real one."""

    def __init__(self, ledger, *, queue=None, read=None):
        self.work_runs = ledger
        self.company_runtime = None
        get = read or (queue.get if queue is not None else (lambda tid: None))
        self.autonomy_queue = types.SimpleNamespace(get=get)
        self.autonomy = types.SimpleNamespace(calls=[])
        self.autonomy.govern_enqueue = _intake(self.autonomy.calls, queue)


_ROW = {
    "kind": "research", "summary": "collect the figures",
    "task": {"agent": "jarvis", "kind": "research.collect", "title": "Collect the figures",
             "payload": {"source": "q3"}},
}


async def test_the_runtime_builds_from_the_real_orchestrator_attribute_names(ledger, monkeypatch):
    """The shipped orchestrator never had ``task_queue``/``govern_enqueue``, so the
    runtime never built in production and no sweep job was ever registered."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    orch = _RealOrch(ledger)
    runtime = build_company_runtime(orch)
    assert runtime is not None
    assert runtime.parts.reconciler is not None
    assert not any("can never be resumed" in r for r in runtime.parts.reasons)
    # H487's approval-wait credit reads the same durable queue
    assert ledger._approval_task_reader is orch.autonomy_queue.get


async def test_the_sweep_job_is_registered_for_a_real_shaped_orchestrator(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    from agents.core.scheduler_service import SchedulerService

    sched = _Sched()
    orch = _RealOrch(ledger)
    orch.heartbeat_scheduler = types.SimpleNamespace(scheduler=sched)
    orch.get_setting = lambda key, default=None: default
    SchedulerService(orch).schedule_company_mode()
    assert [job[2] for job in sched.jobs] == ["company-mode-sweep"]
    assert orch.company_runtime is not None


async def test_the_real_intake_is_the_one_steps_go_to(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    goal = _approved(_draft(plan=[_ROW]))
    run = ledger.open_run(_goal_obj())
    orch = _RealOrch(ledger)
    runtime = build_company_runtime(orch, goals=lambda _gid: goal)
    await runtime.sweep()
    assert orch.autonomy.calls == [_ROW["task"]]
    assert [s.summary for s in ledger.steps(run.id)] == ["collect the figures"]



class _EmptyQueue:
    """A queue that is present but falsy (nothing in it): presence, not truthiness."""

    def __len__(self):
        return 0

    def get(self, tid):
        return None


class _FalsyWorker(types.SimpleNamespace):
    """An autonomy worker that happens to be falsy (nothing queued yet)."""

    def __len__(self):
        return 0


class _FalsyIntake:
    """A callable intake that happens to be falsy."""

    def __init__(self):
        self.calls = []

    def __len__(self):
        return 0

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return 1


@pytest.mark.parametrize("name", ["task_queue", "queue", "autonomy_queue"])
async def test_each_queue_name_is_read_in_order_and_presence_is_what_counts(
    ledger, monkeypatch, name
):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    orch = types.SimpleNamespace(work_runs=ledger, company_runtime=None,
                                 govern_enqueue=lambda **kw: 1)
    queue = _EmptyQueue()
    setattr(orch, name, queue)
    runtime = build_company_runtime(orch)
    assert runtime is not None and runtime.parts.reconciler is not None
    assert ledger._approval_task_reader == queue.get


async def test_the_queue_names_are_tried_in_order_and_the_explicit_reader_wins(
    ledger, monkeypatch
):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    first, second, third = _EmptyQueue(), _EmptyQueue(), _EmptyQueue()
    orch = types.SimpleNamespace(work_runs=ledger, company_runtime=None, task_queue=first,
                                 queue=second, autonomy_queue=third,
                                 govern_enqueue=lambda **kw: 1)
    build_company_runtime(orch)
    assert ledger._approval_task_reader == first.get
    del orch.task_queue
    build_company_runtime(orch)
    assert ledger._approval_task_reader == second.get
    orch.queue = types.SimpleNamespace(get="not callable")     # only a callable counts
    build_company_runtime(orch)
    assert ledger._approval_task_reader == third.get

    def explicit(_tid):
        return None

    build_company_runtime(orch, read_task=explicit)
    assert ledger._approval_task_reader is explicit


async def test_the_intake_is_the_explicit_one_then_the_orchestrator_s_then_the_worker_s(
    ledger, monkeypatch
):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    goal = _approved(_draft(plan=[_ROW]))
    worker = _FalsyIntake()
    orch = types.SimpleNamespace(
        work_runs=ledger, company_runtime=None, autonomy_queue=_EmptyQueue(),
        govern_enqueue="not callable", autonomy=_FalsyWorker(govern_enqueue=worker),
    )
    run = ledger.open_run(_goal_obj())
    await build_company_runtime(orch, goals=lambda _gid: goal).sweep()
    assert worker.calls == [_ROW["task"]]           # a falsy intake is still the intake
    assert [s.summary for s in ledger.steps(run.id)] == ["collect the figures"]

    own = _FalsyIntake()
    orch.govern_enqueue = own
    runtime = build_company_runtime(orch, goals=lambda _gid: goal)
    assert runtime.parts.supervisor._enqueue is own

    def explicit(**_kw):
        return 1

    runtime = build_company_runtime(orch, enqueue=explicit, goals=lambda _gid: goal)
    assert runtime.parts.supervisor._enqueue is explicit
    orch.govern_enqueue = None
    orch.autonomy = types.SimpleNamespace(govern_enqueue=None)
    assert build_company_runtime(orch) is None


# ── H464b C3: the checklist is read back from the goal's own approval task ────

@pytest.fixture
def world(tmp_path, monkeypatch):
    """A real task queue and a ledger on ONE clock (H487's ``world`` pattern): the
    goal is proposed, decided and read back through the durable queue."""
    from datetime import UTC, datetime

    from agents.core.autonomy.queue import TaskQueue

    clock = [1_800_000_000.0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    q = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    store = WorkRunLedger(tmp_path / "work.db", clock=lambda: clock[0])
    yield types.SimpleNamespace(clock=clock, q=q, ledger=store)
    store.close()
    q.close()


def _goal_task(q, draft, decided_by="owner"):
    """The goal card as the inbox carries it, decided by ``decided_by``."""
    from agents.core.autonomy.queue import TaskStatus

    payload = draft.as_payload()
    payload["fingerprint"] = draft.fingerprint()
    tid = q.enqueue("jarvis", "goal.approve", f"Approve goal: {draft.title}", payload)
    q.transition(tid, TaskStatus.APPROVED, decided_by=decided_by, decision="accept",
                 human_reason=None)
    return tid


def _approved_run(q, ledger, draft, decided_by="owner"):
    """Propose, approve and open, exactly as the ``goal.approve`` handler does."""
    from agents.core.autonomy.goal_contract import approve_from_task

    goal = approve_from_task(q.get(_goal_task(q, draft, decided_by)))
    return ledger.open_run(goal, budget=goal.budget, deadline_at=goal.deadline_at)


async def test_the_approved_checklist_is_read_from_its_own_approval_task(world):
    """No ``goals=`` is injected: the shipped runtime has none, so the checklist
    must come back from the approval task, or nothing ever runs."""
    run = _approved_run(world.q, world.ledger, _draft(plan=[_ROW]))
    orch = _RealOrch(world.ledger, queue=world.q)
    await build_company_runtime(orch).sweep()
    assert orch.autonomy.calls == [_ROW["task"]]
    steps = world.ledger.steps(run.id)
    assert [s.summary for s in steps] == ["collect the figures"]
    assert steps[0].outcome == "queued"
    assert world.ledger.get(run.id).status == "blocked"


async def test_the_goal_read_back_keeps_the_run_s_goal_id(world):
    """``approve_from_task`` mints a fresh goal id; the judge's goal-identity rule
    needs the run's own."""
    from agents.core.autonomy.company_runtime import _approved_goal_for

    run = _approved_run(world.q, world.ledger, _draft(plan=[_ROW]))
    goal = _approved_goal_for(run, world.q.get)
    assert goal is not None
    assert goal.goal_id == run.goal_id
    assert goal.approved_by == run.approved_by
    assert [s.summary for s in goal.plan_steps()] == ["collect the figures"]


def _open_from(ledger, *, approved_by, draft, title=None, deadline=None, budget=None):
    """A run opened from a goal object that is NOT the approval's own read-back."""
    goal = types.SimpleNamespace(
        goal_id="g-other", title=title or draft.title, approved_by=approved_by,
        deadline_at=draft.deadline_at if deadline is None else deadline,
    )
    return ledger.open_run(goal, budget=budget or draft.budget,
                           deadline_at=draft.deadline_at if deadline is None else deadline)


def _case_legacy(world, draft):
    return _open_from(world.ledger, approved_by="owner:accept:7", draft=draft), None


def _case_missing(world, draft):
    return _open_from(world.ledger, approved_by="task:9999:owner", draft=draft), None


def _case_reader_raises(world, draft):
    tid = _goal_task(world.q, draft)

    def read(task_id):
        if int(task_id) == tid:
            raise RuntimeError("the queue db is locked")
        return world.q.get(task_id)

    return _open_from(world.ledger, approved_by=f"task:{tid}:owner", draft=draft), read


def _case_policy(world, draft):
    tid = _goal_task(world.q, draft, decided_by="policy")
    return _open_from(world.ledger, approved_by=f"task:{tid}:policy", draft=draft), None


def _case_edited(world, draft):
    run = _approved_run(world.q, world.ledger, draft)
    tid = int(run.approved_by.split(":")[1])
    payload = dict(world.q.get(tid).payload)
    payload["plan"] = [dict(_ROW, summary="collect ALL the figures")]
    world.q.update_payload(tid, payload)
    return run, None


def _case_title(world, draft):
    tid = _goal_task(world.q, draft)
    return _open_from(world.ledger, approved_by=f"task:{tid}:owner", draft=draft,
                      title="Another goal"), None


def _case_deadline(world, draft):
    tid = _goal_task(world.q, draft)
    return _open_from(world.ledger, approved_by=f"task:{tid}:owner", draft=draft,
                      deadline=draft.deadline_at - 60), None


def _case_budget(world, draft):
    tid = _goal_task(world.q, draft)
    return _open_from(world.ledger, approved_by=f"task:{tid}:owner", draft=draft,
                      budget=Budget(max_steps=7)), None


def _case_decider(world, draft):
    tid = _goal_task(world.q, draft, decided_by="owner")
    return _open_from(world.ledger, approved_by=f"task:{tid}:someone-else", draft=draft), None


def _case_another_task(world, draft):
    from agents.core.autonomy.queue import TaskStatus

    other = world.q.enqueue("jarvis", "research.collect", "Collect", {})
    world.q.transition(other, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                       human_reason=None)
    return _open_from(world.ledger, approved_by=f"task:{other}:owner", draft=draft), None


def _case_reader_swaps(world, draft):
    """The reader hands back a DIFFERENT approved goal task than the one asked for
    (an id reused after a purge): same content, another approval."""
    asked = _goal_task(world.q, draft)
    other = _goal_task(world.q, draft)

    def read(task_id):
        return world.q.get(other if int(task_id) == asked else task_id)

    return _open_from(world.ledger, approved_by=f"task:{asked}:owner", draft=draft), read


@pytest.mark.parametrize("case", [
    _case_legacy, _case_missing, _case_reader_raises, _case_policy, _case_edited,
    _case_title, _case_deadline, _case_budget, _case_decider, _case_another_task,
    _case_reader_swaps,
], ids=lambda c: c.__name__.removeprefix("_case_"))
async def test_a_goal_that_cannot_be_bound_to_its_run_drives_nothing(world, case):
    """Any doubt is an EMPTY checklist, never an open one: a policy-decided goal,
    an edited payload, or a goal that belongs to another run cannot drive this one."""
    draft = _draft(plan=[_ROW])
    run, read = case(world, draft)
    orch = _RealOrch(world.ledger, queue=world.q, read=read)
    runtime = build_company_runtime(orch)
    assert runtime is not None
    await runtime.sweep()
    assert orch.autonomy.calls == []
    assert [s for s in world.ledger.steps(run.id) if s.outcome == "queued"] == []
    from agents.core.autonomy.company_runtime import _approved_goal_for

    assert _approved_goal_for(world.ledger.get(run.id), read or world.q.get) is None


async def test_an_explicit_goal_reader_still_wins(world):
    """Tests and callers that inject ``goals=`` keep that exact meaning."""
    run = _approved_run(world.q, world.ledger, _draft(plan=[_ROW]))
    orch = _RealOrch(world.ledger, queue=world.q)
    await build_company_runtime(orch, goals=lambda _gid: None).sweep()
    assert orch.autonomy.calls == []
    assert world.ledger.steps(run.id) == []


# ── H464b C4 (AC11): the shipped chain parks a run on its own approved task ────

def _record_ticks(runtime):
    """Observe what each tick answered. Observation only: the chain is the shipped
    one, built with no injected callable."""
    seen = []
    tick = runtime.parts.scheduler._tick

    async def _tick(run_id):
        result = await tick(run_id)
        seen.append(result)
        return result

    runtime.parts.scheduler._tick = _tick
    return seen


async def _sweep(runtime):
    runtime.parts.scheduler._last.clear()      # the interval is not what is under test
    return await runtime.sweep()


def _hub_sets(ledger, run_id):
    return ledger.barrier_sets(run_id, source="hub")


async def _parked_on_the_approved_step(world):
    """Steps 1-4: approve a one-row goal, sweep, the owner accepts the step's task,
    sweep again — the run is parked on that task by the hub."""
    from agents.core.autonomy.queue import TaskStatus

    run = _approved_run(world.q, world.ledger, _draft(plan=[_ROW]))
    orch = _RealOrch(world.ledger, queue=world.q)
    runtime = build_company_runtime(orch, config=ScheduleConfig(enabled=True))
    ticks = _record_ticks(runtime)

    await _sweep(runtime)
    assert world.ledger.get(run.id).status == "blocked"
    step = world.ledger.steps(run.id)[0]
    assert orch.autonomy.calls == [_ROW["task"]]

    world.clock[0] += 30
    world.q.transition(step.task_id, TaskStatus.APPROVED, decided_by="owner",
                       decision="accept", human_reason=None)
    ticks.clear()
    await _sweep(runtime)
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("waiting", f"parked: task {step.task_id} to finish")]
    barrier = world.ledger.get(run.id).barrier
    assert (barrier["kind"], barrier["target"], barrier["source"]) == (
        "trigger", f"task:{step.task_id}", "hub")
    assert barrier["reason"] == f"task {step.task_id} is still running"
    return run, step, runtime, ticks


async def test_the_shipped_chain_parks_a_run_on_its_approved_task_and_moves_on_when_it_is_done(
    world,
):
    from agents.core.autonomy.queue import TaskStatus

    run, step, runtime, ticks = await _parked_on_the_approved_step(world)
    steps_used = world.ledger.get(run.id).steps_used
    assert steps_used == 1                                   # the park spent nothing

    world.q.transition(step.task_id, TaskStatus.RUNNING)
    ticks.clear()
    result = await _sweep(runtime)
    assert result["skipped"] == {run.id: "waiting"} and ticks == []
    assert world.ledger.get(run.id).steps_used == steps_used

    world.q.transition(step.task_id, TaskStatus.DONE, result={"ok": True})
    ticks.clear()
    await _sweep(runtime)
    cleared = [e["detail"] for e in world.ledger.events(run.id) if e["kind"] == "barrier.cleared"]
    assert [(c["why"], c["by"]) for c in cleared] == [("fired", "check")]
    assert [(t.outcome, t.detail) for t in ticks] == [
        ("idle", "no work left, and no grader is wired to settle the run")]
    assert len(_hub_sets(world.ledger, run.id)) == 1
    assert world.ledger.verdicts(run.id) == []
    assert world.ledger.get(run.id).steps_used == steps_used


async def test_an_owner_clear_of_the_hub_park_sticks_in_the_shipped_chain(world):
    run, step, runtime, ticks = await _parked_on_the_approved_step(world)
    cleared, _after = runtime.parts.barriers.clear(run.id)
    assert cleared is True
    ticks.clear()
    await _sweep(runtime)
    assert [t.outcome for t in ticks] == ["idle"]
    assert world.ledger.get(run.id).barrier is None
    assert len(_hub_sets(world.ledger, run.id)) == 1
    assert world.ledger.owner_cleared(run.id) == [
        {"kind": "trigger", "target": f"task:{step.task_id}"}]
