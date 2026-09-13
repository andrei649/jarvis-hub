"""Whisper says something when it hears nothing. This is what stops that becoming a turn.

Fed silence, near-silence or noise, Whisper does not return an empty string — it
returns a fluent sentence from its training data. The classics are subtitle
credits ("Subtitles by the Amara.org community"), sign-offs ("Thanks for
watching!") and, in Romanian, "Subtitrarea: ...". They are confident, complete
and entirely invented.

For a dictation box that is an annoyance. Here it is a **safety control**, and
that is why this module exists rather than a `.strip()` somewhere. A voice note
becomes an inbound turn, and an inbound turn is what the kernel escalates from
GRANT to QUEUE — so a hallucinated transcript is an *un-authored instruction*
entering a governed system. Nobody said it. It should not be able to ask for
anything, and it should not sit in a transcript looking like the owner spoke.

The design is shaped entirely by which error is worse:

- **Dropping a real message is the unacceptable failure.** Someone records
  "mulțumesc" and it vanishes with no reply. So a transcript is only ever
  discarded when the *whole* of it is canned — never when it merely contains a
  known phrase. "Thanks for watching the demo I just sent you" is a message.
- **Letting one through is cheap.** It costs a stray turn the owner can ignore.
  So everything ambiguous is kept, and an unrecognised transcript is a message.

Hence two tiers, not one list:

- :data:`CANNED` — phrases no one sends as an entire voice note. A subtitle
  credit is not something a human says. Dropped on text alone.
- :data:`AMBIGUOUS` — real things people really say ("Thank you.", "Mulțumesc.",
  "Bye."). Whisper does emit these on silence, but a person saying only
  "mulțumesc" is an ordinary message. These are dropped **only** when the caller
  can say the audio was too short to contain them — and a caller that does not
  know the duration keeps them, which is the safe direction.

Pure: a table, a normaliser and two predicates. No model, no I/O, no settings.
"""

from __future__ import annotations

import re
import unicodedata

#: Below this, a recording is too short to hold even a one-word reply, so an
#: :data:`AMBIGUOUS` phrase in it was invented rather than spoken. Deliberately
#: under a second: "mulțumesc" takes about that long to say, and the rule must
#: never reach a recording that could plausibly contain the words it drops.
SHORT_AUDIO_SECONDS = 1.0

#: Reported when a transcript is discarded, so a caller can say *why* nothing
#: arrived rather than going quiet.
REASON_HALLUCINATION = "silence_hallucination"

#: Subtitle credits, sign-offs and channel spam — Whisper's training data
#: surfacing when the audio holds nothing. No person sends one of these as their
#: entire voice note, so text alone is enough to discard them.
CANNED: frozenset[str] = frozenset({
    # Subtitle credits, the single most common family.
    "subtitles by the amara org community",
    "subtitles by the amaraorg community",
    "subtitling by the amara org community",
    "subtitles by amara org community",
    "sous titres realises par la communaute d amara org",
    "sous titres realises para la communaute d amara org",
    "subtitulos realizados por la comunidad de amara org",
    "legendas pela comunidade amara org",
    "ondertiteling door de amara org gemeenschap",
    "napisy stworzone przez spolecznosc amara org",
    "sottotitoli e revisione a cura di qtss",
    "sottotitoli creati dalla comunita amara org",
    "untertitel von stephanie geiges",
    "untertitel der amara org community",
    "untertitelung aufgrund der amara org community",
    "subtitrarea realizata de comunitatea amara org",
    "subtitrare realizata de comunitatea amara org",
    "subtitrarea si adaptarea",
    "subtitrarea",
    "subs by www zeoranger co uk",
    "transcription by castingwords",
    "transcript by castingwords",
    "amara org",
    "subtitles by steamteam",
    "subtitle by subtitle team",
    "redaktor subtitrov a sineckaa",
    "korrektor a egorova",
    "subtitry sdelal dimatorzok",
    "subtitry dobavil dimatorzok",
    "prodolzenie sleduet",
    # Channel sign-offs and calls to action.
    "thanks for watching",
    "thank you for watching",
    "thanks for watching this video",
    "thank you for watching this video",
    "thanks for watching and see you next time",
    "please subscribe to my channel",
    "please subscribe to our channel",
    "like and subscribe",
    "don t forget to subscribe",
    "subscribe to my channel",
    "va multumesc pentru vizionare",
    "multumesc pentru vizionare",
    "merci d avoir regarde cette video",
    "vielen dank fur s zuschauen",
    "vielen dank furs zuschauen",
    "gracias por ver el video",
    "gracias por ver este video",
    "obrigado por assistir",
    "go seongnae jusyeoseo gamsahabnida",
    "sicheonghaejusyeoseo gamsahabnida",
    "gosichonghaejusyeoseo gamsahamnida",
    "gosiqing ni bulin dianzan dingyue zhuanfa",
    "qing bulin dianzan dingyue zhuanfa dashang zhichi mingjing yu diandian lanmu",
    "gosichong arigatogozaimashita",
    "gosichong arigatou gozaimashita",
    # Music / noise markers, which are annotations rather than speech.
    "music",
    "music playing",
    "applause",
    "laughter",
    "silence",
    "blank audio",
    "inaudible",
    "background noise",
    "muzica",
})

#: Vendor and domain names from Whisper's subtitle-credit output. The credit
#: family comes back in endless permutations — "Subtitles by the Amara.org
#: community", "Subtitrarea: Amara.org community", "sous-titres ... d'Amara.org"
#: — so a table trying to enumerate them rots, and one of these names is the
#: reliable tell that a piece belongs to the family.
CREDIT_MARKERS: frozenset[str] = frozenset({
    "amara org",
    "castingwords",
    "zeoranger",
    "dimatorzok",
})

#: The only other words a subtitle credit is made of. A marker alone is NOT
#: enough to discard a piece — "am văzut pe amara.org un film bun" contains one
#: and is somebody talking. So the module's whole-transcript rule is applied
#: again at word level: a piece is a credit when it carries a marker *and every
#: word in it* comes from this list. Anything the speaker added that is not
#: credit vocabulary makes it a message, which is the failure direction this
#: module is built to prefer.
CREDIT_WORDS: frozenset[str] = frozenset({
    # the marker words themselves
    "amara", "org", "castingwords", "zeoranger", "dimatorzok",
    # English
    "subtitles", "subtitling", "subtitle", "subs", "transcription", "transcript",
    "by", "the", "community", "www", "co", "uk", "com", "from", "for",
    # Romanian
    "subtitrarea", "subtitrare", "realizata", "de", "comunitatea", "adaptarea", "si",
    # French / Spanish / Portuguese / Italian
    "sous", "titres", "realises", "par", "la", "communaute", "d", "subtitulos",
    "realizados", "por", "comunidad", "legendas", "pela", "comunidade",
    "sottotitoli", "creati", "dalla", "comunita", "revisione", "e", "a", "cura", "di",
    # German / Dutch / Polish / Russian
    "untertitel", "von", "der", "aufgrund", "ondertiteling", "door", "gemeenschap",
    "napisy", "stworzone", "przez", "spolecznosc", "subtitry", "sdelal", "dobavil",
    "redaktor", "subtitrov",
})

#: Things people genuinely say. Whisper emits them on silence too, so they are
#: listed — but only a known-short recording may drop them. See the module
#: docstring: a false negative costs a stray turn, a false positive costs a real
#: message, and those are not the same price.
AMBIGUOUS: frozenset[str] = frozenset({
    "you",
    "thank you",
    "thank you very much",
    "thanks",
    "bye",
    "bye bye",
    "goodbye",
    "okay",
    "ok",
    "yeah",
    "hello",
    "hi",
    "the end",
    "multumesc",
    "multumesc mult",
    "va multumesc",
    "pa",
    "buna",
    "salut",
    "da",
    "nu",
    "merci",
    "danke",
    "gracias",
    "grazie",
})

# A sentence ends at ., !, ?, … or a CJK full stop — but only where a sentence
# can actually end: at whitespace or the end of the string. Splitting on every
# dot tore "Amara.org" into "Amara" + "org", and neither half matched anything,
# so the most common canned line of all sailed straight through.
# Whisper repeats itself when it hallucinates ("Thank you. Thank you. Thank
# you."), so the check is per sentence: every piece must be canned, or the
# transcript is a message.
_SENTENCE_SPLIT = re.compile(r"(?:[.!?…]+(?=\s|$)|[。！？\n]+)")
# Everything that is not a letter, a digit or a space is punctuation for our
# purposes — including the ♪ and [] that wrap Whisper's annotation output.
_NOT_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Fold a fragment to its comparable form: no accents, no punctuation, no case.

    Accents go because the same canned line comes back as "Subtitrarea" and
    "Subtitrărea" depending on the decode, and a table that had to list both
    spellings of every phrase would rot. Matching is on the folded form only, so
    nothing here ever rewrites what the caller keeps.
    """
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _NOT_WORD.sub(" ", stripped.casefold())
    return _SPACES.sub(" ", cleaned).strip()


def _pieces(text: str) -> list[str]:
    """The transcript as normalised sentences, empties dropped."""
    return [p for p in (normalise(part) for part in _SENTENCE_SPLIT.split(text or "")) if p]


def _is_credit(piece: str) -> bool:
    """True when a normalised piece is a subtitle credit and nothing else.

    Both halves are required. The marker says which family this belongs to; the
    vocabulary check says the speaker contributed nothing of their own, which is
    what separates a credit line from a sentence that happens to name the site.
    """
    if not any(marker in piece for marker in CREDIT_MARKERS):
        return False
    return all(word in CREDIT_WORDS for word in piece.split())


def is_hallucination(text: str, *, audio_seconds: float | None = None) -> bool:
    """True when *text* is Whisper talking to itself rather than a person talking.

    ``audio_seconds`` is the recording's real length when the caller knows it.
    Passing it lets the :data:`AMBIGUOUS` tier apply to recordings too short to
    hold the words; leaving it out keeps every ambiguous phrase, which is the
    behaviour a caller with no duration should get.
    """
    pieces = _pieces(text)
    if not pieces:
        # Punctuation and symbols only — Whisper's "♪♪♪" for music, a row of
        # dots. Nothing was said, whatever the raw string looks like. Genuinely
        # empty input is not a hallucination; it is empty, and callers already
        # have a path for that.
        return bool((text or "").strip())
    short = (
        isinstance(audio_seconds, (int, float))
        and not isinstance(audio_seconds, bool)
        and 0 <= float(audio_seconds) < SHORT_AUDIO_SECONDS
    )
    allowed = CANNED | AMBIGUOUS if short else CANNED
    return all(piece in allowed or _is_credit(piece) for piece in pieces)


__all__ = [
    "AMBIGUOUS",
    "CANNED",
    "CREDIT_MARKERS",
    "CREDIT_WORDS",
    "REASON_HALLUCINATION",
    "SHORT_AUDIO_SECONDS",
    "is_hallucination",
    "normalise",
]
