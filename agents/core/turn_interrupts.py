"""H224 — stop a running ``POST /chat`` turn on its caller's request (Ctrl+C in `nerva chat -i`).

A turn the web door runs is registered here, while the model works on it, under the
**credential that started it** (:func:`agents.core.routers.chat_pending.http_actor`, a
hash of the token, browser session or localhost peer — never a name the request
carries). ``POST /chat/interrupt`` cancels only the turns registered under the
caller's own credential, optionally narrowed to one session: another credential's turn
is not found, not refused, so a caller cannot even learn that it exists.

Cancelling is the same thing the hub already does when the HTTP client goes away
(``http_chat_binding``'s disconnect watcher, ``/chat/stream``'s runner): the turn's
task is cancelled where it awaits. What this adds is that the turn ends with a reply,
:data:`INTERRUPTED_REPLY`, and a ``turn_interrupted`` notice, instead of a dropped
connection — and the turn's own ``finally`` blocks (approvals sink, lease, principal)
run exactly as on any other exit. Nothing here can approve, execute or bypass anything:
it only stops work that its caller started.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

INTERRUPTED_REPLY = "Interrupted. Nothing more was done for this message."
NOTICE_CODE = "turn_interrupted"
NOTICE_TEXT = "You stopped this turn; any step it had not finished was not done."


@dataclass(eq=False)
class LiveTurn:
    actor: str
    session_id: str
    task: asyncio.Task
    interrupted: bool = False


_live: dict[str, set[LiveTurn]] = {}


@contextmanager
def track(actor: str | None, session_id: str | None) -> Iterator[LiveTurn | None]:
    """Register the current task as *actor*'s running turn for the block's duration.

    ``actor`` None (no credential could be derived) registers nothing: such a turn
    cannot be interrupted over HTTP, only by disconnecting."""
    task = asyncio.current_task()
    if not actor or task is None:
        yield None
        return
    turn = LiveTurn(actor, str(session_id or ""), task)
    _live.setdefault(actor, set()).add(turn)
    try:
        yield turn
    finally:
        turns = _live.get(actor)
        if turns is not None:
            turns.discard(turn)
            if not turns:
                del _live[actor]


def interrupt(actor: str | None, session_id: str | None = None) -> int:
    """Cancel *actor*'s running turns (in *session_id* only, when given); how many."""
    if not actor:
        return 0
    stopped = 0
    for turn in tuple(_live.get(actor, ())):
        if session_id is not None and turn.session_id != session_id:
            continue
        if turn.task.done() or turn.interrupted:
            continue
        turn.interrupted = True
        turn.task.cancel()
        stopped += 1
    return stopped


def running(actor: str | None) -> int:
    """How many turns *actor* has running (for tests and diagnostics)."""
    return len(_live.get(actor or "", ()))


def absorb(turn: LiveTurn | None) -> bool:
    """Whether a CancelledError the turn just raised is this module's interrupt.

    When it is, the task's cancel request is withdrawn (``uncancel``) so the web door
    can answer normally; a cancel from anywhere else (a disconnect, shutdown) is not
    absorbed and keeps propagating."""
    if turn is None or not turn.interrupted:
        return False
    task = asyncio.current_task()
    if task is not None and task is turn.task and task.cancelling():
        task.uncancel()
    return True
