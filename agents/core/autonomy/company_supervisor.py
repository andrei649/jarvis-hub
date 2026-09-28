"""company_supervisor.py — the loop that keeps one work run going, 24/7.

This is the component that makes "work like a company would" real: it takes an
owner-approved goal, opens a run, and keeps stepping it until the goal is met,
the budget runs out, a stop condition fires, or the owner stops it — across
reboots, because everything it needs is in the ledger and nothing is in memory.

What it is NOT is the part that decides it may do something. The supervisor owns
sequencing and stopping; every privileged effect leaves through the existing
governed intake (``enqueue``), which is the same approval queue and Action Kernel
everything else uses. That is what ``delegated_execution_only`` means in the
contract registry: this loop can arrange work, never authorise it.

The rules it enforces, none of which the planner or the model can talk it out of:

* **Default-off.** ``JARVIS_COMPANY_MODE`` gates construction at the call site;
  ``SupervisorConfig.enabled`` gates every tick here, so a supervisor built by
  accident does nothing rather than something.
* **One tick, one step.** A tick plans at most one action and records at most one
  step. A loop that could take "as many steps as it likes" per tick has no
  meaningful budget.
* **Stop beats everything.** The stop flag is read at the top of every tick,
  before planning, before the deadline check, before anything else.
* **A refusal is a step.** When the kernel or the queue refuses, that is recorded
  as a ``refused``/``queued`` step and spends budget. A loop that retried
  silently on refusal would grind against a guard forever.
* **The same failure twice ends the run.** Consecutive identical failures are the
  signature of a stuck loop; ``max_consecutive_failures`` (default 3) ends it
  with an honest reason rather than burning the night on it.
* **Finishing is graded, never asserted.** The supervisor calls the verifier and
  then the judge; it has no way to mark a run succeeded itself.
* **A parked run spends nothing (H464).** While a barrier holds — a process, a
  trigger, a clock — a tick returns ``waiting`` after the stop and budget checks
  and before planning or grading: no step, no plan, no judge call. The planner can
  ask to park (``Action(kind="wait", barrier=…)``) and so can the judge's wait
  probe, before any verdict is spent; either way the barrier only suppresses work.
  A wait with nothing left to wait on (the task already finished, the process
  already exited, the owner already let the run go from it) costs nothing either,
  nor does one whose check failed for a moment (a locked queue, a probe that
  raised): the tick is ``idle`` and the next one plans again, told why its wait
  was refused (``last_wait_refused``). Free is not unbounded: after
  ``MAX_FREE_WAIT_REFUSALS`` such refusals in a row — reset by a real step, a park
  or a grade — the next one is a failed ``plan`` step, so the streak rule stops a
  planner that keeps asking. A malformed or forbidden wait is a failed ``plan``
  step at once.

  When the plan is done but a task this run queued was approved and is still
  executing, the hub parks the run on it (``task:<id>``, source ``hub``) BEFORE
  any grader is asked — the checklist moves on when a task is approved, not when
  it finishes, and grading then would spend the run's only verdicts on work that
  has not landed (H464b). At most once per task per run, never on a task the
  owner let the run go from, and any failure to check or set it falls through to
  grading exactly as before. The park spends wall-clock time, never a step or a
  verdict, and it stops a grading margin short of the run's end so the run can
  still be graded when it runs out (H464c).

The planner is injected (``plan_next``) and returns either an :class:`Action` or
``None`` meaning "nothing left to do" — at which point the run goes to grading —
or a :class:`Hold` meaning "I cannot say what is next" (H464c), which is never
read as "done": a plan that cannot be read just now holds the tick (no step, no
park, no grade; the next tick asks again), and one that provably cannot be run —
its approval does not bind, or an approved row is refused — stops the run with the
reason on its record, the way a stuck run is stopped, rather than grading a
checklist nobody can prove was finished.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agents.core.autonomy.run_barriers import (
    MAX_JUDGE_WAITS,
    NOTHING_TO_WAIT_ON,
    WAIT_CHECK_FAILED,
)
from agents.core.autonomy.work_runs import WorkRunError

logger = logging.getLogger("jarvis.company_supervisor")

FLAG = "JARVIS_COMPANY_MODE"

# Why a tick stopped doing anything. Each maps to one honest sentence in the
# brief; there is deliberately no "unknown" — a tick always knows why it ended.
TICK_OUTCOMES = (
    "stepped",        # one action was arranged and recorded
    "graded",         # the plan was exhausted, so the run was verified and judged
    "stopped",        # the owner's stop was honoured
    "exhausted",      # a budget ended the run
    "blocked",        # the run is waiting on an approval and cannot proceed
    "disabled",       # company mode is off
    "idle",           # the run is already terminal; nothing to do
    "waiting",        # parked on a process, a trigger or a clock (H464)
)

# The action kind that parks the run instead of doing anything (H464).
_WAIT_KIND = "wait"

# Free planner-wait refusals (nothing to wait on, or a check that failed for a
# moment) allowed in a row before the next one is charged as a failed plan step
# (H464 review round 2, N1). Free keeps a finished build from costing a step; the
# bound keeps a planner that asks for it on every sweep from spending the night on
# model calls with nothing to show — the streak rule then ends the run.
MAX_FREE_WAIT_REFUSALS = 3
#: The failed-step reason once a planner is past its free wait refusals.
OVER_LIMIT_WAIT = "the planner keeps asking for waits that cannot be set"


@dataclass(frozen=True)
class Action:
    """One thing the run wants to do next, as the planner describes it.

    ``kind`` is the step kind (also the goal-scope key the judge checks) and
    ``task`` is what will be handed to the governed intake. The supervisor never
    inspects ``task`` beyond passing it on: interpreting it would make this
    component an authoriser, which it must not be.

    Only an action carrying a ``barrier`` parks the run, and only ``kind="wait"``
    may carry one. A ``wait`` with no barrier is an owner-approved checklist row
    that happens to be named "wait": it carries a task, and it is queued like any
    other row (H464 review F5) — the model planner refuses a barrier-less wait
    itself, before it ever gets here.
    """

    kind: str
    summary: str
    task: dict[str, Any] = field(default_factory=dict)
    interrupts_owner: bool = False
    # H464: only on ``kind="wait"`` — what to park the run on instead of doing
    # anything. A wait never reaches the governed intake and never becomes a step.
    barrier: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not str(self.kind or "").strip():
            raise ValueError("action kind is required")
        if not str(self.summary or "").strip():
            raise ValueError("action summary is required")
        if self.barrier is not None and self.kind != _WAIT_KIND:
            raise ValueError("only a wait action carries a barrier")
        if self.barrier is not None and not isinstance(self.barrier, Mapping):
            raise ValueError("a barrier is a mapping")

    @property
    def parks(self) -> bool:
        """True when this action asks to park the run rather than do anything."""
        return self.barrier is not None


@dataclass(frozen=True)
class Hold:
    """The planner cannot say what the run should do next (H464c).

    ``stop=False``: it cannot tell *right now* (the approval task could not be
    read). The tick does nothing — no step, no park, no grade — and says so; the
    next tick asks again. ``stop=True``: it can prove the plan cannot be run (the
    approval does not bind to this run, or an approved row is refused). The run
    is stopped with ``reason`` on its record. Either way the run is never graded
    as though its checklist were finished.
    """

    reason: str
    stop: bool = False


@dataclass(frozen=True)
class SupervisorConfig:
    enabled: bool = False
    max_consecutive_failures: int = 3
    # Ticks per wake. One is the honest default: a caller that wants more should
    # say so, and each still spends one step of budget.
    max_ticks_per_wake: int = 1


@dataclass(frozen=True)
class TickResult:
    outcome: str
    detail: str
    run_id: str
    step_seq: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "detail": self.detail,
            "run_id": self.run_id,
            "step_seq": self.step_seq,
        }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class CompanySupervisor:
    """Drives one work run forward, one governed step at a time.

    ``enqueue`` is the governed intake (the worker's ``govern_enqueue``): it
    returns a durable task id, or raises. ``plan_next`` proposes the next action.
    ``verify`` and ``judge`` are the graders. ``stop_requested`` lets an outside
    signal (the HUD, a kill switch) end the run between ticks.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        enqueue: Callable[..., Any],
        plan_next: Callable[..., Any],
        verify: Callable[..., Any] | None = None,
        judge: Callable[..., Any] | None = None,
        stop_requested: Callable[[str], bool] | None = None,
        config: SupervisorConfig | None = None,
        barrier_active: Callable[[str], bool] | None = None,
        barriers: Any = None,
        judge_wait: Callable[[str], Any] | None = None,
    ) -> None:
        self._ledger = ledger
        self._enqueue = enqueue
        self._plan_next = plan_next
        self._verify = verify
        self._judge = judge
        self._stop_requested = stop_requested
        # H464: ``barriers`` is the RunBarriers that sets and describes barriers;
        # ``barrier_active`` is its check (defaulting to it). ``judge_wait`` is the
        # judge's wait probe: run_id -> a barrier request, or None.
        self._barriers = barriers
        self._barrier_active = barrier_active or (
            barriers.active if barriers is not None else None
        )
        self._judge_wait = judge_wait
        self.config = config or SupervisorConfig()
        # Per-run failure streaks. In-memory on purpose: after a restart the run
        # deserves a fresh attempt at whatever it was stuck on, and the durable
        # budget still bounds how long that can go on.
        self._streaks: dict[str, tuple[str, int]] = {}
        # Per-run free wait refusals in a row, and the last refusal's reason (what
        # the planner is told). In memory for the same reason as the streaks.
        self._free_refusals: dict[str, int] = {}
        self._last_refused: dict[str, str] = {}

    # ── the loop ─────────────────────────────────────────────────────────

    async def run_until_settled(self, run_id: str) -> list[TickResult]:
        """Tick until the run stops making progress or settles. Bounded by config."""
        results: list[TickResult] = []
        for _ in range(max(1, self.config.max_ticks_per_wake)):
            result = await self.tick(run_id)
            results.append(result)
            if result.outcome != "stepped":
                break
        return results

    async def tick(self, run_id: str) -> TickResult:
        """Advance the run by at most one governed step."""
        if not self.config.enabled:
            return TickResult("disabled", "company mode is off", run_id)

        run = self._ledger.get(run_id)
        if run is None:
            return TickResult("idle", "unknown run", run_id)
        if run.terminal:
            return TickResult("idle", f"run is already {run.status}", run_id)

        # Stop is read first, before planning: a stop that arrived while the last
        # tick was running must not be overtaken by one more step.
        if self._stop_requested is not None and self._stop_requested(run_id):
            return self._honour_stop(run_id, run.status)
        if run.status == "stopping":
            return self._honour_stop(run_id, run.status)

        budget = self._ledger.budget_state(run_id)
        if budget["exceeded"]:
            return self._settle_exhausted(run_id, budget["exceeded"])
        if run.status == "blocked":
            return TickResult(
                "blocked", "waiting on an outstanding approval", run_id
            )
        # Parked: after stop and budget, so an owner stop or a spent budget always
        # settles even a parked run; before planning and grading, so waiting on a
        # build costs no step, no plan and no judge call.
        if self._barrier_active is not None:
            try:
                if self._barrier_active(run_id):
                    return TickResult("waiting", f"parked: {self._waiting_on(run_id)}", run_id)
            except Exception:
                logger.debug("barrier check failed; ticking normally", exc_info=True)

        context: dict[str, Any] = {"run": run.as_dict(), "budget": budget}
        if run_id in self._last_refused:
            # So a model planner can learn why its last wait was not set.
            context["last_wait_refused"] = self._last_refused[run_id]
        action = await _maybe_await(self._plan_next(context))
        if isinstance(action, Hold):
            return self._hold(run_id, action)
        if action is None:
            self._reset_free_refusals(run_id)
            return await self._grade(run_id)
        if not isinstance(action, Action):
            # A planner that returned something unusable is a bug, not a licence
            # to improvise: record it as a failed step so the streak rule sees it.
            return self._record_failure(
                run_id, "plan", "planner returned something that is not an Action"
            )

        return await self._arrange(run_id, action)

    # ── one step ─────────────────────────────────────────────────────────

    async def _arrange(self, run_id: str, action: Action) -> TickResult:
        """Hand one action to the governed intake and record what came back."""
        if action.parks:
            return self._park(run_id, action)
        try:
            task_id = await _maybe_await(self._enqueue(**dict(action.task)))
        except Exception as exc:
            return self._record_failure(
                run_id, action.kind,
                f"the governed intake refused it: {exc.__class__.__name__}",
                summary=action.summary,
            )
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            return self._record_failure(
                run_id, action.kind, "the governed intake returned no durable task",
                summary=action.summary,
            )

        # The task exists but has not been decided: that is a queued step, and the
        # run blocks on it. Claiming the work is done here would be the lie this
        # whole chain exists to prevent.
        try:
            step = self._ledger.record_step(
                run_id,
                kind=action.kind,
                summary=action.summary,
                outcome="queued",
                task_id=task_id,
                interrupted=action.interrupts_owner,
            )
        except WorkRunError as exc:
            return self._settle_from_ledger_refusal(run_id, exc.reason)
        self._streaks.pop(run_id, None)
        self._reset_free_refusals(run_id)
        return TickResult(
            "stepped", f"queued task {task_id} for approval", run_id, step.seq
        )

    def _park(self, run_id: str, action: Action) -> TickResult:
        """The planner asked to wait: set the barrier instead of doing anything.

        Never enqueues and never records a step. A wait with nothing to wait on
        (:data:`NOTHING_TO_WAIT_ON` — the task finished while the planner thought,
        the process already exited, the owner let the run go from this very wait)
        or whose check failed for a moment (:data:`WAIT_CHECK_FAILED` — a locked
        queue, a probe that raised) is not a failure: no step, no budget, and the
        next tick plans again, told why. Only ``MAX_FREE_WAIT_REFUSALS`` of those in
        a row, though; after that each one is a failed ``plan`` step, so the streak
        rule ends a planner that keeps asking instead of letting it loop for free
        until the wall clock runs out (N1). A malformed or forbidden wait goes down
        the road of any unusable plan at once. Nothing raised here leaves the tick.
        """
        if self._barriers is None:
            return self._record_failure(run_id, "plan", "waits are not wired")
        try:
            state = self._barriers.request(run_id, action.barrier, source="planner")
        except WorkRunError as exc:
            self._last_refused[run_id] = exc.reason
            if exc.reason in NOTHING_TO_WAIT_ON or exc.reason in WAIT_CHECK_FAILED:
                return self._free_refusal(run_id, exc.reason)
            return self._record_failure(run_id, "plan", f"invalid wait: {exc.reason}")
        except Exception as exc:
            # The last resort: RunBarriers converts its readers' failures to
            # refusals, so this is a bug — bounded by the streak, never a tick
            # that raises on every sweep and bounds nothing.
            logger.warning("setting a planner wait failed on run %s", run_id, exc_info=True)
            self._last_refused[run_id] = exc.__class__.__name__
            return self._record_failure(
                run_id, "plan", f"invalid wait: {exc.__class__.__name__}"
            )
        # A park on real async work (a task or hook trigger, a process) starts the
        # free-refusal count over; a clock park does not (review round 2 verify, R1),
        # or a planner could buy three more free refusals by parking on a short
        # clock every fourth ask and never reach the streak's stop.
        if str((action.barrier or {}).get("kind")) != "deadline":
            self._reset_free_refusals(run_id)
        else:
            self._last_refused.pop(run_id, None)
        return TickResult("waiting", f"parked: {state.get('waiting_on') or 'a barrier'}", run_id)

    def _hold(self, run_id: str, hold: Hold) -> TickResult:
        """The planner cannot say what is next: do nothing now, or end the run with
        the reason — never grade it (H464c)."""
        reason = str(hold.reason or "the plan cannot be read")[:160]
        if not hold.stop:
            logger.info("run %s held: %s", run_id, reason)
            return TickResult("idle", f"held: {reason}", run_id)
        self._streaks.pop(run_id, None)
        self._reset_free_refusals(run_id)
        try:
            self._ledger.request_stop(run_id, reason=f"plan not bound to its approval: {reason}")
            self._ledger.settle_stop(run_id)
        except WorkRunError as exc:
            return TickResult("idle", f"stop refused: {exc.reason}", run_id)
        logger.warning("run %s stopped: its plan cannot be proven (%s)", run_id, reason)
        return TickResult("stopped", f"the approved plan cannot be proven: {reason}", run_id)

    def _free_refusal(self, run_id: str, reason: str) -> TickResult:
        """A planner wait refused for a reason that is not the planner's fault: free,
        up to ``MAX_FREE_WAIT_REFUSALS`` in a row; after that a failed plan step the
        streak rule sees. The count is not reset by that failure, so a planner that
        keeps asking reaches the streak's stop instead of three more free ticks."""
        count = self._free_refusals.get(run_id, 0) + 1
        self._free_refusals[run_id] = count
        transient = reason in WAIT_CHECK_FAILED
        if count > MAX_FREE_WAIT_REFUSALS:
            # One fixed reason, so the streak rule counts every over-limit ask
            # whatever was refused (R2); the particular refusal is the summary.
            return self._record_failure(
                run_id, "plan", OVER_LIMIT_WAIT,
                summary=f"{OVER_LIMIT_WAIT}: {reason}",
            )
        logger.info("run %s: planner wait refused (%s), %d in a row; planning again",
                    run_id, reason, count)
        what = "the wait could not be checked" if transient else "nothing to wait on"
        return TickResult("idle", f"{what}: {reason}", run_id)

    def _reset_free_refusals(self, run_id: str) -> None:
        self._free_refusals.pop(run_id, None)
        self._last_refused.pop(run_id, None)

    def _waiting_on(self, run_id: str) -> str:
        try:
            state = self._barriers.state(run_id) if self._barriers is not None else None
        except Exception:
            state = None
        return str((state or {}).get("waiting_on") or "a barrier")

    def _record_failure(
        self, run_id: str, kind: str, detail: str, *, summary: str = ""
    ) -> TickResult:
        """Record a failed step and end the run if the same failure keeps repeating."""
        try:
            step = self._ledger.record_step(
                run_id,
                kind=kind,
                summary=summary or detail,
                outcome="failed",
                detail={"reason": detail},
            )
        except WorkRunError as exc:
            return self._settle_from_ledger_refusal(run_id, exc.reason)

        previous, count = self._streaks.get(run_id, ("", 0))
        count = count + 1 if previous == detail else 1
        self._streaks[run_id] = (detail, count)
        if count >= max(1, self.config.max_consecutive_failures):
            self._streaks.pop(run_id, None)
            self._reset_free_refusals(run_id)
            try:
                self._ledger.request_stop(run_id, reason=f"stuck: {detail}")
                self._ledger.settle_stop(run_id)
            except WorkRunError:
                logger.warning("could not settle a stuck run: %s", run_id, exc_info=True)
            return TickResult(
                "stopped", f"the same failure {count}x in a row: {detail}", run_id, step.seq
            )
        return TickResult("stepped", detail, run_id, step.seq)

    # ── settling ─────────────────────────────────────────────────────────

    def _honour_stop(self, run_id: str, status: str) -> TickResult:
        try:
            if status != "stopping":
                self._ledger.request_stop(run_id, reason="owner")
            self._ledger.settle_stop(run_id)
        except WorkRunError as exc:
            return TickResult("idle", f"stop refused: {exc.reason}", run_id)
        return TickResult("stopped", "the owner stopped the run", run_id)

    def _settle_exhausted(self, run_id: str, limit: str) -> TickResult:
        """A spent budget ends the run. The ledger already moves it on the next
        step attempt; doing it here means the loop stops immediately instead of
        waiting for one more refused attempt."""
        run = self._ledger.get(run_id)
        if run is not None and run.status not in {"exhausted", "stopped"}:
            try:
                self._ledger.request_stop(run_id, reason=f"budget:{limit}")
                self._ledger.settle_stop(run_id)
            except WorkRunError:
                logger.debug("run already settling: %s", run_id, exc_info=True)
        return TickResult("exhausted", f"the {limit} budget is spent", run_id)

    def _settle_from_ledger_refusal(self, run_id: str, reason: str) -> TickResult:
        """The ledger refused a step. It has already moved the run; report why."""
        if reason.startswith("budget_exhausted:"):
            return TickResult("exhausted", f"the {reason.split(':', 1)[1]} budget is spent", run_id)
        if reason in {"run_stopping", "run_stopped"}:
            return TickResult("stopped", "the run was stopped", run_id)
        return TickResult("idle", reason, run_id)

    async def _grade(self, run_id: str) -> TickResult:
        """No work left: wait for this run's own in-flight tasks, then verify, then
        judge. The supervisor never decides itself.

        The hub's park comes first — before the "no grader is wired" answer and
        before the judge is asked whether to wait — so a task that is still running
        is waited on whatever graders are (or are not) wired.
        """
        parked = self._hub_parks(run_id)
        if parked is not None:
            return parked
        if self._verify is None or self._judge is None:
            return TickResult(
                "idle", "no work left, and no grader is wired to settle the run", run_id
            )
        parked = await self._judge_parks(run_id)
        if parked is not None:
            return parked
        report = await _maybe_await(self._verify(run_id))
        judgement = await _maybe_await(self._judge(run_id))
        passed = bool(getattr(judgement, "passed", False))
        reason = str(getattr(judgement, "reason", "") or "")
        detail = f"{'met' if passed else 'not met'}: {reason}"
        if not passed and getattr(report, "passed", True) is False:
            detail = f"not met: {getattr(report, 'reason', '') or reason}"
        return TickResult("graded", detail, run_id)


    def _hub_parks(self, run_id: str) -> TickResult | None:
        """Park a finished plan on its own in-flight task, or None (H464b).

        ``RunBarriers.park_in_flight`` picks the oldest task this run queued that
        was approved and has not finished, at most once per task and never one the
        owner let the run go from. The park is an event, not a step: no step, no
        plan, no verdict. It does spend wall-clock time, so it ends the grading
        margin short of the run's end and the run can still be graded (H464c).
        Anything it refuses (a spent budget, no time left, the
        barrier limit, a queue that cannot be read) or raises reads as "not
        waiting", and the run goes on to grading exactly as it did before — a check
        that cannot answer never wedges a run.
        """
        park = getattr(self._barriers, "park_in_flight", None)
        if self._barriers is None or not callable(park):
            return None
        try:
            state = park(run_id)
        except WorkRunError as exc:
            logger.info("run %s: no hub park (%s); grading", run_id, exc.reason)
            return None
        except Exception:
            logger.warning("the hub park failed on run %s; grading", run_id, exc_info=True)
            return None
        if not state:
            return None
        return TickResult("waiting", f"parked: {state.get('waiting_on') or 'a barrier'}", run_id)

    async def _judge_parks(self, run_id: str) -> TickResult | None:
        """Ask the judge whether to wait, BEFORE any verdict is spent — and only
        after the hub's own park on in-flight tasks (:meth:`_hub_parks`) found
        nothing to wait on.

        The ledger takes one verdict per role per run, so a wait decided after
        ``verify`` would have burned the verifier's only verdict on stale evidence.
        Asking first means grading starts clean once the barrier clears. Bounded to
        ``MAX_JUDGE_WAITS`` per run; a probe that fails, answers anything but a
        valid barrier, asks for a wait that is refused (the owner's clear included)
        or whose setting raises anything at all falls through to ordinary grading.
        """
        if self._judge_wait is None or self._barriers is None:
            return None
        try:
            if self._ledger.barrier_set_count(run_id, source="judge") >= MAX_JUDGE_WAITS:
                return None
            request = await _maybe_await(self._judge_wait(run_id))
        except Exception:
            logger.warning("the judge's wait probe failed; grading instead", exc_info=True)
            return None
        if not isinstance(request, Mapping):
            return None
        try:
            state = self._barriers.request(run_id, request, source="judge")
        except WorkRunError as exc:
            logger.info("the judge asked for a wait that was refused (%s); grading", exc.reason)
            return None
        except Exception:
            logger.warning("setting the judge's wait failed on run %s; grading", run_id,
                           exc_info=True)
            return None
        return TickResult(
            "waiting", f"the judge asked to wait: {state.get('waiting_on') or 'a barrier'}",
            run_id,
        )


__all__ = [
    "FLAG",
    "MAX_FREE_WAIT_REFUSALS",
    "TICK_OUTCOMES",
    "Action",
    "CompanySupervisor",
    "Hold",
    "SupervisorConfig",
    "TickResult",
]
