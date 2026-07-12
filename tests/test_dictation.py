"""0.24 Dictation cleanup — offline disfluency + spoken-command normalizer.

Pure post-processor over a raw STT transcript: strip whole-token fillers + phrase hedges,
collapse stutter repetitions, apply the spoken-punctuation convention, capitalize sentences.
Bilingual RO/EN; honest (reports what it removed); conservative (never edits inside a word).
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.voice.dictation import clean_dictation, strip_fillers  # noqa: E402


# ── disfluency removal (conservative) ─────────────────────────────
def test_fillers_removed_but_not_inside_words():
    out = clean_dictation("um I need an umbrella uh today", lang="en", commands=False)
    assert "umbrella" in out["text"]                 # 'um' not stripped from 'umbrella'
    assert "um " not in out["text"].lower() and " uh " not in f" {out['text'].lower()} "
    assert out["removed"]["fillers"] == 2


def test_phrase_hedges_removed():
    out = clean_dictation("you know I think, I mean, it works", lang="en", commands=False)
    assert "you know" not in out["text"].lower() and "i mean" not in out["text"].lower()
    assert out["removed"]["phrase_fillers"] == 2


def test_stutter_repetition_collapsed():
    out = clean_dictation("the the the cat sat sat down", lang="en", commands=False)
    assert out["text"].lower().count("the") == 1 and out["text"].lower().count("sat") == 1
    assert out["removed"]["repeats"] == 3


# ── spoken punctuation convention ─────────────────────────────────
def test_period_command_glues_and_capitalizes():
    out = clean_dictation("add milk period buy eggs period", lang="en")
    assert out["text"] == "Add milk. Buy eggs."


def test_new_line_command():
    out = clean_dictation("line one new line line two", lang="en")
    assert out["text"].split("\n") == ["Line one", "Line two"]


def test_commands_off_leaves_the_word_alone():
    out = clean_dictation("the period was long", lang="en", commands=False)
    assert "period" in out["text"].lower() and "." not in out["text"]


# ── bilingual (RO) ────────────────────────────────────────────────
def test_romanian_fillers_and_punctuation():
    out = clean_dictation("ăă deci scrie un mesaj punct", lang="ro")
    assert "ăă" not in out["text"] and "deci" not in out["text"].lower()
    assert out["text"].endswith(".") and out["removed"]["fillers"] == 2


# ── honesty + bounds + convenience ────────────────────────────────
def test_reports_original_and_is_length_bounded():
    out = clean_dictation("x " * 20000, lang="en", commands=False)
    assert out["original"].startswith("x ")
    assert len(out["text"]) <= 20_000


def test_empty_input_is_safe():
    out = clean_dictation("", lang="en")
    assert out["text"] == "" and out["removed"]["fillers"] == 0


def test_strip_fillers_convenience_returns_text():
    assert isinstance(strip_fillers("um hello there", lang="en"), str)
    assert "um" not in strip_fillers("um hello", lang="en").lower().split()


def test_clean_transcript_is_left_essentially_intact():
    # A clean sentence with no fillers/commands should round-trip (modulo capitalization).
    out = clean_dictation("the meeting is at three", lang="en")
    assert out["text"] == "The meeting is at three"
    assert out["removed"] == {"fillers": 0, "repeats": 0, "phrase_fillers": 0}
