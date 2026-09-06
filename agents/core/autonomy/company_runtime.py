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
* **The planner is a checklist, from the approved goal, by default.** The plan
  the owner read on the card is the plan that runs. A model planner is available
  and must be passed in explicitly: "let a model decide what to do all night" is
  precisely the thing that has to be opted into rather than defaulted to.
* **A goal approved with no plan proposes nothing** and goes straight to grading.
  "You approved a goal with no plan, so nothing happened" is a better outcome
  than a model improvising a night's work from a one-line title, and it is the
  only reading under which approving the goal and approving the work are the
  same act.
* **A sweep never raises into the scheduler.** One bad run must not silently
  unregister the job that would have recovered it.

Nothing here can authorise. The supervisor hands every effect to the governed
intake, the reconciler can only unblock a run, and opening a run still requires
an owner-approved goal decided in the inbox.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents.core.autonomy.company_planner import ChecklistPlanner
from agents.core.autonomy.company_supervisor import CompanySupervisor, SupervisorConfig
from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.schedule_runtime import ScheduleConfig, ScheduleRuntime
from agents.core.autonomy.work_runs import FLAG, WorkRunLedger

logger = logging.getLogger("jarvis.company_runtime")

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


def _plan_for(ledger: Any, run: Any, goals: Any) -> ChecklistPlanner:
    """The planner for one run: the checklist the owner approved, and no more.

    An unreadable or missing goal yields an EMPTY checklist rather than an
    unrestricted one. A planner that proposes nothing wastes a night; a planner
    that proposes anything, because it could not read what it was allowed to do,
    is the failure this whole chain exists to prevent.
    """
    steps: list[Any] = []
    scope: frozenset[str] = frozenset()
    try:
        goal = goals(run.goal_id) if callable(goals) else None
    except Exception:
        logger.warning("could not read the approved goal for %s", run.goal_id, exc_info=True)
        goal = None
    if goal is not None:
        try:
            steps = goal.plan_steps()
            scope = goal.scope_kinds
        except Exception:
            logger.warning("approved goal for %s is unreadable", run.goal_id, exc_info=True)
            steps = []
    return ChecklistPlanner(steps, scope_kinds=scope, ledger=ledger)


def build_company_runtime(
    orch: Any,
    *,
    enqueue: Callable[..., Any] | None = None,
    read_task: Callable[[int], Any] | None = None,
    goals: Callable[[str], Any] | None = None,
    planner: Callable[..., Any] | None = None,
    verify: Callable[..., Any] | None = None,
    judge: Callable[..., Any] | None = None,
    config: ScheduleConfig | None = None,
    supervisor_config: SupervisorConfig | None = None,
) -> CompanyRuntime | None:
    """Build the chain, or return ``None`` and say why in the log.

    ``None`` is not an error: it is the ordinary state of a product where nobody
    turned company mode on. Every reason it can return is a *named* one, because
    "company mode did nothing last night" is a question that has to be answerable.
    """
    if not flag_enabled():
        logger.debug("company mode is off; no runtime built")
        return None

    ledger = getattr(orch, "work_runs", None)
    if not isinstance(ledger, WorkRunLedger):
        logger.warning("company mode is on but no work-run ledger is bound; nothing will run")
        return None

    queue = getattr(orch, "task_queue", None) or getattr(orch, "queue", None)
    reader = read_task or (getattr(queue, "get", None) if queue is not None else None)
    reasons: list[str] = []
    if reader is None:
        # Without a queue reader an approved task can never unblock its run, so the
        # first ask would block the night forever. Say so rather than discovering it
        # at 3am.
        reasons.append("no task queue bound — a blocked run can never be resumed")
        reconciler = None
    else:
        reconciler = PendingRequests(ledger, read_task=reader)

    intake = enqueue or getattr(orch, "govern_enqueue", None)
    if intake is None:
        logger.warning("company mode is on but no governed intake is bound; nothing will run")
        return None

    def _plan_next(context):
        run_id = dict(context.get("run") or {}).get("id")
        run = ledger.get(run_id) if run_id else None
        if run is None:
            return None
        chosen = planner or _plan_for(ledger, run, goals)
        return chosen(context)

    supervisor = CompanySupervisor(
        ledger,
        enqueue=intake,
        plan_next=_plan_next,
        verify=verify,
        judge=judge,
        config=supervisor_config or SupervisorConfig(enabled=True),
    )
    scheduler = ScheduleRuntime(
        ledger,
        tick=supervisor.tick,
        reconcile=(reconciler.sweep if reconciler is not None else None),
        config=config or ScheduleConfig(enabled=True),
    )
    if planner is not None:
        reasons.append("a planner was supplied explicitly; the approved checklist is not in use")
    logger.info("company mode runtime built%s", f" ({'; '.join(reasons)})" if reasons else "")
    return CompanyRuntime(
        RuntimeParts(
            ledger=ledger, supervisor=supervisor,
            scheduler=scheduler, reconciler=reconciler,
            reasons=tuple(reasons),
        )
    )
