"""Durable HITL — reading the owner's answer back into a run that is waiting on it.

A run that needs something privileged queues a durable task and blocks. Without
this reconciler the task gets approved in the morning and the run stays blocked
forever. So the tests here are about the ways an answer can be *invented*:

  · silence is never a yes — an undecided task leaves the run blocked, and no
    amount of waiting changes that;
  · a vanished task is not an approval, it is a lost ask that must be visible;
  · the decision is re-read from the task each time, never cached;
  · the same answer applied twice must not resume a run twice;
  · a stop outranks an answer;
  · who decided is recorded, so a brief can say "5 of 9 were auto-approved".

Hermetic: an on-disk ledger under tmp_path, an injected clock, and a fake task
reader — no queue, no worker, no sleeping.
"""

from __future__ import annotations

import types

import pytest

from agents.core.autonomy.pending_requests import (
    AskOutcome,
    PendingRequests,
    SweepReport,
    classify,
    machine_share,
    waiting_summary,
)
from agents.core.autonomy.work_runs import WorkRunError, WorkRunLedger


class _Clock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


def _goal(goal_id: str = "g1"):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="ship the thing",
        approved_by=types.SimpleNamespace(key="owner:accept:7"),
        deadline_at=0.0,
    )


def _task(status="approved", decision="accept", decided_by="owner", task_id=11):
    return types.SimpleNamespace(
        id=task_id, status=status, decision=decision, decided_by=decided_by
    )


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def ledger(tmp_path, clock):
    store = WorkRunLedger(tmp_path / "runs.db", clock=clock)
    yield store
    store.close()


@pytest.fixture
def blocked(ledger):
    """A run blocked on one outstanding ask carrying durable task 11."""
    run = ledger.open_run(_goal())
    step = ledger.record_step(
        run.id, kind="writeback", summary="update the doc", outcome="queued", task_id=11
    )
    assert ledger.get(run.id).status == "blocked"
    return run, step


def _reconciler(ledger, tasks):
    """``tasks`` maps task_id -> task (or None for 'gone')."""
    return PendingRequests(ledger, read_task=lambda tid: tasks.get(tid))


# ── silence is never a yes ───────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["proposed", "blocked", "deferred"])
def test_an_undecided_task_leaves_the_run_blocked(ledger, blocked, status):
    """This is the rule the whole module exists to protect."""
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(status=status, decision=None)}).reconcile(run.id)
    assert result.resumed is False
    assert result.still_waiting == 1
    assert ledger.get(run.id).status == "blocked"


def test_waiting_does_not_expire_into_an_approval(ledger, blocked, clock):
    """Time passing is not a decision. Sweeping all night changes nothing."""
    run, _ = blocked
    reconciler = _reconciler(ledger, {11: _task(status="proposed", decision=None)})
    for _ in range(20):
        clock.tick(3_600.0)
        assert reconciler.reconcile(run.id).resumed is False
    assert ledger.get(run.id).status == "blocked"
    assert len(ledger.outstanding_asks(run.id)) == 1


def test_a_task_that_cannot_be_read_keeps_waiting(ledger, blocked):
    """A queue that cannot be read is not a queue that said yes."""
    run, _ = blocked

    def _boom(_task_id):
        raise RuntimeError("database is locked")

    result = PendingRequests(ledger, read_task=_boom).reconcile(run.id)
    assert result.still_waiting == 1
    assert ledger.get(run.id).status == "blocked"


def test_a_task_with_no_readable_status_keeps_waiting(ledger, blocked):
    run, _ = blocked
    result = _reconciler(ledger, {11: types.SimpleNamespace(id=11)}).reconcile(run.id)
    assert result.outcomes[0].resolution == "waiting"
    assert ledger.get(run.id).status == "blocked"


# ── a vanished task is not an approval ───────────────────────────────────────

def test_a_gone_task_is_lost_not_approved(ledger, blocked):
    """The single most dangerous line this could have had is "probably fine"."""
    run, _ = blocked
    result = _reconciler(ledger, {}).reconcile(run.id)
    assert result.outcomes[0].resolution == "lost"
    assert ledger.steps(run.id)[0].outcome == "failed"


def test_a_lost_ask_still_lets_the_run_move_on(ledger, blocked):
    """It is answered — badly — so the run un-blocks and the failure is visible
    to the supervisor's repeat-failure rule rather than hanging until dawn."""
    run, _ = blocked
    result = _reconciler(ledger, {}).reconcile(run.id)
    assert result.resumed is True
    assert ledger.get(run.id).status == "working"


def test_a_queued_step_with_no_task_id_is_lost(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="writeback", summary="x", outcome="queued")
    result = _reconciler(ledger, {}).reconcile(run.id)
    assert result.outcomes[0].resolution == "lost"
    assert "no durable task" in result.outcomes[0].detail


# ── answers ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["approved", "running", "done"])
def test_an_approved_task_resumes_the_run(ledger, blocked, status):
    """A task can be decided AND executed between two sweeps; missing that would
    leave the run blocked on work that already happened."""
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(status=status)}).reconcile(run.id)
    assert result.resumed is True
    assert ledger.get(run.id).status == "working"
    assert ledger.steps(run.id)[0].outcome == "ok"


@pytest.mark.parametrize("status", ["rejected", "failed", "quarantined"])
def test_a_rejection_is_an_answer(ledger, blocked, status):
    """It closes the ask and lets the run try something else; the planner's
    refusal fingerprint is what stops it proposing the same thing again."""
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(status=status, decision="reject")}).reconcile(run.id)
    assert result.outcomes[0].resolution == "rejected"
    assert result.resumed is True
    assert ledger.steps(run.id)[0].outcome == "refused"


def test_resolving_never_spends_a_second_step_of_budget(ledger, blocked):
    """The budget was spent when the action was arranged. Charging it again would
    report the run as busier than it was."""
    run, _ = blocked
    before = ledger.budget_state(run.id)["steps_used"]
    _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert ledger.budget_state(run.id)["steps_used"] == before
    assert len(ledger.steps(run.id)) == 1  # rewritten in place, not appended


def test_the_step_keeps_its_sequence_number(ledger, blocked):
    run, step = blocked
    _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert ledger.steps(run.id)[0].seq == step.seq


def test_the_reason_is_recorded_on_the_step(ledger, blocked):
    run, _ = blocked
    _reconciler(ledger, {11: _task()}).reconcile(run.id)
    detail = ledger.steps(run.id)[0].detail
    assert detail["resolution"] == "approved"
    assert detail["decided_by"] == "owner"
    assert detail["by_machine"] is False


# ── mixed asks ───────────────────────────────────────────────────────────────

def test_one_unanswered_ask_holds_the_whole_run(ledger):
    """Resuming with an ask still open would run the night on half an answer."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="a", outcome="queued", task_id=11)
    ledger.record_step(run.id, kind="b", summary="b", outcome="queued", task_id=12)
    tasks = {11: _task(task_id=11), 12: _task(status="proposed", decision=None, task_id=12)}
    result = _reconciler(ledger, tasks).reconcile(run.id)
    assert result.answered == 1
    assert result.still_waiting == 1
    assert result.resumed is False
    assert ledger.get(run.id).status == "blocked"


def test_the_answered_ask_is_still_closed_while_the_other_waits(ledger):
    """Closing what IS answered means the next sweep has less to re-read, and the
    record shows when each answer actually landed."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="a", outcome="queued", task_id=11)
    ledger.record_step(run.id, kind="b", summary="b", outcome="queued", task_id=12)
    tasks = {11: _task(task_id=11), 12: _task(status="proposed", decision=None, task_id=12)}
    _reconciler(ledger, tasks).reconcile(run.id)
    assert len(ledger.outstanding_asks(run.id)) == 1


def test_the_run_resumes_once_the_last_answer_lands(ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="a", summary="a", outcome="queued", task_id=11)
    ledger.record_step(run.id, kind="b", summary="b", outcome="queued", task_id=12)
    tasks = {11: _task(task_id=11), 12: _task(status="proposed", decision=None, task_id=12)}
    reconciler = _reconciler(ledger, tasks)
    reconciler.reconcile(run.id)
    tasks[12] = _task(task_id=12)  # the owner answers the second one
    assert reconciler.reconcile(run.id).resumed is True
    assert ledger.get(run.id).status == "working"


# ── idempotence ──────────────────────────────────────────────────────────────

def test_reconciling_twice_does_not_resume_twice(ledger, blocked):
    """A decision that can be applied twice is one that can unblock a run twice."""
    run, _ = blocked
    reconciler = _reconciler(ledger, {11: _task()})
    assert reconciler.reconcile(run.id).resumed is True
    second = reconciler.reconcile(run.id)
    assert second.resumed is False
    assert "not blocked" in second.note
    assert len(ledger.steps(run.id)) == 1


def test_the_ledger_refuses_to_resolve_a_step_twice(ledger, blocked):
    run, step = blocked
    ledger.resolve_step(run.id, step.seq, outcome="ok")
    with pytest.raises(WorkRunError) as exc:
        ledger.resolve_step(run.id, step.seq, outcome="refused")
    assert exc.value.reason == "step_not_outstanding"


def test_a_resolution_outcome_must_be_a_real_one(ledger, blocked):
    run, step = blocked
    for bad in ("queued", "approved", ""):
        with pytest.raises(WorkRunError):
            ledger.resolve_step(run.id, step.seq, outcome=bad)


def test_resolving_an_unknown_step_is_refused(ledger, blocked):
    run, _ = blocked
    with pytest.raises(WorkRunError) as exc:
        ledger.resolve_step(run.id, 9999, outcome="ok")
    assert exc.value.reason == "unknown_step"


# ── a stop outranks an answer ────────────────────────────────────────────────

def test_the_ledger_itself_refuses_to_resume_a_stopping_run(ledger, blocked):
    """This is the layer the invariant is actually enforced at: even a caller that
    skipped every check in the reconciler cannot restart a run that is stopping."""
    run, _ = blocked
    ledger.request_stop(run.id, reason="owner")
    with pytest.raises(WorkRunError) as exc:
        ledger.resume(run.id)
    assert exc.value.reason == "run_not_blocked"


def test_an_answer_does_not_restart_a_stopping_run(ledger, blocked):
    """The reconciler says so in its own words rather than relying on the generic
    "not blocked" branch — a reader who sees a stopping run with a fresh answer
    on it should not have to work out why nothing happened."""
    run, _ = blocked
    ledger.request_stop(run.id, reason="owner")
    result = _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert result.resumed is False
    assert result.note == "the run is stopping; an answer does not restart it"
    assert ledger.get(run.id).status == "stopping"


def test_a_stopping_run_still_records_what_the_answer_was(ledger, blocked):
    """The run does not move, but the record should say what came back."""
    run, _ = blocked
    ledger.request_stop(run.id, reason="owner")
    _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert ledger.steps(run.id)[0].outcome == "ok"


def test_a_terminal_run_is_never_reopened(ledger, blocked):
    run, _ = blocked
    ledger.request_stop(run.id, reason="owner")
    ledger.settle_stop(run.id)
    result = _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert result.resumed is False
    assert "already stopped" in result.note
    assert ledger.get(run.id).status == "stopped"


def test_blocked_with_nothing_outstanding_is_not_a_licence_to_proceed(ledger, blocked):
    """Resuming here would be inventing the ask that unblocked it."""
    run, step = blocked
    ledger.resolve_step(run.id, step.seq, outcome="ok")  # closed without resuming
    result = _reconciler(ledger, {}).reconcile(run.id)
    assert result.resumed is False
    assert "nothing here can unblock it" in result.note
    assert ledger.get(run.id).status == "blocked"


def test_an_unknown_run_is_reported_not_raised(ledger):
    assert _reconciler(ledger, {}).reconcile("nope").note == "unknown run"


# ── who decided ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("decider", ["policy", "worker", "kernel", "auto", ""])
def test_a_policy_approval_is_recorded_as_a_machine_decision(ledger, blocked, decider):
    """A run may legitimately be unblocked by policy — the owner authorised the
    goal. That is exactly why the split has to be visible."""
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(decided_by=decider)}).reconcile(run.id)
    assert result.resumed is True
    assert result.outcomes[0].by_machine is True
    assert ledger.steps(run.id)[0].detail["by_machine"] is True


def test_the_brief_can_say_how_many_a_person_actually_decided(ledger):
    """"You approved nine things" when the owner approved one is the lie."""
    run = ledger.open_run(_goal())
    for i in (11, 12, 13):
        ledger.record_step(run.id, kind=f"k{i}", summary="s", outcome="queued", task_id=i)
    tasks = {
        11: _task(task_id=11, decided_by="owner"),
        12: _task(task_id=12, decided_by="policy"),
        13: _task(task_id=13, decided_by="policy"),
    }
    result = _reconciler(ledger, tasks).reconcile(run.id)
    assert machine_share(SweepReport((result,))) == {
        "answered": 3, "by_machine": 2, "by_person": 1
    }


def test_machine_share_ignores_the_ones_still_waiting(ledger, blocked):
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(status="proposed", decision=None)}).reconcile(run.id)
    assert machine_share(SweepReport((result,)))["answered"] == 0


# ── the sweep ────────────────────────────────────────────────────────────────

def test_the_sweep_only_touches_runs_that_are_waiting(ledger):
    blocked_run = ledger.open_run(_goal("g1"))
    ledger.record_step(
        blocked_run.id, kind="a", summary="a", outcome="queued", task_id=11
    )
    working = ledger.open_run(_goal("g2"))
    ledger.record_step(working.id, kind="a", summary="a", outcome="ok")

    report = _reconciler(ledger, {11: _task()}).sweep()
    assert [r.run_id for r in report.results] == [blocked_run.id]
    assert report.resumed == 1


def test_one_bad_run_does_not_stop_the_sweep(ledger):
    good = ledger.open_run(_goal("g1"))
    ledger.record_step(good.id, kind="a", summary="a", outcome="queued", task_id=11)
    bad = ledger.open_run(_goal("g2"))
    ledger.record_step(bad.id, kind="a", summary="a", outcome="queued", task_id=12)

    reconciler = _reconciler(ledger, {11: _task(), 12: _task(task_id=12)})
    original = reconciler.reconcile

    def _explode(run_id):
        if run_id == bad.id:
            raise RuntimeError("boom")
        return original(run_id)

    reconciler.reconcile = _explode  # type: ignore[method-assign]
    report = reconciler.sweep()
    assert report.resumed == 1
    assert any(bad.id in err for err in report.errors)


def test_a_sweep_over_nothing_says_so(ledger):
    assert waiting_summary(_reconciler(ledger, {}).sweep()) == "no run is waiting on a decision"


# ── the sentence the brief prints ────────────────────────────────────────────

def test_still_waiting_is_said_in_words(ledger, blocked):
    """"Still waiting on you, since 11pm" is what a morning report exists to say."""
    run, _ = blocked
    result = _reconciler(ledger, {11: _task(status="proposed", decision=None)}).reconcile(run.id)
    assert "still waiting on you" in waiting_summary(result)


def test_resumed_is_said_in_words(ledger, blocked):
    run, _ = blocked
    result = _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert "resumed" in waiting_summary(result)


def test_answered_but_unable_to_resume_is_not_reported_as_resumed(ledger, blocked):
    run, _ = blocked
    ledger.request_stop(run.id, reason="owner")
    result = _reconciler(ledger, {11: _task()}).reconcile(run.id)
    assert waiting_summary(result) == "every ask is answered; no run could resume"


# ── classify, on its own ─────────────────────────────────────────────────────

def test_classify_never_reads_absence_as_approval():
    assert classify(None)[0] == "lost"
    assert classify(types.SimpleNamespace(status="unheard-of"))[0] == "waiting"


def test_an_ask_outcome_serialises_flat():
    payload = AskOutcome("r", 1, 11, "approved", "ok", decided_by="owner").as_dict()
    assert payload["resolution"] == "approved"
    assert payload["by_machine"] is False


# ── durability ───────────────────────────────────────────────────────────────

def test_an_outstanding_ask_survives_a_restart(tmp_path, clock):
    """In-memory would mean a reboot loses every outstanding ask and the run
    blocks until someone notices — which is the failure this is named for."""
    path = tmp_path / "runs.db"
    first = WorkRunLedger(path, clock=clock)
    run = first.open_run(_goal())
    first.record_step(run.id, kind="a", summary="a", outcome="queued", task_id=11)
    first.close()

    reopened = WorkRunLedger(path, clock=clock)
    try:
        assert [s.task_id for s in reopened.outstanding_asks(run.id)] == [11]
        result = _reconciler(reopened, {11: _task()}).reconcile(run.id)
        assert result.resumed is True
    finally:
        reopened.close()


# ── the decision reconciles the run the moment it lands ──────────────────────

class _Worker:
    """``AutonomyWorker._reconcile_waiting_run``, lifted off the worker without
    its queue, policy, executor or kernel."""

    def __init__(self, ledger, tasks):
        from agents.core.autonomy.worker import AutonomyWorker

        self.work_run_ledger = ledger
        self.queue = types.SimpleNamespace(get=lambda tid: tasks.get(tid))
        self._call = AutonomyWorker._reconcile_waiting_run.__get__(self)

    def decide(self, task):
        self._call(task)


def test_a_decision_unblocks_the_waiting_run_immediately(ledger, blocked, monkeypatch):
    """The difference between "Nerva carried on the instant you tapped approve"
    and "some time in the next twenty minutes"."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    run, _ = blocked
    _Worker(ledger, {11: _task()}).decide(_task())
    assert ledger.get(run.id).status == "working"
    assert ledger.steps(run.id)[0].outcome == "ok"


def test_the_hook_does_nothing_with_company_mode_off(ledger, blocked, monkeypatch):
    """Default-off means a decision on an unrelated product does not quietly
    drive a work run."""
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    run, _ = blocked
    _Worker(ledger, {11: _task()}).decide(_task())
    assert ledger.get(run.id).status == "blocked"


def test_the_hook_does_nothing_without_a_ledger(monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    _Worker(None, {}).decide(_task())  # must not raise


def test_the_hook_ignores_a_task_no_run_is_waiting_on(ledger, blocked, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    run, _ = blocked
    _Worker(ledger, {99: _task(task_id=99)}).decide(_task(task_id=99))
    assert ledger.get(run.id).status == "blocked"


def test_a_broken_ledger_never_fails_the_decision(blocked, monkeypatch):
    """A decision that already landed must not be undone by a bookkeeping error."""
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")

    class _Broken:
        def run_waiting_on(self, _task_id):
            raise RuntimeError("database is locked")

    _Worker(_Broken(), {}).decide(_task())  # must not raise


def test_run_waiting_on_only_matches_an_outstanding_ask(ledger, blocked):
    run, step = blocked
    assert ledger.run_waiting_on(11) == run.id
    ledger.resolve_step(run.id, step.seq, outcome="ok")
    assert ledger.run_waiting_on(11) is None


@pytest.mark.parametrize("bad", [0, -1, None, True, "11"])
def test_run_waiting_on_refuses_a_task_id_that_is_not_one(ledger, bad):
    assert ledger.run_waiting_on(bad) is None
