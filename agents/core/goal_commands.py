"""``/goal`` and ``/subgoal`` — say "goal: …" in the conversation (H462).

Both are owner commands. ``/goal <text>`` hands the text to
:func:`agents.core.autonomy.goal_intake.propose_goal`, the same front door the
route, the CLI verb and the Company room's form use: the ``goal.approve`` card
crosses the Action Kernel and waits in the decision inbox, and a run opens only
when the owner accepts it there. ``/subgoal <criterion>`` adds an acceptance
criterion to the running goal through ``WorkRunLedger.add_subgoal`` — narrowing
only, so it needs no approval, and it resets nothing.

Hermes' ``/goal`` re-prompts the agent after every turn until a judge says done.
Nerva's run is the approved checklist, worked one governed step per sweep and
graded by the verifier and the judge; these commands are the conversational door
to it, not a second loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("jarvis.goal_commands")

GOAL_USAGE = (
    "Usage: /goal <what you want done>, then optional lines:\n"
    "  verify: <how anyone would know it is done>\n"
    "  scope: <step kinds, e.g. research, write> | unrestricted\n"
    "  step: <kind>: <one step of the plan>\n"
    "  must not: <a constraint>\n"
    "  stop when: <when to give up>\n"
    "It goes to the decision inbox; nothing runs until you approve it there."
)

SUBGOAL_USAGE = "Usage: /subgoal <criterion> — or /subgoal <run id> <criterion> when several goals run."

_SUBGOAL_REFUSALS = {
    "missing_subgoal": "say what else must hold: /subgoal <criterion>",
    "run_already_graded": "grading already started on that run, so its criteria are fixed",
    "too_many_subgoals": "that run already carries the most criteria a run may take",
    "unknown_run": "there is no such run",
}


def _who(ctx: Any) -> str:
    principal = ctx.principal
    return f"{principal.channel}:{principal.sender or 'owner'}"[:128]


def _ledger(orch: Any) -> Any:
    from agents.core.autonomy.work_runs import WorkRunLedger

    ledger = getattr(orch, "work_runs", None)
    return ledger if isinstance(ledger, WorkRunLedger) else None


def _running(ledger: Any) -> list[Any]:
    from agents.core.autonomy.work_runs import SUBGOAL_OPEN_STATUSES

    return [r for r in ledger.list_runs(active_only=True, limit=50)
            if r.status in SUBGOAL_OPEN_STATUSES]


def _subgoal_refusal(reason: str) -> str:
    if reason.startswith("run_") and reason not in _SUBGOAL_REFUSALS:
        return f"that run is {reason[4:]}, and a criterion is added only to a running goal"
    return _SUBGOAL_REFUSALS.get(reason, reason)


async def goal_command(ctx: Any) -> str:
    """``/goal <text>`` proposes a goal; bare ``/goal`` shows the usage and what runs."""
    from agents.core.autonomy.goal_contract import GoalContractError
    from agents.core.autonomy.goal_intake import propose_goal, refusal_text

    text = (ctx.args or "").strip()
    if not text:
        ledger = _ledger(ctx.orch)
        runs = await asyncio.to_thread(_running, ledger) if ledger is not None else []
        lines = [GOAL_USAGE]
        if runs:
            lines.append("Running goals:")
            for run in runs:
                count = len(await asyncio.to_thread(ledger.subgoals, run.id))
                added = f", {count} criteria added" if count else ""
                lines.append(f"  {run.id} · {run.status} · {run.title}{added}")
        return "\n".join(lines)
    try:
        result = await asyncio.to_thread(
            propose_goal, ctx.orch, text, requested_by=_who(ctx)
        )
    except GoalContractError as exc:
        return f"Not proposed: {refusal_text(exc.reason)}."
    except Exception as exc:
        logger.warning("/goal: the governed intake refused the goal card", exc_info=True)
        return f"Not proposed: the decision inbox refused the goal card ({exc.__class__.__name__})."
    card = "\n".join(f"  {line}" for line in result["card"])
    return (
        f"Goal proposed for your approval as task {result['task_id']} — decide it in the "
        "decision inbox; nothing runs until you accept it there.\n" + card
    )


async def subgoal_command(ctx: Any) -> str:
    """``/subgoal <criterion>`` adds a criterion to the running goal; bare lists them."""
    from agents.core.autonomy.goal_intake import subgoal_target
    from agents.core.autonomy.work_runs import WorkRunError

    ledger = _ledger(ctx.orch)
    if ledger is None:
        return "Company mode's run ledger is not available on this hub."
    runs = await asyncio.to_thread(_running, ledger)
    args = (ctx.args or "").strip()
    if not args:
        if not runs:
            return "No goal is running. /goal proposes one."
        lines = []
        for run in runs:
            rows = await asyncio.to_thread(ledger.subgoals, run.id)
            lines.append(f"{run.id} · {run.title}:")
            lines.extend(f"  {row['id']}: {row['describe']}" for row in rows)
            if not rows:
                lines.append("  no criteria added")
        return "\n".join([*lines, SUBGOAL_USAGE])
    first, _sep, rest = args.partition(" ")
    if rest.strip() and first not in {r.id for r in runs}:
        # A run named by id that is no longer open is refused by name — never read as
        # criterion text and added to whichever other goal happens to be running.
        named = await asyncio.to_thread(ledger.get, first)
        if named is not None:
            return f"Not added: {_subgoal_refusal(f'run_{named.status}')}."
    run, criterion = subgoal_target(runs, args)
    if run is None:
        if not runs:
            return ("No goal is running, so there is nothing to add a criterion to. A goal still "
                    "waiting in the decision inbox is edited there.")
        ids = ", ".join(r.id for r in runs)
        return f"Several goals are running ({ids}); say which: /subgoal <run id> <criterion>."
    try:
        record = await asyncio.to_thread(ledger.add_subgoal, run.id, criterion, by=_who(ctx))
    except WorkRunError as exc:
        return f"Not added: {_subgoal_refusal(exc.reason)}."
    return (
        f"Added to “{run.title}” as {record['id']}: {record['describe']}. The run goes on where "
        "it was; it is not done until this holds as well (a criterion nothing can check grades "
        "unverifiable, never passed)."
    )


__all__ = ["GOAL_USAGE", "SUBGOAL_USAGE", "goal_command", "subgoal_command"]
