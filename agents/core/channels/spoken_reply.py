"""A reply becomes a voice note — bounded, plain, and never a reason to lose the text.

The outbound half of H071, the mirror of :mod:`inbound_voice`. A chat channel
that can carry audio can answer in it; this turns the text the channel is
already delivering into one bounded audio clip over the host's text-to-speech
engine, and turns every failure into a named reason so the adapter can send
the words anyway and say nothing false.

What is deliberately *not* here:

* **No decision about whether to speak.** That is :mod:`voice_mode`, per chat,
  off by default. This module only answers "given this text, what audio".
* **No second copy of the reply.** The text goes out first, on the ordinary
  path with the ordinary delivery decision; the audio is an addition to a reply
  that was already allowed. A failure here costs the voice note and nothing else.
* **No code, links or markup read aloud.** Fenced code is dropped (it is not
  prose), links become the word "link", and inline markers are stripped with
  the same renderer the plain channels use. The clip is capped at a sentence
  boundary so a long answer gets its first paragraph spoken, not truncated
  mid-word — the full text is in the message above it.
* **Nothing is logged but a digest.** The reply text is the owner's
  conversation; log lines carry lengths, reasons and a hash.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.voice.sentence_stream import split_sentences
from agents.core.voice.speech_text import for_speech

logger = logging.getLogger("jarvis.channels.spoken_reply")

REASON_NO_TTS = "tts_not_installed"
REASON_EMPTY = "nothing_to_say"
REASON_FAILED = "tts_failed"
REASON_TOO_LARGE = "audio_too_large"
#: Not raised here: the adapter owns the transport, so it owns this failure.
REASON_SEND = "send_failed"

#: A voice note is a reply, not an audiobook: the first paragraph or so, at a
#: sentence boundary. The whole text is in the message the note follows.
MAX_SPOKEN_CHARS = 1500
#: What may be handed to a chat transport as one clip.
MAX_AUDIO_BYTES = 8 * 1024 * 1024

_MIME = {
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}

#: ``(text, lang)`` → path of the synthesized file, or ``None`` when the engine
#: could not. Injectable so the adapter is testable without a speech stack.
Synthesizer = Callable[[str, str], Awaitable[str | None]]


def speakable(text: object, *, max_chars: int = MAX_SPOKEN_CHARS, lang: object = None) -> str:
    """The prose worth reading aloud, or ``""`` when there is none.

    The hub's one speech normaliser (H526, :func:`agents.core.voice.speech_text.
    for_speech`: reasoning, code, links, markers, emoji and symbols), then cut at a
    sentence boundary inside ``max_chars`` with an ellipsis marking the cut.
    """
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 16:
        raise ValueError("max_chars must be an integer of at least 16")
    plain = for_speech(text, lang=lang)
    if len(plain) <= max_chars:
        return plain
    kept = ""
    for sentence in split_sentences(plain):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) + 1 > max_chars:
            break
        kept = candidate
    if not kept:
        kept = plain[: max_chars - 1].rstrip()
    return kept.rstrip(" .,;:") + "…"


@dataclass(frozen=True)
class Audio:
    """One synthesized clip, or the reason there is none."""

    ok: bool
    data: bytes = b""
    mime: str = "audio/mpeg"
    sha256: str = ""
    reason: str = ""
    chars: int = 0
    backend: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A loggable view: sizes, reason, digest — never the audio or the text."""
        return {
            "ok": self.ok,
            "bytes": len(self.data),
            "mime": self.mime,
            "sha256": self.sha256,
            "reason": self.reason,
            "chars": self.chars,
            "backend": self.backend,
        }


class SpokenReply:
    """``(reply_text, lang=)`` → :class:`Audio`, over the host's own TTS engine.

    ``synthesize`` injects the engine call for tests; in production it builds
    the same :class:`TTSEngine` the ``/tts`` route uses, with the owner's
    configured voice. ``available`` and ``backend`` pin the gate for tests.
    """

    def __init__(
        self,
        *,
        synthesize: Synthesizer | None = None,
        available: bool | None = None,
        backend: str | None = None,
        max_chars: int = MAX_SPOKEN_CHARS,
        max_bytes: int = MAX_AUDIO_BYTES,
    ) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 16:
            raise ValueError("max_chars must be an integer of at least 16")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._synthesize = synthesize
        self._available = available
        self._backend = backend
        self.max_chars = max_chars
        self.max_bytes = max_bytes

    @staticmethod
    def _engines() -> tuple[bool, bool]:
        try:
            from agents.core.voice.tts import HAS_EDGE, HAS_KOKORO
        except Exception:  # pragma: no cover - import guard, not a code path
            return False, False
        return bool(HAS_EDGE), bool(HAS_KOKORO)

    @property
    def is_available(self) -> bool:
        """True only when this host has a text-to-speech backend to call."""
        if self._available is not None:
            return bool(self._available)
        has_edge, has_kokoro = self._engines()
        return has_edge or has_kokoro

    def backend_label(self) -> str:
        """Which engine would speak, named honestly — cloud is called cloud."""
        if self._backend is not None:
            return self._backend
        has_edge, has_kokoro = self._engines()
        if has_edge:
            return "edge-tts (Microsoft, cloud)"
        if has_kokoro:
            return "kokoro (local)"
        return "none"

    def refusal(self) -> Audio | None:
        """Why nothing can be spoken right now, or ``None`` to proceed.

        Answerable before any synthesis, so the adapter can skip the work and
        the sender can be told the truth by ``/voice``.
        """
        if not self.is_available:
            return Audio(False, reason=REASON_NO_TTS)
        return None

    async def __call__(self, text: object, *, lang: str = "ro") -> Audio:
        """Synthesize the speakable part of *text*; refusals are reasons, not raises."""
        # The gate's first answer imports the optional speech stack; that is paid in
        # a worker thread, never on the event loop (the bounded-request-path rule).
        refused = await asyncio.to_thread(self.refusal)
        if refused is not None:
            return refused
        spoken = speakable(text, max_chars=self.max_chars, lang=lang)
        if not spoken:
            return Audio(False, reason=REASON_EMPTY)
        digest = hashlib.sha256(spoken.encode("utf-8")).hexdigest()
        synthesize = self._synthesize or self._engine_call
        try:
            path = await synthesize(spoken, lang)
        except Exception:
            # Never carry engine or transport exception text upward.
            logger.info("spoken reply synthesis failed (sha256=%s)", digest[:12])
            return Audio(False, sha256=digest, reason=REASON_FAILED, chars=len(spoken))
        if not path:
            return Audio(False, sha256=digest, reason=REASON_FAILED, chars=len(spoken))
        file = Path(str(path))
        try:
            data = file.read_bytes()
        except OSError:
            return Audio(False, sha256=digest, reason=REASON_FAILED, chars=len(spoken))
        finally:
            # The clip lives in the message it is sent with, not on the host.
            with contextlib.suppress(OSError):
                file.unlink()
        if not data:
            return Audio(False, sha256=digest, reason=REASON_FAILED, chars=len(spoken))
        if len(data) > self.max_bytes:
            return Audio(False, sha256=digest, reason=REASON_TOO_LARGE, chars=len(spoken))
        mime = _MIME.get(file.suffix.lower(), "application/octet-stream")
        return Audio(True, data=data, mime=mime, sha256=digest, chars=len(spoken),
                     backend=self.backend_label())

    async def _engine_call(self, text: str, lang: str) -> str | None:
        """Speak on the same engine and voice setting the ``/tts`` route uses.

        The engine module pulls the optional speech backends at import, so the
        import and the construction happen in a worker thread; only the
        synthesis itself, which is already async, runs on the loop.
        """
        engine = await asyncio.to_thread(_load_engine)
        return await engine.speak(text, lang=lang)


def _load_engine():
    """Import and build the TTS engine off the event loop (see ``_engine_call``)."""
    from agents.core.settings_db import get_value
    from agents.core.voice.tts import TTSEngine

    return TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))


__all__ = [
    "MAX_AUDIO_BYTES",
    "MAX_SPOKEN_CHARS",
    "REASON_EMPTY",
    "REASON_FAILED",
    "REASON_NO_TTS",
    "REASON_SEND",
    "REASON_TOO_LARGE",
    "Audio",
    "SpokenReply",
    "speakable",
]
