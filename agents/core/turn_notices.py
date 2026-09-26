"""Per-turn collector for notices the owner should see beside a reply (H674).

Some things happen inside a turn that change what the reply could be built from —
the conversation summary was still being written, say — and are the owner's to
know, but are not the reply. The turn records them here and whoever started it
(``/chat``, the stream) hands them back beside the reply, where the HUD shows them.

Same shape as :mod:`turn_approvals`, for the same reason: the ContextVar holds a
**mutable list**, so a turn that runs part of its work under a copied context
(``asyncio.create_task(..., context=...)``) still reaches the caller's list.
One notice per code per turn: a multi-agent turn that builds its history twice
still says it once.
"""

from __future__ import annotations

from contextvars import ContextVar

#: ``None`` — nobody is collecting — is distinct from ``[]``, a turn that had
#: nothing to say.
_turn_notices: ContextVar[list[dict] | None] = ContextVar("jarvis_turn_notices", default=None)


def open_turn_notices() -> tuple[list[dict], object]:
    """Start a fresh collector; the caller keeps the list and resets its own bind."""
    sink: list[dict] = []
    return sink, _turn_notices.set(sink)


def reset_turn_notices(token) -> None:
    if token is not None:
        _turn_notices.reset(token)


def record_turn_notice(code: str, text: str) -> None:
    """Note one notice for the turn in flight; a no-op outside one, and once per code."""
    sink = _turn_notices.get()
    if sink is None or any(item.get("code") == code for item in sink):
        return
    sink.append({"code": str(code), "text": str(text)})


__all__ = ["open_turn_notices", "record_turn_notice", "reset_turn_notices"]
