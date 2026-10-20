"""
repetition_guard.py — content-sanity check for truncated model output.

A local model in a degenerate repetition loop can spend its ENTIRE output
budget echoing one fragment; delivering that fragment floods the channel
(upstream incident: one turn → 60,698 chars → 31 chat messages). These
helpers detect repetition-dominated text so the truncated-answer path can
degrade cleanly (no answer) instead of delivering the flood.

The detection is deliberately conservative: only LONG verbatim repeats
(60+ chars) whose occurrences cover a majority of the fragment trip the
guard, so ordinary truncated responses (a sentence cut mid-word, a heading
repeated, code with similar-looking lines) are never blocked.

Ported from hermes-agent ``agent/repetition_guard.py`` (Nous Research, MIT,
v2026.8.27) — see LICENSES/hermes-agent-MIT.txt.
"""

from __future__ import annotations

import math

# A fragment must be at least this long before the repetition check runs at
# all.  Short truncations (a sentence cut mid-word) can trivially contain
# repeated tokens and are legitimately delivered.
MIN_FRAGMENT_LENGTH = 400

# Length of the exact-repeat window.  A verbatim repeat of this many chars
# is far beyond ordinary phrasing reuse (citations, headings, similar code).
_REPEAT_WINDOW = 60

# A window that repeats at least this many times is a repetition signal,
# even for short fragments.
_MIN_REPEAT_COUNT = 5

# A fragment is "repetition-dominated" when repeated windows account for at
# least this fraction of its characters.
_DOMINANCE_RATIO = 0.5


def is_repetition_dominated(text: str) -> bool:
    """True when ``text`` is dominated by verbatim repeated fragments.

    A truncated response is "repetition-dominated" when a single 60+ char
    substring appears often enough that its occurrences cover at least half
    of the fragment.  That shape is the signature of a model repetition
    loop, and delivering such a fragment is pointless — the reader gets a
    wall of the same text.

    Returns False for non-string / empty / short inputs (fail-open: never
    blocks an answer the guard cannot confidently judge).
    """
    if not isinstance(text, str):
        return False
    n = len(text)
    if n < MIN_FRAGMENT_LENGTH:
        return False

    # Fast path: one normalized line duplicated often enough to cover half
    # the fragment (the most common echo shape — a repeated paragraph or
    # sentence on its own line).  Cheap, no big allocations.
    if _line_repetition_dominated(text, n):
        return True

    # General path: fixed-size exact-repeat windows, sliding one char at a
    # time.  Catches repetition loops that do not align to line boundaries.
    window = _REPEAT_WINDOW
    # A window must appear this many times for its occurrences to cover
    # >= DOMINANCE_RATIO of the fragment (and at least _MIN_REPEAT_COUNT).
    needed = max(_MIN_REPEAT_COUNT, math.ceil(n * _DOMINANCE_RATIO / window))
    # Only NON-overlapping occurrences count: inside one long run of a single
    # character (a markdown rule of 80 dashes) the same window recurs at every
    # offset, and counting those overlaps would score two horizontal rules as
    # "covering" 2.5 KB of text. Non-overlapping occurrences x window is the
    # real coverage; a loop's period >= window is unaffected.
    counts: dict[str, int] = {}
    last: dict[str, int] = {}
    for i in range(n - window + 1):
        key = text[i : i + window]
        prev = last.get(key)
        if prev is not None and i - prev < window:
            continue
        last[key] = i
        c = counts.get(key, 0) + 1
        if c >= needed:
            return True
        counts[key] = c
    return False


def _line_repetition_dominated(text: str, n: int) -> bool:
    """True when a single normalized line covers half the fragment via repeats."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        norm = line.strip()
        if not norm:
            continue
        counts[norm] = counts.get(norm, 0) + 1
    for line, c in counts.items():
        if c >= _MIN_REPEAT_COUNT and c * len(line) >= n * _DOMINANCE_RATIO:
            return True
    return False


# Finish reasons that mean "the output budget ran out", across wire dialects:
# OpenAI-compatible / Ollama ``length``, Anthropic ``max_tokens``, Gemini
# ``MAX_TOKENS``, OpenAI Responses ``max_output_tokens``. (The Responses backend
# refuses ``incomplete`` responses before finalizing, so that last spelling is
# kept for dialect completeness and never reaches a finalizer today.)
TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "MAX_TOKENS", "max_output_tokens"})


def is_truncated_finish(finish: object) -> bool:
    """True when ``finish`` says generation stopped at the output cap."""
    return isinstance(finish, str) and finish in TRUNCATED_FINISH_REASONS


# The streaming detector judges only the most recent stretch of output — a
# loop that started late in a long, legitimate answer must still be caught,
# and the cost of each check stays bounded however long the stream runs.
_STREAM_TAIL = 4000

# Re-run the whole-tail dominance check after this many new characters rather
# than on every token.
_STREAM_CHECK_EVERY = 200

# The onset detector (``_loop_suffix``) trips once the stream ENDS in at least
# ``_MIN_REPEAT_COUNT`` back-to-back copies of one period spanning at least this
# many characters. Measured from the loop's onset rather than over the whole
# tail, so a loop that starts late in a long answer is cut after ~5 repeats
# instead of the ~35 the tail-wide dominance ratio would need.
_STREAM_MIN_LOOP_SPAN = 300


def _loop_suffix(tail: str) -> bool:
    """True when ``tail`` ends in ``_MIN_REPEAT_COUNT``+ copies of one period.

    Candidate periods come from earlier occurrences of the last
    ``_REPEAT_WINDOW`` characters (nearest first), each verified by a single
    slice comparison — so a check costs a few linear scans of the bounded tail.
    """
    n = len(tail)
    if n < _STREAM_MIN_LOOP_SPAN:
        return False
    key = tail[-_REPEAT_WINDOW:]
    start = n - _REPEAT_WINDOW
    max_period = n // _MIN_REPEAT_COUNT
    pos = tail.rfind(key, 0, n - 1)
    while pos != -1:
        period = start - pos
        if period > max_period:
            return False
        span = max(_MIN_REPEAT_COUNT * period, _STREAM_MIN_LOOP_SPAN)
        if span <= n and tail[n - span:n - period] == tail[n - span + period:]:
            return True
        pos = tail.rfind(key, 0, pos + _REPEAT_WINDOW - 1)
    return False


class RepetitionStreamGuard:
    """Incremental repetition-loop detector for a live token stream.

    ``feed(chunk)`` returns the text that is safe to show right now. Once the
    stream's tail becomes repetition-dominated — or it ends in five or more
    back-to-back copies of one fragment (``_loop_suffix``, checked on every
    chunk) — the guard trips and every later chunk (including the one that
    tripped it) is withheld, so a degenerate loop is never painted live into
    the chat bubble beyond its first few repeats. Text shown before the trip is
    not retracted. The caller still accumulates the full text itself — the
    final answer is decided by the finalizers, this only governs what is
    displayed while the model is still generating.
    """

    def __init__(self) -> None:
        self.tripped = False
        self._tail = ""
        self._since_check = 0

    def feed(self, chunk: str) -> str:
        if self.tripped or not isinstance(chunk, str) or not chunk:
            return ""
        self._tail = (self._tail + chunk)[-_STREAM_TAIL:]
        self._since_check += len(chunk)
        if _loop_suffix(self._tail):
            self.tripped = True
            return ""
        if self._since_check >= _STREAM_CHECK_EVERY and len(self._tail) >= MIN_FRAGMENT_LENGTH:
            self._since_check = 0
            if is_repetition_dominated(self._tail):
                self.tripped = True
                return ""
        return chunk


__all__ = [
    "is_repetition_dominated",
    "is_truncated_finish",
    "MIN_FRAGMENT_LENGTH",
    "RepetitionStreamGuard",
    "TRUNCATED_FINISH_REASONS",
]
