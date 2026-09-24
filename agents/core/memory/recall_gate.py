"""H428 — which prompts are worth a memory recall.

Hermes gates its memory prefetch on one anchored ``is_trivial_prompt``
(``agent/memory_provider.py``): empty input, anything starting with ``/``, and a
bare greeting or acknowledgement followed only by punctuation — so "ok", "hi!" and
"done???" skip the embedding and the fused vector ⊕ graph round-trip, while "k8s",
"yolo" and "ok, and what about X?" do not. Nerva's owner writes Romanian as often as
English, so the list carries both; trailing emoji count as punctuation here.

One function, shared by every caller that decides whether to recall (the
pre-turn block today, the query rewriter of H433 next), so the rule cannot drift.
"""
from __future__ import annotations

import unicodedata

# Bare acknowledgements and greetings, compared after case folding, the
# cedilla→comma fold for ş/ţ, whitespace collapsing and trailing-symbol stripping.
_ACKS = frozenset({
    # English — the Hermes list
    "yes", "no", "ok", "okay", "sure", "thanks", "thank you", "y", "n", "yep", "nope", "yeah",
    "nah", "hi", "hey", "hello", "yo", "sup", "continue", "go ahead", "do it", "proceed",
    "got it", "cool", "nice", "great", "done", "next", "lgtm", "k",
    # English — common short forms
    "kk", "thx", "ty", "thanks a lot", "thank you very much", "alright", "all right",
    # Romanian
    "da", "nu", "bine", "mersi", "merci", "mulțumesc", "multumesc", "mulțumesc mult",
    "multumesc mult", "mersi mult", "super", "perfect", "salut", "bună", "buna", "gata",
    "sigur", "hai", "continuă", "continua", "ok mersi", "da mersi", "am înțeles",
    "am inteles", "în regulă", "in regula", "e bine",
})
_MAX_TRIVIAL_CHARS = 40
_FOLD = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})


def _is_trailing_noise(ch: str) -> bool:
    """Punctuation, symbols (emoji), separators and joiners after the words."""
    if ch in "‍︎️":
        return True
    return unicodedata.category(ch)[0] in {"P", "S", "Z"}


def is_trivial_prompt(text: str | None) -> bool:
    """True when a prompt carries no semantic signal worth a recall round-trip."""
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return True
    if len(stripped) > _MAX_TRIVIAL_CHARS:
        return False
    end = len(stripped)
    while end and _is_trailing_noise(stripped[end - 1]):
        end -= 1
    core = " ".join(stripped[:end].translate(_FOLD).casefold().split())
    return core == "" or core in _ACKS
