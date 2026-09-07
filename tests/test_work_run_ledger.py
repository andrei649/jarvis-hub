"""E5.0 — the work-run ledger, the durable spine of company mode.

A work run is one owner-approved goal worked across many turns and reboots. The
ledger is deliberately the *dumbest* component in the chain: it plans nothing and
actuates nothing, so what it must get exactly right is the set of things nobody
downstream can fix — a run that starts without approval, a budget that quietly
overruns, a stop that keeps working, a success nobody graded.

Every test below pins one of those. Hermetic: an in-memory database and an
injected clock, so no test sleeps and none touches the data root.
"""

import types

import pytest

from agents.core.autonomy.work_runs import (
    TERMINAL_STATUSES,
    Budget,
    WorkRunError,
    WorkRunLedger,
)


class _Clock:
    """A clock the test drives by hand."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _goal(*, approved: bool = True, goal_id: str = "g-1", deadline: float = 100_000.0):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="Prepare the quarterly brief",
        approved_by="receipt:owner-accepted-1" if approved else None,
        deadline_at=deadline,
    )


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def ledger(clock):
    led = WorkRunLedger(":memory:", clock=clock)
    yield led
    led.close()


# ── opening ──────────────────────────────────────────────────────────────────

def test_a_run_cannot_open_without_an_owner_approved_goal(ledger):
    """The whole point of the module: work becomes durable only after approval."""
    with pytest.raises(WorkRunError) as exc:
        ledger.open_run(_goal(approved=False))
    assert exc.value.reason == "goal_not_approved"
    assert ledger.list_runs() == []


def test_open_run_records_the_approval_it_rests_on(ledger):
    run = ledger.open_run(_goal())
    assert run.status == "planning"
    assert run.approved_by == "receipt:owner-accepted-1"
    assert run.goal_id == "g-1"
    assert ledger.get(run.id).as_dict()["approved_by"] == "receipt:owner-accepted-1"


def test_a_second_run_for_the_same_goal_is_refused_while_one_is_open(ledger):
    """Two live runs on one goal would double-spend its budget and its attention."""
    ledger.open_run(_goal())
    with pytest.raises(WorkRunError) as exc:
        ledger.open_run(_goal())
    assert exc.value.reason == "run_already_open_for_goal"


def test_a_finished_goal_may_be_re_run(ledger):
    first = ledger.open_run(_goal())
    ledger.request_stop(first.id, reason="owner changed their mind")
    ledger.settle_stop(first.id)
    second = ledger.open_run(_goal())
    assert second.id != first.id
    assert ledger.get(first.id).status == "stopped"


def test_a_deadline_already_past_is_refused_rather_than_opened_exhausted(ledger, clock):
    with pytest.raises(WorkRunError) as exc:
        ledger.open_run(_goal(deadline=clock.now - 1))
    assert exc.value.reason == "deadline_in_the_past"


def test_an_invalid_budget_is_refused_at_construction():
    for kwargs, reason in (
        ({"max_steps": 0}, "invalid_max_steps"),
        ({"max_seconds": 0}, "invalid_max_seconds"),
        ({"max_interrupts": -1}, "invalid_max_interrupts"),
    ):
        with pytest.raises(WorkRunError) as exc:
            Budget(**kwargs)
        assert exc.value.reason == reason


# ── stepping and budgets ─────────────────────────────────────────────────────

def test_a_step_names_the_durable_task_that_was_authorised_to_take_it(ledger):
    run = ledger.open_run(_goal())
    step = ledger.record_step(
        run.id, kind="terminal", summary="ran the build", outcome="ok", task_id=41
    )
    assert step.task_id == 41
    assert ledger.get(run.id).status == "working"
    assert [s.summary for s in ledger.steps(run.id)] == ["ran the build"]


def test_a_completed_step_with_no_task_is_reported_as_unauthorised(ledger):
    """The ledger records what it is told, then says plainly which steps changed
    something without naming an approved task. Silence there would let a run read
    as fully authorised when it was not."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="edit", summary="wrote a file", outcome="ok")
    ledger.record_step(run.id, kind="edit", summary="wrote another", outcome="ok", task_id=9)
    assert ledger.snapshot(run.id)["unauthorised_steps"] == [1]


def test_an_unknown_outcome_is_refused(ledger):
    run = ledger.open_run(_goal())
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="x", summary="y", outcome="probably_fine")
    assert exc.value.reason == "invalid_outcome"


def test_the_step_budget_stops_the_run_rather_than_overrunning(ledger):
    run = ledger.open_run(_goal(), budget=Budget(max_steps=2))
    ledger.record_step(run.id, kind="a", summary="one", outcome="ok", task_id=1)
    ledger.record_step(run.id, kind="a", summary="two", outcome="ok", task_id=2)
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="a", summary="three", outcome="ok", task_id=3)
    assert exc.value.reason == "budget_exhausted:steps"
    settled = ledger.get(run.id)
    assert settled.status == "exhausted"
    assert settled.stop_reason == "budget:steps"
    # the refused step was NOT recorded — a refusal is not a half-write
    assert len(ledger.steps(run.id)) == 2


def test_the_wall_clock_budget_stops_the_run(ledger, clock):
    run = ledger.open_run(_goal(), budget=Budget(max_seconds=60))
    ledger.record_step(run.id, kind="a", summary="one", outcome="ok", task_id=1)
    clock.advance(61)
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="a", summary="two", outcome="ok", task_id=2)
    assert exc.value.reason == "budget_exhausted:seconds"
    assert ledger.get(run.id).status == "exhausted"


def test_the_deadline_stops_the_run_even_with_budget_left(ledger, clock):
    run = ledger.open_run(_goal(deadline=clock.now + 100), budget=Budget(max_steps=99))
    clock.advance(101)
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="a", summary="late", outcome="ok", task_id=1)
    assert exc.value.reason == "budget_exhausted:deadline"
    assert ledger.get(run.id).stop_reason == "budget:deadline"


def test_the_interrupt_budget_blocks_rather_than_ends_the_run(ledger):
    """Attention is the owner's, not a machine resource: running out of interrupts
    means stop bothering them, not abandon the work."""
    run = ledger.open_run(_goal(), budget=Budget(max_interrupts=1))
    ledger.record_step(run.id, kind="ask", summary="first", outcome="ok",
                       task_id=1, interrupted=True)
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="ask", summary="second", outcome="ok",
                           task_id=2, interrupted=True)
    assert exc.value.reason == "budget_exhausted:interrupts"
    assert ledger.get(run.id).status == "blocked"


def test_budget_state_names_only_the_first_spent_limit(ledger, clock):
    run = ledger.open_run(_goal(), budget=Budget(max_steps=1, max_seconds=10))
    assert ledger.budget_state(run.id)["exceeded"] is None
    ledger.record_step(run.id, kind="a", summary="one", outcome="ok", task_id=1)
    clock.advance(11)
    # both steps and seconds are out; the caller gets one honest reason
    assert ledger.budget_state(run.id)["exceeded"] == "steps"


def test_a_queued_step_blocks_the_run_and_resume_reopens_it(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="ask", summary="needs approval", outcome="queued", task_id=5)
    assert ledger.get(run.id).status == "blocked"
    assert ledger.resume(run.id).status == "working"
    with pytest.raises(WorkRunError) as exc:
        ledger.resume(run.id)
    assert exc.value.reason == "run_not_blocked"


# ── stopping ─────────────────────────────────────────────────────────────────

def test_a_stop_request_refuses_every_further_step(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="one", outcome="ok", task_id=1)
    stopping = ledger.request_stop(run.id, reason="owner said stop")
    assert stopping.status == "stopping"
    with pytest.raises(WorkRunError) as exc:
        ledger.record_step(run.id, kind="a", summary="two", outcome="ok", task_id=2)
    assert exc.value.reason == "run_stopping"
    assert ledger.settle_stop(run.id).status == "stopped"


def test_a_stopped_run_is_a_record_not_a_resource(ledger):
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    for call in (
        lambda: ledger.record_step(run.id, kind="a", summary="x", outcome="ok"),
        lambda: ledger.request_stop(run.id),
        lambda: ledger.record_verdict(run.id, role="judge", passed=True),
    ):
        with pytest.raises(WorkRunError) as exc:
            call()
        assert exc.value.reason == "run_stopped"


def test_every_terminal_status_really_has_no_way_out(ledger):
    """The transition table is the guarantee; this asserts it, so a future edit
    that gives a terminal state an outgoing edge fails here rather than in prod."""
    from agents.core.autonomy.work_runs import _TRANSITIONS

    assert frozenset({"succeeded", "failed", "exhausted", "stopped"}) == TERMINAL_STATUSES
    for status in TERMINAL_STATUSES:
        assert _TRANSITIONS[status] == frozenset()


# ── verdicts ─────────────────────────────────────────────────────────────────

def test_only_the_judge_settles_the_run(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="worked", outcome="ok", task_id=1)
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="evidence holds")
    # the verifier's pass is about the evidence, not the goal — the run keeps working
    assert ledger.get(run.id).status == "working"
    ledger.record_verdict(run.id, role="judge", passed=True, reason="goal met")
    assert ledger.get(run.id).status == "succeeded"


def test_a_judge_cannot_pass_a_run_the_verifier_failed(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="worked", outcome="ok", task_id=1)
    ledger.record_verdict(run.id, role="verifier", passed=False, reason="output did not match")
    with pytest.raises(WorkRunError) as exc:
        ledger.record_verdict(run.id, role="judge", passed=True)
    assert exc.value.reason == "verifier_failed"
    assert ledger.get(run.id).status == "working"


def test_a_judge_cannot_pass_a_run_nobody_verified(ledger):
    run = ledger.open_run(_goal())
    with pytest.raises(WorkRunError) as exc:
        ledger.record_verdict(run.id, role="judge", passed=True)
    assert exc.value.reason == "verifier_verdict_missing"


def test_a_judge_may_always_fail_a_run(ledger):
    """Failing needs no verifier: a judge that could only speak when the evidence
    held would be unable to reject a run that produced no evidence at all."""
    run = ledger.open_run(_goal())
    ledger.record_verdict(run.id, role="judge", passed=False, reason="nothing was produced")
    assert ledger.get(run.id).status == "failed"


def test_a_role_writes_one_verdict_only(ledger):
    run = ledger.open_run(_goal())
    ledger.record_verdict(run.id, role="verifier", passed=False, reason="no")
    with pytest.raises(WorkRunError) as exc:
        ledger.record_verdict(run.id, role="verifier", passed=True, reason="actually yes")
    assert exc.value.reason == "verdict_already_recorded"
    assert [v.passed for v in ledger.verdicts(run.id)] == [False]


def test_an_unknown_verdict_role_is_refused(ledger):
    run = ledger.open_run(_goal())
    with pytest.raises(WorkRunError) as exc:
        ledger.record_verdict(run.id, role="the_run_itself", passed=True)
    assert exc.value.reason == "invalid_verdict_role"


# ── integrity and durability ─────────────────────────────────────────────────

def test_a_hand_edited_row_is_detected(tmp_path, clock):
    import sqlite3

    path = tmp_path / "runs.db"
    led = WorkRunLedger(path, clock=clock)
    run = led.open_run(_goal())
    assert led.tampered(run.id) is False
    led.close()

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE runs SET approved_by = 'receipt:forged' WHERE id = ?", (run.id,))
        conn.commit()

    reopened = WorkRunLedger(path, clock=clock)
    try:
        assert reopened.tampered(run.id) is True
    finally:
        reopened.close()


def test_a_run_survives_a_restart_with_its_steps_and_budget(tmp_path, clock):
    path = tmp_path / "runs.db"
    led = WorkRunLedger(path, clock=clock)
    run = led.open_run(_goal(), budget=Budget(max_steps=5))
    led.record_step(run.id, kind="a", summary="before the reboot", outcome="ok", task_id=3)
    led.close()

    reopened = WorkRunLedger(path, clock=clock)
    try:
        assert reopened.get(run.id).steps_used == 1
        assert reopened.budget_state(run.id)["steps_left"] == 4
        assert [s.summary for s in reopened.steps(run.id)] == ["before the reboot"]
        reopened.record_step(run.id, kind="a", summary="after", outcome="ok", task_id=4)
        assert reopened.get(run.id).steps_used == 2
    finally:
        reopened.close()


def test_list_runs_can_show_only_what_is_still_live(ledger):
    live = ledger.open_run(_goal(goal_id="live"))
    done = ledger.open_run(_goal(goal_id="done"))
    ledger.request_stop(done.id)
    ledger.settle_stop(done.id)
    assert [r.id for r in ledger.list_runs(active_only=True)] == [live.id]
    assert {r.id for r in ledger.list_runs()} == {live.id, done.id}


def test_unknown_runs_are_refused_by_name(ledger):
    for call in (
        lambda: ledger.budget_state("nope"),
        lambda: ledger.record_step("nope", kind="a", summary="x", outcome="ok"),
        lambda: ledger.request_stop("nope"),
        lambda: ledger.settle_stop("nope"),
        lambda: ledger.resume("nope"),
        lambda: ledger.record_verdict("nope", role="judge", passed=False),
        lambda: ledger.snapshot("nope"),
    ):
        with pytest.raises(WorkRunError) as exc:
            call()
        assert exc.value.reason == "unknown_run"
    assert ledger.get("nope") is None
    assert ledger.tampered("nope") is False
