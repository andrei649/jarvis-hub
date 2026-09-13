"""Whisper's invented sentences never become a turn — and real speech never stops being one.

Fed silence, Whisper returns fluent text from its training data: subtitle
credits, sign-offs, channel spam. H530 calls the filter a safety control rather
than polish, and the reason is in the governance note on the row: a voice note
becomes an *inbound* turn, an inbound turn can ask for things, so a hallucinated
transcript is an un-authored instruction entering a governed system. Nobody said
it, and it must not be able to ask for anything.

Which makes the asymmetry the thing to test hardest. Two failures are possible
and they do not cost the same:

- **Dropping real speech** is unacceptable: the owner records "mulțumesc", it
  vanishes, nothing replies, and they have no way to know why.
- **Letting one through** costs a stray turn they ignore.

So most of what is pinned here is the filter *not* firing: on a phrase that
merely contains a canned one, on a sentence that names amara.org, on anything
unrecognised, and on every ambiguous phrase when the duration is unknown.
"""

from __future__ import annotations

import pytest

from agents.core.voice.hallucination import (
    AMBIGUOUS,
    CANNED,
    CREDIT_MARKERS,
    CREDIT_WORDS,
    SHORT_AUDIO_SECONDS,
    is_hallucination,
    normalise,
)

# ── what it must drop ───────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Subtitles by the Amara.org community",
    "Subtitles by the Amara.org community.",
    "subtitling by the amara.org community",
    "Subtitrarea: Amara.org community",
    "Subtitrare realizată de comunitatea Amara.org",
    "Sous-titres réalisés par la communauté d'Amara.org",
    "Subtítulos realizados por la comunidad de Amara.org",
    "Sottotitoli e revisione a cura di QTSS",
    "Untertitel von Stephanie Geiges",
    "Subs by www.zeoranger.co.uk",
    "Transcription by CastingWords",
    "Thanks for watching!",
    "Thank you for watching this video.",
    "Please subscribe to my channel.",
    "Mulțumesc pentru vizionare!",
    "Vă mulțumesc pentru vizionare.",
    "Vielen Dank für's Zuschauen!",
    "[Music]",
    "♪♪♪",
    "(applause)",
])
def test_a_canned_line_never_becomes_a_turn(text):
    assert is_hallucination(text) is True


def test_a_repeated_canned_line_is_still_canned():
    """Whisper stutters when it hallucinates; the check is per sentence."""
    said = "Thanks for watching! Thanks for watching! Thanks for watching!"
    assert is_hallucination(said) is True


def test_accents_and_punctuation_do_not_smuggle_a_canned_line_through():
    for spelling in ("Multumesc pentru vizionare",
                     "Mulțumesc pentru vizionare!!!",
                     "  MULȚUMESC PENTRU VIZIONARE  ",
                     "Mulțumesc pentru vizionare."):
        assert is_hallucination(spelling) is True, spelling


# ── what it must never drop ─────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Poți să pornești calculatorul din birou?",
    "Thanks for watching the demo I just sent you",
    "I found the subtitles on amara.org yesterday",
    "Am văzut pe amara.org un film bun aseară",
    "Thank you for sending that, I will look at it tonight",
    "Mulțumesc, dar mai am o întrebare",
    "Subscribe to the newsletter and tell me what you think",
    "bye, see you at six",
])
def test_real_speech_survives(text):
    assert is_hallucination(text) is False


def test_a_sentence_that_merely_names_the_subtitle_site_is_a_message():
    """The credit rule needs the marker *and* nothing but credit vocabulary.

    A marker alone was enough in the first draft, and it silently ate
    "am văzut pe amara.org un film bun" — a person talking about a film.
    """
    assert is_hallucination("Am văzut pe amara.org un film bun") is False
    assert is_hallucination("Subtitles by the Amara.org community") is True


def test_a_canned_phrase_inside_a_longer_message_is_not_a_hallucination():
    said = "Thanks for watching my screen recording, did the button look right?"
    assert is_hallucination(said) is False


def test_one_real_sentence_among_canned_ones_saves_the_whole_transcript():
    """Whole-transcript, never per-piece: if a person spoke at all, it is a message."""
    said = "Thanks for watching! Pornește serverul te rog."
    assert is_hallucination(said) is False


def test_an_unrecognised_transcript_is_always_a_message():
    assert is_hallucination("zzz qwerty flurb") is False


# ── the ambiguous tier, and the duration that guards it ─────────────────────


@pytest.mark.parametrize("text", ["Thank you.", "Mulțumesc.", "you", "Bye.", "Okay."])
def test_an_ambiguous_phrase_is_kept_when_the_duration_is_unknown(text):
    """A caller that cannot say how long the audio was gets the safe answer."""
    assert is_hallucination(text) is False
    assert is_hallucination(text, audio_seconds=None) is False


@pytest.mark.parametrize("text", ["Thank you.", "Mulțumesc.", "you", "Bye."])
def test_an_ambiguous_phrase_in_audio_too_short_to_hold_it_is_dropped(text):
    assert is_hallucination(text, audio_seconds=0.3) is True


def test_an_ambiguous_phrase_in_audio_long_enough_to_hold_it_is_kept():
    assert is_hallucination("Mulțumesc.", audio_seconds=SHORT_AUDIO_SECONDS) is False
    assert is_hallucination("Mulțumesc.", audio_seconds=2.5) is False


def test_the_short_bound_leaves_room_for_a_real_one_word_reply():
    """Under a second. A spoken "mulțumesc" takes about that, and the rule must
    never reach a recording that could genuinely contain the words it drops."""
    assert 0 < SHORT_AUDIO_SECONDS <= 1.0


def test_a_real_sentence_in_a_short_recording_is_still_a_message():
    """Short audio widens the table; it does not make everything a hallucination."""
    assert is_hallucination("Pornește serverul.", audio_seconds=0.2) is False


def test_a_nonsense_duration_does_not_widen_the_table():
    for bogus in (True, "0.3", -5, None, float("nan")):
        assert is_hallucination("Mulțumesc.", audio_seconds=bogus) is False, bogus


# ── shape ───────────────────────────────────────────────────────────────────


def test_empty_input_is_not_a_hallucination():
    """Empty is empty. Callers have their own path for it, and conflating the two
    would report "I heard nothing said" for a download that returned no bytes."""
    for blank in ("", "   ", "\n\n", None):
        assert is_hallucination(blank) is False


def test_punctuation_only_is_a_hallucination():
    for noise in ("...", "♪", "—", "!!!"):
        assert is_hallucination(noise) is True


def test_the_filter_decides_but_never_rewrites():
    """Normalisation is for matching only; what the engine returns is what travels."""
    said = "Pornește  CALCULATORUL, te rog!"
    assert is_hallucination(said) is False
    assert normalise(said) != said


def test_normalise_folds_only_what_matching_needs():
    assert normalise("Mulțumesc, Ștefan!") == "multumesc stefan"
    assert normalise("Amara.org") == "amara org"
    assert normalise("") == ""
    assert normalise(None) == ""


def test_the_two_tiers_do_not_overlap():
    """A phrase in both would be dropped by the canned rule and the duration
    guard would be a lie. They are different promises and must stay disjoint."""
    assert not (CANNED & AMBIGUOUS)


def test_every_table_entry_is_already_normalised():
    """A table entry that does not survive `normalise` can never match anything."""
    for phrase in CANNED | AMBIGUOUS | CREDIT_MARKERS | CREDIT_WORDS:
        assert normalise(phrase) == phrase, phrase


def test_the_credit_markers_are_all_covered_by_the_credit_vocabulary():
    """Otherwise a credit line could carry a marker and still fail the word check."""
    for marker in CREDIT_MARKERS:
        for word in marker.split():
            assert word in CREDIT_WORDS, word


def test_nothing_generic_hides_in_the_credit_vocabulary():
    """CREDIT_WORDS is matched with `in`, so a common word there would let any
    sentence built from common words plus a marker be discarded as a credit."""
    for risky in ("nu", "da", "te", "rog", "este", "sunt", "pornește", "server",
                  "calculator", "film", "bun", "vazut", "am", "pe", "un"):
        assert risky not in CREDIT_WORDS, risky
