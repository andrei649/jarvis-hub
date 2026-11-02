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


def record_turn_notice(code: str, text: str) -> bool:
    """Note one notice for the turn in flight; a no-op outside one, and once per code.
    Whether it was taken: ``False`` outside a turn, so a producer with something to say
    later (H403: a background review's summary) keeps it for a reply that can show it."""
    sink = _turn_notices.get()
    if sink is None:
        return False
    if not any(item.get("code") == code for item in sink):
        sink.append({"code": str(code), "text": str(text)})
    return True


class FootedReply(str):
    """A channel reply with the turn's system lines under it (H674 ``ℹ`` notices, H430
    ``🧠`` recall lines), kept apart from the reply they sit under.

    The ``str`` is the whole message a person reads: the reply, a blank line, one line
    per notice. :attr:`spoken` is the reply alone. The footer is status for reading,
    never part of the answer, so whatever turns a reply into speech (a Telegram chat in
    voice mode) takes :func:`spoken_text` and the voice note says only what was answered.
    """

    spoken: str

    def __new__(cls, reply: str, lines):
        if type(reply) is not str or not reply.strip():
            raise ValueError("A footer sits under a reply")
        footer = [str(line) for line in lines if str(line).strip()]
        if not footer:
            raise ValueError("A footed reply has at least one footer line")
        instance = super().__new__(cls, reply.rstrip() + "\n\n" + "\n".join(footer))
        instance.spoken = reply
        return instance


def spoken_text(message: object) -> str:
    """What a voice note of *message* may say: a :class:`FootedReply`'s reply alone, any
    other message whole."""
    if isinstance(message, FootedReply):
        return message.spoken
    return str(message or "")


__all__ = ["FootedReply", "open_turn_notices", "record_turn_notice", "reset_turn_notices",
           "spoken_text"]
