"""run_barriers.py — park a work run on real async work instead of poking it (H464).

A run waiting on a build, a deploy or a rate-limit cooldown used to be ticked on
every sweep, and every tick is a step of budget spent asking "is it done yet?".
Since a step that spends budget is a hard bound in ``work_runs.py``, that is not
just waste: it is a run failing for lack of budget it spent on polling.

A **barrier** parks the run instead. Three kinds, as Hermes names them:

* ``pid`` — wait until a process the hub spawned *for this run* exits;
* ``trigger`` — wait until something registered fires: a durable ``task:<id>``
  this run queued reaches a terminal status, or an inbound ``hook:<id>`` is
  called after the barrier was set;
* ``deadline`` — wait until a wall-clock time.

While one is active the scheduler skips the run (``waiting``) and the supervisor
returns before planning or grading, so no step, no plan and no judge call is
spent. This module owns validation and the probes; the ledger only stores.

Governance: read-only. A barrier only **suppresses** ticks — it never changes a
run's status, grants an approval, resumes a blocked run or extends a budget. The
rules that keep it from ever wedging a run:

* **Bounded.** Every barrier carries a hard ``cap_at``: the earliest of its own
  wait, the run's deadline and the run's wall-clock budget. So a barrier can never
  outlive the run's time budget. The cap cannot cover a steps or interrupts budget,
  so the scheduler and the supervisor both check the budget *before* the barrier:
  a spent budget always wins over a wait.
* **Anything unprovable clears.** A dead or reused pid, another boot or pid
  namespace, a zombie, a fired or vanished trigger, an elapsed deadline, the cap,
  a probe that raises — each clears the barrier on the next check. Clearing only
  restores normal, budget-bounded behaviour, so it is always the safe direction.
* **A check that errors reports "not waiting".** A broken check can cost one
  step; it can never park a run forever.
* **Only what is provably this run's may be waited on.** A pid must have been
  registered for this run by hub code that spawned it (``register_process`` is
  Python-only: no route, planner, judge or model can register one), and a task
  trigger must be a task this run itself queued.
* **The owner's "stop waiting" sticks.** Once the owner clears a wait, neither the
  planner nor the judge may park the run on that same wait again (``owner_cleared``);
  a different wait is still theirs to ask for.
* **Nothing to wait on is not a failure.** ``request`` refuses a wait on work that
  has already finished (and the other codes in :data:`NOTHING_TO_WAIT_ON`) the same
  way it refuses a malformed one, but a caller must not charge the run for it: the
  work it wanted to wait for is simply not pending any more.
* **``request`` raises only :class:`WorkRunError`.** A task queue, a webhook store
  or a pid probe that fails while a barrier is being set is a refusal
  (``trigger_unavailable`` / ``probe_failed``, :data:`WAIT_CHECK_FAILED`), never a
  raw exception out of a tick. A caller treats those like nothing to wait on: the
  check may well succeed on the next sweep, so the run is not charged for it.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agents.core.autonomy.work_runs import (
    BARRIER_KINDS,
    BARRIER_SOURCES,
    MAX_BARRIERS_PER_RUN,
    WorkRunError,
)

logger = logging.getLogger("jarvis.run_barriers")

MAX_BARRIER_SECONDS = 7 * 86_400     # the furthest any barrier may reach
DEFAULT_WAIT_SECONDS = 6 * 3_600     # max_wait for pid/trigger when none is given
MAX_JUDGE_WAITS = 3                  # judge-sourced sets per run; then no wait probe
MAX_PROCS_PER_RUN = 16
MAX_BACKGROUND = 20                  # entries the judge sees

_MAX_REASON = 200
_MAX_LABEL = 120
_TRIGGER = re.compile(r"^([a-z]+):(.+)$")
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_PARKABLE = frozenset({"planning", "working"})

# The pid probe's answers. Only "alive" keeps a barrier; everything else clears —
# "unknown" (a platform that cannot tell this pid from a reused one) included (I3).
_PID_CLEAR = {"dead": "exited", "reused": "pid_reused", "ns": "ns_mismatch",
              "unknown": "probe_error"}

# Refusals that mean "there is nothing to wait on", not "the request was bad": the
# trigger already fired, the process already exited (or cannot be told apart from
# a reused pid), there is no time left, or the owner already let the run go from
# this very wait. A caller treats these as "no wait happened" — no failed step, no
# budget — and plans again (H464 review F0/F3). Every other refusal is malformed
# or forbidden and goes down the failed-plan-step road the streak rule bounds.
NOTHING_TO_WAIT_ON = frozenset({
    "trigger_already_fired", "pid_not_running", "pid_unprovable", "no_time_left",
    "owner_cleared",
})

# Refusals that mean "the wait could not be checked just now": a locked or missing
# task queue or webhook store, a pid probe that raised. Not the request's fault, so
# a caller does not charge the run for them either (H464 review round 2, N2) — it
# counts them with the nothing-to-wait-on ones, which bounds a check that never
# recovers.
WAIT_CHECK_FAILED = frozenset({"trigger_unavailable", "probe_failed"})

# Who is bound by an owner's clear: the model-driven sources. Hub code that spawned
# the work itself ("hub") is not a model second-guessing the owner.
_MODEL_SOURCES = frozenset({"planner", "judge"})

# A task this run queued that was decided yes and has not finished (H464b): what
# the hub parks a finished plan on before grading. An undecided ask keeps the run
# ``blocked`` instead, and a terminal status means the work is done.
IN_FLIGHT_TASK_STATUSES = frozenset({"approved", "running"})


class RunBarriersError(WorkRunError):
    """A refused barrier request. ``reason`` is a bounded, public code.

    A :class:`WorkRunError` so a caller that already handles the ledger's refusals
    handles these the same way."""


def _clean(value: Any, limit: int) -> str:
    return _CONTROL.sub("", str(value or "")).strip()[:limit]


def _number(value: Any) -> float | None:
    """A finite real number, or None. A bool is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _count(value: Any, cast: Callable[[Any], Any]) -> Any:
    """A counter read from a store a person may have hand-edited: a finite number,
    else 0 — never a ValueError out of a check (H464 review F6)."""
    number = _number(value)
    return cast(number) if number is not None else cast(0)


def _task_status(task: Any) -> str:
    status = getattr(task, "status", "")
    return str(getattr(status, "value", status) or "").strip().lower()


def _terminal_task_statuses() -> frozenset[str]:
    from agents.core.autonomy.queue import TERMINAL

    return frozenset(str(getattr(s, "value", s)) for s in TERMINAL)


def _when(moment: float) -> str:
    """A wall-clock time the way a person reads it: the hour when it is within a
    day, the date as well when it is further out."""
    local = time.localtime(float(moment))
    if abs(float(moment) - time.time()) < 86_400:
        return time.strftime("%H:%M", local)
    return time.strftime("%Y-%m-%d %H:%M", local)


def describe(barrier: Mapping[str, Any] | None) -> str:
    """What the run is waiting on, as a plain phrase. Never probes."""
    b = dict(barrier or {})
    kind = b.get("kind")
    target = b.get("target")
    if kind == "trigger" and isinstance(target, str):
        registry, _, ident = target.partition(":")
        if registry == "task":
            return f"task {ident} to finish"
        if registry == "hook":
            return f"webhook {ident} to be called"
    if kind == "pid":
        label = _clean(b.get("label"), _MAX_LABEL)
        return f"process {target} ({label}) to exit" if label else f"process {target} to exit"
    if kind == "deadline":
        end = _number(target)
        cap = _number(b.get("cap_at"))
        if end is not None:
            return f"the clock to reach {_when(min(end, cap) if cap is not None else end)}"
    return "a barrier"


def until(barrier: Mapping[str, Any] | None) -> str:
    """The latest a barrier can hold, as a plain time — its cap."""
    cap = _number(dict(barrier or {}).get("cap_at"))
    return _when(cap) if cap is not None else ""


# ── the default probes ───────────────────────────────────────────────────────

def _proc_state(pid: int) -> str:
    """The one-letter state from ``/proc/<pid>/stat``, or "" when unreadable."""
    try:
        text = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace")
    except (OSError, ValueError):
        return ""
    fields = text.rpartition(")")[2].split()
    return fields[0] if fields else ""


def default_pid_probe(barrier: Mapping[str, Any]) -> str:
    """``alive``, ``dead``, ``reused``, ``ns`` or ``unknown`` for a pid barrier.

    POSIX-first, with Windows handled through the same exec_cache helpers the
    sandbox lock uses. A pid from another boot or pid namespace means nothing
    here, so it clears; a reused pid (start token changed) clears; a zombie is a
    process that has already exited.

    ``alive`` needs proof: the start token captured at registration must still be
    readable and must match. A permission error from ``kill(pid, 0)`` alone proves
    nothing — exec_cache reads it as alive without comparing tokens — so the token
    is compared here too, and a different one is ``reused``. When no token was
    captured, or none can be read now, the answer is ``unknown``: macOS/BSD, where
    there is no /proc and ``kill(pid, 0)`` cannot tell this process from a zombie
    or a reused pid; or a host that hides other users' /proc entries
    (``hidepid=2``), where a process of another user is invisible. Unknown clears
    (I3: anything the check cannot confirm clears — H464 review F4), and
    ``request`` refuses it as ``pid_unprovable``.
    """
    from agents.core import exec_cache

    boot, ns = str(barrier.get("boot") or ""), str(barrier.get("ns") or "")
    if (boot and exec_cache._boot_id() != boot) or (ns and exec_cache._pid_ns() != ns):
        return "ns"
    pid = int(barrier["target"])
    start = str(barrier.get("start") or "")
    if not exec_cache._pid_alive(pid, start):
        return "reused" if start and exec_cache._pid_alive(pid) else "dead"
    if _proc_state(pid) in {"Z", "X"}:
        return "dead"
    now = exec_cache._start_token(pid)
    if not start or not now:
        return "unknown"
    return "alive" if now == start else "reused"


def default_proc_identity(pid: int) -> dict[str, str] | None:
    """What tells this pid from a later one, or None when it is not running."""
    from agents.core import exec_cache

    if not exec_cache._pid_alive(pid) or _proc_state(pid) in {"Z", "X"}:
        return None
    return {
        "start": exec_cache._start_token(pid),
        "ns": exec_cache._pid_ns(),
        "boot": exec_cache._boot_id(),
    }


# ── the service ──────────────────────────────────────────────────────────────

class RunBarriers:
    """Validates, checks and clears the barriers on work runs.

    ``read_task`` is the durable queue reader (``TaskQueue.get``); ``hooks`` returns
    the webhook store, resolved lazily so nothing here builds one at import. Both
    are optional: without them the matching trigger kind is refused rather than
    guessed. ``pid_probe`` and ``proc_identity`` are injectable so the pid kind is
    testable without spawning a process.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        read_task: Callable[[int], Any] | None = None,
        hooks: Callable[[], Any] | None = None,
        clock: Callable[[], float] | None = None,
        pid_probe: Callable[[Mapping[str, Any]], str] | None = None,
        proc_identity: Callable[[int], Mapping[str, str] | None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._read_task = read_task
        self._hooks = hooks
        self._clock = clock or getattr(ledger, "_clock", None) or time.time
        self._pid_probe = pid_probe or default_pid_probe
        self._proc_identity = proc_identity or default_proc_identity

    def _now(self) -> float:
        return float(self._clock())

    # ── setting ──────────────────────────────────────────────────────────

    def request(self, run_id: str, raw: Any, *, source: str) -> dict[str, Any]:
        """Validate a barrier request and park the run on it. Returns :meth:`state`.

        Refusals are :class:`RunBarriersError` with a public code; the ledger's own
        refusals (``unknown_run``, and its re-checks) come through unchanged. The
        codes in :data:`NOTHING_TO_WAIT_ON` mean there is nothing to wait on, not
        that the request was bad. A failing reader, store or probe is a refusal
        too — nothing but a :class:`WorkRunError` leaves this method on their
        account.
        """
        if source not in BARRIER_SOURCES:
            raise RunBarriersError("invalid_source")
        run = self._ledger.get(run_id)
        if run is None:
            raise WorkRunError("unknown_run")
        if run.status not in _PARKABLE:
            raise RunBarriersError("run_not_parkable")
        budget = self._ledger.budget_state(run_id)
        if budget["exceeded"]:
            raise RunBarriersError("budget_spent")
        if not isinstance(raw, Mapping):
            raise RunBarriersError("malformed_barrier")
        kind = raw.get("kind")
        if kind not in BARRIER_KINDS:
            raise RunBarriersError("unknown_kind")
        reason = _clean(raw.get("reason"), _MAX_REASON) or f"waiting on {kind}"

        max_wait = DEFAULT_WAIT_SECONDS
        if raw.get("max_wait") is not None:
            wanted = _number(raw.get("max_wait"))
            if wanted is None or not 0 < wanted <= MAX_BARRIER_SECONDS:
                raise RunBarriersError("invalid_max_wait")
            max_wait = wanted
        now = self._now()
        # A deadline carries its own end, so its own wait is the furthest any
        # barrier may reach; the run's deadline and the time its budget has left
        # (H487: approval waits are credited back) cap it either way, silently —
        # the budget check then ends the run honestly.
        own = MAX_BARRIER_SECONDS if kind == "deadline" else max_wait
        cap_at = min(
            now + own,
            run.deadline_at or math.inf,
            now + float(budget["seconds_left"]),
        )
        if cap_at <= now:
            raise RunBarriersError("no_time_left")
        if self._ledger.barrier_set_count(run_id) >= MAX_BARRIERS_PER_RUN:
            raise RunBarriersError("barrier_limit")

        record: dict[str, Any] = {
            "v": 1, "id": f"b-{uuid.uuid4().hex[:8]}", "kind": kind,
            "set_at": now, "cap_at": cap_at, "reason": reason, "source": source,
        }
        if kind == "deadline":
            record["target"] = self._deadline_target(raw.get("target"), now)
        elif kind == "pid":
            record.update(self._pid_target(run_id, raw.get("target")))
        else:
            record.update(self._trigger_target(run_id, raw.get("target")))
        if source in _MODEL_SOURCES and self._owner_let_go(
            run_id, kind, record["target"], record.get("start")
        ):
            raise RunBarriersError("owner_cleared")
        self._ledger.set_barrier(run_id, record)
        return self.state(run_id) or {}

    def park_in_flight(self, run_id: str) -> dict[str, Any] | None:
        """Park the run on the oldest task it queued that is still in flight (H464b).

        The checklist moves on as soon as a step's task is *approved*, so a plan can
        finish while that task is still executing; grading then would spend the
        run's single verdict on work that has not landed. The hub waits on it
        instead: a ``task:<id>`` trigger, ``source="hub"``, with the default wait
        (capped by the run's deadline and the time its budget has left).

        Returns :meth:`state`, or None when there is nothing to wait on — no reader
        bound, no task of this run in flight, or every in-flight task already used.
        The hub waits on a task **at most once per run** (a wait that hit its cap is
        never renewed), and never on a task the owner let the run go from, whoever
        set that wait. A reader that raises is ``trigger_unavailable``; a task that
        finished between the two reads is skipped; any other refusal is raised for
        the caller, which falls through to grading. Only a fixed template with the
        task's integer id enters the barrier — no title, payload or result text.
        """
        if self._read_task is None:
            return None
        excluded = {s.get("target") for s in self._ledger.barrier_sets(run_id, source="hub")}
        excluded |= {
            c.get("target") for c in self._ledger.owner_cleared(run_id)
            if c.get("kind") == "trigger"
        }
        seen: list[int] = []
        for step in self._ledger.steps(run_id):
            task_id = step.task_id
            if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
                continue
            if task_id not in seen:
                seen.append(task_id)
        for task_id in seen:
            target = f"task:{task_id}"
            if target in excluded:
                continue
            try:
                task = self._read_task(task_id)
            except Exception:
                logger.warning("could not read task %s while checking run %s for work "
                               "in flight", task_id, run_id, exc_info=True)
                raise RunBarriersError("trigger_unavailable") from None
            if task is None or _task_status(task) not in IN_FLIGHT_TASK_STATUSES:
                continue
            try:
                return self.request(run_id, {
                    "kind": "trigger", "target": target,
                    "reason": f"task {task_id} is still running",
                }, source="hub")
            except RunBarriersError as exc:
                if exc.reason == "trigger_already_fired":
                    continue      # it finished between the two reads
                raise
        return None

    def _owner_let_go(self, run_id: str, kind: str, target: Any, start: Any = "") -> bool:
        """Whether the owner already cleared this same wait on this run.

        "The same wait" is the same kind and target — except the clock: a deadline's
        target is recomputed from ``in_seconds`` on every ask, so for the clock any
        deadline is the same wait. Otherwise the judge would re-park a run on a
        fresh six-hour clock the very tick after the owner let it go.

        A pid is a process, not a number: the same pid AND the same start token
        (N5), so a later process the hub registers on a reused pid is a new wait.
        When either side has no token, nothing tells the two apart and the pid
        number alone decides — the owner's clear keeps binding.
        """
        for cleared in self._ledger.owner_cleared(run_id):
            if cleared.get("kind") != kind:
                continue
            if kind == "deadline":
                return True
            if cleared.get("target") != target:
                continue
            if kind == "pid":
                was, now = str(cleared.get("start") or ""), str(start or "")
                if was and now and was != now:
                    continue
            return True
        return False

    @staticmethod
    def _deadline_target(target: Any, now: float) -> float:
        if isinstance(target, Mapping):
            offset = _number(target.get("in_seconds"))
            end = None if offset is None else now + offset
        else:
            end = _number(target)
        if end is None or not now < end <= now + MAX_BARRIER_SECONDS:
            raise RunBarriersError("deadline_out_of_bounds")
        return end

    def _pid_target(self, run_id: str, target: Any) -> dict[str, Any]:
        if isinstance(target, bool) or not isinstance(target, int):
            raise RunBarriersError("invalid_pid")
        registered = [p for p in self._ledger.processes(run_id) if p["pid"] == target]
        if not registered:
            raise RunBarriersError("pid_not_registered")
        proc = registered[-1]
        fields = {"target": target, "start": proc["start"], "ns": proc["ns"],
                  "boot": proc["boot"], "label": _clean(proc.get("label"), _MAX_LABEL)}
        try:
            answer = self._pid_probe(fields)
        except Exception:
            logger.warning("pid probe failed while parking %s", run_id, exc_info=True)
            raise RunBarriersError("probe_failed") from None
        if answer == "unknown":
            # This platform cannot tell the pid from a reused one: the check would
            # clear it on the next sweep, so there is nothing to wait on.
            raise RunBarriersError("pid_unprovable")
        if answer != "alive":
            # Nothing to wait on: parking on a process that is already gone would
            # only cost a sweep before the check cleared it.
            raise RunBarriersError("pid_not_running")
        return fields

    def _trigger_target(self, run_id: str, target: Any) -> dict[str, Any]:
        match = _TRIGGER.match(target) if isinstance(target, str) else None
        if match is None:
            raise RunBarriersError("invalid_trigger")
        registry, ident = match.groups()
        if registry not in ("task", "hook"):
            raise RunBarriersError("unknown_trigger")
        if not _TRIGGER_ID.match(ident):
            raise RunBarriersError("invalid_trigger")
        if registry == "task":
            if not ident.isdigit():
                raise RunBarriersError("invalid_trigger")
            task_id = int(ident)
            # Ownership: only a task this run itself queued. Waiting on someone
            # else's task would let a run observe work it was never party to.
            if task_id not in {s.task_id for s in self._ledger.steps(run_id)}:
                raise RunBarriersError("trigger_not_owned")
            if self._read_task is None:
                raise RunBarriersError("trigger_unavailable")
            try:
                task = self._read_task(task_id)
            except Exception:
                # A locked or broken queue db: a refusal, never an exception out of
                # the tick — which would fail every sweep and bound nothing.
                logger.warning("could not read task %s while parking %s", task_id, run_id,
                               exc_info=True)
                raise RunBarriersError("trigger_unavailable") from None
            if task is None:
                raise RunBarriersError("trigger_unknown")
            status = _task_status(task)
            if status in _terminal_task_statuses():
                raise RunBarriersError("trigger_already_fired")
            return {"target": f"task:{task_id}", "marker": {"status": status}}
        try:
            store = self._store()
            rec = store.get(ident) if store is not None else None
            enabled = bool(rec) and self._hook_enabled(store, rec)
        except Exception:
            logger.warning("could not read webhook %s while parking %s", ident, run_id,
                           exc_info=True)
            raise RunBarriersError("trigger_unavailable") from None
        if store is None:
            raise RunBarriersError("trigger_unavailable")
        if not enabled:
            raise RunBarriersError("trigger_unknown")
        return {"target": f"hook:{ident}", "marker": self._hook_marker(rec)}

    def _store(self) -> Any:
        return self._hooks() if self._hooks is not None else None

    @staticmethod
    def _hook_enabled(store: Any, rec: Mapping[str, Any]) -> bool:
        check = getattr(store, "is_enabled", None)
        return bool(check(rec)) if callable(check) else rec.get("enabled", True) is True

    @staticmethod
    def _hook_marker(rec: Mapping[str, Any]) -> dict[str, Any]:
        return {"calls": _count(rec.get("calls"), int),
                "last_called": _count(rec.get("last_called"), float)}

    def register_process(self, run_id: str, pid: int, *, label: str = "") -> dict[str, Any]:
        """Register a process the hub spawned for this run, so the run may wait on it.

        Python-only on purpose: no route, planner, judge or model reaches this, so an
        arbitrary host pid can never become a barrier. Refuses init, the hub itself
        and its parent, a process that is not running, and more than
        ``MAX_PROCS_PER_RUN`` per run.
        """
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or pid in {
            os.getpid(), os.getppid(),
        }:
            raise RunBarriersError("pid_forbidden")
        if self._ledger.get(run_id) is None:
            raise WorkRunError("unknown_run")
        if len(self._ledger.processes(run_id)) >= MAX_PROCS_PER_RUN:
            raise RunBarriersError("proc_limit")
        identity = self._proc_identity(pid)
        if not identity:
            raise RunBarriersError("pid_not_running")
        record = {"pid": pid, "start": str(identity.get("start") or ""),
                  "ns": str(identity.get("ns") or ""), "boot": str(identity.get("boot") or ""),
                  "label": _clean(label, _MAX_LABEL)}
        self._ledger.add_process(run_id, record)
        return record

    # ── checking ─────────────────────────────────────────────────────────

    def active(self, run_id: str) -> bool:
        """True while the run is parked. Clears a stale barrier as it finds one.

        The one check both the scheduler and the supervisor call. It never raises:
        anything it cannot answer reads as "not waiting", so the worst a broken
        check can cost is one step.
        """
        try:
            run = self._ledger.get(run_id)
            barrier = run.barrier if run is not None else None
        except Exception:
            logger.warning("barrier check could not read run %s; ticking it", run_id,
                           exc_info=True)
            return False
        if not barrier:
            return False
        try:
            why = self._stale(barrier)
        except Exception:
            logger.warning("barrier probe failed for run %s; clearing it", run_id,
                           exc_info=True)
            why = "probe_error"
        if why is None:
            return True
        try:
            self._ledger.clear_barrier(run_id, why=why, by="check", expect_id=barrier.get("id"))
        except Exception:
            logger.warning("could not clear a stale barrier on run %s", run_id, exc_info=True)
        return False

    def _stale(self, barrier: Mapping[str, Any]) -> str | None:
        """Why this barrier no longer holds, or None while it does."""
        now = self._now()
        cap = float(barrier["cap_at"])
        if now >= cap:
            return "cap"
        kind = barrier.get("kind")
        if kind == "deadline":
            return "elapsed" if now >= min(float(barrier["target"]), cap) else None
        if kind == "pid":
            answer = self._pid_probe(barrier)
            if answer == "alive":
                return None
            return _PID_CLEAR.get(answer, "probe_error")
        if kind == "trigger":
            return self._trigger_state(barrier)
        return "probe_error"

    def _trigger_state(self, barrier: Mapping[str, Any]) -> str | None:
        registry, _, ident = str(barrier.get("target") or "").partition(":")
        marker = dict(barrier.get("marker") or {})
        if registry == "task":
            task = self._read_task(int(ident)) if self._read_task is not None else None
            if task is None:
                return "vanished"
            return "fired" if _task_status(task) in _terminal_task_statuses() else None
        if registry == "hook":
            store = self._store()
            rec = store.get(ident) if store is not None else None
            if not rec or not self._hook_enabled(store, rec):
                return "vanished"
            now = self._hook_marker(rec)
            if now["calls"] > _count(marker.get("calls"), int) or now["last_called"] > _count(
                marker.get("last_called"), float
            ):
                return "fired"
            return None
        return "vanished"

    # ── surfaces ─────────────────────────────────────────────────────────

    def state(self, run_id: str) -> dict[str, Any] | None:
        """The barrier as a surface shows it, or None. Never probes, so it is cheap
        and safe to call from a list route."""
        run = self._ledger.get(run_id)
        barrier = run.barrier if run is not None else None
        if not barrier:
            return None
        return {
            "kind": barrier.get("kind"),
            "target": barrier.get("target"),
            "reason": barrier.get("reason"),
            "set_at": barrier.get("set_at"),
            "cap_at": barrier.get("cap_at"),
            "source": barrier.get("source"),
            "waiting_on": describe(barrier),
        }

    def background(self, run_id: str) -> list[dict[str, Any]]:
        """What is still running for this run, for the judge. Data, never
        instructions: bounded to ``MAX_BACKGROUND`` entries with clipped strings.

        The barrier first, then registered processes, then the run's own tasks
        newest first — so the cap drops the least relevant entries.
        """
        run = self._ledger.get(run_id)
        if run is None:
            return []
        items: list[dict[str, Any]] = []
        state = self.state(run_id)
        if state is not None:
            items.append({
                "kind": "barrier", "barrier_kind": state["kind"],
                "target": _clean(state["target"], _MAX_LABEL)
                if isinstance(state["target"], str) else state["target"],
                "reason": _clean(state["reason"], _MAX_LABEL),
                "waiting_on": _clean(state["waiting_on"], _MAX_LABEL),
                "cap_at": state["cap_at"],
            })
        for proc in self._ledger.processes(run_id):
            try:
                alive = self._pid_probe({"target": proc["pid"], **proc}) == "alive"
            except Exception:
                alive = False
            items.append({"kind": "process", "pid": proc["pid"],
                          "label": _clean(proc["label"], _MAX_LABEL), "alive": alive})
        seen: list[int] = []
        for step in reversed(self._ledger.steps(run_id)):
            if isinstance(step.task_id, int) and step.task_id not in seen:
                seen.append(step.task_id)
        terminal = _terminal_task_statuses()
        for task_id in seen:
            if len(items) >= MAX_BACKGROUND:
                break
            try:
                task = self._read_task(task_id) if self._read_task is not None else None
                status = "missing" if task is None else _clean(_task_status(task), 32)
            except Exception:
                status = "unreadable"
            items.append({"kind": "task", "id": task_id, "status": status,
                          "done": status in terminal})
        return items[:MAX_BACKGROUND]

    def clear(self, run_id: str, *, by: str = "owner") -> tuple[bool, Any]:
        """The owner lets a parked run go. Returns ``(cleared, run)``.

        Idempotent: with no barrier it clears nothing and says so. It compares and
        clears the barrier it read, so a newer one set in between is left alone.
        ``cleared`` is what THIS call did — the compare-and-clear's own answer —
        never read off the state afterwards: a barrier the check cleared first is
        not the owner's clear, and a newer one left in place is not "nothing to
        clear" (H464 review F8). ``run`` is the state afterwards, so a caller can
        say what it is waiting on now.
        """
        before = self._ledger.get(run_id)
        if before is None:
            raise WorkRunError("unknown_run")
        if not before.barrier:
            return False, before
        return self._ledger.clear_barrier_if(
            run_id, why="owner", by=by, expect_id=before.barrier.get("id")
        )


__all__ = [
    "BARRIER_KINDS",
    "DEFAULT_WAIT_SECONDS",
    "IN_FLIGHT_TASK_STATUSES",
    "MAX_BACKGROUND",
    "MAX_BARRIERS_PER_RUN",
    "MAX_BARRIER_SECONDS",
    "MAX_JUDGE_WAITS",
    "MAX_PROCS_PER_RUN",
    "NOTHING_TO_WAIT_ON",
    "WAIT_CHECK_FAILED",
    "RunBarriers",
    "RunBarriersError",
    "default_pid_probe",
    "default_proc_identity",
    "describe",
    "until",
]
