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

import hashlib
import math
import re

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
# ``=`` rule, a run of spaces) is exempt from the overlapping-occurrence count
# while every contiguous run of it is shorter than ``_LOW_VARIETY_RULE_SPAN``
# characters; it still trips through real character coverage.  The only
# deviation from the Hermes port, which counts two 80-dash markdown rules as a
# repetition loop.  A longer run ("hahaha…", a newline or ``0 0 0`` flood) is a
# loop, so from then on the key counts exactly as in the port.
_LOW_VARIETY_DISTINCT = 2
_LOW_VARIETY_RULE_SPAN = 2 * 60


def is_repetition_dominated(text: str, *, min_distinct: int = 0, count_trigger: bool = True) -> bool:
    """True when ``text`` is dominated by verbatim repeated fragments.

    A truncated response is "repetition-dominated" when a single 60+ char
    substring appears often enough that its occurrences cover at least half
    of the fragment.  That shape is the signature of a model repetition
    loop, and delivering such a fragment is pointless — the reader gets a
    wall of the same text.

    Returns False for non-string / empty / short inputs (fail-open: never
    blocks an answer the guard cannot confidently judge).

    Detection is a superset of the Hermes port except for low-variety windows
    (at most ``_LOW_VARIETY_DISTINCT`` distinct characters) whose every
    contiguous run is shorter than ``_LOW_VARIETY_RULE_SPAN`` — rule-length
    dash / ``=`` lines.

    ``count_trigger=False`` turns the Hermes overlapping-occurrence count off and
    scores real character coverage only (the live stream guard's setting: a
    short zero matrix late in a long answer is not a loop to stop painting).

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
    # a run of spaces) while none of its contiguous runs has reached
    # ``_LOW_VARIETY_RULE_SPAN``. Inside such a run the same window recurs at
    # EVERY offset, so two horizontal rules alone reach ``needed``.
    #
    # Secondary trigger (OR): the characters a key's occurrences actually cover
    # (the union of [i, i + window)) reach half the fragment. Exempt keys still
    # count here, so a genuine low-variety flood is caught by its real span.
    target = n * _DOMINANCE_RATIO
    counts: dict[str, int] = {}
    covered: dict[str, int] = {}
    covered_end: dict[str, int] = {}
    low_variety: set[str] = set()
    run_start: dict[str, int] = {}
    for i in range(n - window + 1):
        key = text[i : i + window]
        end = covered_end.get(key)
        if end is None:
            distinct = len(set(key))
            if min_distinct and distinct < min_distinct:
                continue   # never recorded, so re-checked (cheaply) on each occurrence
            if distinct <= _LOW_VARIETY_DISTINCT:
                low_variety.add(key)
                run_start[key] = i
            counts[key] = 1
            covered[key] = window
        else:
            counts[key] += 1
            covered[key] += min(window, i + window - end)
            if key in low_variety:
                if i > end:
                    run_start[key] = i   # a new run starts (gap since the last one)
                elif i + window - run_start[key] >= _LOW_VARIETY_RULE_SPAN:
                    low_variety.discard(key)   # too long for a rule: a loop
        covered_end[key] = i + window
        c = counts[key]
        if count_trigger and c >= needed and key not in low_variety:
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

# The short-loop HOLD (``_short_loop_period``) covers what the onset detector
# skips: a stream whose last ``_STREAM_MIN_LOOP_SPAN`` characters repeat with a
# period of at most this many characters ("the the the", "I'm sorry I'm
# sorry", "ha ha ha", "0, 0, 0"). Such a run may be formatting (a zero matrix, a
# rule), so the hold is recoverable: it is lifted — and the held text flushed —
# the moment the stream stops repeating.
_STREAM_SHORT_PERIOD_MAX = _REPEAT_WINDOW

# Longest period the tail-based checks (``_loop_suffix``,
# ``_low_variety_loop_period``) can see: five back-to-back copies must fit in
# the tail. Longer loops are caught by the whole-stream line detector.
_STREAM_TAIL_PERIOD_MAX = _STREAM_TAIL // _MIN_REPEAT_COUNT

# The whole-stream line detector remembers at most this many distinct line
# hashes (least recently seen evicted first), so its memory stays bounded.
_STREAM_LINE_SLOTS = 4096

# The line breaks ``str.splitlines`` splits on (the finalizer's line path).
_LINE_BREAKS = re.compile("\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


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


def _short_loop_period(tail: str) -> int:
    """The period (1..``_STREAM_SHORT_PERIOD_MAX``) ``tail`` ends repeating, else 0.

    "Ends repeating" means the last ``_STREAM_MIN_LOOP_SPAN`` characters are
    periodic with that period — at least five back-to-back copies of the unit.
    """
    span = _STREAM_MIN_LOOP_SPAN
    if len(tail) < span:
        return 0
    seg = tail[-span:]
    last = seg[-1]
    for period in range(1, _STREAM_SHORT_PERIOD_MAX + 1):
        if seg[-1 - period] == last and seg[:-period] == seg[period:]:
            return period
    return 0


def _low_variety_loop_period(tail: str) -> int:
    """The period (61..``_STREAM_TAIL_PERIOD_MAX``) of a low-variety loop ``tail`` ends in, else 0.

    A low-variety loop is a unit built from fewer than ``_STREAM_MIN_DISTINCT``
    distinct characters (a ``[0, 0, …],`` row, a ``| 0 | 0 |`` table row, a
    ``ha ha`` line, a dash rule) repeated back to back over
    ``max(_STREAM_MIN_LOOP_SPAN, _MIN_REPEAT_COUNT * period)`` characters. The
    onset detector skips such units (they may be formatting) and the short-loop
    hold stops at a period of ``_STREAM_SHORT_PERIOD_MAX``, so this covers the
    rest of what the tail can hold. Candidates come from earlier occurrences of
    the last ``_REPEAT_WINDOW`` characters, as in ``_loop_suffix``.
    """
    n = len(tail)
    if n < _STREAM_MIN_LOOP_SPAN:
        return 0
    key = tail[-_REPEAT_WINDOW:]
    if len(set(key)) >= _STREAM_MIN_DISTINCT:
        return 0   # a unit containing this window has at least as many distinct chars
    start = n - _REPEAT_WINDOW
    max_period = n // _MIN_REPEAT_COUNT
    pos = tail.rfind(key, 0, n - 1)
    while pos != -1:
        period = start - pos
        if period > max_period:
            return 0
        if period > _STREAM_SHORT_PERIOD_MAX:
            span = max(_MIN_REPEAT_COUNT * period, _STREAM_MIN_LOOP_SPAN)
            lo = n - span
            if (
                span <= n
                # cheap pre-check on the oldest copy before the full comparison
                and tail[lo:lo + _REPEAT_WINDOW] == tail[lo + period:lo + period + _REPEAT_WINDOW]
                and len(set(tail[n - period:])) < _STREAM_MIN_DISTINCT
                and tail[lo:n - period] == tail[lo + period:]
            ):
                return period
        pos = tail.rfind(key, 0, pos + _REPEAT_WINDOW - 1)
    return 0


class _LineRepeatTracker:
    """Whole-stream counterpart of ``_line_repetition_dominated``.

    Hashes each completed, ``strip()``-normalized line incrementally (memory per
    line is O(1), however long the line), counts hashes in a bounded LRU map and
    tracks the current back-to-back run of one line (blank lines in between do
    not break a run). Lines shorter than ``_REPEAT_WINDOW`` are ignored and break
    a run, as any other different line does.
    """

    def __init__(self) -> None:
        self.total = 0                       # characters streamed so far
        self.counts: dict[bytes, int] = {}   # line hash -> occurrences (LRU order)
        self.run_key: bytes | None = None
        self.run = 0
        self._new_line()

    def _new_line(self) -> None:
        self._started = False                # a non-whitespace char was seen
        self._h_full = hashlib.blake2b(digest_size=16)    # incl. trailing whitespace
        self._h_kept = self._h_full.copy()   # up to the last non-whitespace char
        self._len_full = 0
        self._len_kept = 0
        self._distinct: set[str] = set()
        self._pending_ws: set[str] = set()

    def _extend(self, piece: str) -> None:
        if not self._started:
            piece = piece.lstrip()
            if not piece:
                return
            self._started = True
        body = piece.rstrip()
        trail = piece[len(body):]
        if body:
            self._h_full.update(body.encode("utf-8", "surrogatepass"))
            self._len_full += len(body)
            self._h_kept = self._h_full.copy()
            self._len_kept = self._len_full
            if len(self._distinct) < _STREAM_MIN_DISTINCT:
                self._distinct |= self._pending_ws
                self._distinct.update(body)
            self._pending_ws = set()
        if trail:
            self._h_full.update(trail.encode("utf-8", "surrogatepass"))
            self._len_full += len(trail)
            self._pending_ws.update(trail)

    def feed(self, chunk: str) -> list[tuple[bytes | None, int, int, int, bool, int]]:
        """Consume ``chunk``; one ``(key, length, count, run, low_variety, end)`` per completed line.

        ``end`` is the offset in ``chunk`` just past the line's break. A
        non-blank line shorter than ``_REPEAT_WINDOW`` is reported with
        ``key=None`` (it is not counted, but it ends any run); blank lines are
        not reported.
        """
        self.total += len(chunk)
        done: list[tuple[bytes | None, int, int, int, bool, int]] = []
        pos = 0
        for m in _LINE_BREAKS.finditer(chunk):
            self._extend(chunk[pos:m.start()])
            pos = m.end()
            started, length = self._started, self._len_kept
            key, low = self._h_kept.digest(), len(self._distinct) < _STREAM_MIN_DISTINCT
            self._new_line()
            if not started:
                continue   # a blank line: transparent to the back-to-back run
            if length < _REPEAT_WINDOW:
                self.run_key, self.run = None, 0
                done.append((None, length, 0, 0, low, pos))
                continue
            count = self.counts.pop(key, 0) + 1
            self.counts[key] = count
            if len(self.counts) > _STREAM_LINE_SLOTS:
                del self.counts[next(iter(self.counts))]
            if key == self.run_key:
                self.run += 1
            else:
                self.run_key, self.run = key, 1
            done.append((key, length, count, self.run, low, pos))
        self._extend(chunk[pos:])
        return done


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

    Loops whose period is too long for the 4000-char tail are caught over the
    WHOLE stream by a line detector (``_LineRepeatTracker``, the live twin of
    the finalizer's line path): outside an open fence, a normalized line of
    ``_REPEAT_WINDOW``+ characters and ``_STREAM_MIN_DISTINCT``+ distinct
    characters trips the guard once it completes ``_MIN_REPEAT_COUNT``
    back-to-back copies (blank lines between them allowed), or — fence or not —
    once its ``_MIN_REPEAT_COUNT``+ copies cover half of everything streamed.

    Outside those trips, a stream that ends in a short-period run
    (``_short_loop_period``: a unit of at most 60 characters repeated over the
    last 300), in a low-variety run of a longer period
    (``_low_variety_loop_period``: a unit of fewer than 8 distinct characters,
    period 61..800, repeated five times) or in five back-to-back copies of one
    low-variety line longer than 800 characters is HELD rather than tripped:
    chunks are withheld while the run continues, and the moment the stream stops
    repeating (for the long-line hold: once a different line completes) the
    held text is returned with the chunk that broke the run, so a zero matrix,
    a table or a rule in a normal answer is only delayed. A degenerate loop
    never stops before the output cap, so it stays held to the end.

    ``withholding`` is true while either a trip or a hold is withholding text.

    The trip and the hold are provisional: the finalizers decide the answer. After
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
        self._holding = False
        self._lines = _LineRepeatTracker()
        self._line_hold: bytes | None = None

    @property
    def withholding(self) -> bool:
        """True while later text is being withheld (a trip or a short-loop hold)."""
        return self.tripped or self._holding

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
        fence_before, carry_before = self._fence_open, self._fence_carry
        self._track_fences(chunk)
        if self._scan_lines(chunk, fence_before, carry_before):
            return self._trip(chunk)
        if not self._fence_open and _loop_suffix(self._tail):
            return self._trip(chunk)
        if self._since_check >= _STREAM_CHECK_EVERY and len(self._tail) >= MIN_FRAGMENT_LENGTH:
            self._since_check = 0
            # Coverage only (no Hermes overlapping count), so a hard trip needs
            # the loop to cover half the tail. Low-variety runs (zero matrices,
            # byte tables, rules) only count once they flood the whole tail —
            # never a normal-sized block; a short run is at most held below.
            if is_repetition_dominated(
                self._tail, min_distinct=_STREAM_MIN_DISTINCT, count_trigger=False
            ) or (
                len(self._tail) >= _STREAM_TAIL
                and is_repetition_dominated(self._tail, count_trigger=False)
            ):
                return self._trip(chunk)
        if (
            self._line_hold is not None
            or _short_loop_period(self._tail)
            or _low_variety_loop_period(self._tail)
        ):
            self._holding = True
            self._held.append(chunk)
            return ""
        if self._holding:   # the run ended: flush what was held, resume live
            self._holding = False
            self._held.append(chunk)
            out = "".join(self._held)
            self._held = []
            return out
        return chunk

    def _scan_lines(self, chunk: str, fence_before: bool, carry_before: str) -> bool:
        """Feed the line detector; True when a completed line is a loop to trip on.

        Each line is judged with the fence state at its own end (a fence that
        opens or closes later in the same chunk does not apply to it).
        """
        trip = False
        scan = carry_before + chunk
        for key, length, count, run, low, end in self._lines.feed(chunk):
            if self._line_hold is not None and key != self._line_hold:
                self._line_hold = None   # a different line completed: the run ended
            if key is None:
                continue
            if low:
                if run >= _MIN_REPEAT_COUNT and length > _STREAM_TAIL_PERIOD_MAX:
                    self._line_hold = key   # may be formatting: hold, never trip
                continue
            fence_open = fence_before ^ bool(scan.count(_FENCE, 0, len(carry_before) + end) % 2)
            onset = run >= _MIN_REPEAT_COUNT and not fence_open
            dominant = count >= _MIN_REPEAT_COUNT and count * length >= self._lines.total * _DOMINANCE_RATIO
            trip = trip or onset or dominant
        return trip

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
