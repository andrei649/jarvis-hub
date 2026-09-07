"""goal_contract.py — the front door of company mode.

Everything downstream of this module refuses. The ledger refuses an unapproved
goal, the verifier refuses unprobed claims, the judge refuses out-of-scope work.
That leaves one question none of them answers: **how does a goal become approved
in the first place?**

This module is that path, and its whole job is to make an approval mean something
specific. An owner accepting "sort out the quarterly stuff" has agreed to nothing
in particular; the same person accepting a goal that names its scope, its budget,
its deadline, its stop conditions and *how anyone would know it was done* has made
a decision the rest of the chain can hold every later step against.

So a :class:`GoalDraft` must carry all six before it can be proposed:

* **title** — what a person will read in the decision inbox;
* **scope** — the step kinds this run may use. Empty is allowed but must be
  *chosen*: ``unrestricted=True`` is explicit, so nobody widens a goal by
  forgetting to fill a field in;
* **budget** — steps, wall-clock, and how many times it may interrupt you;
* **deadline** — in the future, or it is not a deadline;
* **stop conditions** — at least one. A goal with no circumstance that should end
  it is a goal that only ends when the budget does;
* **success checks** — at least one, each with an id and a sentence. These become
  the verifier's checks; a goal that declares nothing to verify cannot be verified,
  and the verifier will (correctly) refuse to pass it.

``propose`` hands the draft to the governed intake as an ask-tier task and returns
the durable task id. It grants nothing. ``approve_from_task`` is the other half:
it runs from the approved task's execution, refuses any task a human did not
decide, and only then produces the approved goal the ledger will open a run for.

That asymmetry is the same shape as ``permission_ledger``: requesting is cheap and
crosses the kernel; granting happens only out of the owner's own decision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.core.autonomy.policy import ASK, RiskTier
from agents.core.autonomy.work_runs import Budget

logger = logging.getLogger("jarvis.goal_contract")

KIND = "goal.approve"
SCHEMA = "nerva.goal-contract.v1"

# Deciders that are machines. A task carrying one of these did not have a human
# behind it and must never mint an approved goal. Mirrors permission_ledger, on
# purpose: one rule about what "the owner decided" means, spelled the same way.
MACHINE_DECIDERS = frozenset({"policy", "system", "kernel", "auto", "worker", "scheduler", ""})
HUMAN_DECISIONS = frozenset({"accept", "approve", "edit"})

MAX_TITLE = 200
MAX_SENTENCE = 500
MAX_CHECKS = 20
MAX_STOP_CONDITIONS = 10
MAX_SCOPE_KINDS = 20
# A plan the owner reads before approving. Bounded because a card nobody can
# finish reading is a card nobody actually approved.
MAX_PLAN_STEPS = 40


class GoalContractError(ValueError):
    """A refusal from the contract. ``reason`` is a bounded, public code."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "goal_refused")
        super().__init__(self.reason)


def _text(value: Any, name: str, *, limit: int = MAX_SENTENCE) -> str:
    out = str(value or "").strip()
    if not out:
        raise GoalContractError(f"missing_{name}")
    return out[:limit]


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class SuccessCheck:
    """How anyone would know the goal was met. Becomes a verifier check.

    ``probe_ref`` names the callable that will go and look. It is optional here
    because a goal may legitimately be written before its probe exists — but a
    check with no probe is ``unverifiable`` at grading time, never ``passed``, so
    an unprobed goal cannot quietly succeed. Writing the probe later is work; it
    is not a loophole.
    """

    id: str
    describe: str
    probe_ref: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "check_id", limit=64))
        object.__setattr__(self, "describe", _text(self.describe, "check_describe"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "describe": self.describe,
            "probe_ref": self.probe_ref, "required": self.required,
        }


@dataclass(frozen=True)
class GoalDraft:
    """What the owner is being asked to approve. Every field is required.

    ``unrestricted`` is how an unlimited scope is expressed. An empty
    ``scope_kinds`` with ``unrestricted=False`` is refused, so a goal never
    becomes unlimited because someone left a field blank.
    """

    title: str
    scope_kinds: tuple[str, ...] = ()
    unrestricted: bool = False
    budget: Budget = field(default_factory=Budget)
    deadline_at: float = 0.0
    stop_conditions: tuple[str, ...] = ()
    checks: tuple[SuccessCheck, ...] = ()
    deliverable: str = ""
    requested_by: str = "owner"
    # The steps the owner is approving, in order. Optional, and its absence is a
    # real state rather than a gap to fill in later: a goal approved with no plan
    # and no model planner bound proposes NOTHING and grades immediately. "You
    # approved a goal with no plan, so nothing happened" is a better outcome than
    # a model inventing a night's work off a one-line title — and it is the only
    # reading under which approving the goal and approving the work are the same
    # act, which is what makes the card meaningful.
    plan: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _text(self.title, "title", limit=MAX_TITLE))

        kinds = tuple(
            dict.fromkeys(str(k).strip().lower() for k in self.scope_kinds if str(k).strip())
        )
        if len(kinds) > MAX_SCOPE_KINDS:
            raise GoalContractError("too_many_scope_kinds")
        if not kinds and not self.unrestricted:
            # An unlimited scope is a real choice with real consequences; it has to
            # be made, not defaulted into by an empty list.
            raise GoalContractError("scope_required_or_declare_unrestricted")
        if kinds and self.unrestricted:
            raise GoalContractError("scope_and_unrestricted_conflict")
        object.__setattr__(self, "scope_kinds", kinds)

        if not isinstance(self.budget, Budget):
            raise GoalContractError("invalid_budget")

        stops = tuple(
            dict.fromkeys(
                str(s).strip()[:MAX_SENTENCE] for s in self.stop_conditions if str(s).strip()
            )
        )
        if not stops:
            # Without one, the only thing that ends this run is its budget.
            raise GoalContractError("stop_condition_required")
        if len(stops) > MAX_STOP_CONDITIONS:
            raise GoalContractError("too_many_stop_conditions")
        object.__setattr__(self, "stop_conditions", stops)

        checks = tuple(self.checks or ())
        if not checks:
            # A goal that declares nothing to verify cannot be verified, and the
            # verifier will refuse to pass it. Say so now rather than at 4am.
            raise GoalContractError("success_check_required")
        if len(checks) > MAX_CHECKS:
            raise GoalContractError("too_many_checks")
        if len({c.id for c in checks}) != len(checks):
            raise GoalContractError("duplicate_check_id")
        if not any(c.required for c in checks):
            raise GoalContractError("at_least_one_required_check")
        object.__setattr__(self, "checks", checks)

        plan: list[dict[str, Any]] = []
        for row in self.plan or ():
            if not isinstance(row, Mapping):
                raise GoalContractError("invalid_plan_step")
            kind = str(row.get("kind", "") or "").strip().lower()
            summary = str(row.get("summary", "") or "").strip()[:MAX_SENTENCE]
            if not kind or not summary:
                # A step with no kind cannot be scope-checked and a step with no
                # summary cannot be read on the card. Either one makes the plan
                # unapprovable rather than merely untidy.
                raise GoalContractError("invalid_plan_step")
            if not self.unrestricted and kinds and kind not in kinds:
                # Refused here, not at 3am: a plan that leaves the goal's scope is
                # a contradiction in the card the owner is being shown.
                raise GoalContractError("plan_step_out_of_scope")
            task = row.get("task")
            plan.append({
                "kind": kind,
                "summary": summary,
                "task": dict(task) if isinstance(task, Mapping) else {},
                "interrupts_owner": bool(row.get("interrupts_owner", False)),
            })
        if len(plan) > MAX_PLAN_STEPS:
            raise GoalContractError("plan_too_long")
        object.__setattr__(self, "plan", tuple(plan))

        object.__setattr__(
            self, "deliverable", str(self.deliverable or "").strip()[:MAX_SENTENCE]
        )
        object.__setattr__(
            self, "requested_by", str(self.requested_by or "owner").strip()[:128]
        )

    def validate_deadline(self, now: float) -> None:
        """A deadline in the past is not a deadline."""
        if not isinstance(self.deadline_at, (int, float)) or isinstance(self.deadline_at, bool):
            raise GoalContractError("invalid_deadline")
        if float(self.deadline_at) <= float(now):
            raise GoalContractError("deadline_in_the_past")

    def as_payload(self) -> dict[str, Any]:
        """The decision card's payload — everything the owner is agreeing to."""
        return {
            "schema": SCHEMA,
            "kind": KIND,
            "title": self.title,
            "scope_kinds": list(self.scope_kinds),
            "unrestricted": self.unrestricted,
            "budget": self.budget.as_dict(),
            "deadline_at": self.deadline_at,
            "stop_conditions": list(self.stop_conditions),
            "checks": [c.as_dict() for c in self.checks],
            "deliverable": self.deliverable,
            "requested_by": self.requested_by,
            # In the payload, therefore in the fingerprint: editing the plan after
            # the card was shown invalidates the approval, exactly like editing
            # the budget would.
            "plan": [dict(step) for step in self.plan],
            "risk_tier": int(RiskTier.EXTERNAL),
            "reversible": True,
        }

    def fingerprint(self) -> str:
        """SHA-256 over the payload — what the owner approved, exactly.

        `approve_from_task` compares this against the approved task's payload, so
        an edit between proposal and execution cannot slip a different goal past
        an approval that was given for another one.
        """
        return hashlib.sha256(_canonical(self.as_payload()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovedGoal:
    """A goal the owner accepted. This is what ``WorkRunLedger.open_run`` takes.

    ``approved_by`` is the evidence — the task id and who decided it — and its
    presence is exactly what the ledger checks. Constructing one of these outside
    ``approve_from_task`` is possible in Python and pointless: the value carries
    no authority of its own, it records that a decision happened.
    """

    goal_id: str
    title: str
    approved_by: str
    deadline_at: float
    draft: GoalDraft
    approved_at: float

    @property
    def scope_kinds(self) -> frozenset[str]:
        return frozenset(self.draft.scope_kinds)

    @property
    def budget(self) -> Budget:
        return self.draft.budget

    def plan_steps(self) -> list[Any]:
        """The approved plan as planner ``PlanStep`` objects.

        Empty when the owner approved a goal without one — which the runtime reads
        as "propose nothing", not as "improvise".
        """
        from agents.core.autonomy.company_planner import PlanStep

        return [
            PlanStep(
                kind=row["kind"], summary=row["summary"],
                task=dict(row.get("task") or {}),
                interrupts_owner=bool(row.get("interrupts_owner", False)),
            )
            for row in self.draft.plan
        ]

    def verifier_checks(self, probes: Mapping[str, Any] | None = None) -> list[Any]:
        """The declared checks as verifier ``Check`` objects.

        ``probes`` binds ``probe_ref`` names to callables. A check whose probe is
        missing is built WITHOUT one on purpose — it then grades as
        ``unverifiable``, which is the honest outcome, rather than being silently
        dropped from the run's success criteria.
        """
        from agents.core.autonomy.work_verifier import Check

        table = dict(probes or {})
        return [
            Check(
                id=c.id,
                describe=c.describe,
                probe=table.get(c.probe_ref) if c.probe_ref else None,
                required=c.required,
            )
            for c in self.draft.checks
        ]

    def goal_terms(self) -> Any:
        """The judge's view of this goal."""
        from agents.core.autonomy.work_judge import GoalTerms

        return GoalTerms(
            goal_id=self.goal_id,
            title=self.title,
            scope_kinds=self.scope_kinds,
            deliverable=self.draft.deliverable,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "deadline_at": self.deadline_at,
            "draft": self.draft.as_payload(),
        }


def _kernel_on() -> bool:
    """Default-off, like FileTools and the permission ledger: the hook is bound at
    boot but consulted only once ``JARVIS_ACTION_KERNEL`` is on."""
    from agents.core.kernel import kernel_enabled

    return kernel_enabled()


def propose(
    draft: GoalDraft,
    govern_enqueue: Any,
    *,
    agent: str = "jarvis",
    authorizer: Any = None,
    now: float | None = None,
) -> int:
    """Ask the owner to approve a goal. Returns the durable task id.

    Grants nothing. The draft is validated, crosses the Action Kernel (a DENY
    refuses it before the decision inbox ever sees it — kill-switch, budget, loop),
    and is then handed to the *injected* governed intake at EXTERNAL/ASK. The task
    is never transitioned here.

    Approving a goal is registered as a privileged action for the same reason
    widening a permission is: it is capability growth. Every individual step the
    run later takes crosses the kernel again on its own — this hop is about the
    decision to spend a night at all.
    """
    moment = time.time() if now is None else float(now)
    draft.validate_deadline(moment)
    payload = draft.as_payload()
    payload["fingerprint"] = draft.fingerprint()

    if authorizer is not None and _kernel_on():
        from agents.core.kernel import Action, Verdict

        verdict = authorizer(
            Action(kind=KIND, agent=agent, title=f"Approve goal: {draft.title}",
                   payload=payload)
        )
        if getattr(verdict, "verdict", None) is Verdict.DENY:
            reason = getattr(verdict, "reason", "") or "denied"
            raise GoalContractError(f"kernel_denied:{reason}")

    task_id = govern_enqueue(
        agent=agent,
        kind=KIND,
        title=f"Approve goal: {draft.title}",
        payload=payload,
        risk_tier=int(RiskTier.EXTERNAL),
        autonomy_level=ASK,
        origin="generated",
    )
    logger.info("goal proposed for approval: %s (task %s)", draft.title, task_id)
    return int(task_id)


def approve_from_task(task: Any, *, now: float | None = None) -> ApprovedGoal:
    """Mint the approved goal, from the approved task's own execution.

    Refuses unless a *human* decided accept/edit on this very task, and unless the
    payload still fingerprints to what was proposed. Both checks matter: the first
    stops a policy auto-decision from minting a goal, the second stops an edited
    payload from riding an approval given for something else.
    """
    kind = str(getattr(task, "kind", "") or "")
    if kind != KIND:
        raise GoalContractError("kind_mismatch")

    decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decided_by in MACHINE_DECIDERS:
        raise GoalContractError("not_decided_by_a_human")
    if decision not in HUMAN_DECISIONS:
        raise GoalContractError("not_accepted")

    payload = getattr(task, "payload", None)
    if not isinstance(payload, Mapping):
        raise GoalContractError("invalid_payload")
    draft = draft_from_payload(payload)
    claimed = str(payload.get("fingerprint") or "")
    if claimed and claimed != draft.fingerprint():
        raise GoalContractError("payload_changed_after_approval")

    task_id = getattr(task, "id", None)
    return ApprovedGoal(
        goal_id=uuid.uuid4().hex[:16],
        title=draft.title,
        approved_by=f"task:{task_id}:{decided_by}",
        deadline_at=float(draft.deadline_at),
        draft=draft,
        approved_at=time.time() if now is None else float(now),
    )


def draft_from_payload(payload: Mapping[str, Any]) -> GoalDraft:
    """Rebuild a draft from a task payload, refusing anything malformed."""
    if str(payload.get("schema") or "") != SCHEMA:
        raise GoalContractError("unknown_schema")
    raw_checks: Sequence[Any] = payload.get("checks") or ()
    if not isinstance(raw_checks, Sequence) or isinstance(raw_checks, (str, bytes)):
        raise GoalContractError("invalid_checks")
    checks = tuple(
        SuccessCheck(
            id=str(row.get("id", "")),
            describe=str(row.get("describe", "")),
            probe_ref=str(row.get("probe_ref", "") or ""),
            required=bool(row.get("required", True)),
        )
        for row in raw_checks
        if isinstance(row, Mapping)
    )
    try:
        return GoalDraft(
            title=str(payload.get("title", "")),
            scope_kinds=tuple(payload.get("scope_kinds") or ()),
            unrestricted=bool(payload.get("unrestricted", False)),
            budget=Budget.from_dict(payload.get("budget")),
            deadline_at=float(payload.get("deadline_at") or 0.0),
            stop_conditions=tuple(payload.get("stop_conditions") or ()),
            checks=checks,
            deliverable=str(payload.get("deliverable", "") or ""),
            requested_by=str(payload.get("requested_by", "owner") or "owner"),
            plan=tuple(row for row in (payload.get("plan") or ()) if isinstance(row, Mapping)),
        )
    except GoalContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise GoalContractError("invalid_payload") from exc


__all__ = [
    "KIND",
    "MACHINE_DECIDERS",
    "SCHEMA",
    "ApprovedGoal",
    "GoalContractError",
    "GoalDraft",
    "SuccessCheck",
    "approve_from_task",
    "draft_from_payload",
    "propose",
]
