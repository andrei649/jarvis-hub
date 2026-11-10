"""Verify-on-stop: the model is told to verify before it claims the work is done.

Hermes (``agent/verification_stop.py`` + ``turn_stop_gates.py``): when the model tries to
end a turn with a text answer after editing code that has no fresh passing verification,
its answer is held and a user-role nudge hands the turn back, at most twice. Nerva's
version, for an execution model where an edit runs only after the owner approved it:

* **When.** The owner turned it on (``/verify on-stop on``; off by default, as in Hermes),
  the model is ending its turn with a text answer, and this session has *applied* edits
  to code (not prose: ``.md``, ``.txt``, ``LICENSE`` …) in a project whose evidence
  ledger has no full passing check since (:func:`.evidence.pending`).
* **How.** The tool loop keeps the answer, appends it and the nudge to the transcript and
  gives the model another round (``agent_runtime``); at most one nudge per turn and
  :data:`.evidence.MAX_NUDGES` per generation of edits, so it can never loop. If the
  loop's budget runs out, the held answer is the turn's reply.
* **Never around approvals.** The nudge only asks. Running the check is a ``terminal_run``
  call like any other: an approval card, the approval mode, plan mode and the e-stop all
  apply; the nudge says that a queued check is not a passing one. There is no nudge in
  plan mode or under the e-stop (nothing could run), nor for a turn that cannot run a
  command, where the nudge would ask for the impossible; it then says to report the gap.

Not adopted: Hermes's ``pre_verify`` plugin hook. Nerva has no hook that may return
prompt text (extension events are observe-only by design; owner hooks are an open owner
decision, G17).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("jarvis.verify.stop")

MAX_PATHS_SHOWN = 8


def _blocked(session: str) -> bool:
    from agents.core import estop
    from agents.core.kernel import plan_mode

    if estop.is_engaged():
        return True
    try:
        return plan_mode.default_store().is_active(session)
    except Exception:  # noqa: BLE001
        return True


def build_nudge(session: str | None, offered: frozenset[str] | None = None) -> tuple[str, str] | None:
    """``(root, nudge text)`` when this turn should not end yet, else None."""
    from . import config, evidence
    from .project import detect_facts, load_recipe, verify_commands

    if not session or not config.verify_on_stop() or _blocked(session):
        return None
    candidates = evidence.pending(session)
    if not candidates:
        return None
    item = candidates[0]
    root = item["root"]
    from pathlib import Path

    try:
        facts = detect_facts(Path(root))
        recipe, _source = load_recipe(Path(root))
        commands = verify_commands(facts, recipe)
    except Exception:  # noqa: BLE001
        commands = []
    state = evidence.status(root, session)
    detail = state["status"]
    last = state.get("evidence") or {}
    if last.get("canonical"):
        detail += f"; last check `{last['canonical']}` exited {last.get('exit_code')}"
    paths = item["changed_paths"]
    shown = "\n".join(f"- `{p}`" for p in paths[:MAX_PATHS_SHOWN])
    if len(paths) > MAX_PATHS_SHOWN:
        shown += f"\n- ... and {len(paths) - MAX_PATHS_SHOWN} more"
    can_run = offered is None or "terminal_run" in offered
    if commands and can_run:
        listed = ", ".join(f"`{c}`" for c in commands[:3]) + (", ..." if len(commands) > 3 else "")
        instruction = (f"Run the relevant verification command now with `terminal_run` in `{root}` ({listed}), "
                       "read any failure, repair the code, and summarise what passed. A command that waits for "
                       "the owner's approval has not passed yet: say it is queued, do not claim it passed.")
    elif commands:
        instruction = ("You cannot run a command in this turn. Tell the owner which check to run "
                       f"({', '.join(f'`{c}`' for c in commands[:3])}, or `/verify run`) instead of claiming "
                       "the work is verified.")
    else:
        instruction = ("No test, lint or build command was detected for this project. Say how the change "
                       "could be checked, and describe it as unverified rather than claiming it works.")
    text = ("[System: code in this project was edited in this conversation, but the project has no fresh "
            "passing verification yet.\n\n"
            f"Verification status: {detail}\n\nChanged paths:\n{shown}\n\n{instruction} If verification "
            "is not possible, explain the concrete blocker instead of claiming the work is fully verified.]")
    return root, text


def turn_end_nudge(session: str | None, offered: frozenset[str] | None = None) -> str | None:
    """The nudge for a turn about to end, recorded as given; None when the turn may end."""
    try:
        built = build_nudge(session, offered)
        if built is None:
            return None
        root, text = built
        from . import evidence

        evidence.note_nudged(str(session), root)
        return text
    except Exception:  # noqa: BLE001 — the gate never breaks a turn
        logger.warning("verify-on-stop check failed", exc_info=True)
        return None


__all__ = ["build_nudge", "turn_end_nudge"]
