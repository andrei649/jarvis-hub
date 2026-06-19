"""Unit tests for the pure sentence-streaming helpers (H5.16).

Hermetic: no audio, no network, no backend — just the deterministic segmentation
(`split_sentences`) and the incremental aggregator (`SentenceAggregator`)."""
import pytest

from agents.core.voice.sentence_stream import (
    SentenceAggregator,
    split_sentences,
)


# ── split_sentences ──────────────────────────────────────────────

def test_split_basic_terminators():
    assert split_sentences("Hello world. How are you? Fine!") == [
        "Hello world.",
        "How are you?",
        "Fine!",
    ]


def test_split_empty_and_whitespace():
    assert split_sentences("") == []
    assert split_sentences("   \n  ") == []


def test_split_no_terminator_single_chunk():
    assert split_sentences("just a fragment with no end") == [
        "just a fragment with no end",
    ]


def test_split_trailing_text_after_last_terminator():
    # Trailing fragment without a terminator is still emitted as a final chunk.
    assert split_sentences("Done. And more") == ["Done.", "And more"]


def test_split_collapses_terminator_runs():
    assert split_sentences("Really?! Wow... Yes.") == [
        "Really?!",
        "Wow...",
        "Yes.",
    ]


def test_split_keeps_decimals_together():
    assert split_sentences("Pi is 3.14 today. Done.") == [
        "Pi is 3.14 today.",
        "Done.",
    ]


def test_split_keeps_abbreviations_together():
    assert split_sentences("Ask Dr. Smith now. Bye.") == [
        "Ask Dr. Smith now.",
        "Bye.",
    ]
    # Romanian abbreviation.
    assert split_sentences("Vezi nr. 5 acolo. Gata.") == [
        "Vezi nr. 5 acolo.",
        "Gata.",
    ]


def test_split_multilingual_terminators():
    assert split_sentences("你好。再见！") == ["你好。", "再见！"]


def test_split_strips_whitespace():
    assert split_sentences("  A.   B.  ") == ["A.", "B."]


# ── SentenceAggregator: incremental streaming ────────────────────

def test_aggregator_emits_on_boundary():
    agg = SentenceAggregator()
    # A sentence emits as soon as its terminator arrives (low latency) — the next
    # delta starts a fresh sentence.
    assert agg.push("Hello ") == []
    assert agg.push("world.") == ["Hello world."]
    assert agg.push(" Next one.") == ["Next one."]
    assert agg.flush() == []
    assert agg.emitted_count == 2


def test_aggregator_flush_emits_remainder_without_terminator():
    agg = SentenceAggregator()
    agg.push("no terminator here")
    assert agg.flush() == ["no terminator here"]


def test_aggregator_order_preserved_across_many_deltas():
    agg = SentenceAggregator()
    deltas = ["One. ", "Two", "! ", "Thr", "ee?", " Four."]
    collected = []
    for d in deltas:
        collected.extend(agg.push(d))
    collected.extend(agg.flush())
    assert collected == ["One.", "Two!", "Three?", "Four."]


def test_aggregator_reconstructs_full_text():
    # The concatenation of all emitted sentences (sans inter-sentence spacing) should
    # cover every word from the source — nothing dropped.
    source = "First sentence here. Second one follows! And a third? Tail end"
    agg = SentenceAggregator()
    out = []
    # one char at a time — worst case for a streaming splitter
    for ch in source:
        out.extend(agg.push(ch))
    out.extend(agg.flush())
    assert out == [
        "First sentence here.",
        "Second one follows!",
        "And a third?",
        "Tail end",
    ]


def test_aggregator_empty_flush_is_idempotent():
    agg = SentenceAggregator()
    assert agg.flush() == []
    assert agg.flush() == []
    assert agg.emitted_count == 0


def test_aggregator_ignores_empty_pushes():
    agg = SentenceAggregator()
    assert agg.push("") == []           # empty delta is a no-op
    assert agg.push("Hi. ") == ["Hi."]  # closed sentence emits immediately
    assert agg.flush() == []
