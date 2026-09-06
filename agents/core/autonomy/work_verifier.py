"""work_verifier.py — does the evidence a work run produced actually hold?

The verifier answers one narrow question, and refuses to answer any other:

    For each check the goal declared, is there evidence in THIS run that it
    holds — evidence that was observed, not asserted?

It never asks whether the goal was worth pursuing (that is the owner's), and it
never decides whether the run succeeded (that is the judge's, and the judge is
refused a pass unless the verifier passed first — see ``work_runs``).

Why it exists. A long-running agent grades itself generously: "I ran the build"
becomes "the build passes". The verifier is the component that refuses to make
that leap. Its rules are deliberately boring and mechanical:

* **A check needs a probe.** A ``Check`` carries a callable that goes and looks.
  A check with no probe is ``unverifiable`` — never ``passed``. The absence of a
  way to look is a fact about the check, not a pass.
* **A probe that raises is a failure, not a skip.** A verifier that swallowed
  errors would turn every broken probe into silent success.
* **The run's own claims are not evidence.** ``verify`` reads the ledger's steps
  to decide *what* to probe and to attach provenance, but a step saying
  ``outcome="ok"`` never satisfies a check by itself.
* **Unauthorised work fails the run.** A step that changed something without
  naming the durable approved task that authorised it fails verification
  outright, whatever the probes say: work Nerva was not authorised to do cannot
  be laundered into a passing result.
* **The verdict is written once, through the ledger.** The verifier has no
  durable state of its own.

Nothing here actuates, so there is no kernel hop: a probe is a read. A probe that
wants to *do* something is a step, and steps go through the queue like everything
else.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("jarvis.work_verifier")

# A check's outcome. `unverifiable` is deliberately distinct from `failed`: the
# first says "nobody can tell", the second says "we looked and it is not true".
# Collapsing them would let a run with no probes read the same as a broken one.
CHECK_RESULTS = ("passed", "failed", "unverifiable")

_MAX_TEXT = 500


@dataclass(frozen=True)
class Check:
    """One declared, probeable property of a finished goal.

    ``probe`` returns ``True``/``False`` (or an awaitable of one). Returning
    anything else is treated as a failure: a probe that cannot express a clear
    yes/no has not established anything.
    """

    id: str
    describe: str
    probe: Callable[[], Any] | None = None
    required: bool = True

    def __post_init__(self) -> None:
        if not str(self.id or "").strip():
            raise ValueError("check id is required")
        if not str(self.describe or "").strip():
            raise ValueError("check description is required")


@dataclass(frozen=True)
class CheckOutcome:
    result: str
    check_id: str
    describe: str
    detail: str = ""
    required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "describe": self.describe,
            "result": self.result,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass(frozen=True)
class VerificationReport:
    """What the verifier found, and the one-line reason it will hand the ledger."""

    passed: bool
    reason: str
    outcomes: tuple[CheckOutcome, ...] = ()
    unauthorised_steps: tuple[int, ...] = ()
    evidence: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "outcomes": [o.as_dict() for o in self.outcomes],
            "unauthorised_steps": list(self.unauthorised_steps),
            "evidence": list(self.evidence),
        }

    @property
    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(CHECK_RESULTS, 0)
        for outcome in self.outcomes:
            out[outcome.result] += 1
        return out


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


async def _run_probe(check: Check) -> CheckOutcome:
    """Run one probe. Never raises: a broken probe is a failed check, not a crash."""
    if check.probe is None:
        return CheckOutcome(
            result="unverifiable",
            check_id=check.id,
            describe=check.describe,
            detail="no probe: nothing looked, so nothing is established",
            required=check.required,
        )
    try:
        value = check.probe()
        if inspect.isawaitable(value):
            value = await value
    except Exception as exc:  # a probe that blew up established nothing
        logger.warning("work verifier probe failed: %s", check.id, exc_info=True)
        return CheckOutcome(
            result="failed",
            check_id=check.id,
            describe=check.describe,
            detail=f"probe raised {exc.__class__.__name__}",
            required=check.required,
        )
    if value is True:
        return CheckOutcome(
            result="passed", check_id=check.id, describe=check.describe,
            detail="probe observed the property", required=check.required,
        )
    if value is False:
        return CheckOutcome(
            result="failed", check_id=check.id, describe=check.describe,
            detail="probe looked and the property does not hold", required=check.required,
        )
    return CheckOutcome(
        result="failed", check_id=check.id, describe=check.describe,
        detail=f"probe returned {type(value).__name__}, not a yes/no",
        required=check.required,
    )


class WorkVerifier:
    """Grades the evidence of one run. Stateless; safe to construct per verification."""

    def __init__(self, ledger: Any) -> None:
        self._ledger = ledger

    async def verify(
        self,
        run_id: str,
        checks: Sequence[Check],
        *,
        record: bool = True,
    ) -> VerificationReport:
        """Probe every check, then hand the verdict to the ledger.

        ``record=False`` returns the report without writing it — used by the
        supervisor to look ahead mid-run without spending the run's one verdict.
        """
        snapshot = self._ledger.snapshot(run_id)
        unauthorised = tuple(int(seq) for seq in snapshot.get("unauthorised_steps", ()))
        outcomes = tuple([await _run_probe(check) for check in checks])
        report = self._grade(outcomes, unauthorised, snapshot)
        if record:
            self._ledger.record_verdict(
                run_id,
                role="verifier",
                passed=report.passed,
                reason=report.reason,
                evidence=report.evidence,
            )
        return report

    def _grade(
        self,
        outcomes: tuple[CheckOutcome, ...],
        unauthorised: tuple[int, ...],
        snapshot: Mapping[str, Any],
    ) -> VerificationReport:
        """Combine the outcomes into one verdict, worst news first."""
        evidence = tuple(
            f"{o.check_id}: {o.result} — {o.detail}" for o in outcomes
        )
        # Order matters: each branch is a strictly worse finding than the next, so
        # the reason a caller sees is the most serious thing that is true.
        if snapshot.get("tampered"):
            return VerificationReport(
                False, "run row does not match its fingerprint", outcomes, unauthorised, evidence
            )
        if unauthorised:
            return VerificationReport(
                False,
                f"{len(unauthorised)} step(s) changed something with no approved task",
                outcomes, unauthorised, evidence,
            )
        if not outcomes:
            return VerificationReport(
                False, "the goal declared no checks, so nothing could be verified",
                outcomes, unauthorised, evidence,
            )
        failed = [o for o in outcomes if o.result == "failed"]
        if failed:
            return VerificationReport(
                False, f"{len(failed)} check(s) failed: {_text(failed[0].check_id, 64)}",
                outcomes, unauthorised, evidence,
            )
        blind = [o for o in outcomes if o.result == "unverifiable" and o.required]
        if blind:
            return VerificationReport(
                False,
                f"{len(blind)} required check(s) had no probe: {_text(blind[0].check_id, 64)}",
                outcomes, unauthorised, evidence,
            )
        optional_blind = [o for o in outcomes if o.result == "unverifiable"]
        reason = "every required check was probed and holds"
        if optional_blind:
            reason += f" ({len(optional_blind)} optional check(s) unprobed)"
        return VerificationReport(True, reason, outcomes, unauthorised, evidence)


__all__ = [
    "CHECK_RESULTS",
    "Check",
    "CheckOutcome",
    "VerificationReport",
    "WorkVerifier",
]
