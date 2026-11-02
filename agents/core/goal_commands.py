"""``/goal`` and ``/subgoal`` — say "goal: …" in the conversation (H462).

Both are owner commands. ``/goal <text>`` hands the text to
:func:`agents.core.autonomy.goal_intake.propose_goal`, the same front door the
route, the CLI verb and the Company room's form use: the ``goal.approve`` card
crosses the Action Kernel and waits in the decision inbox, and a run opens only
when the owner accepts it there. ``/subgoal <criterion>`` adds an acceptance
criterion to the running goal through ``WorkRunLedger.add_subgoal`` — narrowing
only, so it needs no approval, and it resets nothing.

The owner intervenes from the chat through the same governed paths as the HUD and
the routes — never a second, weaker one:

* ``/goal status`` — what each running goal is doing (read-only);
* ``/goal stop`` (or ``clear``) — ``WorkRunLedger.request_stop``, exactly what
  ``POST /api/company/runs/{id}/stop`` does: a one-way door, narrowing only;
* ``/goal pause`` — parks the run on an owner barrier (``RunBarriers.request``,
  ``source="owner"``): it suppresses ticks, grants nothing, and still ends at the
  run's own deadline;
* ``/goal resume`` — the owner's clear (``RunBarriers.clear``), exactly what
  ``POST /api/company/runs/{id}/barrier/clear`` (the HUD's "stop waiting") does;
* ``/subgoal remove <N>`` / ``/subgoal clear`` — take back criteria the owner
  added (``WorkRunLedger.remove_subgoal`` / ``clear_subgoals``). Only the owner's own
  additions: the checks approved on the goal card stay, so the run returns to —
  never below — the contract that was approved.

A control verb is the whole argument, optionally followed by a run id
(``/goal pause 3f2a…``), so a goal text that merely starts with one of these
words ("/goal stop the leaking tap") is still a goal; ``remove``/``clear`` in
``/subgoal`` likewise only when followed by a criterion number or nothing.

Hermes' ``/goal`` re-prompts the agent after every turn until a judge says done.
Nerva's run is the approved checklist, worked one governed step per sweep and
graded by the verifier and the judge; these commands are the conversational door
to it, not a second loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("jarvis.goal_commands")

GOAL_USAGE = (
    "Usage: /goal <what you want done>, then optional lines:\n"
    "  verify: <how anyone would know it is done>\n"
    "  scope: <step kinds, e.g. research, write> | unrestricted\n"
    "  step: <kind>: <one step of the plan>\n"
    "  must not: <a constraint>\n"
    "  boundaries: <a limit in words or paths, e.g. only docs/>\n"
    "  stop when: <when to give up>\n"
    "It goes to the decision inbox; nothing runs until you approve it there.\n"
    "Controls: /goal status · /goal pause · /goal resume · /goal stop [run id]"
)

SUBGOAL_USAGE = ("Usage: /subgoal <criterion> — or /subgoal <run id> <criterion> when several "
                 "goals run; /subgoal remove <N> · /subgoal clear.")

#: The control verbs of ``/goal`` (Hermes' names; ``clear`` is Hermes' stop).
CONTROL_VERBS = frozenset({"status", "stop", "clear", "pause", "resume"})

#: A run id as the ledger mints it.
_RUN_ID = re.compile(r"^[0-9a-f]{16}$")
_SUBGOAL_REF = re.compile(r"^(?:subgoal:)?(\d{1,4})$")

_PAUSE_REASON = "paused by the owner"

_SUBGOAL_REFUSALS = {
    "missing_subgoal": "say what else must hold: /subgoal <criterion>",
    "run_already_graded": "grading already started on that run, so its criteria are fixed",
    "too_many_subgoals": "that run already carries the most criteria a run may take",
    "unknown_run": "there is no such run",
    "unknown_subgoal": "that run has no such criterion (/subgoal lists them)",
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


def _active(ledger: Any) -> list[Any]:
    return list(ledger.list_runs(active_only=True, limit=50))


def _subgoal_refusal(reason: str) -> str:
    from agents.core.autonomy.work_runs import MAX_SUBGOAL_CHARS

    if reason == "subgoal_too_long":
        return (f"a criterion is at most {MAX_SUBGOAL_CHARS} characters; nothing was cut, and "
                "nothing was added")
    if reason.startswith("run_") and reason not in _SUBGOAL_REFUSALS:
        return f"that run is {reason[4:]}, and a criterion is added only to a running goal"
    return _SUBGOAL_REFUSALS.get(reason, reason)


def _paused(run: Any) -> bool:
    return bool(run.barrier) and (run.barrier or {}).get("source") == "owner"


def _status_line(ledger: Any, run: Any) -> str:
    from agents.core.autonomy.run_barriers import describe

    facts = [f"{run.steps_used}/{run.budget.max_steps} steps"]
    if run.barrier and run.status in {"planning", "working"}:
        facts.append(f"waiting on {describe(run.barrier)}")
    elif run.status == "blocked":
        facts.append("waiting on your decision in the inbox")
    count = len(ledger.subgoals(run.id))
    if count:
        facts.append(f"{count} criteria added")
    return f"{run.id} · {run.status} · {run.title} — " + "; ".join(facts)


def _control(args: str, known: set[str]) -> tuple[str, str] | None:
    """``(verb, run id or "")`` when *args* is a control verb, else None (goal text)."""
    first, _sep, rest = args.strip().partition(" ")
    verb = first.lower()
    if verb not in CONTROL_VERBS:
        return None
    rest = rest.strip()
    if not rest:
        return verb, ""
    if " " not in rest and (rest in known or _RUN_ID.match(rest)):
        return verb, rest
    return None


def _pick(runs: list[Any], run_id: str, verb: str) -> tuple[Any | None, str]:
    """The run a control verb means, or ``(None, why not)``."""
    if run_id:
        for run in runs:
            if run.id == run_id:
                return run, ""
        return None, f"there is no running goal {run_id}"
    if verb == "resume":
        paused = [r for r in runs if _paused(r)] or [r for r in runs if r.barrier]
        if len(paused) == 1:
            return paused[0], ""
        runs = paused or runs
    if len(runs) == 1:
        return runs[0], ""
    if not runs:
        return None, ("no goal is running (a goal still waiting in the decision inbox is "
                      "decided there)")
    ids = ", ".join(r.id for r in runs)
    return None, f"several goals are running ({ids}); say which: /goal {verb} <run id>"


async def _goal_control(ledger: Any, verb: str, run_id: str) -> str:
    from agents.core.autonomy.run_barriers import (
        MAX_BARRIER_SECONDS,
        RunBarriers,
        describe,
        until,
    )
    from agents.core.autonomy.work_runs import WorkRunError

    runs = await asyncio.to_thread(_active, ledger)
    if verb == "status":
        chosen = [r for r in runs if not run_id or r.id == run_id]
        if not chosen:
            return ("No goal is running." if not run_id
                    else f"There is no running goal {run_id}.") + " /goal proposes one."
        lines = await asyncio.to_thread(lambda: [_status_line(ledger, r) for r in chosen])
        return "\n".join(["Running goals:", *(f"  {line}" for line in lines)])
    run, why = _pick(runs, run_id, verb)
    if run is None:
        return f"Nothing changed: {why}."
    try:
        if verb in {"stop", "clear"}:
            # The route's own call: a one-way door, narrowing only.
            after = await asyncio.to_thread(ledger.request_stop, run.id, reason="owner")
            if after.status == "stopped":
                return f"Stopped “{run.title}” ({run.id}). It takes no further step."
            return (f"Stopping “{run.title}” ({run.id}): it takes no further step, and the step "
                    "in flight unwinds.")
        barriers = RunBarriers(ledger)
        if verb == "pause":
            if _paused(run):
                return f"“{run.title}” is already paused; /goal resume lets it go on."
            if run.status == "blocked":
                return (f"Nothing changed: “{run.title}” is waiting on your decision in the "
                        "decision inbox, so it takes no step until you answer; /goal stop ends it.")
            if run.barrier:
                return (f"Nothing changed: “{run.title}” is already waiting on "
                        f"{describe(run.barrier)}, so it takes no step; /goal stop ends it.")
            state = await asyncio.to_thread(barriers.request, run.id, {
                "kind": "deadline", "target": {"in_seconds": MAX_BARRIER_SECONDS},
                "reason": _PAUSE_REASON,
            }, source="owner")
            end = until(state)
            reply = f"Paused “{run.title}” ({run.id}): it takes no step until you /goal resume."
            if end:
                reply += f" Its time still runs: at the latest the pause ends at {end}."
            return reply
        # resume — the HUD's "stop waiting": the same owner compare-and-clear.
        cleared, after = await asyncio.to_thread(barriers.clear, run.id, by="owner")
        if cleared:
            return f"Resumed “{run.title}” ({run.id}): it goes on from where it was."
        if after.barrier and after.status in {"planning", "working"}:
            return f"Nothing changed: “{run.title}” now waits on {describe(after.barrier)}."
        if after.status == "blocked":
            return (f"Nothing changed: “{run.title}” is waiting on your decision in the decision "
                    "inbox, not on a pause.")
        return f"Nothing changed: “{run.title}” was not paused or waiting."
    except WorkRunError as exc:
        reason = exc.reason
        if reason == "run_not_parkable":
            return f"Nothing changed: “{run.title}” is {run.status} and cannot be paused."
        if reason in {"budget_spent", "no_time_left"}:
            return f"Nothing changed: “{run.title}” has no time or steps left to pause."
        if reason.startswith("run_"):
            return f"Nothing changed: that run is {reason[4:]}."
        return f"Nothing changed: {reason}."


async def goal_command(ctx: Any) -> str:
    """``/goal <text>`` proposes a goal; bare ``/goal`` shows the usage and what runs;
    ``/goal status|stop|clear|pause|resume [run id]`` intervene in a running one."""
    from agents.core.autonomy.goal_contract import GoalContractError
    from agents.core.autonomy.goal_intake import propose_goal, refusal_text

    text = (ctx.args or "").strip()
    ledger = _ledger(ctx.orch)
    if not text:
        runs = await asyncio.to_thread(_running, ledger) if ledger is not None else []
        lines = [GOAL_USAGE]
        if runs:
            lines.append("Running goals:")
            for run in runs:
                count = len(await asyncio.to_thread(ledger.subgoals, run.id))
                added = f", {count} criteria added" if count else ""
                lines.append(f"  {run.id} · {run.status} · {run.title}{added}")
        return "\n".join(lines)
    if "\n" not in text:
        known = ({r.id for r in await asyncio.to_thread(_active, ledger)}
                 if ledger is not None else set())
        control = _control(text, known)
        if control is not None:
            if ledger is None:
                return "Company mode's run ledger is not available on this hub."
            return await _goal_control(ledger, *control)
    try:
        # The card is an interrupt: capture this loop before leaving it, so the
        # intake (in a worker thread) can still push the card to the owner.
        result = await asyncio.to_thread(
            propose_goal, ctx.orch, text, requested_by=_who(ctx),
            push_loop=asyncio.get_running_loop(),
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


def _subgoal_edit(args: str, known: set[str]) -> tuple[str, str, str] | None:
    """``(verb, run id or "", criterion ref or "")`` for ``remove``/``clear``, else
    None — the arguments are a criterion to add."""
    words = args.split()
    if not words or words[0].lower() not in {"remove", "clear"}:
        return None
    verb, rest = words[0].lower(), words[1:]
    run_id = ""
    if rest and (rest[0] in known or _RUN_ID.match(rest[0])):
        run_id, rest = rest[0], rest[1:]
    if verb == "clear":
        return (verb, run_id, "") if not rest else None
    if len(rest) == 1 and _SUBGOAL_REF.match(rest[0]):
        return verb, run_id, rest[0]
    return None


async def _subgoal_change(ledger: Any, runs: list[Any], verb: str, run_id: str, ref: str,
                          who: str) -> str:
    from agents.core.autonomy.work_runs import WorkRunError

    if run_id:
        run = next((r for r in runs if r.id == run_id), None)
        if run is None:
            named = await asyncio.to_thread(ledger.get, run_id)
            if named is None:
                return f"Nothing changed: {_subgoal_refusal('unknown_run')}."
            return f"Nothing changed: that run is {named.status}."
    elif len(runs) == 1:
        run = runs[0]
    elif not runs:
        return "No goal is running, so there are no criteria to take back."
    else:
        ids = ", ".join(r.id for r in runs)
        return f"Several goals are running ({ids}); say which: /subgoal {verb} <run id>" + (
            f" {ref}." if ref else ".")
    try:
        if verb == "remove":
            row = await asyncio.to_thread(ledger.remove_subgoal, run.id, ref, by=who)
            return (f"Removed {row['id']} from “{run.title}”: {row['describe']}. The checks you "
                    "approved on the goal card are unchanged.")
        rows = await asyncio.to_thread(ledger.clear_subgoals, run.id, by=who)
    except WorkRunError as exc:
        return f"Nothing changed: {_subgoal_refusal(exc.reason)}."
    if not rows:
        return f"“{run.title}” carries no criteria you added, so there was nothing to clear."
    return (f"Cleared {len(rows)} criteria from “{run.title}”; the checks you approved on the "
            "goal card are unchanged.")


async def subgoal_command(ctx: Any) -> str:
    """``/subgoal <criterion>`` adds a criterion to the running goal; bare lists them;
    ``/subgoal remove <N>`` and ``/subgoal clear`` take the owner's own back."""
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
    edit = _subgoal_edit(args, {r.id for r in runs})
    if edit is not None:
        return await _subgoal_change(ledger, runs, *edit, who=_who(ctx))
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


__all__ = ["CONTROL_VERBS", "GOAL_USAGE", "SUBGOAL_USAGE", "goal_command", "subgoal_command"]
