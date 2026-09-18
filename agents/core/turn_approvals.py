"""Per-turn collector for the approval ids a turn queued.

The gated Tool-RPC path already knows the id of the task it pushed onto the
approval queue — it hands it back beside ``reason="approval_required"`` — but the
tool loop answers the turn with one fixed sentence and the turn answers its
caller with a plain string, so the id died between them. A caller was told "this
needs approval" about something it could not name, let alone show or poll. This
module carries those ids back out to whoever started the turn.

The ContextVar holds a **mutable list**, never a value the child re-sets: a gated
tool call runs under ``asyncio.create_task(..., context=...)`` (see
``agent_runtime``), which *copies* the context, so a ``set()`` down there would
never reach the turn that is waiting on it. Appending to the shared list does —
the same reason ``kernel/binding._OneShotDecision`` can hand a decision across
that copy.

Reporting only. Nothing here approves, executes or unblocks a queued task; the
Action Kernel and the decision inbox stay the only things that can.
"""

from __future__ import annotations

from contextvars import ContextVar

#: ``None`` — not inside a turn that is collecting — is deliberately distinct
#: from ``[]``: the first means nobody is listening, the second means a turn
#: listened and queued nothing.
_turn_approvals: ContextVar[list[int] | None] = ContextVar(
    "jarvis_turn_approvals",
    default=None,
)


def open_turn_approvals() -> tuple[list[int], object]:
    """Start a fresh collector and hand the caller the list the turn appends to.

    For whoever wraps the turn (``/chat``): it keeps the list object, so it can
    read the ids back after ``handle_input`` has returned and reset its own bind.
    """
    sink: list[int] = []
    return sink, _turn_approvals.set(sink)


def bind_turn_approvals():
    """Bind a collector for a turn, unless the caller already opened one.

    Adopting an outer sink is the point: a caller that wants the ids opened one
    first, and the turn must fill *that* list rather than a private one nobody
    holds a reference to. With no caller sink, the turn still gets its own — so a
    voice or CLI turn can never append into a neighbouring turn's collector.

    Returns a reset token, or ``None`` when an outer sink was adopted (the outer
    binder owns resetting it).
    """
    if _turn_approvals.get() is not None:
        return None
    return _turn_approvals.set([])


def reset_turn_approvals(token) -> None:
    if token is not None:
        _turn_approvals.reset(token)


def record_pending_approval(task_id) -> None:
    """Note one queued approval id for the turn in flight.

    A no-op outside a turn: the same enqueue sites are reached by background
    autonomy ticks, and those belong to no caller.
    """
    sink = _turn_approvals.get()
    try:
        queued = int(task_id)
    except (TypeError, ValueError):
        # An id the caller could not act on is worse than no id at all — the
        # queue row exists either way and the reply still says approval is due.
        return
    sink.append(queued)


def current_turn_approvals() -> list[int]:
    """A copy of what this turn has queued so far (empty outside a turn)."""
    return list(_turn_approvals.get() or ())
