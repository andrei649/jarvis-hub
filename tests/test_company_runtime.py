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
