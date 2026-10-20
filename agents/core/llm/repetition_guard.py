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

# A repeat window built from at most this many distinct characters (a dash or
# ``=`` rule, a run of spaces) is exempt from the overlapping-occurrence count;
# it still trips through real character coverage.  The only deviation from the
# Hermes port, which counts two 80-dash markdown rules as a repetition loop.
_LOW_VARIETY_DISTINCT = 2


def is_repetition_dominated(text: str, *, min_distinct: int = 0) -> bool:
    """True when ``text`` is dominated by verbatim repeated fragments.

    A truncated response is "repetition-dominated" when a single 60+ char
    substring appears often enough that its occurrences cover at least half
    of the fragment.  That shape is the signature of a model repetition
    loop, and delivering such a fragment is pointless — the reader gets a
    wall of the same text.

    Returns False for non-string / empty / short inputs (fail-open: never
    blocks an answer the guard cannot confidently judge).

    Detection is a superset of the Hermes port on every input whose repeated
    windows have more than ``_LOW_VARIETY_DISTINCT`` distinct characters.

    ``min_distinct`` (default 0: off — the finalizers' setting) ignores any
    repeated line or window built from fewer distinct characters; the live
    stream guard uses it so a zero matrix or ``====`` rule is not a loop.
    """
    if not isinstance(text, str):
        return False
    n = len(text)
    if n < MIN_FRAGMENT_LENGTH:
        return False

    # Fast path: one normalized line duplicated often enough to cover half
    # the fragment (the most common echo shape — a repeated paragraph or
    # sentence on its own line).  Cheap, no big allocations.
    if _line_repetition_dominated(text, n, min_distinct):
        return True

    # General path: fixed-size exact-repeat windows, sliding one char at a
    # time.  Catches repetition loops that do not align to line boundaries.
    window = _REPEAT_WINDOW
    # Primary trigger — the Hermes rule, unchanged: a window that occurs (with
    # overlap) at least ``needed`` times. Overlapping occurrences make it more
    # sensitive to short periods: a period-p loop trips once it covers roughly
    # p/120 of the fragment (~8% at p=10, ~25% at p=30).
    needed = max(_MIN_REPEAT_COUNT, math.ceil(n * _DOMINANCE_RATIO / window))
    # The one exemption from that count: a window of at most
    # ``_LOW_VARIETY_DISTINCT`` distinct characters (an 80-dash / ``====`` rule,
    # a run of spaces). Inside such a run the same window recurs at EVERY
    # offset, so two horizontal rules alone reach ``needed``.
    #
    # Secondary trigger (OR): the characters a key's occurrences actually cover
    # (the union of [i, i + window)) reach half the fragment. Exempt keys still
    # count here, so a genuine low-variety flood is caught by its real span.
    target = n * _DOMINANCE_RATIO
    counts: dict[str, int] = {}
    covered: dict[str, int] = {}
    covered_end: dict[str, int] = {}
    low_variety: set[str] = set()
    for i in range(n - window + 1):
        key = text[i : i + window]
        end = covered_end.get(key)
        if end is None:
            distinct = len(set(key))
            if min_distinct and distinct < min_distinct:
                continue   # never recorded, so re-checked (cheaply) on each occurrence
            if distinct <= _LOW_VARIETY_DISTINCT:
                low_variety.add(key)
            counts[key] = 1
            covered[key] = window
        else:
            counts[key] += 1
            covered[key] += min(window, i + window - end)
        covered_end[key] = i + window
        c = counts[key]
        if c >= needed and key not in low_variety:
            return True
        if covered[key] >= target and c >= _MIN_REPEAT_COUNT:
            return True
    return False


def _line_repetition_dominated(text: str, n: int, min_distinct: int = 0) -> bool:
    """True when a single normalized line covers half the fragment via repeats."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        norm = line.strip()
        if not norm or (min_distinct and len(set(norm)) < min_distinct):
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

# A loop's repeating unit must be at least this long and use at least this many
# distinct characters before the onset detector counts it. A run of one or a
# few characters (an ``====`` underline, a zero matrix, a ``0x00`` byte table)
# is periodic at every period yet is ordinary formatting, not a model loop; the
# tail-wide dominance check still catches such a run once it fills the tail.
_STREAM_MIN_PERIOD = 20
_STREAM_MIN_DISTINCT = 8


def _loop_suffix(tail: str) -> bool:
    """True when ``tail`` ends in ``_MIN_REPEAT_COUNT``+ copies of one period.

    Candidate periods come from earlier occurrences of the last
    ``_REPEAT_WINDOW`` characters (nearest first), each verified by a single
    slice comparison — so a check costs a few linear scans of the bounded tail.
    A period shorter than ``_STREAM_MIN_PERIOD`` or whose unit has fewer than
    ``_STREAM_MIN_DISTINCT`` distinct characters never counts.
    """
    n = len(tail)
    if n < _STREAM_MIN_LOOP_SPAN:
        return False
    key = tail[-_REPEAT_WINDOW:]
    if len(set(key)) < _STREAM_MIN_DISTINCT:
        return False   # every unit inside a low-variety window is low-variety too
    start = n - _REPEAT_WINDOW
    max_period = n // _MIN_REPEAT_COUNT
    pos = tail.rfind(key, 0, n - 1)
    while pos != -1:
        period = start - pos
        if period > max_period:
            return False
        if period >= _STREAM_MIN_PERIOD and len(set(tail[n - period:])) >= _STREAM_MIN_DISTINCT:
            span = max(_MIN_REPEAT_COUNT * period, _STREAM_MIN_LOOP_SPAN)
            if span <= n and tail[n - span:n - period] == tail[n - span + period:]:
                return True
        pos = tail.rfind(key, 0, pos + _REPEAT_WINDOW - 1)
    return False


_FENCE = "```"


class RepetitionStreamGuard:
    """Incremental repetition-loop detector for a live token stream.

    ``feed(chunk)`` returns the text that is safe to show right now. Once the
    stream's tail becomes repetition-dominated — or, outside an open ``````
    code fence, it ends in five or more back-to-back copies of one fragment
    (``_loop_suffix``, checked on every chunk) — the guard trips and every
    later chunk (including the one that tripped it) is WITHHELD, so a
    degenerate loop is never painted live into the chat bubble beyond its first
    few repeats. Text shown before the trip is not retracted.

    The trip is provisional: the finalizers decide the answer. After
    finalizing, the backend calls ``release(answer)``: when the answer was kept
    (non-empty — not dropped as a truncated loop) it returns the withheld text
    so the caller emits it and the live bubble / streamed TTS ends with the
    same text the answer carries; when the answer was dropped it returns ``""``.
    """

    def __init__(self) -> None:
        self.tripped = False
        self._tail = ""
        self._since_check = 0
        self._held: list[str] = []
        self._fence_open = False
        self._fence_carry = ""

    def _track_fences(self, chunk: str) -> None:
        # A fence marker may straddle a chunk boundary: scan with the previous
        # chunk's last two characters prepended (a marker ending in the carry
        # alone was already counted).
        scan = self._fence_carry + chunk
        if scan.count(_FENCE) % 2:
            self._fence_open = not self._fence_open
        self._fence_carry = scan[-(len(_FENCE) - 1):] if not scan.endswith(_FENCE) else ""

    def feed(self, chunk: str) -> str:
        if not isinstance(chunk, str) or not chunk:
            return ""
        if self.tripped:
            self._held.append(chunk)
            return ""
        self._tail = (self._tail + chunk)[-_STREAM_TAIL:]
        self._since_check += len(chunk)
        self._track_fences(chunk)
        if not self._fence_open and _loop_suffix(self._tail):
            return self._trip(chunk)
        if self._since_check >= _STREAM_CHECK_EVERY and len(self._tail) >= MIN_FRAGMENT_LENGTH:
            self._since_check = 0
            # Low-variety runs (zero matrices, byte tables, rules) only count
            # once they flood the whole tail — never a normal-sized block.
            if is_repetition_dominated(self._tail, min_distinct=_STREAM_MIN_DISTINCT) or (
                len(self._tail) >= _STREAM_TAIL and is_repetition_dominated(self._tail)
            ):
                return self._trip(chunk)
        return chunk

    def _trip(self, chunk: str) -> str:
        self.tripped = True
        self._held.append(chunk)
        return ""

    def release(self, answer: object) -> str:
        """The withheld text when the finalized ``answer`` was kept, else ``""``.

        Clears the withheld buffer either way, so a second call returns ``""``.
        """
        held = "".join(self._held)
        self._held = []
        if not held or not (isinstance(answer, str) and answer):
            return ""
        return held


__all__ = [
    "is_repetition_dominated",
    "is_truncated_finish",
    "MIN_FRAGMENT_LENGTH",
    "RepetitionStreamGuard",
    "TRUNCATED_FINISH_REASONS",
]
