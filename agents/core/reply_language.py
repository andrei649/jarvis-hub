"""Narrow output-language hints from an owner's explicit request.

This is deliberately not language detection. Ambiguous text leaves the shared
system/runtime instruction to decide; it never turns source text into authority.
"""

from __future__ import annotations

import re


_LANGUAGE = r"english|romanian|engleză|engleza|română|romana"
_WORD = r"([^\W\d_]+)"
_POLITE = r"(?:please\s+|can you\s+|could you\s+|te rog\s+|vă rog\s+|va rog\s+)?"
_COMMANDS = (
    re.compile(rf"^{_POLITE}(?:reply|answer|respond)\s+(?:only\s+)?in\s+{_WORD}\b", re.IGNORECASE),
    re.compile(rf"^{_POLITE}write\s+(?:only\s+)?in\s+{_WORD}\b", re.IGNORECASE),
    re.compile(
        rf"^{_POLITE}(?:write|draft|compose)\s+(?:(?:a|an|one|the|this|your)\s+)?"
        rf"(?:(?:short|brief|plain)\s+)?(?:sentence|caption|email|e-mail|invitation|reply|response|answer|note|draft)"
        rf"\s+in\s+{_WORD}\b", re.IGNORECASE,
    ),
    re.compile(rf"^{_POLITE}translate\s+(?:(?:this|it|the following text|the text)\s+)?(?:to|into)\s+{_WORD}\b", re.IGNORECASE),
    re.compile(rf"^{_POLITE}(?:give|provide)\s+(?:a|one)\s+(?:short\s+)?plain[- ]{_WORD}\s+sentence\b", re.IGNORECASE),
    re.compile(rf"^{_POLITE}(?:răspunde|raspunde|scrie|redactează|redacteaza)\s+(?:(?:doar|numai)\s+)?(?:în|in)\s+{_WORD}\b", re.IGNORECASE),
    re.compile(
        rf"^{_POLITE}(?:scrie|redactează|redacteaza)\s+"
        rf"(?:răspunsul|raspunsul|răspuns|raspuns|o propoziție|o propozitie|un mesaj|un email|o invitație|o invitatie|un text)"
        rf"\s+(?:în|in)\s+{_WORD}\b", re.IGNORECASE,
    ),
    re.compile(rf"^{_POLITE}tradu\s+(?:(?:acest text|mesajul|asta)\s+)?(?:în|in)\s+{_WORD}\b", re.IGNORECASE),
)
_MIXED = re.compile(r"\b(?:bilingual|both languages|ambele limbi|două limbi|doua limbi)\b", re.IGNORECASE)
_CONDITIONAL = re.compile(r"\b(?:if|unless|otherwise|dacă|daca|altfel)\b", re.IGNORECASE)
_EXTRA_TARGET = re.compile(
    rf"^\s*(?:and|or|then|also|și|si|sau|apoi)\b"
    rf"|\b(?:and|or|then|și|si|sau|apoi)\s+(?:in|în)\s+{_WORD}"
    rf"|[/,]\s*(?:in|în)\s+\w+"
    rf"|\bwith\b.{{0,30}}\b(?:{_LANGUAGE})\b"
    rf"|\b(?:not|nu)\s+(?:{_LANGUAGE})\b",
    re.IGNORECASE,
)
_ALLOWED_TAIL = re.compile(
    r"^\s*(?:$|[.!?;:,]|(?:about|on|for|only|with|as|using|o|un|despre|pentru|inviting)\b)",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_ATTACHED = "--- Attached Context ---"


def _without_quoted_examples(text: str) -> str:
    """Remove straight/curly quoted spans, including spans across lines."""
    close_for = {'"': '"', "'": "'", '“': '”', '‘': '’', '„': '”', '«': '»', '`': '`'}
    closing = None
    result: list[str] = []
    for index, char in enumerate(text):
        if closing is not None:
            if char == closing:
                closing = None
            elif char == "\n":
                result.append("\n")
            continue
        if char in close_for:
            if char == "'" and index > 0 and text[index - 1].isalnum():
                result.append(char)  # don't is a word, not a quoted example
                continue
            closing = close_for[char]
            result.append(" ")
            continue
        result.append(char)
    return "".join(result)


def _owner_instruction_text(owner_words: str) -> str:
    text = owner_words.split(_ATTACHED, 1)[0]
    kept: list[str] = []
    in_fence = False
    in_example = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        if not line.strip():
            in_example = False
        if not in_example:
            kept.append(line)
        # Unmarked command lines after an introducing colon may be examples.
        if line.rstrip().endswith(":"):
            in_example = True
    return _without_quoted_examples("\n".join(kept))


def _canonical(word: str) -> str | None:
    if word.casefold() in {"english", "engleză", "engleza"}:
        return "English"
    if word.casefold() in {"romanian", "română", "romana"}:
        return "Romanian"
    return None


def requested_reply_language(owner_words: str) -> str | None:
    """Return a closed output-language hint only for a clear instruction."""
    if not isinstance(owner_words, str) or not owner_words or len(owner_words) > 8192:
        return None
    source = _owner_instruction_text(owner_words)
    if _CONDITIONAL.search(source):
        return None
    found: set[str] = set()
    for clause in re.split(r"(?<=[.!?;])\s+|\n", source):
        clause = clause.strip()
        if not clause:
            continue
        if _MIXED.search(clause):
            return None
        match = next((candidate for pattern in _COMMANDS if (candidate := pattern.search(clause))), None)
        if match is None:
            continue
        # Negation preceding the command or its target is never an affirmative request.
        if re.search(r"\b(?:not|never|don't|do not|nu|fără|fara)\b", clause[:match.end()], re.IGNORECASE):
            return None
        target = _canonical(match.group(1))
        if target is None:
            return None
        tail = clause[match.end():]
        # A following topic word or hyphen can make the language word descriptive.
        if not _ALLOWED_TAIL.match(tail) or tail.startswith("-"):
            return None
        # After a colon, the remainder is requested content, not more instructions.
        if _EXTRA_TARGET.search(tail.split(":", 1)[0]):
            return None
        found.add(target)
        if len(found) > 1:
            return None
    return next(iter(found)) if found else None


def append_reply_language(prompt: str, language: object) -> str:
    """Append only a vetted closed-language instruction; never echo owner text."""
    if type(language) is not str or language not in {"English", "Romanian"}:
        return prompt
    return prompt + f"\n\nWrite this response in {language}."
