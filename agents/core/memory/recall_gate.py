"""H428 — which prompts are worth a memory recall.

Hermes gates its memory prefetch on one anchored ``is_trivial_prompt``
(``agent/memory_provider.py``): empty input, a slash command, and a bare greeting or
acknowledgement followed only by punctuation — so "ok", "hi!" and "done???" skip the
embedding and the fused vector ⊕ graph round-trip, while "k8s", "yolo" and "ok, and
what about X?" do not.

Nerva differs from Hermes in four ways:
- Its owner writes Romanian as often as English, so the list carries both, with
  internal commas read as spaces ("ok, mersi").
- Trailing emoji count as punctuation, and an emoji-only reaction ("👍", "🙏") is an
  acknowledgement too, unless it asks something ("🦷?", "📅❓"). Punctuation alone
  ("?", "…?", "❓", "$?") is trivial: there is nothing to search for.
- Slash commands are dispatched before recall ever runs, so only a command-shaped
  text counts as one. A path such as "/etc/hosts changed, why?" is a question.
- Text is compared after NFC normalisation with invisible format characters
  removed, so a decomposed "mulțumesc" or "ok" + zero-width space still match.

One function, shared by every caller that decides whether to recall (the pre-turn
block and the H433 query rewrite behind it), so the rule cannot drift.
"""
from __future__ import annotations

import re
import unicodedata

# Bare acknowledgements and greetings, compared after NFC normalisation, case
# folding, the cedilla→comma fold for ş/ţ, commas read as spaces, whitespace
# collapsing and trailing-symbol stripping.
_ACKS = frozenset({
    # English — the Hermes list
    "yes", "no", "ok", "okay", "sure", "thanks", "thank you", "y", "n", "yep", "nope", "yeah",
    "nah", "hi", "hey", "hello", "yo", "sup", "continue", "go ahead", "do it", "proceed",
    "got it", "cool", "nice", "great", "done", "next", "lgtm", "k",
    # English — common short forms
    "kk", "thx", "ty", "thanks a lot", "thank you very much", "alright", "all right", "ok thanks",
    "yes thanks",
    # Romanian
    "da", "nu", "bine", "mersi", "merci", "mulțumesc", "multumesc", "mulțumesc mult",
    "multumesc mult", "mersi mult", "mersi frumos", "mulțumesc frumos", "multumesc frumos",
    "super", "perfect", "salut", "bună", "buna", "gata", "sigur", "hai", "continuă", "continua",
    "ok mersi", "da mersi", "am înțeles", "am inteles", "în regulă", "in regula", "e bine",
})
_MAX_TRIVIAL_CHARS = 40
_FOLD = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț", ",": " ", "،": " "})
# The head of agents.core.commands._COMMAND_RE: "/name", "/name@bot", then nothing or
# whitespace. A path's second slash is not whitespace, so "/etc/hosts …" is no command.
_COMMAND_SHAPE = re.compile(r"^/[A-Za-z][A-Za-z0-9_]*(?:@\w+)?(?:\s|$)")
_QUESTION_MARKS = frozenset("?？¿❓❔⁇⁈⁉")
_LEADING_NOISE = frozenset("¿¡")


def _is_trailing_noise(ch: str) -> bool:
    """Punctuation, symbols (emoji), separators and joiners after the words."""
    if ch in "\u200d\ufe0e\ufe0f":
        return True
    return unicodedata.category(ch)[0] in {"P", "S", "Z"}


def _normalise(text: str | None) -> str:
    """NFC, with invisible format characters (zero-width space/joiner, bidi marks) removed."""
    composed = unicodedata.normalize("NFC", text or "")
    return "".join(ch for ch in composed if unicodedata.category(ch) != "Cf").strip()


def is_trivial_prompt(text: str | None) -> bool:
    """True when a prompt carries no semantic signal worth a recall round-trip."""
    stripped = _normalise(text)
    if not stripped or _COMMAND_SHAPE.match(stripped):
        return True
    if len(stripped) > _MAX_TRIVIAL_CHARS:
        return False
    start, end = 0, len(stripped)
    while start < end and stripped[start] in _LEADING_NOISE:
        start += 1
    while end > start and _is_trailing_noise(stripped[end - 1]):
        end -= 1
    core = " ".join(stripped[start:end].translate(_FOLD).casefold().split())
    if core == "":
        # Punctuation alone ("?", "…?", "❓", "$?") is trivial. An emoji is a reaction
        # ("👍"), unless it comes with a question mark ("🦷?", "📅❓"): then it asks about
        # something. Emoji are the "other symbol" category; a currency or maths sign is not.
        has_emoji = any(unicodedata.category(ch) == "So" and ch not in _QUESTION_MARKS for ch in stripped)
        return not (has_emoji and any(ch in _QUESTION_MARKS for ch in stripped))
    return core in _ACKS
