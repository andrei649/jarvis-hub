"""Fuzzy, description-aware matching of a typed name against a catalog (H231, H235).

One scorer for the hub's unknown-command reply (``CommandRegistry.dispatch``) and the
terminal client's Tab completion (``agents/cli/repl.py``), so ``/summary`` finds the same
commands in both. Stdlib only and pure: it ranks; it never resolves a guess into an
action — the hub *suggests* the closest commands and runs none of them.

A candidate scores on its name (prefix, subsequence or edit similarity) and on its
description (a word sharing a stem of at least four letters with a word of the query:
``summary`` meets ``summarise``, ``history`` meets ``histories``).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

_WORD = re.compile(r"[a-z0-9]+")
#: Below this a candidate is not offered at all.
THRESHOLD = 0.6
_STEM = 4


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _subsequence(needle: str, haystack: str) -> bool:
    letters = iter(haystack)
    return all(char in letters for char in needle)


def _shares_stem(a: str, b: str) -> bool:
    size = min(len(a), len(b))
    if size < _STEM:
        return False
    common = 0
    while common < size and a[common] == b[common]:
        common += 1
    return common >= _STEM and common >= size - 2


def score(query: str, name: str, description: str = "") -> float:
    """How well *query* (``/summary`` or ``summary``) matches one catalog entry, 0..1."""
    q = query.strip().lstrip("/").lower()
    n = name.strip().lstrip("/").lower()
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    best = 0.0
    if n.startswith(q):
        best = 0.95
    elif len(q) >= 3 and _subsequence(q, n):
        best = 0.75
    best = max(best, difflib.SequenceMatcher(None, q, n).ratio() * 0.85)
    query_words = _words(q)
    if any(_shares_stem(word, other) for word in query_words for other in _words(n)):
        best = max(best, 0.8)
    if description and any(_shares_stem(word, other) for word in query_words for other in _words(description)):
        best = max(best, 0.7)
    return best


def rank(query: str, catalog: Iterable[tuple[str, str]], *, limit: int = 3,
         threshold: float = THRESHOLD) -> list[str]:
    """The names in *catalog* (``(name, description)`` pairs) that match *query*, best
    first, at most *limit*; ties keep catalog order."""
    scored = []
    for index, (name, description) in enumerate(catalog):
        value = score(query, name, description or "")
        if value >= threshold:
            scored.append((-value, index, name))
    scored.sort()
    seen: list[str] = []
    for _value, _index, name in scored:
        if name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return seen
