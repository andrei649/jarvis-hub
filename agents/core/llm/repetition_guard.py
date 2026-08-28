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
    counts: dict[str, int] = {}
    for i in range(n - window + 1):
        key = text[i : i + window]
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


__all__ = ["is_repetition_dominated", "MIN_FRAGMENT_LENGTH"]
