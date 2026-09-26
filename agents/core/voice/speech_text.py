"""H526 — what a reply sounds like: speech, not read-out markdown.

The one normaliser every text-to-speech entry point shares (``TTSEngine.speak`` and
``speak_stream``, so the wake-word pipeline, the voice channel and chat voice notes, and
the ``/tts`` and ``/tts/stream`` routes). ``frontend/src/speech-text.ts`` is its twin
for the HUD's browser voice and live sentence stream; both are pinned by the same cases
(``frontend/src/test/speech-text-cases.json``), so a change here must land there too.

What it does, in order:

1. **Reasoning goes.** ``<think>``/``<thinking>``/``<reasoning>`` blocks, an unclosed
   one to the end, and everything before a closing tag that never opened.
2. **Code goes.** Fenced blocks (```` ``` ```` or ``~~~``), an unclosed fence to the end.
3. **Links read as words.** ``[text](url)`` is its text, ``![alt](url)`` its alt, a bare
   or ``<autolinked>`` URL the word "link" — the URL never eats a closing parenthesis or
   the sentence's full stop. HTML tags go.
4. **Blocks read as sentences.** Headings, list items (``-``, ``*``, ``+``, ``•``,
   ``1.``, ``1)``, task boxes), quotes and table rows lose their markers and end with a
   full stop when they have none; a table's cells are read with commas, its separator row
   and a horizontal rule not at all.
5. **Inline markers go**: bold, italic, strikethrough, inline code (its words stay).
6. **Symbols are said** in the reply's language (Romanian or English): ``&``, ``%``,
   ``->``/``→``/``=>``, ``°``/``°C``/``°F``.
7. **Emoji go** — pictographs, flags, keycaps, skin tones, joiners and variation
   selectors — and the spaces they leave are closed up.

Fish ``[emotion]`` tags are left exactly as they are (``TTSEngine`` strips them for every
other backend). Whitespace is folded, and what has no letter or digit left is ``""``
(nothing to say). The result is a fixed point, so a second pass (a
voice note normalised, then spoken by the engine) changes nothing. Pure: no I/O.
"""
from __future__ import annotations

import re

_THINK_TAGS = r"think|thinking|reasoning"
_THINK_CLOSED = re.compile(rf"<({_THINK_TAGS})\b[^>]*>.*?</\1\s*>", re.S | re.I)
_THINK_OPEN = re.compile(rf"<(?:{_THINK_TAGS})\b[^>]*>.*\Z", re.S | re.I)
_THINK_STRAY_CLOSE = re.compile(rf"\A.*</(?:{_THINK_TAGS})\s*>", re.S | re.I)
_FENCE = re.compile(r"(```|~~~).*?(?:\1|\Z)", re.S)
_AUTOLINK = re.compile(r"<https?://[^<>\s]+>")
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]*\)")
_URL = re.compile(r"https?://[^\s<>()\[\]]+")
_URL_TRAIL = re.compile(r"[.,;:!?'\"]+$")

_RULE = re.compile(r"^([-*_])(?:\s*\1){2,}$")
_TABLE_SEPARATOR = re.compile(r"^\|?(?:\s*:?-{2,}:?\s*\|)+\s*(?::?-{2,}:?)?\s*\|?$")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)(?:\s+#+)?$")
_QUOTE = re.compile(r"^(?:>\s?)+")
_LIST_MARKER = re.compile(r"^(?:[-*+•]|\d{1,3}[.)])\s+")
_TASK_BOX = re.compile(r"^\[[ xX]\]\s+")

#: Bold, strikethrough and inline-code markers simply go (their words stay); single-
#: character emphasis needs the word-boundary guards so ``2*3*4`` and ``my_var`` survive.
_PAIRED_MARKERS = re.compile(r"\*\*|__|~~|`")
_ITALIC = re.compile(r"(^|[^\w*])\*(\S(?:.*?\S)?)\*(?![\w*])")
_ITALIC_UNDERSCORE = re.compile(r"(^|[^\w])_(\S(?:.*?\S)?)_(?!\w)")

_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoticons, transport, flags, skin tones, …
    "\u2600-\u27BF"           # miscellaneous symbols, dingbats
    "\u2B00-\u2BFF"           # arrows and stars used as emoji
    "\u2300-\u23FF"           # watches, hourglasses, media keys
    "\uFE00-\uFE0F"           # variation selectors
    "\u200D"                  # zero-width joiner
    "\u20E3"                  # keycap
    "\U000E0020-\U000E007F"   # tag sequences (subdivision flags)
    "]+"
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?…])")
_SPACES = re.compile(r"\s+")
_ENDS_A_SENTENCE = re.compile(r"[.!?…:;,]$")
_SAYABLE = re.compile(r"[^\W_]")          # a letter or a digit, in any script

#: The words for each symbol, per language (anything not Romanian reads English).
WORDS = {
    "en": {"and": "and", "percent": "percent", "to": "to", "degrees": "degrees"},
    "ro": {"and": "și", "percent": "la sută", "to": "spre", "degrees": "grade"},
}


def speech_lang(lang: object = None, voice: object = None, *, default: str = "en") -> str:
    """``"ro"`` or ``"en"``: the request's language, else the voice's (``ro-RO-…``),
    else *default*."""
    for hint in (lang, voice if isinstance(voice, str) and re.match(r"^[a-z]{2}-[A-Z]{2}-", voice) else None,
                 default):
        if isinstance(hint, str) and hint.strip():
            return "ro" if hint.strip().lower().startswith("ro") else "en"
    return "en"


def _symbols(line: str, words: dict[str, str]) -> str:
    line = re.sub(r"\s*&\s*", f" {words['and']} ", line)
    line = re.sub(r"\s*%", f" {words['percent']}", line)
    line = re.sub(r"\s*(?:->|→|=>)\s*", f" {words['to']} ", line)
    line = re.sub(r"\s*°\s*C\b", f" {words['degrees']} Celsius", line)
    line = re.sub(r"\s*°\s*F\b", f" {words['degrees']} Fahrenheit", line)
    return re.sub(r"\s*°", f" {words['degrees']}", line)


def _inline(line: str) -> str:
    line = _PAIRED_MARKERS.sub("", line)
    line = _ITALIC.sub(r"\1\2", line)
    return _ITALIC_UNDERSCORE.sub(r"\1\2", line)


def _url(match: re.Match) -> str:
    trail = _URL_TRAIL.search(match.group(0))
    return "link" + (trail.group(0) if trail else "")


def _line(raw: str, words: dict[str, str]) -> str:
    line = raw.strip()
    if not line or _RULE.match(line):
        return ""
    block = False
    if line.startswith("|"):
        if _TABLE_SEPARATOR.match(line):
            return ""
        line = ", ".join(cell.strip() for cell in line.strip("|").split("|") if cell.strip())
        block = True
    elif heading := _HEADING.match(line):
        line, block = heading.group(1), True
    else:
        quoted = _QUOTE.sub("", line)
        block = quoted != line
        listed = _TASK_BOX.sub("", _LIST_MARKER.sub("", quoted))
        block = block or listed != quoted
        line = listed
    line = _inline(line)
    line = _URL.sub(_url, line)
    line = _symbols(line, words)
    line = _EMOJI.sub(" ", line)
    line = _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", line)).strip()
    if block and line and not _ENDS_A_SENTENCE.search(line):
        line += "."
    return line


def for_speech(text: object, *, lang: object = None) -> str:
    """*text* as it should be heard, or ``""`` when nothing in it is worth saying."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = _THINK_CLOSED.sub(" ", raw)
    raw = _THINK_OPEN.sub("", raw)
    raw = _THINK_STRAY_CLOSE.sub("", raw)
    raw = _FENCE.sub("\n", raw)
    raw = _AUTOLINK.sub("link", raw)
    raw = _HTML_TAG.sub(" ", raw)
    raw = _IMAGE.sub(r"\1", raw)
    raw = _LINK.sub(r"\1", raw)
    words = WORDS[speech_lang(lang)]
    lines = (_line(line, words) for line in raw.split("\n"))
    spoken = " ".join(line for line in lines if line)
    return spoken if _SAYABLE.search(spoken) else ""     # a lone "." is nothing to say


__all__ = ["WORDS", "for_speech", "speech_lang"]
