"""company_planner.py — what should this work run do next?

The supervisor asks one question per tick: *next action, or nothing?* This module
answers it. It is the only place in the chain where a language model gets to
propose, which is exactly why it is also where the clamps live.

The design rule: **the planner proposes, the clamp disposes.** A proposal from a
model is untrusted input, no different from a webhook body, so it is validated
against the goal before it ever becomes an :class:`Action`:

* **Scope is enforced at proposal time**, not just at judgement time. A model that
  suggests running a shell command for a research-only goal is refused here, so
  the run never spends a step on work the judge would reject at the end.
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

Two proposers ship. :class:`ChecklistPlanner` walks a fixed list written when the
goal was approved — fully deterministic, and the one to use when the owner wants
the run to do a known thing. :class:`ModelPlanner` wraps an injected async
callable (an LLM) behind the same clamps.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.core.autonomy.company_supervisor import Action

logger = logging.getLogger("jarvis.company_planner")

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
    """What the planner decided, and why — refusals included."""

    action: Action | None
    refusal: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": None if self.action is None else {
                "kind": self.action.kind,
                "summary": self.action.summary,
                "interrupts_owner": self.action.interrupts_owner,
            },
            "refusal": self.refusal,
            "detail": self.detail,
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

    async def __call__(self, context: Mapping[str, Any]) -> Action | None:
        decision = await self.decide(context)
        self.last = decision
        if decision.refusal:
            logger.info("planner refused a proposal: %s (%s)",
                        decision.refusal, decision.detail)
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
        if proposed is None:
            return PlanDecision(None)

        action = self._coerce(proposed)
        if action is None:
            return PlanDecision(None, "malformed", f"{type(proposed).__name__} is not an action")
        if not self.covers(action.kind):
            return PlanDecision(
                None, "out_of_scope",
                f"{action.kind} is not in {sorted(self.scope_kinds)}",
            )
        if self._already_done(context, action):
            return PlanDecision(None, "already_done", action.summary[:120])
        return PlanDecision(action)

    async def _propose(self, context: Mapping[str, Any]) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def _coerce(self, proposed: Any) -> Action | None:
        """Turn a proposal into an Action, or None. Never raises on bad input."""
        if isinstance(proposed, Action):
            return proposed
        if isinstance(proposed, PlanStep):
            return Action(
                kind=proposed.kind, summary=proposed.summary,
                task=dict(proposed.task), interrupts_owner=proposed.interrupts_owner,
            )
        if isinstance(proposed, Mapping):
            try:
                return Action(
                    kind=str(proposed.get("kind", "")),
                    summary=str(proposed.get("summary", ""))[:_MAX_SUMMARY],
                    task=dict(proposed.get("task") or {}),
                    interrupts_owner=bool(proposed.get("interrupts_owner", False)),
                )
            except (ValueError, TypeError):
                return None
        return None

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
        return any(_fingerprint(step.kind, step.summary) == want for step in steps)


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
        """
        done = self._done_fingerprints(context)
        for step in self._steps:
            if _fingerprint(step.kind, step.summary) not in done:
                return step
        return None

    def _done_fingerprints(self, context: Mapping[str, Any]) -> set[str]:
        run_id = dict(context.get("run") or {}).get("id")
        if self._ledger is None or not run_id:
            return set()
        try:
            return {_fingerprint(s.kind, s.summary) for s in self._ledger.steps(run_id)}
        except Exception:
            logger.debug("planner could not read prior steps", exc_info=True)
            return set()


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
    "REFUSALS",
    "ChecklistPlanner",
    "ModelPlanner",
    "PlanDecision",
    "PlanStep",
]
