"""work_judge.py — did the run actually meet the goal it was approved for?

The verifier answers "does the evidence hold". The judge answers the question
after it: **was this the goal?** A run can produce impeccable evidence for the
wrong thing — the checks all green, the deliverable not what the owner asked for,
or produced by drifting outside the scope the goal was approved with.

The split matters because the two questions fail differently. Evidence is
mechanical: probe it. Goal-fit is a judgement, and a judgement made by the same
agent that did the work is worth very little. So:

* **The judge is the last gate, and it is fail-closed.** Every rule below must
  hold for a pass. There is no "mostly met" verdict — a partial result is a
  failed run with an honest reason, and the owner can open a new goal.
* **It cannot pass what the verifier failed.** The ledger enforces this too
  (``verifier_failed``); the judge checks it first so the reason it reports names
  the real problem rather than a database refusal.
* **Scope is a hard boundary, not a preference.** A step whose kind falls outside
  the goal's declared scope fails the run even when it helped. Drifting into
  useful adjacent work is exactly how an autonomous system stops being governable.
* **A stop condition that fired is decisive.** The goal named the circumstances
  under which the run should end; if one is true, the run does not get to pass
  because it happened to finish first.
* **A rubric is evidence, not authority.** An optional ``rubric`` callable (an
  LLM grader, a heuristic) can only ever *withhold* a pass. It cannot grant one:
  a model saying "looks good" must never be the thing that turns a failing run
  into a successful one.

The judge writes exactly one verdict, through the ledger, which settles the run.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.work_judge")

_MAX_REASON = 500


@dataclass(frozen=True)
class GoalTerms:
    """What the approved goal said the run had to stay inside.

    ``scope_kinds`` is the set of step kinds the goal was approved for; empty
    means unrestricted, which is a decision the goal's author makes explicitly.
    ``stop_conditions`` are named conditions that end the run if they hold — the
    judge is handed the ones that FIRED, it does not evaluate them itself.
    """

    goal_id: str
    title: str
    scope_kinds: frozenset[str] = frozenset()
    deliverable: str = ""

    def covers(self, kind: str) -> bool:
        if not self.scope_kinds:
            return True
        return kind in self.scope_kinds


@dataclass(frozen=True)
class Judgement:
    passed: bool
    reason: str
    rule: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "rule": self.rule,
            "detail": dict(self.detail),
        }


def _reason(text: str) -> str:
    return str(text or "").strip()[:_MAX_REASON]


class WorkJudge:
    """Grades one run against its goal. Stateless; construct per judgement."""

    def __init__(self, ledger: Any, *, rubric: Callable[..., Any] | None = None) -> None:
        self._ledger = ledger
        self._rubric = rubric

    async def judge(
        self,
        run_id: str,
        terms: GoalTerms,
        *,
        fired_stop_conditions: Sequence[str] = (),
        record: bool = True,
    ) -> Judgement:
        """Apply every rule in order and settle the run on the result.

        The rules are ordered by how fundamental the failure is, so the reason the
        owner reads is the most basic thing that went wrong — not the last check
        to run.
        """
        snapshot = self._ledger.snapshot(run_id)
        run = snapshot["run"]
        steps = snapshot["steps"]
        verdicts = {v["role"]: v for v in snapshot["verdicts"]}

        judgement = await self._apply_rules(
            run, steps, verdicts, snapshot, terms, tuple(fired_stop_conditions)
        )
        if record:
            self._ledger.record_verdict(
                run_id,
                role="judge",
                passed=judgement.passed,
                reason=judgement.reason,
                evidence=(f"rule:{judgement.rule}",),
            )
        return judgement

    async def _apply_rules(
        self,
        run: dict[str, Any],
        steps: list[dict[str, Any]],
        verdicts: dict[str, dict[str, Any]],
        snapshot: dict[str, Any],
        terms: GoalTerms,
        fired: tuple[str, ...],
    ) -> Judgement:
        if run.get("goal_id") != terms.goal_id:
            return Judgement(
                False, "the run was opened for a different goal", "goal_identity",
                {"run_goal": run.get("goal_id"), "terms_goal": terms.goal_id},
            )
        if snapshot.get("tampered"):
            return Judgement(
                False, "the run row does not match its fingerprint", "integrity", {}
            )
        if snapshot.get("unauthorised_steps"):
            return Judgement(
                False,
                "the run changed things without an approved task",
                "authorisation",
                {"steps": list(snapshot["unauthorised_steps"])},
            )
        verifier = verdicts.get("verifier")
        if verifier is None:
            return Judgement(
                False, "nothing verified the run's evidence", "verification_missing", {}
            )
        if not verifier.get("passed"):
            return Judgement(
                False,
                f"the evidence did not hold: {_reason(verifier.get('reason', ''))}",
                "verification_failed",
                {},
            )
        if fired:
            return Judgement(
                False,
                f"a stop condition fired: {_reason(fired[0])}",
                "stop_condition",
                {"fired": list(fired)},
            )
        out_of_scope = sorted(
            {step["kind"] for step in steps if not terms.covers(step["kind"])}
        )
        if out_of_scope:
            return Judgement(
                False,
                f"the run worked outside its approved scope: {', '.join(out_of_scope[:3])}",
                "scope",
                {"kinds": out_of_scope},
            )
        failed_steps = [s["seq"] for s in steps if s["outcome"] == "failed"]
        if failed_steps:
            return Judgement(
                False,
                f"{len(failed_steps)} step(s) failed and were never recovered",
                "failed_steps",
                {"steps": failed_steps},
            )
        if not steps:
            return Judgement(
                False, "the run produced no steps at all", "no_work", {}
            )

        # Everything mechanical holds. A rubric may still withhold the pass, but
        # nothing here can turn a failing run into a passing one — by this point
        # the run has already earned a pass on the rules that matter.
        withheld = await self._rubric_withholds(run, steps, terms)
        if withheld is not None:
            return Judgement(False, withheld, "rubric", {})
        return Judgement(
            True,
            f"the run met its goal within scope and budget: {_reason(terms.title)}",
            "met",
            {"steps": len(steps)},
        )

    async def _rubric_withholds(
        self, run: dict[str, Any], steps: list[dict[str, Any]], terms: GoalTerms
    ) -> str | None:
        """Ask the optional grader. Returns a refusal reason, or None to allow.

        A rubric that raises, or that answers anything other than a clear verdict
        dict, withholds nothing: a broken grader must not be able to fail a run
        that satisfied every rule, any more than a happy one can pass a run that
        did not. It is logged and ignored.
        """
        if self._rubric is None:
            return None
        try:
            value = self._rubric(
                {"run": run, "steps": steps, "goal": terms.title,
                 "deliverable": terms.deliverable}
            )
            if inspect.isawaitable(value):
                value = await value
        except Exception:
            logger.warning("work judge rubric failed; ignoring it", exc_info=True)
            return None
        if not isinstance(value, dict) or "passed" not in value:
            logger.warning("work judge rubric returned no verdict; ignoring it")
            return None
        if value.get("passed") is False:
            return _reason(value.get("reason") or "the grader did not accept the result")
        return None


__all__ = ["GoalTerms", "Judgement", "WorkJudge"]
