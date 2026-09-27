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

import pytest

from agents.core.autonomy.run_barriers import (
    BARRIER_KINDS,
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
    assert default_pid_probe(live) == "alive"
    if live["start"]:
        assert default_pid_probe({**live, "start": "not-the-same"}) == "reused"
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
