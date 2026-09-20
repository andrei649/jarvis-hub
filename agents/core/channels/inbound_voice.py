"""A voice note becomes what the sender said — or nothing, and they are told why.

The counterpart to :mod:`media_reader`, and deliberately not a copy of it,
because a transcript and a photo description are different kinds of thing and
the difference decides the security design.

**A description is not fenced here, and that is the point.** ``media_reader``
wraps what it produces in the untrusted fence because a photo description is a
*model's observation of bytes a stranger chose* — text rendered into an image is
exactly as untrusted as text from the web. A transcript is not that. It is the
sender's own words, at precisely the trust level those words would have had if
they had typed them, so it travels as an ordinary turn: the channel's `inbound`
origin already holds an action derived from it for approval, and `Gateway`'s
taint marking already applies. Fencing it would be worse than redundant — it
would tell the model to read the owner's own request as quarantined data, and it
would advertise a protection that is not the one doing the work here.

**The protection that is doing the work is the hallucination filter.** Fed
silence, Whisper returns a fluent invented sentence. A voice note becomes an
inbound turn, and an inbound turn can ask for things, so a hallucinated
transcript is an un-authored instruction entering a governed system — nobody
said it. :mod:`agents.core.voice.hallucination` is what stops that, and it runs
inside the engine so the HTTP dictation path gets it too.

The rest is the discipline ``media_reader`` established, for the same reasons:
the gate is asked *before* the download so a host with no speech engine never
pulls someone's recording down; bytes are size-capped, held only for the call,
never written to disk and never logged; every failure is a named reason rather
than an exception or, worse, a sentinel string that reaches the model as if it
were speech.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.channels.inbound_voice")

PROVENANCE = "local_whisper"

REASON_NO_STT = "stt_not_installed"
REASON_EMPTY = "empty_audio"
REASON_TOO_LARGE = "audio_too_large"
REASON_FAILED = "stt_failed"
REASON_SILENCE = "silence_or_hallucination"
#: Not raised here: the caller fetches the bytes, so it owns this failure and
#: builds the refusal. The reason lives here so one table explains every outcome.
REASON_DOWNLOAD = "download_failed"

#: A voice note is speech, not a podcast. Telegram's own ceiling is 20 MB; this
#: is what may be handed to a local transcriber in one call.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
#: Bounds what reaches the transcript even if a long recording gets through.
MAX_TRANSCRIPT_CHARS = 4000

#: What :meth:`STTEngine.transcribe` returns instead of raising. Each is a
#: failure, and none of them is ever handed onward as something a person said.
#: Matching is on the leading bracket because the error variant carries a
#: message — the same rule `routers/voice.py` and `frontend/src/voice.ts` use.
SENTINEL_PREFIX = "["
SENTINEL_SILENCE = "[silence]"
SENTINEL_UNAVAILABLE = "[STT unavailable]"

Transcriber = Callable[[bytes, str], Awaitable[str]]


@dataclass(frozen=True)
class Transcript:
    """What a local engine heard in one recording, plus why not."""

    ok: bool
    text: str = ""
    sha256: str = ""
    reason: str = ""
    provenance: str = PROVENANCE

    def to_dict(self) -> dict[str, Any]:
        """A loggable view. What the sender said stays out of the log."""
        return {
            "ok": self.ok,
            "sha256": self.sha256,
            "reason": self.reason,
            "provenance": self.provenance,
            "chars": len(self.text),
        }


class InboundVoiceReader:
    """``(audio_bytes, language=)`` → what was said, over a local engine only.

    ``transcribe`` injects the engine call for tests; in production it resolves
    to the process-wide Whisper engine, so a refusal costs no model load.
    """

    provenance = PROVENANCE

    def __init__(
        self,
        *,
        transcribe: Transcriber | None = None,
        available: bool | None = None,
        max_bytes: int = MAX_AUDIO_BYTES,
        max_chars: int = MAX_TRANSCRIPT_CHARS,
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 32:
            raise ValueError("max_chars must be an integer of at least 32")
        self._transcribe = transcribe
        self._available = available
        self.max_bytes = max_bytes
        self.max_chars = max_chars

    @property
    def is_available(self) -> bool:
        """True only when this host actually has a local speech engine."""
        if self._available is not None:
            return bool(self._available)
        try:
            from agents.core.voice.stt import HAS_WHISPER
        except Exception:  # pragma: no cover - import guard, not a code path
            return False
        return bool(HAS_WHISPER)

    def refusal(self) -> Transcript | None:
        """Why nothing can be transcribed right now, or ``None`` to proceed.

        Answerable before any bytes exist, so a caller can skip the download —
        a host with no speech engine never pulls someone's recording onto it.
        :meth:`__call__` consults the same method, so the two cannot disagree.
        """
        if not self.is_available:
            return Transcript(False, reason=REASON_NO_STT)
        return None

    async def __call__(self, audio_bytes: bytes, *, language: str = "ro") -> Transcript:
        """Transcribe ``audio_bytes``; every refusal is a reason, never an exception."""
        digest = hashlib.sha256(bytes(audio_bytes or b"")).hexdigest()
        if not audio_bytes:
            return Transcript(False, reason=REASON_EMPTY)
        if len(audio_bytes) > self.max_bytes:
            return Transcript(False, sha256=digest, reason=REASON_TOO_LARGE)
        refused = self.refusal()
        if refused is not None:
            return Transcript(False, sha256=digest, reason=refused.reason)

        transcribe = self._transcribe or self._engine_call
        try:
            raw = await transcribe(bytes(audio_bytes), language)
        except Exception:
            # Never carry engine or transport exception text upward.
            logger.info("voice note transcription failed (sha256=%s)", digest[:12])
            return Transcript(False, sha256=digest, reason=REASON_FAILED)
        text = (raw if isinstance(raw, str) else "").strip()
        if not text:
            return Transcript(False, sha256=digest, reason=REASON_FAILED)
        if text.startswith(SENTINEL_PREFIX):
            # `[silence]` is the engine saying nothing was said — which is also
            # what it now says for a discarded hallucination, so a recording of
            # silence and an invented sentence reach the sender as the same
            # honest answer. Anything else bracketed is the engine failing.
            reason = REASON_SILENCE if text == SENTINEL_SILENCE else REASON_FAILED
            if text == SENTINEL_UNAVAILABLE:
                reason = REASON_NO_STT
            return Transcript(False, sha256=digest, reason=reason)
        return Transcript(True, text=text[: self.max_chars], sha256=digest)

    async def _engine_call(self, audio_bytes: bytes, language: str) -> str:
        """Transcribe on the process-wide engine, off the event loop.

        The cache lives in ``routers/voice.py`` today, which is the wrong home
        for it — a channel reaching into a router is a layering wart. It is
        imported rather than duplicated because the alternative is a second
        Whisper model resident in memory, and moving the cache is its own change
        with its own tests, not something to smuggle into this one.
        """
        import asyncio

        from agents.core.routers.voice import _stt_engine

        engine = await asyncio.to_thread(_stt_engine)
        return await engine.transcribe_async(audio_bytes, language=language)


#: One plain clause per refusal, for the sender. No handles, no host names, no
#: exception text — the discipline `inbound_media._NOTES` set.
NOTES: dict[str, str] = {
    REASON_NO_STT: "there is no speech engine installed here yet",
    REASON_EMPTY: "the download came back empty",
    REASON_TOO_LARGE: "it is longer than I will hand to the local transcriber",
    REASON_FAILED: "the local transcriber did not manage to read it",
    REASON_SILENCE: "I could not hear anything said in it",
    REASON_DOWNLOAD: "I could not download it from Telegram",
}


def note(transcript: Transcript) -> str:
    """The clause explaining a refusal, for the one honest line the sender gets."""
    if not isinstance(transcript, Transcript):
        raise TypeError("note() needs a Transcript")
    if transcript.ok:
        return ""
    return NOTES.get(transcript.reason, "I could not make it out")


def echo_line(transcript: Transcript) -> str:
    """The one line that says back what was heard (Hermes ``stt_echo_transcripts``).

    Sent before the answer, so a misheard note is caught by the person who
    sent it. A service line: the adapter never speaks it and it never counts
    as the reply to the note.
    """
    if not isinstance(transcript, Transcript):
        raise TypeError("echo_line() needs a Transcript")
    if not transcript.ok:
        return ""
    return f"🎙️ I heard: “{transcript.text.strip()}”"


def turn_text(transcript: Transcript, caption: str = "") -> str:
    """The turn: what the sender said, as if they had typed it.

    No fence and no preamble — see the module docstring. A caption on a voice
    note is unusual but legal on Telegram; when there is one it leads, because
    the person wrote it deliberately, and the spoken part follows.
    """
    if not isinstance(transcript, Transcript):
        raise TypeError("turn_text() needs a Transcript")
    written = caption.strip() if isinstance(caption, str) else ""
    if not transcript.ok:
        return written
    spoken = transcript.text.strip()
    if written and spoken:
        return f"{written}\n\n{spoken}"
    return spoken or written


__all__ = [
    "MAX_AUDIO_BYTES",
    "MAX_TRANSCRIPT_CHARS",
    "NOTES",
    "PROVENANCE",
    "REASON_DOWNLOAD",
    "REASON_EMPTY",
    "REASON_FAILED",
    "REASON_NO_STT",
    "REASON_SILENCE",
    "REASON_TOO_LARGE",
    "SENTINEL_SILENCE",
    "SENTINEL_UNAVAILABLE",
    "InboundVoiceReader",
    "Transcript",
    "echo_line",
    "note",
    "turn_text",
]
