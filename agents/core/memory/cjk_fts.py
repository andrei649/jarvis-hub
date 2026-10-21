"""cjk_fts.py — CJK-aware full-text segmentation for SQLite FTS5 (H574).

SQLite's ``unicode61`` tokenizer splits on whitespace and punctuation, so a run of
Chinese, Japanese or Korean text with no spaces (``明天去看牙医``) is one token and a
search for ``牙医`` inside it cannot match. Hermes ships a C tokenizer extension
(``unicode61`` + CJK bigrams) for this; Python's ``sqlite3`` cannot register an FTS5
tokenizer, so Nerva gets the same index by pre-segmenting the text on both sides of the
index with one pure function:

* :func:`index_text` — what is stored in the FTS5 column: the text with every CJK run
  rewritten as its unigrams and overlapping bigrams, each a separate ``unicode61``
  token (``牙医`` → ``牙 医 牙医``); non-CJK text passes through unchanged.
* :func:`match_expression` — the FTS5 ``MATCH`` for a query's CJK runs: a 1-character
  run is its unigram, a longer run is all of its bigrams (``AND``). Every n-gram of a
  query run is an n-gram of any stored run that contains it, so the index answers a
  *superset* of the substring matches; callers keep exact substring semantics by
  re-checking the candidates (``MemoryStore`` does).

Both sides NFKC-fold and lower-case first, so half-width katakana and full-width forms
meet their canonical spelling. :data:`SEGMENTER_VERSION` is stored next to an index and a
change to it rebuilds that index.
"""

from __future__ import annotations

import re
import unicodedata

#: Bump when :func:`index_text` changes shape; stored indexes rebuild on mismatch.
SEGMENTER_VERSION = "cjk-bigram-1"

#: FTS5 table option every CJK-segmented index uses. ``remove_diacritics 0`` keeps the
#: tokenizer from rewriting combining marks the segmenter already left in place.
TOKENIZE = "unicode61 remove_diacritics 0"

_CJK_RANGES = (
    (0x1100, 0x11FF),    # Hangul Jamo
    (0x3005, 0x3007),    # 々 〆 〇
    (0x3041, 0x3096),    # Hiragana letters
    (0x309D, 0x309F),    # Hiragana iteration marks, digraph
    (0x30A1, 0x30FA),    # Katakana letters
    (0x30FC, 0x30FF),    # Katakana prolonged sound mark, iteration marks
    (0x3105, 0x312F),    # Bopomofo
    (0x3131, 0x318E),    # Hangul compatibility Jamo
    (0x31A0, 0x31BF),    # Bopomofo extended
    (0x31F0, 0x31FF),    # Katakana phonetic extensions
    (0x3400, 0x4DBF),    # CJK unified ideographs extension A
    (0x4E00, 0x9FFF),    # CJK unified ideographs
    (0xA960, 0xA97F),    # Hangul Jamo extended A
    (0xAC00, 0xD7AF),    # Hangul syllables
    (0xD7B0, 0xD7FF),    # Hangul Jamo extended B
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0x20000, 0x323AF),  # CJK unified ideographs extensions B-H
)


def is_cjk(char: str) -> bool:
    """A CJK *letter or number* — punctuation (``、``, ``・``) is never part of a run."""
    point = ord(char)
    if not any(lo <= point <= hi for lo, hi in _CJK_RANGES):
        return False
    return unicodedata.category(char)[0] in "LN"


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def cjk_runs(text: str) -> list[str]:
    """The maximal CJK runs of the *normalized* text, in order."""
    runs: list[str] = []
    current: list[str] = []
    for char in normalize(text):
        if is_cjk(char):
            current.append(char)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def has_cjk(text: str) -> bool:
    return any(is_cjk(char) for char in normalize(text))


def _grams(run: str) -> list[str]:
    return list(run) + [run[i:i + 2] for i in range(len(run) - 1)]


def index_text(text: str) -> str:
    """*text* as an FTS5 column value: each CJK run becomes its unigrams and bigrams."""
    out: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            out.append(" " + " ".join(_grams("".join(current))) + " ")
            current.clear()

    for char in normalize(text):
        if is_cjk(char):
            current.append(char)
        else:
            flush()
            out.append(char)
    flush()
    return "".join(out)


_SAFE_GRAM = re.compile(r'^[^"\s]+$')


def query_grams(query: str) -> list[str]:
    """The n-grams a match must contain: a lone character's unigram, else every bigram."""
    grams: list[str] = []
    for run in cjk_runs(query):
        parts = [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
        for gram in parts:
            if gram not in grams and _SAFE_GRAM.match(gram):
                grams.append(gram)
    return grams


def match_expression(query: str) -> str | None:
    """An FTS5 ``MATCH`` over *query*'s CJK n-grams, or None when it has no CJK run.

    Each gram is a quoted string, so FTS5 query syntax in user text is never parsed.
    """
    grams = query_grams(query)
    if not grams:
        return None
    return " AND ".join(f'"{gram}"' for gram in grams)


def split_script_boundaries(term: str) -> list[str]:
    """Split one whitespace-free keyword where CJK meets non-CJK (``明天dentist`` →
    ``明天``, ``dentist``): CJK writing does not put spaces between scripts."""
    parts: list[str] = []
    current: list[str] = []
    state: bool | None = None
    for char in term:
        cjk = is_cjk(char)
        if state is not None and cjk != state and current:
            parts.append("".join(current))
            current = []
        current.append(char)
        state = cjk
    if current:
        parts.append("".join(current))
    return parts


__all__ = [
    "SEGMENTER_VERSION", "TOKENIZE", "cjk_runs", "has_cjk", "index_text", "is_cjk",
    "match_expression", "normalize", "query_grams", "split_script_boundaries",
]
