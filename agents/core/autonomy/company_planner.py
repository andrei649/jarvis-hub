"""company_planner.py — what should this work run do next?

The supervisor asks one question per tick: *next action, or nothing?* This module
answers it. It is the only place in the chain where a language model gets to
propose, which is exactly why it is also where the clamps live.

The design rule: **the planner proposes, the clamp disposes.** A proposal from a
model is untrusted input, no different from a webhook body, so it is validated
against the goal before it ever becomes an :class:`Action`:

* **Scope is enforced at proposal time**, not just at judgement time. A model that
  suggests running a shell command for a research-only goal is refused here, so
  the run never spends a step on work the judge would reject at the end. The
  task an action would queue is held to the same scope (H464c): its kind must be
  a scope kind or sit under one (``research.collect`` under ``research``), so a
  ``research`` row cannot queue a ``file.write`` task.
* **The step budget is respected before proposing.** With no budget left the
  planner returns ``None`` (nothing left to do) rather than proposing work that
  the ledger will refuse — a refusal loop is not a plan.
* **A repeat is not a plan.** A proposal matching a step the run already took is
  refused: repeating a step is how an agent loops forever while looking busy.
* **A proposer that fails proposes nothing.** An exception, a timeout, a malformed
  reply — all become ``None``. The supervisor then grades the run, which is the
  honest outcome: we ran out of ideas, not "we finished".
* **The planner never enqueues.** It returns a description; only the supervisor
  hands it to the governed intake.
* **A wait is not a step (H464).** A proposal ``{"kind": "wait", "barrier": …}``
  asks the supervisor to park the run instead of doing anything. It is exempt
  from the scope and repeat clamps — it never becomes a step row, so it is
  invisible to the judge's scope rule — and the barrier itself is validated where
  it is set, by ``RunBarriers``. A proposed wait with no barrier is malformed.
  An owner-approved *checklist* row that happens to be named "wait" is not a
  barrier — it carries a task and is queued like any other row (H464 review F5).

Two proposers ship. :class:`ChecklistPlanner` walks a fixed list written when the
goal was approved — fully deterministic, and the one to use when the owner wants
the run to do a known thing. :class:`ModelPlanner` wraps an injected async
callable (an LLM) behind the same clamps.

A checklist row is done once it reached the queue (H464d), not once anything was
recorded for it: a row whose intake failed (no durable task) is asked again on a
later tick, at most :data:`MAX_ROW_ATTEMPTS` times, and then the run stops with a
readable reason; a row the queue answered — approved, refused, lost or expired
unanswered — is done, because asking again would be a duplicate ask. And "I could
not read what was done" is never "nothing was done": the tick holds instead.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.core.autonomy.company_supervisor import Action, Hold
from agents.core.autonomy.goal_contract import task_kind_in_scope

logger = logging.getLogger("jarvis.company_planner")

# H464d — how many times one approved checklist row may fail to reach the queue
# (the governed intake raised, or handed back no durable task) before the planner
# stops the run instead of asking a fourth time. Durable: counted from the ledger's
# failed steps, so it holds across restarts and whatever the failures said. It is
# the backstop to the supervisor's streak rule (``max_consecutive_failures``, also
# 3 by default), which is in memory and needs the SAME failure in a row: a row
# failing identically three ticks running is stopped by the streak on its third
# failure ("stuck: …"); one whose failures differ, or straddle a restart or another
# outcome, is stopped here before its fourth attempt ("approved row failed too
# often: …"). Whichever is reached first ends the run; neither lets a row be tried
# more than three times with the defaults.
MAX_ROW_ATTEMPTS = 3
#: The transient hold when the run's steps cannot be read (H464d).
STEPS_UNREADABLE = "the run's steps could not be read"

# Why a proposal was refused. Every one is reported; a silently dropped proposal
# would look identical to "the model had no ideas", which is a different thing.
REFUSALS = (
    "out_of_scope",
    "already_done",
    "malformed",
    "proposer_failed",
    "budget_spent",
)

_MAX_SUMMARY = 500


@dataclass(frozen=True)
class PlanStep:
    """One entry of a checklist written when the goal was approved."""

    kind: str
    summary: str
    task: dict[str, Any]
    interrupts_owner: bool = False

    def __post_init__(self) -> None:
        if not str(self.kind or "").strip():
            raise ValueError("plan step kind is required")
        if not str(self.summary or "").strip():
            raise ValueError("plan step summary is required")


@dataclass(frozen=True)
class PlanDecision:
    """What the planner decided, and why — refusals included.

    ``hold`` (H464d) is the planner saying it cannot answer: it is what the planner
    returns in place of an action, and it is neither "nothing left to do" nor a
    refusal of a proposal."""

    action: Action | None
    refusal: str = ""
    detail: str = ""
    hold: Hold | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": None if self.action is None else {
                "kind": self.action.kind,
                "summary": self.action.summary,
                "interrupts_owner": self.action.interrupts_owner,
            },
            "refusal": self.refusal,
            "detail": self.detail,
            "hold": None if self.hold is None else {
                "reason": self.hold.reason, "stop": self.hold.stop, "cause": self.hold.cause,
            },
        }


def _fingerprint(kind: str, summary: str) -> str:
    """What counts as "the same step". Deliberately coarse — kind plus a
    normalised summary — so a model cannot dodge the repeat check by changing
    whitespace or casing."""
    return f"{kind.strip().lower()}|{' '.join(str(summary).lower().split())}"


class _ClampedPlanner:
    """Shared clamps. Subclasses supply ``_propose``; they never bypass these."""

    def __init__(
        self,
        *,
        scope_kinds: frozenset[str] | Sequence[str] = (),
        ledger: Any = None,
    ) -> None:
        self.scope_kinds = frozenset(scope_kinds or ())
        self._ledger = ledger
        self.last: PlanDecision | None = None

    def covers(self, kind: str) -> bool:
        """Empty scope means unrestricted — a decision the goal's author makes."""
        return not self.scope_kinds or kind in self.scope_kinds

    async def __call__(self, context: Mapping[str, Any]) -> Action | Hold | None:
        decision = await self.decide(context)
        self.last = decision
        if decision.refusal:
            logger.info("planner refused a proposal: %s (%s)",
                        decision.refusal, decision.detail)
        if decision.hold is not None:
            logger.info("planner holds the run: %s", decision.hold.reason)
            return decision.hold
        return decision.action

    async def decide(self, context: Mapping[str, Any]) -> PlanDecision:
        budget = dict(context.get("budget") or {})
        if budget.get("exceeded") or budget.get("steps_left") == 0:
            return PlanDecision(None, "budget_spent", str(budget.get("exceeded") or "steps"))

        try:
            proposed = await self._propose(context)
        except Exception as exc:
            logger.warning("planner proposer failed", exc_info=True)
            return PlanDecision(None, "proposer_failed", exc.__class__.__name__)
        if isinstance(proposed, Hold):
            # "Cannot say" goes to the supervisor as it is (H464d): never coerced
            # into an action, never read as "nothing left to do". A Hold only ever
            # narrows — it does nothing now, or stops the run.
            return PlanDecision(None, hold=proposed)
        if proposed is None:
            return PlanDecision(None)

        action = self._coerce(proposed)
        if action is None:
            return PlanDecision(None, "malformed", f"{type(proposed).__name__} is not an action")
        if action.parks:
            return PlanDecision(action)
        if not self.covers(action.kind):
            return PlanDecision(
                None, "out_of_scope",
                f"{action.kind} is not in {sorted(self.scope_kinds)}",
            )
        if "kind" in action.task and not task_kind_in_scope(
            action.task["kind"], self.scope_kinds
        ):
            # The row's kind is in scope; the task it would queue is not (H464c).
            return PlanDecision(
                None, "out_of_scope",
                f"task kind {str(action.task['kind'])[:64]} is not in "
                f"{sorted(self.scope_kinds)}",
            )
        if self._already_done(context, action):
            return PlanDecision(None, "already_done", action.summary[:120])
        return PlanDecision(action)

    async def _propose(self, context: Mapping[str, Any]) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def _coerce(self, proposed: Any) -> Action | None:
        """Turn a proposal into an Action, or None. Never raises on bad input.

        A checklist row is the owner's approved text: it never carries a barrier,
        so a row named "wait" becomes an ordinary step with its task. A proposal
        (a mapping or an Action from a model) that says "wait" must say what on —
        one without a barrier is malformed, never queued as work.
        """
        if isinstance(proposed, PlanStep):
            try:
                return Action(
                    kind=proposed.kind, summary=proposed.summary,
                    task=dict(proposed.task), interrupts_owner=proposed.interrupts_owner,
                )
            except (ValueError, TypeError):
                return None
        if isinstance(proposed, Action):
            action = proposed
        elif isinstance(proposed, Mapping):
            try:
                barrier = proposed.get("barrier")
                action = Action(
                    kind=str(proposed.get("kind", "")),
                    summary=str(proposed.get("summary", ""))[:_MAX_SUMMARY],
                    task=dict(proposed.get("task") or {}),
                    interrupts_owner=bool(proposed.get("interrupts_owner", False)),
                    barrier=dict(barrier) if isinstance(barrier, Mapping) else barrier,
                )
            except (ValueError, TypeError):
                return None
        else:
            return None
        if action.kind == "wait" and not action.parks:
            return None
        return action

    def _already_done(self, context: Mapping[str, Any], action: Action) -> bool:
        """True when this run already took a step just like this one."""
        run = dict(context.get("run") or {})
        run_id = run.get("id")
        if self._ledger is None or not run_id:
            return False
        try:
            steps = self._ledger.steps(run_id)
        except Exception:
            logger.debug("planner could not read prior steps", exc_info=True)
            return False
        want = _fingerprint(action.kind, action.summary)
        return any(
            _fingerprint(step.kind, step.summary) == want and self._counts_as_done(step)
            for step in steps
        )

    def _counts_as_done(self, step: Any) -> bool:
        """Whether a recorded step makes a proposal like it a repeat. Any step, for
        a proposer the planner cannot bound: repeating one is how a model loops
        while looking busy. :class:`ChecklistPlanner` narrows it (H464d)."""
        return True


class ChecklistPlanner(_ClampedPlanner):
    """Walks a fixed list written when the goal was approved.

    Fully deterministic: no model, no surprises. The clamps still apply, so a
    checklist that wandered outside the goal's scope is refused like any other
    proposal — the list is not more trusted for having been written by hand.
    """

    def __init__(
        self,
        steps: Sequence[PlanStep],
        *,
        scope_kinds: frozenset[str] | Sequence[str] = (),
        ledger: Any = None,
    ) -> None:
        super().__init__(scope_kinds=scope_kinds, ledger=ledger)
        self._steps = list(steps)

    async def _propose(self, context: Mapping[str, Any]) -> Any:
        """The first step this run has not taken yet, else None.

        Position is derived from the ledger rather than from a counter, so a
        planner rebuilt after a restart resumes where the run actually is instead
        of starting the checklist again.

        H464d: a row is taken once it reached the queue (:meth:`_counts_as_done`);
        one whose intake failed is proposed again, until it has failed
        ``MAX_ROW_ATTEMPTS`` times — then the run is stopped with the row named, as
        a stop Hold (``cause="retries"``). Steps that cannot be read are a
        transient Hold: "cannot tell" is not "nothing done", and reading it as
        that re-asked row 1 — a duplicate ask to the owner.
        """
        steps = self._recorded_steps(context)
        if steps is None:
            return Hold(STEPS_UNREADABLE)
        done = self._done_fingerprints(steps)
        for step in self._steps:
            want = _fingerprint(step.kind, step.summary)
            if want in done:
                continue
            # Not done, so every recorded step like it is a failed attempt.
            attempts = sum(1 for s in steps if _fingerprint(s.kind, s.summary) == want)
            if attempts >= MAX_ROW_ATTEMPTS:
                return Hold(f"{step.summary[:120]} ({attempts} attempts)", stop=True,
                            cause="retries")
            return step
        return None

    def _recorded_steps(self, context: Mapping[str, Any]) -> list[Any] | None:
        """The run's steps, ``[]`` with no ledger or run to read, ``None`` when the
        read failed."""
        run_id = dict(context.get("run") or {}).get("id")
        if self._ledger is None or not run_id:
            return []
        try:
            return list(self._ledger.steps(run_id))
        except Exception:
            logger.warning("planner could not read the run's steps; holding", exc_info=True)
            return None

    def _done_fingerprints(self, steps: Sequence[Any]) -> set[str]:
        """The rows the run has taken: a step counts only once it reached the queue
        (H464d, :meth:`_counts_as_done`)."""
        return {_fingerprint(s.kind, s.summary) for s in steps if self._counts_as_done(s)}

    def _counts_as_done(self, step: Any) -> bool:
        """A row is done once it reached the queue (H464d): queued, approved (``ok``)
        or refused by the owner — or failed AFTER it was queued (it carries its
        durable task: the task vanished, or the ask expired unanswered). Asking
        again would be a duplicate ask. Only a failure with no durable task — the
        governed intake raised or answered nothing — never reached anyone, and is
        tried again (bounded by ``MAX_ROW_ATTEMPTS``)."""
        if str(getattr(step, "outcome", "")) != "failed":
            return True
        return getattr(step, "task_id", None) is not None


class ModelPlanner(_ClampedPlanner):
    """Wraps an injected model call behind the same clamps.

    ``propose`` receives the tick context and returns an Action-shaped mapping or
    ``None``. Whatever it returns is untrusted: the clamps in
    :meth:`_ClampedPlanner.decide` are the contract, not the prompt.
    """

    def __init__(
        self,
        propose: Callable[[Mapping[str, Any]], Any],
        *,
        scope_kinds: frozenset[str] | Sequence[str] = (),
        ledger: Any = None,
    ) -> None:
        super().__init__(scope_kinds=scope_kinds, ledger=ledger)
        self._propose_fn = propose

    async def _propose(self, context: Mapping[str, Any]) -> Any:
        value = self._propose_fn(dict(context))
        if inspect.isawaitable(value):
            value = await value
        return value


__all__ = [
    "MAX_ROW_ATTEMPTS",
    "REFUSALS",
    "STEPS_UNREADABLE",
    "ChecklistPlanner",
    "ModelPlanner",
    "PlanDecision",
    "PlanStep",
]
