"""goal_intake.py — how the owner says "goal: …", from any surface (H462).

``goal_contract`` says what a goal must name before anyone may approve it, and the
decision inbox is where it is approved. Until this module nothing ever proposed
one: no command, route, CLI verb or HUD control called ``goal_contract.propose``,
so the whole company-mode chain could only be reached from a test. This is the one
front door every entry point uses — the ``/goal`` chat command, ``POST
/api/company/goals``, ``nerva goal propose`` and the Company room's form all hand
the same text to :func:`propose_goal`.

**The text.** A headline, plus optional ``field: value`` lines in the five-field
completion contract Hermes uses (outcome, verification, constraints, boundaries,
stop when), recognised through the same CLOSED alias table — so an incidental
colon ("Fix bug: the parser drops commas") is a headline, never a field. Nerva adds
one prefix of its own, ``step: <kind>: <summary>``: a row of the plan the owner is
approving, because a goal approved with no plan proposes nothing (goal_contract).

**Where the fields land.** Every one maps onto a field the contract already
requires, so nothing here widens or loosens it:

* the headline (else the outcome) is the title; the outcome is the deliverable;
* each verification line is a required success check — with no probe bound it
  grades ``unverifiable``, never ``passed``; with none given, the outcome itself is
  the one check (still unprobed: words are not evidence);
* each stop-when line is a stop condition, and so is each constraint ("continuing
  would break a constraint: …") and each boundary ("continuing would leave a
  boundary: …"); with none of them, the run stops when it is blocked and needs the
  owner — Hermes' own default;
* **boundaries** are Hermes' limits in words or paths (``boundaries:``,
  ``files:``, ``allowed:`` — "only docs/", "agents/core/x.py"): carried into the
  contract as stop conditions, in the owner's words, never read as step kinds;
* the **scope** is Nerva's own syntax and stays explicit: a ``scope:`` line that
  is a comma list of step kinds (``scope: research, file.write``) or the word
  ``unrestricted``. A ``scope:`` line in words ("only the docs folder") is a
  boundary, not four step kinds. With no scope given, the scope is exactly the
  kinds the plan's own steps name; with no plan either, the goal is refused — an
  unlimited scope is a choice, never a default (goal_contract);
* the budget is Hermes' 20 turns as 20 steps (more if the plan is longer), the
  ledger's default wall clock and interrupts, and a deadline a day out.

**Nothing is cut short.** The headline, every field, every constraint and every
boundary must fit the contract's own bound as it will appear on the card (prefix
included); one that does not refuses the WHOLE goal with a code that says which
and how long it may be. A goal cut short is a different goal — a dropped "NEVER
delete the production database" would reach the card looking complete.

**What it grants: nothing.** :func:`propose_goal` refuses while company mode is
off (an approved goal would open a run nothing works), then calls
``goal_contract.propose``: the ``goal.approve`` action crosses the Action Kernel and
lands in the decision inbox as an ask. A run opens only when the owner accepts
that card there, and every step the run later takes crosses the kernel again.

**Criteria added mid-run** (``/subgoal``) are the ledger's
(``WorkRunLedger.add_subgoal``): an event on the run that resets nothing, folded in
by the verifier as a required check. :func:`subgoal_target` is the chat surface's
"which running goal" rule.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agents.core.autonomy import goal_contract
from agents.core.autonomy.goal_contract import (
    MAX_SENTENCE,
    MAX_STOP_CONDITIONS,
    MAX_TITLE,
    GoalContractError,
    GoalDraft,
    SuccessCheck,
)
from agents.core.autonomy.work_runs import FLAG, SUBGOAL_OPEN_STATUSES, Budget

logger = logging.getLogger("jarvis.goal_intake")

#: The five fields of the completion contract, in the order a card shows them.
CONTRACT_FIELDS = ("outcome", "verification", "constraints", "boundaries", "stop_when")

#: The closed alias table (Hermes v2026.8.31 ``_CONTRACT_ALIASES``). Only these
#: prefixes are fields; any other ``word:`` at the start of a line is headline text.
CONTRACT_ALIASES: Mapping[str, str] = {
    "outcome": "outcome", "goal": "outcome", "done": "outcome", "done when": "outcome",
    "verification": "verification", "verify": "verification", "verified by": "verification",
    "evidence": "verification", "proof": "verification",
    "constraints": "constraints", "constraint": "constraints", "preserve": "constraints",
    "must not": "constraints", "do not change": "constraints",
    "boundaries": "boundaries", "boundary": "boundaries", "scope": "boundaries",
    "allowed": "boundaries", "files": "boundaries",
    "stop when": "stop_when", "stop_when": "stop_when", "blocked": "stop_when",
    "stop if blocked": "stop_when", "give up when": "stop_when",
}

#: Nerva's own prefix: one row of the plan the owner approves.
STEP_PREFIX = "step"

#: Hermes' ``goals.max_turns`` default, as a step budget.
DEFAULT_MAX_STEPS = 20
DEFAULT_DEADLINE_SECONDS = 24 * 3600.0
DEFAULT_STOP = "it is blocked and needs the owner's input"
UNRESTRICTED = "unrestricted"
MAX_TEXT = 4_000

#: The alias that carries Nerva's explicit step-kind scope. Every other boundaries
#: alias (Hermes' ``boundaries``/``files``/``allowed``) is a limit in words.
SCOPE_ALIAS = "scope"

#: How a constraint, a boundary and the default check read on the card.
CONSTRAINT_PREFIX = "continuing would break a constraint: "
BOUNDARY_PREFIX = "continuing would leave a boundary: "
OUTCOME_CHECK_PREFIX = "the outcome is met: "
TOWARD = " — toward the goal: "

_FIELD_LINE = re.compile(r"^\s*(?:[-*]\s+)?([A-Za-z][A-Za-z_ ]{0,23}?)\s*:\s*(.*)$")
_KIND = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")
_STEP = re.compile(r"^([A-Za-z][A-Za-z0-9_.]*)\s*:\s*(.+)$")

#: What a refusal reason means, in words a person acts on. Keys are the bounded
#: codes ``GoalContractError`` carries; a code not listed is shown as is.
REFUSALS: Mapping[str, str] = {
    "company_mode_off": ("company mode is off (JARVIS_COMPANY_MODE), so an approved goal "
                         "would open a run that nothing works; nothing was proposed"),
    "intake_unavailable": "the decision inbox is not available on this hub; nothing was proposed",
    "missing_title": "say what the goal is: a headline, or an `outcome:` line",
    "goal_text_too_long": f"the goal text is longer than {MAX_TEXT} characters",
    "scope_required_or_declare_unrestricted": (
        "say what the run may do: a `scope:` line naming step kinds (e.g. `scope: research, "
        "write`), `scope: unrestricted`, or `step: <kind>: <what>` lines (a limit in words, "
        "like `boundaries: only docs/`, is kept as a boundary but is not a scope)"),
    "invalid_plan_step": "a step names its kind first: `step: research: read the Q3 figures`",
    "plan_step_out_of_scope": (
        "a step's kind is not in the goal's scope (`scope:` names step kinds; say a limit in "
        "words with `boundaries:` or `files:`)"),
    "scope_and_unrestricted_conflict": "a scope is either step kinds or `unrestricted`, not both",
    "too_many_scope_kinds": "the scope names too many step kinds",
    "too_many_checks": "the goal names too many verification lines",
    "too_many_stop_conditions": (
        f"the goal names more than {MAX_STOP_CONDITIONS} stop-when, constraint and boundary "
        "lines together"),
    "plan_too_long": "the plan has too many steps",
    # Over a cap: the whole goal is refused, never cut (a goal cut short is a
    # different goal).
    "title_too_long": (
        f"the goal's title — its headline (every line that is not a field), or the outcome "
        f"when there is no headline — is longer than {MAX_TITLE} characters; keep it short and "
        "put the detail in `outcome:` or `verify:` lines. Nothing was cut, and nothing was "
        "proposed"),
    "outcome_too_long": (
        f"the outcome is longer than {MAX_SENTENCE - len(OUTCOME_CHECK_PREFIX)} characters; "
        "nothing was cut, and nothing was proposed"),
    "verification_too_long": (
        f"a `verify:` line is longer than {MAX_SENTENCE} characters; nothing was cut, and "
        "nothing was proposed"),
    "stop_condition_too_long": (
        f"a `stop when:` line is longer than {MAX_SENTENCE} characters; nothing was cut, and "
        "nothing was proposed"),
    "constraint_too_long": (
        f"a constraint is longer than {MAX_SENTENCE - len(CONSTRAINT_PREFIX)} characters; "
        "nothing was cut, and nothing was proposed"),
    "boundary_too_long": (
        f"a boundary is longer than {MAX_SENTENCE - len(BOUNDARY_PREFIX)} characters; "
        "nothing was cut, and nothing was proposed"),
    "plan_step_too_long": (
        f"a `step:` line is longer than {MAX_SENTENCE} characters; nothing was cut, and "
        "nothing was proposed"),
}


def refusal_text(reason: str) -> str:
    """The sentence for a refusal code (``kernel_denied:<why>`` included)."""
    code = str(reason or "")
    if code.startswith("kernel_denied:"):
        return f"the Action Kernel refused the goal card ({code.split(':', 1)[1]}); nothing was proposed"
    return REFUSALS.get(code, code or "the goal was refused")


@dataclass(frozen=True)
class ParsedGoal:
    """The goal text, split into its headline, contract fields and plan rows.

    ``fields["boundaries"]`` holds the limits in words; ``scope`` the step kinds an
    explicit ``scope:`` line named, and ``unrestricted`` whether one said so.
    """

    headline: str
    fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    steps: tuple[tuple[str, str], ...] = ()
    scope: tuple[str, ...] = ()
    unrestricted: bool = False

    def get(self, name: str) -> tuple[str, ...]:
        return tuple(self.fields.get(name, ()))


def _alias_key(key: str) -> str:
    return " ".join(key.lower().split())


def _alias(key: str) -> str | None:
    return CONTRACT_ALIASES.get(_alias_key(key))


def _kind_list(value: str) -> list[str] | None:
    """The step kinds a ``scope:`` value names — a comma list of kind tokens, or
    ``unrestricted`` — or None when it is a limit in words or paths."""
    items = [item.strip().lower() for item in value.split(",")]
    if not items or any(not item or not _KIND.match(item) for item in items):
        return None
    return items


def parse_goal_text(text: str) -> ParsedGoal:
    """Split goal text into headline, contract fields, scope and ``step:`` rows.

    One field per line: a line whose prefix is in :data:`CONTRACT_ALIASES` (or is
    ``step``) is a field; every other line is headline text. Repeated fields add
    up; empty values are dropped. A ``scope:`` line that is a comma list of step
    kinds is the scope; any other boundaries line is a boundary in words.
    """
    raw = str(text or "")
    if len(raw) > MAX_TEXT:
        raise GoalContractError("goal_text_too_long")
    headline: list[str] = []
    fields: dict[str, list[str]] = {}
    steps: list[tuple[str, str]] = []
    scope: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = _FIELD_LINE.match(line)
        key = match.group(1) if match else ""
        value = " ".join(match.group(2).split()) if match else ""
        if match and _alias_key(key) == STEP_PREFIX:
            row = _STEP.match(value)
            if row is None:
                raise GoalContractError("invalid_plan_step")
            steps.append((row.group(1).lower(), " ".join(row.group(2).split())))
            continue
        name = _alias(key) if match else None
        if name is None:
            headline.append(" ".join(line.split()))
            continue
        if not value:
            continue
        kinds = _kind_list(value) if _alias_key(key) == SCOPE_ALIAS else None
        if kinds is not None:
            scope.extend(kinds)
            continue
        fields.setdefault(name, []).append(value)
    unrestricted = UNRESTRICTED in scope
    kinds = tuple(dict.fromkeys(kind for kind in scope if kind != UNRESTRICTED))
    return ParsedGoal(
        headline=" ".join(headline).strip(),
        fields={name: tuple(values) for name, values in fields.items()},
        steps=tuple(steps),
        scope=kinds,
        unrestricted=unrestricted,
    )


def _scope(parsed: ParsedGoal) -> tuple[tuple[str, ...], bool]:
    if not parsed.scope and not parsed.unrestricted:
        return tuple(dict.fromkeys(kind for kind, _ in parsed.steps)), False
    return parsed.scope, parsed.unrestricted


def _fits(value: str, limit: int, code: str) -> str:
    """*value* when it fits *limit*; otherwise the whole goal is refused — never cut."""
    if len(value) > limit:
        raise GoalContractError(code)
    return value


def _step_label(summary: str, title: str) -> str:
    """The queued task's title: the step toward the goal, or the step alone when
    both do not fit a title — never a cut sentence."""
    label = f"{summary}{TOWARD}{title}"
    return label if len(label) <= MAX_TITLE else summary


def draft_from_text(
    text: str, *, now: float | None = None, requested_by: str = "owner",
) -> GoalDraft:
    """The :class:`GoalDraft` the owner's goal text describes, or a refusal.

    Every refusal is a ``GoalContractError`` with a bounded code; the draft's own
    validation (scope, checks, stop conditions, plan in scope) runs unchanged. A
    headline, field, constraint or boundary over its bound refuses the whole goal
    (``*_too_long``): the draft is never built from a cut version of the text.
    """
    moment = time.time() if now is None else float(now)
    parsed = parse_goal_text(text)
    outcome = "; ".join(parsed.get("outcome"))
    _fits(outcome, MAX_SENTENCE - len(OUTCOME_CHECK_PREFIX), "outcome_too_long")
    title = _fits(parsed.headline or outcome, MAX_TITLE, "title_too_long")
    if not title:
        raise GoalContractError("missing_title")
    scope, unrestricted = _scope(parsed)
    for kind, summary in parsed.steps:
        if not _KIND.match(kind):
            raise GoalContractError("invalid_plan_step")
        _fits(summary, MAX_SENTENCE, "plan_step_too_long")

    verification = parsed.get("verification")
    if verification:
        checks = tuple(
            SuccessCheck(id=f"verify-{n}",
                         describe=_fits(line, MAX_SENTENCE, "verification_too_long"))
            for n, line in enumerate(verification, start=1)
        )
    else:
        checks = (SuccessCheck(id="outcome", describe=f"{OUTCOME_CHECK_PREFIX}{outcome or title}"),)

    stops = [
        *(_fits(s, MAX_SENTENCE, "stop_condition_too_long") for s in parsed.get("stop_when")),
        *(_fits(f"{CONSTRAINT_PREFIX}{c}", MAX_SENTENCE, "constraint_too_long")
          for c in parsed.get("constraints")),
        *(_fits(f"{BOUNDARY_PREFIX}{b}", MAX_SENTENCE, "boundary_too_long")
          for b in parsed.get("boundaries")),
    ]
    plan = tuple(
        {
            "kind": kind,
            "summary": summary,
            # Flat on purpose: the card is a signed, mediated task whose canonical
            # JSON is depth-bounded (mediation._MAX_JSON_DEPTH), and a nested task
            # payload inside a plan row would exceed it — the card would be refused.
            "task": {"agent": "jarvis", "kind": kind, "title": _step_label(summary, title)},
        }
        for kind, summary in parsed.steps
    )
    return GoalDraft(
        title=title,
        scope_kinds=scope,
        unrestricted=unrestricted,
        budget=Budget(max_steps=max(DEFAULT_MAX_STEPS, len(plan))),
        deadline_at=moment + DEFAULT_DEADLINE_SECONDS,
        stop_conditions=tuple(stops) or (DEFAULT_STOP,),
        checks=checks,
        deliverable=outcome,
        requested_by=requested_by,
        plan=plan,
    )


def card_lines(draft: GoalDraft) -> list[str]:
    """What the owner is being asked to approve, line by line (chat and CLI)."""
    budget = draft.budget
    hours = budget.max_seconds / 3600.0
    deadline = datetime.fromtimestamp(float(draft.deadline_at), UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"goal: {draft.title}",
        f"scope: {UNRESTRICTED if draft.unrestricted else ', '.join(draft.scope_kinds)}",
        f"budget: {budget.max_steps} steps, {hours:g}h, {budget.max_interrupts} interrupt(s); "
        f"deadline {deadline}",
    ]
    lines += [f"check {c.id}: {c.describe}" for c in draft.checks]
    lines += [f"stop when: {s}" for s in draft.stop_conditions]
    if draft.plan:
        lines += [f"step {n}: {row['kind']}: {row['summary']}" for n, row in enumerate(draft.plan, 1)]
    else:
        lines.append("plan: none — approving it opens a run that proposes nothing")
    return lines


def _company_mode_on() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(FLAG)


def propose_goal(
    orch: Any,
    text: str,
    *,
    requested_by: str = "owner",
    agent: str = "jarvis",
    now: float | None = None,
    push_loop: Any = None,
) -> dict[str, Any]:
    """Propose the goal *text* describes for the owner's approval. Grants nothing.

    Returns ``{"task_id", "title", "card", "draft"}``. Refuses with
    ``GoalContractError``: ``company_mode_off``, a draft refusal,
    ``intake_unavailable``, or ``kernel_denied:<why>`` when the Action Kernel denies
    ``goal.approve``. An error from the governed intake itself propagates.

    ``push_loop`` is the hub's event loop when this runs in a worker thread
    (``asyncio.to_thread`` — every async entry point does, to keep the loop free):
    the card is an interrupt, and its push must still reach the owner — scheduled
    on that loop, thread-safely (``worker.decision_push_loop``). It changes nothing
    else about the card.
    """
    if not _company_mode_on():
        raise GoalContractError("company_mode_off")
    moment = time.time() if now is None else float(now)
    draft = draft_from_text(text, now=moment, requested_by=requested_by)
    from agents.core.autonomy.company_runtime import _governed_intake

    intake = _governed_intake(orch, None) if orch is not None else None
    if intake is None:
        raise GoalContractError("intake_unavailable")
    from agents.core.autonomy.worker import decision_push_loop
    from agents.core.kernel.binding import make_action_kernel

    authorizer = make_action_kernel(orch)
    with decision_push_loop(push_loop):
        task_id = goal_contract.propose(draft, intake, agent=agent, authorizer=authorizer,
                                        now=moment)
    logger.info("goal proposed by %s: task %s", requested_by, task_id)
    return {"task_id": task_id, "title": draft.title, "card": card_lines(draft),
            "draft": draft.as_payload()}


def subgoal_target(runs: Sequence[Any], args: str) -> tuple[Any | None, str]:
    """Which running goal ``/subgoal <args>`` means, and the criterion text.

    The only open run, when there is one; otherwise the run whose id is the first
    word. ``(None, text)`` when that is ambiguous or there is no open run — the
    caller says which.
    """
    open_runs = [r for r in runs if getattr(r, "status", "") in SUBGOAL_OPEN_STATUSES]
    first, _sep, rest = str(args or "").strip().partition(" ")
    by_id = {getattr(r, "id", None): r for r in open_runs}
    if first in by_id and rest.strip():
        return by_id[first], rest.strip()
    if len(open_runs) == 1:
        return open_runs[0], str(args or "").strip()
    return None, str(args or "").strip()


__all__ = [
    "BOUNDARY_PREFIX",
    "CONSTRAINT_PREFIX",
    "CONTRACT_ALIASES",
    "CONTRACT_FIELDS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_STOP",
    "OUTCOME_CHECK_PREFIX",
    "SCOPE_ALIAS",
    "ParsedGoal",
    "card_lines",
    "draft_from_text",
    "parse_goal_text",
    "propose_goal",
    "refusal_text",
    "subgoal_target",
]
