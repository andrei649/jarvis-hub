"""H464 — park a work run on real async work instead of poking it.

A run waiting on a build, a deploy or a cooldown used to burn a step of budget on
every "is it done yet?" tick. A barrier parks it instead: wait on a registered
process until it exits, on a trigger (a durable task, an inbound webhook) until it
fires, or until a wall-clock time. What these tests pin is that a barrier can only
ever SUPPRESS work, never wedge a run or grant anything:

  · every barrier is bounded — by its own wait, the run's deadline and the run's
    wall-clock budget — and the bound clears it;
  · anything the check cannot prove clears it: a dead or reused pid, another boot
    or pid namespace, a zombie, a fired or vanished trigger, a probe that raises;
  · only a pid the hub registered for THIS run, and only a task this run queued,
    can be waited on — an arbitrary host pid or someone else's task is refused;
  · a blocked, stopping, finished or spent run cannot be parked at all.

Hermetic: an in-memory ledger, a hand-driven clock, and fakes for the process
probe, the task queue and the webhook store. No process is spawned.
"""

from __future__ import annotations

import os
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.run_barriers import (
    BARRIER_KINDS,
    DEFAULT_WAIT_SECONDS,
    IN_FLIGHT_TASK_STATUSES,
    MAX_BARRIER_SECONDS,
    MAX_BARRIERS_PER_RUN,
    MAX_PROCS_PER_RUN,
    RunBarriers,
    RunBarriersError,
    default_pid_probe,
    describe,
)
from agents.core.autonomy.work_runs import Budget, WorkRunError, WorkRunLedger


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _goal(goal_id: str = "g-1", deadline: float = 0.0):
    return types.SimpleNamespace(
        goal_id=goal_id, title="Ship the release",
        approved_by="receipt:owner-accepted-1", deadline_at=deadline,
    )


class _Probe:
    """Stands in for the pid probe: answers whatever the test sets."""

    def __init__(self, answer: str = "alive") -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self, _barrier) -> str:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class _Tasks:
    """A task queue reader: id -> status, or missing."""

    def __init__(self, **statuses) -> None:
        self.statuses = {int(k.removeprefix("t")): v for k, v in statuses.items()}

    def __call__(self, task_id: int):
        status = self.statuses.get(int(task_id))
        return None if status is None else types.SimpleNamespace(id=task_id, status=status)


class _Hooks:
    """The webhook store, as far as a barrier reads it."""

    def __init__(self, **hooks) -> None:
        self.hooks = {k: dict(v) for k, v in hooks.items()}

    def get(self, hook_id):
        rec = self.hooks.get(hook_id)
        return dict(rec) if rec else None

    @staticmethod
    def is_enabled(rec):
        return rec.get("enabled", True) is True


def _identity(pid: int):
    return {"start": "111", "ns": "ns-1", "boot": "boot-1"}


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def ledger(clock):
    led = WorkRunLedger(":memory:", clock=clock)
    yield led
    led.close()


def _barriers(ledger, clock, *, probe=None, tasks=None, hooks=None, identity=_identity):
    return RunBarriers(
        ledger, clock=clock, pid_probe=probe or _Probe(),
        read_task=tasks, hooks=(lambda: hooks) if hooks is not None else None,
        proc_identity=identity,
    )


def _events(ledger, run_id):
    return [(e["kind"], e["detail"]) for e in ledger.events(run_id)]


# ── the vocabulary ───────────────────────────────────────────────────────────

def test_the_three_barrier_kinds_are_the_ones_hermes_names():
    assert BARRIER_KINDS == ("pid", "trigger", "deadline")
    assert issubclass(RunBarriersError, WorkRunError)


# ── deadline ─────────────────────────────────────────────────────────────────

def test_a_deadline_barrier_parks_the_run_until_the_time_passes(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    state = barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 600}},
                             source="planner")
    assert state["kind"] == "deadline" and state["target"] == 1_600.0
    assert barriers.active(run.id) is True
    clock.advance(599)
    assert barriers.active(run.id) is True
    clock.advance(1)
    assert barriers.active(run.id) is False
    assert ledger.get(run.id).barrier is None
    assert _events(ledger, run.id)[0][0] == "barrier.cleared"
    assert _events(ledger, run.id)[0][1]["why"] == "elapsed"
    assert _events(ledger, run.id)[0][1]["by"] == "check"


def test_a_deadline_in_the_past_or_beyond_seven_days_is_refused(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    for target in (clock.now, clock.now - 5, clock.now + MAX_BARRIER_SECONDS + 1,
                   {"in_seconds": 0}, {"in_seconds": -3}, float("nan"), True, "soon"):
        with pytest.raises(RunBarriersError) as exc:
            barriers.request(run.id, {"kind": "deadline", "target": target}, source="planner")
        assert exc.value.reason == "deadline_out_of_bounds", target
    assert ledger.get(run.id).barrier is None
    # exactly seven days is the furthest a barrier may reach
    barriers.request(run.id, {"kind": "deadline", "target": clock.now + MAX_BARRIER_SECONDS},
                     source="planner")


def test_a_deadline_beyond_the_run_deadline_is_capped_not_refused(ledger, clock):
    run = ledger.open_run(_goal(deadline=clock.now + 300))
    barriers = _barriers(ledger, clock)
    state = barriers.request(run.id, {"kind": "deadline", "target": clock.now + 3_600},
                             source="planner")
    assert state["cap_at"] == run.deadline_at
    clock.advance(300)
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "cap"


def test_every_barrier_is_capped_by_the_wall_clock_budget(ledger, clock):
    run = ledger.open_run(_goal(), budget=Budget(max_seconds=120))
    state = _barriers(ledger, clock).request(
        run.id, {"kind": "deadline", "target": clock.now + 3_600}, source="planner")
    assert state["cap_at"] == run.started_at + 120


# ── the cap is the EFFECTIVE budget: H487's approval-wait credit counts (H464b C1) ──

@pytest.fixture
def credited(tmp_path, monkeypatch):
    """A real queue and a ledger on one clock, as H487's ``world`` builds them: the
    approval-wait credit is only ever proven from durable queue facts."""
    clock = [1_800_000_000.0]
    monkeypatch.setattr("agents.core.autonomy.queue._now",
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr("agents.core.autonomy.queue._approval_now",
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    q = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    led = WorkRunLedger(tmp_path / "runs.db", clock=lambda: clock[0])
    yield clock, q, led
    led.close()
    q.close()


def _run_after_a_credited_wait(clock, q, led):
    """A 30 s budget, then a 100 s wait on the owner's decision: all of it credited."""
    run = led.open_run(_goal("credited"), budget=Budget(max_seconds=30))
    led.bind_approval_task_reader(q.get)
    tid = q.enqueue("jarvis", "test", "Ask", {})
    q.transition(tid, TaskStatus.BLOCKED)
    led.record_step(run.id, kind="ask", summary="Ask", outcome="queued", task_id=tid)
    clock[0] += 100
    q.transition(tid, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                 human_reason=None)
    assert PendingRequests(led, read_task=q.get).reconcile(run.id).resumed
    state = led.budget_state(run.id)
    assert state["seconds_left"] == 30 and state["exceeded"] is None
    return run


def test_a_barrier_cap_counts_the_approval_wait_credit(credited):
    """The budget says 30 s are left; the barrier must agree. Capping by the raw
    wall clock (started_at + 30, long past) refused this as ``no_time_left``."""
    clock, q, led = credited
    run = _run_after_a_credited_wait(clock, q, led)
    barriers = RunBarriers(led, read_task=q.get)
    state = barriers.request(
        run.id, {"kind": "deadline", "target": {"in_seconds": 20}}, source="planner")
    # a deadline's own wait is its target; the cap is the 30 s the budget has left
    assert state["target"] == clock[0] + 20
    assert state["cap_at"] == clock[0] + 30
    clock[0] += 20
    assert barriers.active(run.id) is False
    assert led.events(run.id)[0]["detail"]["why"] == "elapsed"


def test_a_long_wait_is_cut_to_the_credited_budget_left(credited):
    clock, q, led = credited
    run = _run_after_a_credited_wait(clock, q, led)
    state = RunBarriers(led, read_task=q.get).request(
        run.id, {"kind": "deadline", "target": {"in_seconds": 3_600}}, source="planner")
    assert state["cap_at"] == clock[0] + 30
    assert state["cap_at"] > run.started_at + 30     # the raw cap is in the past
    barriers = RunBarriers(led, read_task=q.get)
    clock[0] += 29
    assert barriers.active(run.id) is True
    clock[0] += 1
    assert barriers.active(run.id) is False
    assert led.events(run.id)[0]["detail"]["why"] == "cap"


# ── what may be parked at all ────────────────────────────────────────────────

def test_a_barrier_cannot_be_set_on_a_blocked_stopping_terminal_or_spent_run(ledger, clock):
    barriers = _barriers(ledger, clock)
    want = {"kind": "deadline", "target": {"in_seconds": 60}}

    blocked = ledger.open_run(_goal("blocked"))
    ledger.record_step(blocked.id, kind="ask", summary="ask", outcome="queued", task_id=1)
    stopping = ledger.open_run(_goal("stopping"))
    ledger.record_step(stopping.id, kind="a", summary="a", outcome="ok", task_id=2)
    ledger.request_stop(stopping.id)
    stopped = ledger.open_run(_goal("stopped"))
    ledger.request_stop(stopped.id)
    for run in (blocked, stopping, stopped):
        with pytest.raises(RunBarriersError) as exc:
            barriers.request(run.id, want, source="planner")
        assert exc.value.reason == "run_not_parkable"

    spent = ledger.open_run(_goal("spent"), budget=Budget(max_steps=1))
    ledger.record_step(spent.id, kind="a", summary="a", outcome="ok", task_id=3)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(spent.id, want, source="planner")
    assert exc.value.reason == "budget_spent"

    with pytest.raises(WorkRunError) as exc:
        barriers.request("nope", want, source="planner")
    assert exc.value.reason == "unknown_run"


def test_a_malformed_request_is_refused_by_name(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    for raw, reason in (
        ("deadline", "malformed_barrier"),
        ({"kind": "sleep", "target": 5}, "unknown_kind"),
        ({"kind": "deadline", "target": {"in_seconds": 60}, "max_wait": 0}, "invalid_max_wait"),
        ({"kind": "trigger", "target": "task:1", "max_wait": MAX_BARRIER_SECONDS + 1},
         "invalid_max_wait"),
    ):
        with pytest.raises(RunBarriersError) as exc:
            barriers.request(run.id, raw, source="planner")
        assert exc.value.reason == reason
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}},
                         source="a-model")
    assert exc.value.reason == "invalid_source"


def test_the_reason_is_bounded_and_stripped_of_control_characters(ledger, clock):
    run = ledger.open_run(_goal())
    state = _barriers(ledger, clock).request(
        run.id,
        {"kind": "deadline", "target": {"in_seconds": 60}, "reason": "wait\x1b[31m" + "x" * 500},
        source="planner",
    )
    assert "\x1b" not in state["reason"] and len(state["reason"]) <= 200
    default = _barriers(ledger, clock).request(
        run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="planner")
    assert default["reason"] == "waiting on deadline"


def test_the_number_of_barriers_per_run_is_bounded(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    for _ in range(MAX_BARRIERS_PER_RUN):
        barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}},
                         source="planner")
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}},
                         source="planner")
    assert exc.value.reason == "barrier_limit"


# ── pid ──────────────────────────────────────────────────────────────────────

def test_an_unregistered_host_pid_is_refused(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert exc.value.reason == "pid_not_registered"

    # a pid registered for ANOTHER run is not this run's to wait on
    other = ledger.open_run(_goal("other"))
    barriers.register_process(other.id, 4242, label="npm run build")
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert exc.value.reason == "pid_not_registered"
    for junk in ("4242", True, None, 4242.0):
        with pytest.raises(RunBarriersError):
            barriers.request(run.id, {"kind": "pid", "target": junk}, source="planner")


def test_registration_refuses_init_the_hub_itself_and_a_dead_pid(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    for pid in (0, 1, -5, os.getpid(), os.getppid()):
        with pytest.raises(RunBarriersError) as exc:
            barriers.register_process(run.id, pid)
        assert exc.value.reason == "pid_forbidden", pid
    dead = _barriers(ledger, clock, identity=lambda _pid: None)
    with pytest.raises(RunBarriersError) as exc:
        dead.register_process(run.id, 4242)
    assert exc.value.reason == "pid_not_running"
    with pytest.raises(WorkRunError):
        barriers.register_process("nope", 4242)
    assert ledger.processes(run.id) == []


def test_the_number_of_registered_processes_is_bounded(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    for pid in range(1000, 1000 + MAX_PROCS_PER_RUN):
        barriers.register_process(run.id, pid)
    with pytest.raises(RunBarriersError) as exc:
        barriers.register_process(run.id, 5000)
    assert exc.value.reason == "proc_limit"


def test_a_registered_pid_parks_until_it_exits(ledger, clock):
    run = ledger.open_run(_goal())
    probe = _Probe("alive")
    barriers = _barriers(ledger, clock, probe=probe)
    barriers.register_process(run.id, 4242, label="npm run build")
    state = barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    assert state["waiting_on"] == "process 4242 (npm run build) to exit"
    record = ledger.get(run.id).barrier
    assert (record["start"], record["ns"], record["boot"]) == ("111", "ns-1", "boot-1")
    assert barriers.active(run.id) is True
    probe.answer = "dead"
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "exited"


def test_a_pid_already_gone_cannot_be_waited_on(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock, probe=_Probe("dead"))
    barriers.register_process(run.id, 4242)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    assert exc.value.reason == "pid_not_running"


@pytest.mark.parametrize("answer,why", [
    ("reused", "pid_reused"), ("ns", "ns_mismatch"), ("dead", "exited"), ("??", "probe_error"),
])
def test_anything_the_pid_probe_cannot_prove_clears(ledger, clock, answer, why):
    run = ledger.open_run(_goal())
    probe = _Probe("alive")
    barriers = _barriers(ledger, clock, probe=probe)
    barriers.register_process(run.id, 4242)
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    probe.answer = answer
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == why


def test_a_probe_that_raises_clears_rather_than_wedging(ledger, clock):
    run = ledger.open_run(_goal())
    probe = _Probe("alive")
    barriers = _barriers(ledger, clock, probe=probe)
    barriers.register_process(run.id, 4242)
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    probe.answer = OSError("proc went away")
    assert barriers.active(run.id) is False
    assert ledger.get(run.id).barrier is None
    assert _events(ledger, run.id)[0][1]["why"] == "probe_error"


def test_every_barrier_is_capped_and_the_cap_clears_it(ledger, clock):
    """A process that never exits must not park the run forever."""
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock, probe=_Probe("alive"))
    barriers.register_process(run.id, 4242)
    state = barriers.request(run.id, {"kind": "pid", "target": 4242, "max_wait": 900},
                             source="hub")
    assert state["cap_at"] == clock.now + 900
    clock.advance(899)
    assert barriers.active(run.id) is True
    clock.advance(1)
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "cap"


def test_the_default_pid_probe_reads_real_processes():
    """No spawn: the probe is exercised on this test process and on a pid that is
    certainly free."""
    from agents.core import exec_cache

    me = os.getpid()
    live = {"target": me, "start": exec_cache._start_token(me),
            "ns": exec_cache._pid_ns(), "boot": exec_cache._boot_id()}
    # Linux and Windows expose real process identity; macOS/BSD do not.
    if os.name == "nt" or Path("/proc/self/stat").exists():
        assert live["start"]
    if live["start"]:
        assert default_pid_probe(live) == "alive"
        assert default_pid_probe({**live, "start": "not-the-same"}) == "reused"
    else:
        assert default_pid_probe(live) == "unknown"
    if live["boot"]:
        assert default_pid_probe({**live, "boot": "another-boot"}) == "ns"
    if live["ns"]:
        assert default_pid_probe({**live, "ns": "another-ns"}) == "ns"
    assert default_pid_probe({**live, "target": 2 ** 22 + 12_345}) == "dead"


def test_the_default_pid_probe_reads_a_zombie_as_dead(monkeypatch):
    from agents.core.autonomy import run_barriers

    monkeypatch.setattr(run_barriers, "_proc_state", lambda _pid: "Z")
    me = os.getpid()
    assert default_pid_probe({"target": me, "start": "", "ns": "", "boot": ""}) == "dead"


# ── trigger ──────────────────────────────────────────────────────────────────

def _run_with_task(ledger, task_id: int = 412):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="build", summary="start the build", outcome="queued",
                       task_id=task_id)
    ledger.resolve_step(run.id, 1, outcome="ok")
    ledger.resume(run.id)
    return run


def test_a_task_trigger_fires_when_the_task_is_terminal(ledger, clock):
    run = _run_with_task(ledger)
    tasks = _Tasks(t412="running")
    barriers = _barriers(ledger, clock, tasks=tasks)
    state = barriers.request(run.id, {"kind": "trigger", "target": "task:412"}, source="planner")
    assert state["waiting_on"] == "task 412 to finish"
    assert ledger.get(run.id).barrier["marker"] == {"status": "running"}
    assert barriers.active(run.id) is True
    tasks.statuses[412] = "done"
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "fired"


def test_a_vanished_task_clears_the_barrier(ledger, clock):
    run = _run_with_task(ledger)
    tasks = _Tasks(t412="approved")
    barriers = _barriers(ledger, clock, tasks=tasks)
    barriers.request(run.id, {"kind": "trigger", "target": "task:412"}, source="planner")
    del tasks.statuses[412]
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "vanished"


def test_a_task_status_enum_is_read_by_its_value(ledger, clock):
    from agents.core.autonomy.queue import TaskStatus

    run = _run_with_task(ledger)
    tasks = _Tasks(t412=TaskStatus.RUNNING)
    barriers = _barriers(ledger, clock, tasks=tasks)
    barriers.request(run.id, {"kind": "trigger", "target": "task:412"}, source="planner")
    tasks.statuses[412] = TaskStatus.DONE
    assert barriers.active(run.id) is False


def test_trigger_ownership_and_registry_are_checked(ledger, clock):
    run = _run_with_task(ledger)
    barriers = _barriers(ledger, clock, tasks=_Tasks(t412="done", t7="running", t9="running"),
                         hooks=_Hooks(ab12cd={"enabled": True, "calls": 0},
                                      off={"enabled": False, "calls": 0}))
    for target, reason in (
        ("task:7", "trigger_not_owned"),     # a real task, but not one this run queued
        ("task:412", "trigger_already_fired"),
        ("hook:zz", "trigger_unknown"),
        ("hook:off", "trigger_unknown"),
        ("foo:1", "unknown_trigger"),
        ("task:abc", "invalid_trigger"),
        ("task:1;drop", "invalid_trigger"),
        (412, "invalid_trigger"),
    ):
        with pytest.raises(RunBarriersError) as exc:
            barriers.request(run.id, {"kind": "trigger", "target": target}, source="planner")
        assert exc.value.reason == reason, target

    ledger.record_step(run.id, kind="build", summary="again", outcome="queued", task_id=9)
    ledger.resolve_step(run.id, 2, outcome="ok")
    ledger.resume(run.id)
    missing = _barriers(ledger, clock, tasks=_Tasks())
    with pytest.raises(RunBarriersError) as exc:
        missing.request(run.id, {"kind": "trigger", "target": "task:9"}, source="planner")
    assert exc.value.reason == "trigger_unknown"
    unwired = _barriers(ledger, clock)
    for target in ("task:9", "hook:ab12cd"):
        with pytest.raises(RunBarriersError) as exc:
            unwired.request(run.id, {"kind": "trigger", "target": target}, source="planner")
        assert exc.value.reason == "trigger_unavailable"


def test_a_hook_trigger_fires_when_called_after_set(ledger, clock):
    run = ledger.open_run(_goal())
    hooks = _Hooks(ab12cd={"enabled": True, "calls": 3, "last_called": 900.0})
    barriers = _barriers(ledger, clock, hooks=hooks)
    state = barriers.request(run.id, {"kind": "trigger", "target": "hook:ab12cd"},
                             source="judge")
    assert state["waiting_on"] == "webhook ab12cd to be called"
    assert ledger.get(run.id).barrier["marker"] == {"calls": 3, "last_called": 900.0}
    assert barriers.active(run.id) is True
    hooks.hooks["ab12cd"]["calls"] = 4
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "fired"


def test_a_disabled_or_deleted_hook_clears_as_vanished(ledger, clock):
    run = ledger.open_run(_goal())
    hooks = _Hooks(ab12cd={"enabled": True, "calls": 0})
    barriers = _barriers(ledger, clock, hooks=hooks)
    barriers.request(run.id, {"kind": "trigger", "target": "hook:ab12cd"}, source="planner")
    hooks.hooks["ab12cd"]["enabled"] = False
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "vanished"


# ── surfaces ─────────────────────────────────────────────────────────────────

def test_state_never_probes(ledger, clock):
    run = ledger.open_run(_goal())
    probe = _Probe("alive")
    barriers = _barriers(ledger, clock, probe=probe)
    barriers.register_process(run.id, 4242)
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    probe.calls = 0
    state = barriers.state(run.id)
    assert probe.calls == 0
    assert set(state) == {"kind", "target", "reason", "set_at", "cap_at", "source", "waiting_on"}
    assert barriers.state(ledger.open_run(_goal("idle")).id) is None


def test_describe_says_what_the_run_waits_on_in_plain_words():
    assert describe({"kind": "trigger", "target": "task:412"}) == "task 412 to finish"
    assert describe({"kind": "trigger", "target": "hook:ab12cd"}) == "webhook ab12cd to be called"
    assert describe({"kind": "pid", "target": 7, "label": ""}) == "process 7 to exit"
    assert describe({"kind": "deadline", "target": 1_000.0, "cap_at": 900.0}).startswith(
        "the clock to reach ")
    assert describe({}) == "a barrier"


def test_background_lists_step_tasks_processes_and_the_barrier_bounded(ledger, clock):
    run = ledger.open_run(_goal())
    for task_id in range(1, 31):
        ledger.record_step(run.id, kind="build", summary=f"step {task_id}", outcome="queued",
                           task_id=task_id)
        ledger.resolve_step(run.id, task_id, outcome="ok")
        ledger.resume(run.id)
    tasks = _Tasks(**{f"t{i}": ("done" if i % 2 else "running") for i in range(1, 31)})
    barriers = _barriers(ledger, clock, tasks=tasks)
    barriers.register_process(run.id, 4242, label="x" * 500)
    barriers.request(run.id, {"kind": "trigger", "target": "task:30"}, source="planner")
    items = barriers.background(run.id)
    assert len(items) == 20
    assert items[0]["kind"] == "barrier" and items[0]["barrier_kind"] == "trigger"
    assert items[1] == {"kind": "process", "pid": 4242, "label": "x" * 120, "alive": True}
    assert items[2] == {"kind": "task", "id": 30, "status": "running", "done": False}
    assert {"kind": "task", "id": 29, "status": "done", "done": True} in items


def test_background_is_empty_for_an_unknown_run(ledger, clock):
    assert _barriers(ledger, clock).background("nope") == []


def test_an_owner_clear_reports_whether_anything_was_cleared(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    cleared, _run = barriers.clear(run.id)
    assert cleared is False
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="planner")
    cleared, after = barriers.clear(run.id)
    assert cleared is True and after.barrier is None
    assert _events(ledger, run.id)[0][1] | {"id": None} == {"id": None, "why": "owner",
                                                            "by": "owner"}
    with pytest.raises(WorkRunError):
        barriers.clear("nope")


def test_a_check_that_errors_reports_not_waiting(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="planner")

    def _boom(*_a, **_k):
        raise RuntimeError("database is locked")

    ledger.clear_barrier = _boom          # even the clear failing must not wedge
    clock.advance(61)
    assert barriers.active(run.id) is False
    ledger.get = _boom
    assert barriers.active(run.id) is False


# ── review round (H464 F1, F3, F4, F6, F8) ───────────────────────────────────

class _Raises:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __call__(self, *_a, **_k):
        raise self.exc

    def get(self, *_a, **_k):
        raise self.exc


def test_a_task_reader_that_raises_is_a_refusal_not_an_escape(ledger, clock):
    """F1: a locked queue db while parking is ``trigger_unavailable``, never a raw
    exception out of ``request`` (which would escape the tick every sweep)."""
    run = _run_with_task(ledger, 7)
    barriers = _barriers(ledger, clock, tasks=_Raises(RuntimeError("database is locked")))
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "trigger", "target": "task:7"}, source="judge")
    assert exc.value.reason == "trigger_unavailable"
    assert ledger.get(run.id).barrier is None


@pytest.mark.parametrize("where", ["build", "get"])
def test_a_webhook_store_that_raises_is_a_refusal_not_an_escape(ledger, clock, where):
    run = ledger.open_run(_goal())
    boom = _Raises(OSError("store unreadable"))
    barriers = RunBarriers(
        ledger, clock=clock, pid_probe=_Probe(), proc_identity=_identity,
        hooks=boom if where == "build" else (lambda: boom),
    )
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "trigger", "target": "hook:ab12cd"}, source="judge")
    assert exc.value.reason == "trigger_unavailable"


def test_a_pid_probe_that_raises_while_parking_is_probe_failed(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock, probe=_Probe(OSError("proc unreadable")))
    barriers.register_process(run.id, 4242)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert exc.value.reason == "probe_failed"


def test_a_hand_edited_hook_record_never_raises(ledger, clock):
    """F6: ``last_called: "2026-09-01"`` in the store is read as nothing, not as a
    ValueError out of ``request`` or out of the check."""
    run = ledger.open_run(_goal())
    hooks = _Hooks(ab12cd={"enabled": True, "calls": "three", "last_called": "2026-09-01"})
    barriers = _barriers(ledger, clock, hooks=hooks)
    barriers.request(run.id, {"kind": "trigger", "target": "hook:ab12cd"}, source="judge")
    assert ledger.get(run.id).barrier["marker"] == {"calls": 0, "last_called": 0.0}
    assert barriers.active(run.id) is True
    hooks.hooks["ab12cd"].update(calls=1, last_called=1_001.0)
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "fired"


@pytest.mark.parametrize("source", ["planner", "judge"])
def test_an_owner_clear_sticks_against_the_same_wait(ledger, clock, source):
    """F3: once the owner lets a run go from a wait, neither the planner nor the
    judge may park it on that same wait again; a different wait is still allowed."""
    run = _run_with_task(ledger, 7)
    ledger.record_step(run.id, kind="build", summary="another", outcome="ok", task_id=8)
    barriers = _barriers(ledger, clock, tasks=_Tasks(t7="running", t8="running"))
    barriers.request(run.id, {"kind": "trigger", "target": "task:7"}, source=source)
    assert barriers.clear(run.id)[0] is True
    for who in ("planner", "judge"):
        with pytest.raises(RunBarriersError) as exc:
            barriers.request(run.id, {"kind": "trigger", "target": "task:7"}, source=who)
        assert exc.value.reason == "owner_cleared"
    assert ledger.get(run.id).barrier is None
    state = barriers.request(run.id, {"kind": "trigger", "target": "task:8"}, source=source)
    assert state["target"] == "task:8"
    # hub code that spawned the work is not a model; the owner's clear binds the models
    barriers.clear(run.id)
    assert barriers.request(run.id, {"kind": "trigger", "target": "task:7"},
                            source="hub")["target"] == "task:7"


def test_an_owner_clear_of_a_clock_wait_refuses_any_clock_wait_after_it(ledger, clock):
    """A deadline's target is re-computed from ``in_seconds`` on every ask, so "the
    same wait" for the clock is any clock wait — else the judge re-parks at once."""
    run = _run_with_task(ledger, 7)
    barriers = _barriers(ledger, clock, tasks=_Tasks(t7="running"))
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 600}}, source="judge")
    barriers.clear(run.id)
    clock.advance(5)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 900}},
                         source="judge")
    assert exc.value.reason == "owner_cleared"
    assert barriers.request(run.id, {"kind": "trigger", "target": "task:7"},
                            source="judge")["kind"] == "trigger"


def test_a_check_clear_does_not_make_a_wait_sticky(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="judge")
    clock.advance(61)
    assert barriers.active(run.id) is False          # cleared by the check, not the owner
    assert barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}},
                            source="judge")["kind"] == "deadline"


def _unprovable(monkeypatch):
    """What macOS/BSD look like to the probe: no /proc, so no start token, no pid
    namespace, no boot id and no process state — only ``kill(pid, 0)``."""
    from agents.core import exec_cache
    from agents.core.autonomy import run_barriers

    monkeypatch.setattr(exec_cache, "_start_token", lambda _pid: "")
    monkeypatch.setattr(exec_cache, "_pid_ns", lambda: "")
    monkeypatch.setattr(exec_cache, "_boot_id", lambda: "")
    monkeypatch.setattr(exec_cache, "_pid_alive", lambda _pid, _start="": True)
    monkeypatch.setattr(run_barriers, "_proc_state", lambda _pid: "")


def test_a_pid_the_probe_cannot_prove_reads_unknown_and_clears(ledger, clock, monkeypatch):
    """F4: off Linux (and off Windows) nothing tells this pid from a reused one or a
    zombie, so the default probe answers ``unknown`` — and unknown clears (I3)."""
    _unprovable(monkeypatch)
    blank = {"target": 4242, "start": "", "ns": "", "boot": ""}
    assert default_pid_probe(blank) == "unknown"
    assert default_pid_probe({**blank, "start": "111"}) == "unknown"   # token unreadable now

    run = ledger.open_run(_goal())

    def _blank_identity(_pid):
        return {"start": "", "ns": "", "boot": ""}

    barriers = RunBarriers(ledger, clock=clock, proc_identity=_blank_identity)  # default probe
    ledger.set_barrier(run.id, {
        "v": 1, "id": "b-mac", "kind": "pid", "target": 4242, "set_at": clock.now,
        "cap_at": clock.now + 3_600, "reason": "build", "source": "hub",
        "start": "", "ns": "", "boot": "", "label": "",
    })
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "probe_error"

    barriers.register_process(run.id, 4242)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="hub")
    assert exc.value.reason == "pid_unprovable"


class _RacingLedger:
    """Runs ``race`` right after RunBarriers.clear has read the run, before its
    compare-and-clear — the window F8 is about."""

    def __init__(self, ledger, race) -> None:
        self._ledger, self._race, self._armed = ledger, race, True

    def get(self, run_id):
        run = self._ledger.get(run_id)
        if self._armed:
            self._armed = False
            self._race()
        return run

    def __getattr__(self, name):
        return getattr(self._ledger, name)


def test_an_owner_clear_reports_what_this_call_did_when_a_new_barrier_raced_in(ledger, clock):
    """F8: the check cleared barrier A and the planner set B between the read and the
    compare-and-clear. The owner's call cleared nothing, and says so — with the run
    still holding B, not "was not waiting on anything"."""
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="judge")
    first = ledger.get(run.id).barrier["id"]

    def _race():
        ledger.clear_barrier(run.id, why="elapsed", by="check", expect_id=first)
        barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 90}},
                         source="planner")

    cleared, after = RunBarriers(_RacingLedger(ledger, _race), clock=clock).clear(run.id)
    assert cleared is False
    assert after.barrier is not None and after.barrier["id"] != first
    assert [e["detail"].get("by") for e in ledger.events(run.id)
            if e["kind"] == "barrier.cleared"] == ["check"]


def test_an_owner_clear_that_lost_the_race_to_the_check_did_not_clear(ledger, clock):
    """The mirror case: the check cleared A first. The run is not waiting, but this
    call cleared nothing — the audit says by=check, and so does the answer."""
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="judge")
    first = ledger.get(run.id).barrier["id"]

    def _race():
        ledger.clear_barrier(run.id, why="elapsed", by="check", expect_id=first)

    cleared, after = RunBarriers(_RacingLedger(ledger, _race), clock=clock).clear(run.id)
    assert cleared is False and after.barrier is None


def test_the_ledger_compare_and_clear_says_whether_it_wrote(ledger, clock):
    run = ledger.open_run(_goal())
    barriers = _barriers(ledger, clock)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="judge")
    first = ledger.get(run.id).barrier["id"]
    assert ledger.clear_barrier_if(run.id, why="owner", by="owner", expect_id="b-other")[0] is False
    wrote, after = ledger.clear_barrier_if(run.id, why="owner", by="owner", expect_id=first)
    assert wrote is True and after.barrier is None
    assert ledger.clear_barrier_if(run.id, why="owner", by="owner", expect_id=first)[0] is False


# ── H464 review round 2 ──────────────────────────────────────────────────────

def test_an_owner_clear_of_a_pid_wait_does_not_refuse_a_later_process_on_that_pid(
    ledger, clock,
):
    """N5: the owner's clear binds that process — pid AND start token. A later process
    the hub registers on the reused pid number is a different wait."""
    identity = {"start": "111", "ns": "ns-1", "boot": "boot-1"}
    barriers = _barriers(ledger, clock, identity=lambda _pid: dict(identity))
    run = ledger.open_run(_goal())
    barriers.register_process(run.id, 4242, label="build")
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert barriers.clear(run.id)[0] is True
    with pytest.raises(RunBarriersError) as exc:      # the same process: still refused
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="judge")
    assert exc.value.reason == "owner_cleared"

    identity["start"] = "222"                          # the pid is reused later
    barriers.register_process(run.id, 4242, label="rebuild")
    state = barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert state["target"] == 4242
    assert ledger.get(run.id).barrier["start"] == "222"


def test_a_pid_owner_clear_recorded_without_a_start_token_matches_on_the_pid(ledger, clock):
    """N5: an audit row with no start token (none was captured) cannot tell two
    processes apart, so the owner's clear keeps binding the pid number."""
    barriers = _barriers(ledger, clock, identity=lambda _pid: {"start": "", "ns": "",
                                                                "boot": ""})
    run = ledger.open_run(_goal())
    barriers.register_process(run.id, 4242)
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    barriers.clear(run.id)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert exc.value.reason == "owner_cleared"


def test_a_tokenless_owner_clear_still_binds_a_later_request_with_a_token(ledger, clock):
    """N5: when only ONE side has a start token (the owner's clear was recorded
    without one), the two processes cannot be told apart, so the clear keeps binding
    the pid number — only two different tokens prove a different process."""
    token = {"start": ""}
    barriers = _barriers(ledger, clock,
                         identity=lambda _pid: {"start": token["start"], "ns": "", "boot": ""})
    run = ledger.open_run(_goal())
    barriers.register_process(run.id, 4242)
    barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    barriers.clear(run.id)                                  # recorded with no token
    token["start"] = "777"
    barriers.register_process(run.id, 4242)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4242}, source="planner")
    assert exc.value.reason == "owner_cleared"


def test_a_pid_whose_signal_is_refused_is_still_checked_against_its_start_token(
    monkeypatch,
):
    """N4: ``kill(pid, 0)`` answering EPERM makes exec_cache call the pid alive without
    comparing start tokens. The probe compares them itself, so a reused pid clears;
    and when /proc is hidden (hidepid=2) there is no token to read — unknown, clears."""
    from agents.core import exec_cache
    from agents.core.autonomy import run_barriers

    token = {"now": "999"}
    monkeypatch.setattr(exec_cache, "_pid_alive", lambda _pid, _start="": True)  # EPERM
    monkeypatch.setattr(exec_cache, "_start_token", lambda _pid: token["now"])
    monkeypatch.setattr(exec_cache, "_pid_ns", lambda: "ns-1")
    monkeypatch.setattr(exec_cache, "_boot_id", lambda: "boot-1")
    monkeypatch.setattr(run_barriers, "_proc_state", lambda _pid: "S")
    barrier = {"target": 4242, "start": "111", "ns": "ns-1", "boot": "boot-1"}
    assert default_pid_probe(barrier) == "reused"
    token["now"] = "111"
    assert default_pid_probe(barrier) == "alive"
    token["now"] = ""                                  # hidepid=2: nothing to read
    monkeypatch.setattr(run_barriers, "_proc_state", lambda _pid: "")
    assert default_pid_probe(barrier) == "unknown"
    assert "A permission error reads as alive" not in (default_pid_probe.__doc__ or "")


# ── the mutation pass ────────────────────────────────────────────────────────


def test_a_pid_wait_needs_that_pid_registered_not_just_any(ledger, clock):
    """Registering one process for a run does not let the run wait on another."""
    barriers = _barriers(ledger, clock)
    run = ledger.open_run(_goal())
    barriers.register_process(run.id, 4242)
    with pytest.raises(RunBarriersError) as exc:
        barriers.request(run.id, {"kind": "pid", "target": 4343}, source="planner")
    assert exc.value.reason == "pid_not_registered"


def test_a_clock_wait_days_ahead_is_not_cut_to_the_default_wait(ledger, clock):
    """A clock wait's own bound is the 7-day ceiling, not the 6-hour default that
    process and trigger waits get; only the run's budget or deadline cap it sooner."""
    barriers = _barriers(ledger, clock)
    run = ledger.open_run(_goal(), budget=Budget(max_seconds=5 * 86_400))
    target = clock.now + 2 * 86_400
    barriers.request(run.id, {"kind": "deadline", "target": target}, source="planner")
    assert ledger.get(run.id).barrier["cap_at"] >= target


# ── H464b C4: the hub parks a finished plan on its own in-flight tasks ────────

def _run_with_tasks(ledger, *task_ids, goal_id="g-1", budget=None):
    """A run whose steps queued these tasks, each answered and the run resumed —
    what the checklist leaves behind once every row is approved."""
    run = ledger.open_run(_goal(goal_id), budget=budget)
    for n, task_id in enumerate(task_ids, 1):
        step = ledger.record_step(run.id, kind="build", summary=f"step {n}", outcome="queued",
                                  task_id=task_id)
        ledger.resolve_step(run.id, step.seq, outcome="ok")
        ledger.resume(run.id)
    return run


class _Flips:
    """A task reader whose answer for one task changes after its first read: the
    task finished between the park's two reads."""

    def __init__(self, first, then, **others) -> None:
        self.answers = {int(k.removeprefix("t")): list(v) for k, v in (first or {}).items()}
        self.then = then
        self.others = _Tasks(**others)

    def __call__(self, task_id):
        queued = self.answers.get(int(task_id))
        if queued:
            status = queued.pop(0)
            return types.SimpleNamespace(id=task_id, status=status)
        if int(task_id) in self.answers:
            return types.SimpleNamespace(id=task_id, status=self.then)
        return self.others(task_id)


def test_in_flight_means_decided_yes_and_not_finished():
    assert frozenset({"approved", "running"}) == IN_FLIGHT_TASK_STATUSES


def test_barrier_sets_lists_each_park_oldest_first_and_by_source(ledger, clock):
    run = _run_with_tasks(ledger, 7)
    other = _run_with_tasks(ledger, 9, goal_id="g-2")
    barriers = _barriers(ledger, clock, tasks=_Tasks(t7="running", t9="running"))
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}},
                     source="planner")
    clock.advance(1)
    barriers.request(run.id, {"kind": "trigger", "target": "task:7"}, source="hub")
    clock.advance(1)
    barriers.request(run.id, {"kind": "deadline", "target": {"in_seconds": 60}}, source="judge")
    barriers.request(other.id, {"kind": "trigger", "target": "task:9"}, source="hub")
    sets = ledger.barrier_sets(run.id)
    assert [(s["source"], s["kind"]) for s in sets] == [
        ("planner", "deadline"), ("hub", "trigger"), ("judge", "deadline")]
    hub = ledger.barrier_sets(run.id, source="hub")
    assert [s["target"] for s in hub] == ["task:7"]
    assert set(hub[0]) >= {"id", "kind", "target", "cap_at", "source", "reason"}
    assert ledger.barrier_sets(run.id, source="owner") == []
    assert ledger.barrier_sets("nope") == []


def test_park_in_flight_parks_on_the_oldest_approved_or_running_task(ledger, clock):
    run = _run_with_tasks(ledger, 7, 8, 9)
    ledger.record_step(run.id, kind="plan", summary="a failed plan", outcome="failed")
    before = ledger.get(run.id)
    barriers = _barriers(ledger, clock, tasks=_Tasks(t7="done", t8="running", t9="approved"))
    state = barriers.park_in_flight(run.id)
    assert state["kind"] == "trigger" and state["target"] == "task:8"
    assert state["source"] == "hub"
    assert state["reason"] == "task 8 is still running"
    assert state["waiting_on"] == "task 8 to finish"
    # the default wait, never more than the budget left
    assert state["cap_at"] == clock.now + DEFAULT_WAIT_SECONDS
    after = ledger.get(run.id)
    assert (after.steps_used, after.interrupts_used) == (before.steps_used, before.interrupts_used)
    assert len(ledger.steps(run.id)) == 4                      # a park is never a step
    assert barriers.active(run.id) is True
    # an approved task that has not started is in flight too
    fresh = _run_with_tasks(ledger, 9, goal_id="g-2")
    assert barriers.park_in_flight(fresh.id)["target"] == "task:9"


@pytest.mark.parametrize("status", [
    "proposed", "blocked", "deferred", None, "done", "failed", "rejected", "quarantined",
    "expired",
])
def test_park_in_flight_ignores_undecided_missing_and_terminal_tasks(ledger, clock, status):
    """Undecided asks keep the run ``blocked`` instead; finished work is done."""
    run = _run_with_tasks(ledger, 7)
    statuses = {} if status is None else {"t7": status}
    barriers = _barriers(ledger, clock, tasks=_Tasks(**statuses))
    assert barriers.park_in_flight(run.id) is None
    assert ledger.get(run.id).barrier is None
    assert ledger.barrier_sets(run.id) == []


def test_park_in_flight_never_waits_on_the_same_task_twice(ledger, clock):
    """At most one hub wait per task per run: a wait that hit its cap is not renewed."""
    run = _run_with_tasks(ledger, 8, 9, budget=Budget(max_seconds=3 * DEFAULT_WAIT_SECONDS))
    barriers = _barriers(ledger, clock, tasks=_Tasks(t8="running", t9="running"))
    assert barriers.park_in_flight(run.id)["target"] == "task:8"
    clock.advance(DEFAULT_WAIT_SECONDS)
    assert barriers.active(run.id) is False
    assert _events(ledger, run.id)[0][1]["why"] == "cap"
    assert barriers.park_in_flight(run.id)["target"] == "task:9"
    clock.advance(DEFAULT_WAIT_SECONDS)
    assert barriers.active(run.id) is False
    assert barriers.park_in_flight(run.id) is None
    assert [s["target"] for s in ledger.barrier_sets(run.id, source="hub")] == [
        "task:8", "task:9"]


def test_park_in_flight_skips_a_task_the_owner_let_the_run_go_from(ledger, clock):
    """The owner's "stop waiting" binds the hub too: once the owner let the run go
    from ``task:8`` — whoever set that wait — the hub never parks on it again."""
    run = _run_with_tasks(ledger, 8, 9)
    tasks = _Tasks(t8="running", t9="running")
    barriers = _barriers(ledger, clock, tasks=tasks)
    barriers.request(run.id, {"kind": "trigger", "target": "task:8"}, source="planner")
    assert barriers.clear(run.id)[0] is True
    assert barriers.park_in_flight(run.id)["target"] == "task:9"
    assert barriers.clear(run.id)[0] is True
    assert barriers.park_in_flight(run.id) is None
    # and when the other task is not in flight, nothing is left to park on
    quiet = _run_with_tasks(ledger, 8, 9, goal_id="g-2")
    only = _barriers(ledger, clock, tasks=_Tasks(t8="running", t9="done"))
    only.request(quiet.id, {"kind": "trigger", "target": "task:8"}, source="judge")
    only.clear(quiet.id)
    assert only.park_in_flight(quiet.id) is None
    assert ledger.get(quiet.id).barrier is None


def test_park_in_flight_without_a_reader_is_none_and_a_raising_reader_is_a_refusal(
    ledger, clock
):
    run = _run_with_tasks(ledger, 7)
    assert _barriers(ledger, clock).park_in_flight(run.id) is None
    locked = _barriers(ledger, clock, tasks=_Raises(RuntimeError("database is locked")))
    with pytest.raises(RunBarriersError) as exc:
        locked.park_in_flight(run.id)
    assert exc.value.reason == "trigger_unavailable"
    assert ledger.get(run.id).barrier is None
    assert ledger.barrier_sets(run.id) == []


def test_park_in_flight_skips_a_task_that_finished_between_the_reads(ledger, clock):
    run = _run_with_tasks(ledger, 8, 9)
    flips = _Flips({"t8": ["running"]}, "done", t9="running")
    state = _barriers(ledger, clock, tasks=flips).park_in_flight(run.id)
    assert state["target"] == "task:9"
    alone = _run_with_tasks(ledger, 8, goal_id="g-2")
    flips = _Flips({"t8": ["running"]}, "done")
    assert _barriers(ledger, clock, tasks=flips).park_in_flight(alone.id) is None
    assert ledger.get(alone.id).barrier is None


def test_park_in_flight_passes_any_other_refusal_on(ledger, clock):
    """Only "it finished in between" moves on; a spent run, a full barrier count or
    an unparkable run is the caller's to handle."""
    run = _run_with_tasks(ledger, 8, budget=Budget(max_seconds=60))
    barriers = _barriers(ledger, clock, tasks=_Tasks(t8="running"))
    clock.advance(60)
    with pytest.raises(RunBarriersError) as exc:
        barriers.park_in_flight(run.id)
    assert exc.value.reason == "budget_spent"


def test_park_in_flight_survives_a_restart(tmp_path, clock):
    """The hub's wait history is the append-only audit, so a restart never buys a
    task a second wait."""
    path = tmp_path / "runs.db"
    first = WorkRunLedger(path, clock=clock)
    run = _run_with_tasks(first, 8, 9)
    tasks = _Tasks(t8="running", t9="done")
    assert _barriers(first, clock, tasks=tasks).park_in_flight(run.id)["target"] == "task:8"
    clock.advance(DEFAULT_WAIT_SECONDS)
    assert _barriers(first, clock, tasks=tasks).active(run.id) is False
    first.close()
    again = WorkRunLedger(path, clock=clock)
    try:
        assert _barriers(again, clock, tasks=tasks).park_in_flight(run.id) is None
        assert len(again.barrier_sets(run.id, source="hub")) == 1
    finally:
        again.close()

