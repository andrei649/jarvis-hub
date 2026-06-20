"""
sentence_stream.py — Pure, deterministic helpers for sentence-level TTS streaming
(backlog H5.16).

Today TTS synthesizes the whole reply before any audio plays, so the user waits for
the full message. Splitting the reply into sentence-sized chunks lets synthesis (and
playback) start after the *first* sentence instead of the last one.

Everything here is pure and side-effect free — no audio, no network — so it is fully
unit-testable. The streaming synthesis path (`TTSEngine.speak_stream`) and the
`/tts/stream` endpoint build on these primitives.

Two entry points:
  - `split_sentences(text)`        — segment a finished string into sentences.
  - `SentenceAggregator`           — accumulate streamed token deltas and emit
                                     complete sentences as soon as they close, with a
                                     final flush for the trailing remainder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Sentence-final punctuation (Latin + a couple of common CJK/Arabic marks so we
# segment multilingual replies sensibly). A run of these collapses into one boundary
# so "Really?!" / "Wait..." stay together.
_TERMINATORS = ".!?…。！？؟"

# Fullwidth/CJK terminators end a sentence even with no following whitespace (CJK
# text typically isn't space-separated). ASCII terminators still need whitespace/end
# after them to avoid breaking "U.S." style tokens.
_HARD_TERMINATORS = "…。！？"

# Abbreviations whose trailing period must NOT end a sentence. Bilingual RO/EN subset
# matching the surrounding code's style (router HEAVY_KEYWORDS etc.). Compared
# case-insensitively against the token immediately before the period.
_ABBREVIATIONS = frozenset({
    # English
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "inc", "ltd", "co", "no", "vol", "fig", "approx", "dept", "univ", "gov",
    # Romanian
    "dl", "dna", "dra", "nr", "str", "bd", "art", "alin", "ex", "ed", "pag",
})

# Default minimum characters before we are willing to emit a chunk mid-stream. Very
# short fragments ("Yes.") still emit on a real boundary, but this guards against
# pathological one-char-at-a-time flushing of, say, an initial "1." list marker.
DEFAULT_MIN_CHARS = 1


def _ends_with_abbreviation(text: str) -> bool:
    """True if `text` ends with a known abbreviation + period (so not a real boundary)."""
    # Grab the alphanumeric word right before the trailing period(s).
    m = re.search(r"([A-Za-zÀ-ɏ.]+)\.\s*$", text)
    if not m:
        return False
    word = m.group(1).rstrip(".").lower()
    return word in _ABBREVIATIONS


def _is_decimal_split(text: str, nxt: str) -> bool:
    """True if a period sits between two digits (e.g. "3.14") — not a boundary."""
    return bool(text) and text[-1].isdigit() and bool(nxt) and nxt[0].isdigit()


def split_sentences(text: str, min_chars: int = DEFAULT_MIN_CHARS) -> list[str]:
    """Segment `text` into a list of trimmed, non-empty sentences.

    Deterministic and dependency-free. Handles:
      - runs of terminators (``?!``, ``...``) as a single boundary,
      - abbreviations (``Dr.``, ``etc.``, ``nr.``) — no split,
      - decimal numbers (``3.14``) — no split,
      - text with no terminator at all → returned as one chunk.

    `min_chars`: a candidate sentence shorter than this is held and merged with the
    next one (prevents emitting tiny fragments like a lone list marker).
    """
    if not text or not text.strip():
        return []

    out: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        if ch in _TERMINATORS:
            # Consume a run of terminators, tracking whether any was a hard one.
            run = ch
            j = i + 1
            while j < n and text[j] in _TERMINATORS:
                run += text[j]
                buf.append(text[j])
                j += 1
            current = "".join(buf)
            rest = text[j:]
            # A boundary needs whitespace/end after it (or a hard CJK terminator,
            # which doesn't); a decimal or abbreviation is never one.
            boundary = (j >= n or text[j].isspace()
                        or any(c in _HARD_TERMINATORS for c in run))
            if boundary and not _is_decimal_split(current, rest) and not _ends_with_abbreviation(current):
                candidate = current.strip()
                if candidate and len(candidate) >= min_chars:
                    out.append(candidate)
                    buf = []
                # else: keep accumulating into buf (too short → merge forward)
            i = j
            continue
        i += 1

    tail = "".join(buf).strip()
    if tail:
        if out and len(tail) < min_chars:
            out[-1] = f"{out[-1]} {tail}"
        else:
            out.append(tail)
    return out


@dataclass
class SentenceAggregator:
    """Incremental sentence segmenter for a token/delta stream.

    Feed it text deltas as they arrive from the LLM; it returns any *complete*
    sentences that just closed, preserving order. Call `flush()` once at the end to
    get the trailing remainder. This is what lets TTS start on sentence #1 while the
    model is still producing sentence #2.

    Usage::

        agg = SentenceAggregator()
        for delta in token_stream:
            for sentence in agg.push(delta):
                synthesize(sentence)
        for sentence in agg.flush():
            synthesize(sentence)
    """

    min_chars: int = DEFAULT_MIN_CHARS
    _buffer: str = field(default="", init=False)
    _emitted: int = field(default=0, init=False)

    def push(self, delta: str) -> list[str]:
        """Add a text delta; return sentences that became complete (may be empty)."""
        if not delta:
            return []
        self._buffer += delta
        return self._drain(final=False)

    def flush(self) -> list[str]:
        """Emit any remaining buffered text as a final chunk. Idempotent."""
        out = self._drain(final=True)
        self._buffer = ""
        return out

    @property
    def emitted_count(self) -> int:
        """How many sentences have been emitted so far (push + flush)."""
        return self._emitted

    def _drain(self, final: bool) -> list[str]:
        if not self._buffer.strip():
            if final:
                self._buffer = ""
            return []
        if final:
            sentences = split_sentences(self._buffer, min_chars=self.min_chars)
            self._buffer = ""
            self._emitted += len(sentences)
            return sentences

        # Mid-stream: a sentence still being typed must not be cut off. We only emit
        # the segment(s) preceding the last one, unless the buffer clearly ended on a
        # completed boundary (trailing terminator) — then the last one is done too.
        sentences = split_sentences(self._buffer, min_chars=self.min_chars)
        if not sentences:
            return []

        buf_stripped = self._buffer.rstrip()
        trailing_ws = self._buffer[len(buf_stripped):]
        closed = bool(buf_stripped) and buf_stripped[-1] in _TERMINATORS
        if closed:
            ready = sentences
            self._buffer = ""
        else:
            ready = sentences[:-1]
            self._buffer = sentences[-1] + trailing_ws

        self._emitted += len(ready)
        return ready
