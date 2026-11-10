"""``/plan`` — plan before acting (Hermes H668).

``/plan <task>`` does three things, all for the owner only:

1. It puts this conversation in **plan mode** (``kernel/plan_mode.py``): from now on the
   Action Kernel and the tool front door let only reads run in it. That is the part
   that makes "do not implement anything" true whatever the model does, and it stays
   on — across turns and across a restart — until the owner sends ``/plan off``.
2. It hands the model Hermes's own plan prompt (``agent/plan_prompt.py``, adopted
   byte-identical) as an ordinary turn, plus one Nerva note: the hub, not the model,
   saves the plan, and where.
3. When that turn answers, the hub saves the reply as a markdown file under
   ``<data>/plans/YYYY-MM-DD_HHMMSS-<slug>.md`` and says where. The file is written by
   the hub for the owner, never by a model tool, so plan mode does not have to let any
   write through.

``/plan`` alone plans what the conversation has been about (Hermes: the prompt asks
the model to infer the task, or to ask). ``/plan status`` shows the mode and the saved
plans; ``/plan off`` (``exit``, ``done``) leaves plan mode — the owner's action, audited.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.plan_commands")

PLAN_USAGE = ("Usage: /plan <what to plan> — plan mode on, a written plan, nothing implemented; "
              "/plan (plan what we have been discussing) · /plan status · /plan off")
_OFF_WORDS = frozenset({"off", "exit", "done", "leave", "stop"})
_STATUS_WORDS = frozenset({"status", "list"})
_MAX_PLAN_BYTES = 256_000

#: The note Nerva adds after Hermes's prompt: plan mode is enforced here, and the hub
#: saves the reply. Hermes's own text says "If the runtime provides a specific target
#: path, use that exact path instead" — this is that runtime.
RUNTIME_NOTE = (
    "Runtime note (Nerva): plan mode is enforced by the hub for this conversation — tools "
    "that write, send or run anything are refused until the owner sends /plan off. Do not "
    "try to save the file yourself. Reply with the complete plan in markdown; Nerva saves "
    "your reply as the plan file at this path: {path}"
)


@dataclass(frozen=True)
class TurnRewrite:
    """A command's answer that continues the turn: *prompt* goes to the model as the
    user's message; *reply* is what the command plane reports (logs, events)."""

    prompt: str
    reply: str
    #: For ``/plan``: where the hub saves the reply when the turn answers.
    path: str = ""


@dataclass(frozen=True)
class _PlanTurn:
    session_id: str
    path: str


_plan_turn: ContextVar[_PlanTurn | None] = ContextVar("nerva_plan_turn", default=None)


def plans_dir() -> Path:
    from agents.core.paths import data_path

    return data_path("plans")


def _slug(task: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", (task or "").lower()).strip("-")
    return (words[:48].rstrip("-") or "plan")


def plan_path(task: str, now: float | None = None) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now if now is not None else time.time()))
    return plans_dir() / f"{stamp}-{_slug(task)}.md"


def build_prompt(task: str, path: Path) -> str:
    from agents.vendor.hermes.agent.plan_prompt import build_plan_prompt

    return build_plan_prompt(task) + "\n" + RUNTIME_NOTE.format(path=path)


def _who(ctx: Any) -> str:
    return f"{ctx.principal.channel}:{ctx.principal.sender or 'owner'}"


async def plan_command(ctx: Any):
    from .kernel.plan_mode import PlanModeRefused, PlanModeUnreadable, default_store

    if not ctx.principal.admin:          # the tier says so too; re-checked at the change
        return "Only the owner can use plan mode; nothing changed."
    session = getattr(ctx.orch, "session_id", None)
    if not session:
        return "Plan mode is per conversation, and there is no conversation here."
    store = default_store()
    audit = getattr(ctx.orch, "intent_log", None)
    words = (ctx.args or "").split()
    word = words[0].lower() if len(words) == 1 else ""
    if word in _OFF_WORDS:
        try:
            was = await asyncio.to_thread(store.exit, session, owner=True, by=_who(ctx), audit=audit)
        except PlanModeRefused:
            return "Only the owner can leave plan mode; nothing changed."
        return ("Plan mode is off: this conversation can act again (every action still asks as "
                "your approval mode says)." if was else "Plan mode was not on here.")
    if word in _STATUS_WORDS:
        try:
            row = await asyncio.to_thread(store.state, session)
        except PlanModeUnreadable:
            return ("The plan-mode state cannot be read, so every conversation is held in plan mode. "
                    "/plan off resets it.")
        if row is None:
            return "Plan mode is off here. " + PLAN_USAGE
        since = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(row.get("since") or 0)))
        lines = [f"Plan mode is ON here since {since}: only reads run until you send /plan off."]
        if row.get("task"):
            lines.append(f"Planning: {row['task']}")
        plans = list(row.get("plans") or [])
        if plans:
            lines.append("Saved plans:")
            lines.extend(f"- {p}" for p in plans[-5:])
        return "\n".join(lines)
    task = " ".join((ctx.args or "").split())
    path = plan_path(task)
    try:
        await asyncio.to_thread(store.enter, session, owner=True, by=_who(ctx), task=task, audit=audit)
    except PlanModeRefused:
        return "Only the owner can turn plan mode on; nothing changed."
    except (OSError, ValueError):
        logger.warning("/plan: plan mode could not be saved", exc_info=True)
        return "Plan mode could not be turned on (its state could not be saved); nothing was planned."
    return TurnRewrite(prompt=build_prompt(task, path), path=str(path),
                       reply=f"Plan mode on; planning{': ' + task if task else ''} → {path}")


def begin_plan_turn(session_id: str, path: str) -> None:
    """Mark the running turn as the plan turn (the orchestrator, when it continues one)."""
    if session_id and path:
        _plan_turn.set(_PlanTurn(str(session_id), str(path)))


async def finish_plan_turn(session_id: str, reply: str) -> str | None:
    """Save the plan turn's reply where the prompt said; the saved path, or None.

    Only the turn :func:`begin_plan_turn` marked, only for its own session, only while
    the session is still in plan mode, and only inside the plans folder."""
    marked = _plan_turn.get()
    if marked is None or marked.session_id != str(session_id or ""):
        return None
    _plan_turn.set(None)
    from .kernel.plan_mode import default_store

    store = default_store()
    if not store.is_active(marked.session_id):
        return None
    text = str(reply or "").strip()
    if not text:
        return None
    root = plans_dir().resolve()
    target = Path(marked.path)
    try:
        if target.parent.resolve() != root or target.suffix != ".md":
            return None
    except OSError:
        return None

    def _write() -> str:
        root.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")[:_MAX_PLAN_BYTES]
        with open(target, "xb") as fh:
            fh.write(data + b"\n")
        store.note_plan(marked.session_id, str(target))
        return str(target)

    try:
        saved = await asyncio.to_thread(_write)
    except FileExistsError:
        return None
    except OSError:
        logger.warning("/plan: the plan file could not be written", exc_info=True)
        return None
    from .turn_notices import record_turn_notice

    record_turn_notice("plan.saved", f"Plan saved: {saved} — plan mode stays on until /plan off.")
    return saved
