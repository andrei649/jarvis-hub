"""dictation.py — 0.24 Dictation cleanup (offline disfluency + spoken-command normalizer).

`STTEngine.transcribe` returns the raw transcript — fillers, stutters, and the spoken words
for punctuation all still in it. This is the pure post-processor that turns that into clean
dictated text: strip disfluencies, collapse stutter repetitions, and apply the standard
spoken-punctuation convention ("period" → ".", "new line" → a line break). Bilingual RO/EN
(the cabinet is talked to in both — same discipline as `router.py`).

Capability-pack discipline: pure, deterministic, offline, bounded. **Honest** — it returns
what it removed (filler + repeat counts) so the cleanup is inspectable, never a black box, and
conservative: disfluencies match only as whole tokens (never inside a word — "um" is dropped,
"umbrella" is not), and spoken-punctuation commands are opt-in and matched only as standalone
tokens so ordinary prose survives.
"""

from __future__ import annotations

import re

# Single-token fillers (matched whole-word, case-insensitive).
FILLERS = {
    "en": {"um", "uh", "er", "erm", "hmm", "mm", "uhh", "umm", "ah", "eh"},
    "ro": {"ăă", "îî", "aa", "ăăă", "mm", "păi", "deci", "gen"},
}
# Multi-word hedges — matched on word boundaries.
_PHRASE_FILLERS = {
    "en": ("you know", "i mean", "sort of", "kind of", "like i said"),
    "ro": ("adică cum", "știi tu", "cum să zic"),
}
# Spoken punctuation / formatting commands → literal. Attached to the preceding word
# (no leading space) for punctuation; line breaks stand alone.
_PUNCT = {
    "en": {"period": ".", "full stop": ".", "comma": ",", "question mark": "?",
           "exclamation mark": "!", "exclamation point": "!", "colon": ":",
           "semicolon": ";", "new line": "\n", "newline": "\n", "new paragraph": "\n\n"},
    "ro": {"punct": ".", "virgulă": ",", "virgula": ",", "semnul întrebării": "?",
           "semnul exclamării": "!", "două puncte": ":", "punct și virgulă": ";",
           "linie nouă": "\n", "paragraf nou": "\n\n"},
}

_MAX_LEN = 20_000


def _lang(lang: str) -> str:
    return "ro" if str(lang or "").lower().startswith("ro") else "en"


def _apply_punct_commands(text: str, lang: str) -> str:
    table = _PUNCT[lang]
    # Longest phrases first so "new paragraph" wins over "new".
    for phrase in sorted(table, key=len, reverse=True):
        repl = table[phrase]
        # Eat any leading space so punctuation glues to the preceding word and a line break
        # doesn't leave a dangling space; `_tidy` handles the rest.
        pat = re.compile(rf"(?<!\w)\s*{re.escape(phrase)}(?!\w)", re.IGNORECASE)
        text = pat.sub(repl, text)
    return text


def _strip_phrase_fillers(text: str, lang: str) -> tuple[str, int]:
    removed = 0
    for phrase in _PHRASE_FILLERS[lang]:
        pat = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)
        text, n = pat.subn(" ", text)
        removed += n
    return text, removed


def strip_fillers(text: str, lang: str = "en") -> str:
    """Just the disfluency pass (whole-token fillers + phrase hedges), no punctuation logic."""
    return clean_dictation(text, lang=lang, commands=False)["text"]


def clean_dictation(text: str, *, lang: str = "en", commands: bool = True) -> dict:
    """Clean a raw dictation transcript. Returns ``{text, original, removed, lang}``.

    ``removed`` reports counts (``fillers``, ``repeats``, ``phrase_fillers``) so the edit is
    inspectable. ``commands`` applies the spoken-punctuation convention (default on).
    """
    original = str(text or "")
    lg = _lang(lang)
    work = original[:_MAX_LEN]

    work, phrase_removed = _strip_phrase_fillers(work, lg)

    # Resolve spoken punctuation/line commands *before* the token pass, so a text word that
    # happens to equal a command word ("new line line two") isn't mistaken for a stutter and
    # any inserted line break survives (the token pass runs per line).
    if commands:
        work = _apply_punct_commands(work, lg)

    fillers = FILLERS[lg]
    filler_removed = 0
    repeat_removed = 0
    out_lines: list[str] = []
    for line in work.split("\n"):
        out_tokens: list[str] = []
        prev_norm: str | None = None
        for tok in line.split():
            core = tok.lower().strip(".,!?;:—-\"'()")
            if core in fillers:
                filler_removed += 1
                continue
            if core and core == prev_norm:           # collapse immediate repetition
                repeat_removed += 1
                continue
            out_tokens.append(tok)
            if core:
                prev_norm = core
        out_lines.append(" ".join(out_tokens))
    cleaned = "\n".join(out_lines)

    cleaned = _tidy(cleaned)
    return {
        "text": cleaned,
        "original": original,
        "lang": lg,
        "removed": {"fillers": filler_removed, "repeats": repeat_removed,
                    "phrase_fillers": phrase_removed},
    }


def _tidy(text: str) -> str:
    """Whitespace hygiene + sentence-start capitalization."""
    text = re.sub(r" +([.,!?;:])", r"\1", text)     # no space before punctuation
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text).strip()
    # Capitalize the first alphabetic character of each sentence/line.
    def _cap(m: re.Match) -> str:
        return m.group(0).upper()
    text = re.sub(r"(?:^|(?<=[.!?]\s)|(?<=\n))([^\W\d_])", _cap, text, flags=re.UNICODE)
    return text
