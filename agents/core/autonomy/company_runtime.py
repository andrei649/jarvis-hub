"""company_runtime.py — the wiring that makes company mode actually run.

Everything else in the chain is a component: a ledger, a planner, a supervisor,
graders, a reconciler, a scheduler. Until this module they were nine parts that
never met, which is a specific kind of dishonesty — the tests all pass, the
documentation is accurate, and no night of work ever happens.

This builds the whole chain from an orchestrator and hands back one object with
one method the scheduler can call. It owns no policy: every rule already lives in
the component that enforces it. What it owns is *whether anything is built at
all*, and the answers to that are deliberate:

* **Off means nothing is constructed**, not "constructed but inert". A supervisor
  that exists is a supervisor something can call.
* **Turning it off takes effect immediately; turning it on needs a restart.**
  Each sweep re-reads the flag, so clearing it stops work at the next tick. But
  nothing registers unless the flag was set at boot — a capability that can start
  a night of autonomous work should not begin because a config file changed while
  nobody was looking. The asymmetry is the point: stopping is always easy, and
  starting is always deliberate.
* **The planner is a checklist, from the approved goal, by default** — read
  back from the goal's own approval task (H464b): the task named in the run's
  ``approved_by`` is re-read from the durable queue, re-checked (a human accepted
  it) and bound to this run (same approval, title, deadline and budget, and — H464c
  — the very fingerprint the run pinned when it opened, never the one the payload
  now carries about itself). A read that fails just now HOLDS the run (no step, no
  park, no grade; the next sweep reads again); a goal that provably does not bind —
  a policy decision, an edit, another run's goal, a run opened with no pin — STOPS
  it with the reason on its record, and so does an approved row the planner has to
  refuse. Neither is ever graded as a finished checklist.
  The plan the owner read on the card is the plan that runs. A model planner is available
  and must be passed in explicitly: "let a model decide what to do all night" is
  precisely the thing that has to be opted into rather than defaulted to.
* **A goal approved with no plan proposes nothing** and goes straight to grading.
  "You approved a goal with no plan, so nothing happened" is a better outcome
  than a model improvising a night's work from a one-line title, and it is the
  only reading under which approving the goal and approving the work are the
  same act.
* **A sweep never raises into the scheduler.** One bad run must not silently
  unregister the job that would have recovered it.
* **Safe mode leaves it out (H464c).** A hub started in safe mode registers no
  sweep, and a sweep that finds safe mode on (it is read at call time) does nothing.
* **A parked run is skipped, not poked (H464).** One :class:`RunBarriers` is built
  over the ledger, the task reader and the webhook store, and its check is handed
  to both the scheduler and the supervisor. It is not an orchestrator slot: it
  lives here, on :class:`RuntimeParts`, with the rest of the chain. With the
  orchestrator's own queue as its reader (H464b), a finished plan waits on its
  own approved tasks that are still running before it is graded.

Nothing here can authorise. The supervisor hands every effect to the governed
intake, the reconciler can only unblock a run, and opening a run still requires
an owner-approved goal decided in the inbox.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents.core.autonomy.company_planner import ChecklistPlanner
from agents.core.autonomy.company_supervisor import CompanySupervisor, Hold, SupervisorConfig
from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.run_barriers import RunBarriers, grade_margin
from agents.core.autonomy.schedule_runtime import ScheduleConfig, ScheduleRuntime
from agents.core.autonomy.work_runs import FLAG, WorkRunError, WorkRunLedger

logger = logging.getLogger("jarvis.company_runtime")

# ``approved_by`` as ``approve_from_task`` writes it: ``task:<id>:<decider>``.
_APPROVED_BY_TASK = re.compile(r"^task:(\d+):(.+)$")

__all__ = ["CompanyRuntime", "RuntimeParts", "build_company_runtime", "flag_enabled"]


def flag_enabled() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(FLAG)


@dataclass
class RuntimeParts:
    """What was built, for the status surface and for tests."""

    ledger: Any
    supervisor: Any
    scheduler: Any
    reconciler: Any
    reasons: tuple[str, ...] = field(default=())
    barriers: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "built": True,
            "reasons": list(self.reasons),
        }


class CompanyRuntime:
    """One sweep, on a timer. The scheduler calls :meth:`sweep` and nothing else."""

    def __init__(
        self,
        parts: RuntimeParts,
        *,
        enabled: Callable[[], bool] = flag_enabled,
    ) -> None:
        self.parts = parts
        self._enabled = enabled

    async def sweep(self) -> dict[str, Any]:
        """Advance whatever is due. Never raises — the scheduler owns the timer.

        The flag is re-read here, not cached at construction: clearing it must
        stop work at the very next tick rather than at the next restart.
        """
        if not self._enabled():
            return {"ok": True, "swept": 0, "reason": "company mode is off"}
        from agents.core import safe_mode

        if safe_mode.enabled():
            safe_mode.note("company_mode")
            return {"ok": True, "swept": 0, "reason": "safe mode is on"}
        try:
            result = await self.parts.scheduler.sweep()
        except Exception as exc:
            logger.warning("company sweep failed", exc_info=True)
            return {"ok": False, "swept": 0, "reason": exc.__class__.__name__}
        return {
            "ok": True,
            "swept": len(result.ticked),
            "ticked": list(result.ticked),
            "skipped": dict(result.skipped),
        }

    def snapshot(self) -> dict[str, Any]:
        """What is running, for the HUD. Honest when nothing is."""
        try:
            base = self.parts.scheduler.snapshot()
        except Exception:
            logger.debug("scheduler snapshot unavailable", exc_info=True)
            base = {}
        # Two different facts, and they used to share one key: the scheduler's
        # own `enabled` is its config, while `enabled` here is the gate that
        # decides whether a sweep does anything at all. Spreading `base` last let
        # the config shadow the gate, so a runtime with the flag cleared still
        # reported itself as enabled. They are named apart now.
        scheduler_enabled = base.pop("enabled", None)
        return {
            **base,
            "enabled": self._enabled(),
            "scheduler_enabled": scheduler_enabled,
            "reasons": list(self.parts.reasons),
        }


def _webhook_store() -> Any:
    """The canonical inbound-webhook store, built lazily on first use."""
    from agents.core.routers.webhooks import _get_webhook_store

    return _get_webhook_store()


def _first_callable(*candidates: Any) -> Callable[..., Any] | None:
    """The first candidate that is present (``is not None``) and callable."""
    for candidate in candidates:
        if candidate is not None and callable(candidate):
            return candidate
    return None


def _queue_reader(orch: Any, read_task: Any) -> Callable[[int], Any] | None:
    """The durable queue reader: the explicit one, else the orchestrator's queue.

    The shipped orchestrator names its queue ``autonomy_queue`` (orchestrator.py);
    ``task_queue`` and ``queue`` are the names older wiring and tests use. Each is
    tested for presence, never truthiness: an empty queue is still a queue.
    """
    candidates = [read_task]
    for name in ("task_queue", "queue", "autonomy_queue"):
        queue = getattr(orch, name, None)
        candidates.append(getattr(queue, "get", None) if queue is not None else None)
    return _first_callable(*candidates)


def _governed_intake(orch: Any, enqueue: Any) -> Callable[..., Any] | None:
    """The governed intake: the explicit one, else the orchestrator's own.

    In the shipped product it is the autonomy worker's ``govern_enqueue``
    (``orch.autonomy``, worker.py). Whichever is found, it is the same governed
    door: the policy decides, the caller's level is a floor, and the effective
    origin applies — nothing here widens what a step may do.
    """
    autonomy = getattr(orch, "autonomy", None)
    return _first_callable(
        enqueue,
        getattr(orch, "govern_enqueue", None),
        getattr(autonomy, "govern_enqueue", None) if autonomy is not None else None,
    )


@dataclass(frozen=True)
class _ReadBack:
    """What reading a run's approved goal back from its approval task found.

    ``goal`` when it binds. Otherwise ``reason`` names why not, and ``transient``
    says whether that is "cannot tell right now" (hold, read again next tick) or
    provable (the run is stopped with the reason)."""

    goal: Any = None
    reason: str = ""
    transient: bool = False


def _read_back(run: Any, read_task: Callable[[int], Any] | None) -> _ReadBack:
    """The goal this run was opened for, read back from its own approval task.

    The runs table keeps no plan: only ``approved_by = "task:<id>:<decider>"`` and,
    since H464c, the fingerprint of the goal the owner approved, pinned when the run
    opened. So the approval task is re-read from the durable queue and re-minted
    through :func:`approve_from_task` (a human accepted this very task), then bound
    to THIS run — the same approval, title, deadline and budget, and a payload that
    fingerprints to the PINNED value. The fingerprint the payload carries about
    itself proves nothing on its own: an edit can drop or recompute it. The goal is
    given the run's own ``goal_id`` (``approve_from_task`` mints a random one, and
    the judge's goal-identity rule needs the run's).

    Transient — the run holds: no reader bound, or a read that raised. Provable —
    the run is stopped: a run not opened from a goal card, a run with no pin (opened
    before it existed), a task that is gone (H262 retention may have purged it), a
    policy decision, an edited payload, a goal that belongs to another run, or
    anything at all that raises while the task that WAS read is re-minted or bound
    (H464d).
    """
    from agents.core.autonomy.goal_contract import GoalContractError

    match = _APPROVED_BY_TASK.match(str(getattr(run, "approved_by", "") or ""))
    if match is None:
        return _ReadBack(reason="not_opened_from_a_goal_card")
    pinned = str(getattr(run, "approved_fingerprint", "") or "")
    if not pinned:
        return _ReadBack(reason="no_approved_fingerprint")
    if read_task is None:
        return _ReadBack(reason="no_task_queue", transient=True)
    task_id = int(match.group(1))
    try:
        task = read_task(task_id)
    except Exception:
        logger.warning("could not read the approval task %s for run %s", task_id,
                       getattr(run, "id", "?"), exc_info=True)
        return _ReadBack(reason="approval_task_unreadable", transient=True)
    if task is None:
        return _ReadBack(reason="approval_task_gone")
    try:
        return _bind(run, task, task_id, pinned)
    except Exception as exc:
        # (H464d) The task WAS read, so re-minting and binding it is a function of
        # what the queue holds: whatever raised here raises again on every later
        # sweep. Only GoalContractError used to be caught, so an approval task edited
        # until Budget(...) no longer validates (WorkRunError) failed every tick and
        # left the run planning forever. Any failure is "provably not bound": the
        # run stops, with a public code on its record — never the exception's text,
        # which can carry the payload's.
        reason = _refusal_code(exc)
        logger.log(logging.INFO if isinstance(exc, GoalContractError) else logging.WARNING,
                   "approval task %s cannot drive run %s: %s (%s)", task_id,
                   getattr(run, "id", "?"), reason, exc.__class__.__name__)
        return _ReadBack(reason=reason)


# A code the read-back may put on a run's record (H464d): the bare, bounded codes
# the contract's and the ledger's refusals carry — nothing with a space or markup.
_PUBLIC_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _refusal_code(exc: Exception) -> str:
    """The stop reason for a re-mint or bind that raised: the refusal's own code
    when it is a :class:`GoalContractError` or :class:`WorkRunError` carrying a bare
    code (``invalid_max_steps``), else ``approval_task_unusable``."""
    from agents.core.autonomy.goal_contract import GoalContractError

    reason = getattr(exc, "reason", None)
    if (isinstance(exc, (GoalContractError, WorkRunError)) and isinstance(reason, str)
            and _PUBLIC_CODE.match(reason)):
        return reason
    return "approval_task_unusable"


def _bind(run: Any, task: Any, task_id: int, pinned: str) -> _ReadBack:
    """Re-mint the goal from the approval task that was read, and bind it to this
    run (:func:`_read_back`). Raises whatever re-minting raises; the caller turns it
    into a stop."""
    from agents.core.autonomy.goal_contract import approve_from_task

    goal = approve_from_task(task)
    try:
        bound = (
            goal.approved_by == run.approved_by
            and goal.title == run.title
            and float(goal.deadline_at) == float(run.deadline_at)
            and goal.budget.as_dict() == run.budget.as_dict()
        )
    except Exception:
        bound = False
    if not bound:
        logger.warning("approved goal does not match run %s (approval task %s)",
                       getattr(run, "id", "?"), task_id)
        return _ReadBack(reason="goal_does_not_match_run")
    if goal.approved_fingerprint != pinned:
        logger.warning("approval task %s no longer holds what was approved for run %s",
                       task_id, getattr(run, "id", "?"))
        return _ReadBack(reason="approved_goal_changed")
    return _ReadBack(goal=dataclasses.replace(goal, goal_id=run.goal_id))


def _approved_goal_for(run: Any, read_task: Callable[[int], Any] | None) -> Any:
    """The bound goal from :func:`_read_back`, or ``None`` on any doubt."""
    return _read_back(run, read_task).goal


def _checklist(ledger: Any, goal: Any) -> ChecklistPlanner:
    """The planner for one goal: the checklist the owner approved, and no more.

    An unreadable plan yields an EMPTY checklist rather than an unrestricted one. A
    planner that proposes nothing wastes a night; a planner that proposes anything,
    because it could not read what it was allowed to do, is the failure this whole
    chain exists to prevent.
    """
    steps: list[Any] = []
    scope: frozenset[str] = frozenset()
    if goal is not None:
        try:
            steps = goal.plan_steps()
            scope = goal.scope_kinds
        except Exception:
            logger.warning("approved goal is unreadable", exc_info=True)
            steps = []
    return ChecklistPlanner(steps, scope_kinds=scope, ledger=ledger)


def _plan_for(ledger: Any, run: Any, goals: Any) -> ChecklistPlanner:
    """The checklist of an injected goal reader (``goals=``): an unreadable or
    missing goal is an EMPTY checklist, as before H464c."""
    try:
        goal = goals(run.goal_id)
    except Exception:
        logger.warning("could not read the approved goal for %s", run.goal_id, exc_info=True)
        goal = None
    return _checklist(ledger, goal)


async def _walk(checklist: ChecklistPlanner, context: Any) -> Any:
    """The next approved row — or, when the planner has to refuse one, a stop.

    An approved row outside the goal's scope (its kind, or the kind of the task it
    would queue) can never run, so the checklist can never be finished: that is not
    "nothing left to do", and grading it as such would call a half-run plan done
    (H464c). The run is stopped with the refusal on its record instead, named as a
    scope refusal (H464d): the approval did bind, the goal's own scope refused the row.
    """
    action = await checklist(context)
    decision = checklist.last
    if action is None and decision is not None and decision.refusal == "out_of_scope":
        return Hold(decision.detail, stop=True, cause="scope")
    return action


def build_company_runtime(
    orch: Any,
    *,
    enqueue: Callable[..., Any] | None = None,
    read_task: Callable[[int], Any] | None = None,
    goals: Callable[[str], Any] | None = None,
    planner: Callable[..., Any] | None = None,
    verify: Callable[..., Any] | None = None,
    judge: Callable[..., Any] | None = None,
    judge_wait: Callable[[str], Any] | None = None,
    config: ScheduleConfig | None = None,
    supervisor_config: SupervisorConfig | None = None,
    sweep_seconds: float | None = None,
) -> CompanyRuntime | None:
    """Build the chain, or return ``None`` and say why in the log.

    ``None`` is not an error: it is the ordinary state of a product where nobody
    turned company mode on. Every reason it can return is a *named* one, because
    "company mode did nothing last night" is a question that has to be answerable.

    ``sweep_seconds`` is how often the scheduler will call :meth:`CompanyRuntime.sweep`
    (the per-run interval when not given). With the scheduler's per-run interval it
    sets how far short of the run's end the hub's park before grading stops
    (:func:`~agents.core.autonomy.run_barriers.grade_margin`, H464d): the whole sweeps
    until the one the interval lets tick the run again, plus a minute — so a park
    that runs to its cap is still graded inside the run's time.
    """
    if not flag_enabled():
        logger.debug("company mode is off; no runtime built")
        return None

    ledger = getattr(orch, "work_runs", None)
    if not isinstance(ledger, WorkRunLedger):
        logger.warning("company mode is on but no work-run ledger is bound; nothing will run")
        return None

    reader = _queue_reader(orch, read_task)
    reasons: list[str] = []
    if reader is None:
        # Without a queue reader an approved task can never unblock its run, so the
        # first ask would block the night forever. Say so rather than discovering it
        # at 3am.
        reasons.append("no task queue bound — a blocked run can never be resumed")
        reconciler = None
    else:
        reconciler = PendingRequests(ledger, read_task=reader)

    intake = _governed_intake(orch, enqueue)
    if intake is None:
        logger.warning("company mode is on but no governed intake is bound; nothing will run")
        return None
    # Only now that the runtime builds (H464c, N2): the reader turns H487 approval
    # credit on for every user of this shared ledger, the report routes included.
    ledger.bind_approval_task_reader(reader)
    schedule = config or ScheduleConfig(enabled=True)

    def _plan_next(context):
        run_id = dict(context.get("run") or {}).get("id")
        run = ledger.get(run_id) if run_id else None
        if run is None:
            return None
        if planner is not None:
            return planner(context)
        if callable(goals):
            return _walk(_plan_for(ledger, run, goals), context)
        found = _read_back(run, reader)
        if found.goal is None:
            return Hold(found.reason, stop=not found.transient)
        return _walk(_checklist(ledger, found.goal), context)

    # Without a queue reader a task trigger is refused rather than guessed; the
    # webhook store is resolved only when a hook trigger is actually used. The
    # hub's park leaves room for the sweep that grades the run (H464d): one sweep
    # was not enough when the cadence is under the per-run interval, since due()
    # keeps the run not_due until the interval is up.
    barriers = RunBarriers(
        ledger, read_task=reader, hooks=_webhook_store,
        grade_margin_seconds=grade_margin(
            interval_seconds=schedule.interval_seconds, sweep_seconds=sweep_seconds,
        ),
    )
    supervisor = CompanySupervisor(
        ledger,
        enqueue=intake,
        plan_next=_plan_next,
        verify=verify,
        judge=judge,
        config=supervisor_config or SupervisorConfig(enabled=True),
        barriers=barriers,
        judge_wait=judge_wait,
    )
    scheduler = ScheduleRuntime(
        ledger,
        tick=supervisor.tick,
        reconcile=(reconciler.sweep if reconciler is not None else None),
        config=schedule,
        barrier_active=barriers.active,
    )
    if planner is not None:
        reasons.append("a planner was supplied explicitly; the approved checklist is not in use")
    logger.info("company mode runtime built%s", f" ({'; '.join(reasons)})" if reasons else "")
    return CompanyRuntime(
        RuntimeParts(
            ledger=ledger, supervisor=supervisor,
            scheduler=scheduler, reconciler=reconciler,
            reasons=tuple(reasons), barriers=barriers,
        )
    )
