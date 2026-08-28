"""
Tests for the truncated-output repetition guard (agents/core/llm/
repetition_guard.py) and its wiring into the LLM finalizers — ported from
hermes-agent agent/repetition_guard.py (Nous Research, MIT, v2026.8.27).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend, _finalize_lmstudio_message
from agents.core.llm.repetition_guard import (
    MIN_FRAGMENT_LENGTH,
    is_repetition_dominated,
)

# A single long sentence echoed until it dominates the fragment (line-aligned).
_ECHO_LINE = "I will now repeat this exact sentence because I am stuck in a loop."
REPEATED_TEXT = "\n".join([_ECHO_LINE] * 40)

# Repetition that does NOT align to line boundaries (one unbroken stream).
UNALIGNED_TEXT = ("the same sixty-plus character fragment keeps flowing without a break " * 30)


def test_short_fragments_never_trip():
    assert is_repetition_dominated(_ECHO_LINE) is False
    assert is_repetition_dominated("a" * (MIN_FRAGMENT_LENGTH - 1)) is False


def test_non_string_and_empty_fail_open():
    assert is_repetition_dominated(None) is False
    assert is_repetition_dominated("") is False
    assert is_repetition_dominated(12345) is False


def test_line_aligned_repetition_detected():
    assert is_repetition_dominated(REPEATED_TEXT) is True


def test_unaligned_repetition_detected():
    assert is_repetition_dominated(UNALIGNED_TEXT) is True


def test_ordinary_long_prose_not_blocked():
    # Long, varied text (unique lines) must never be classified as repetition.
    text = "\n".join(f"Paragraph {i}: unique content about topic number {i}." for i in range(60))
    assert len(text) > MIN_FRAGMENT_LENGTH
    assert is_repetition_dominated(text) is False


def test_repeated_headings_in_varied_text_not_blocked():
    # A heading repeated a few times inside otherwise-unique text is ordinary.
    blocks = []
    for i in range(4):
        blocks.append("## Results")
        blocks.append(f"Section {i} discusses a different aspect of the data, {i * 17}.")
    text = "\n".join(blocks) * 3
    assert is_repetition_dominated(text) is False


# ── wiring: truncated + repetition-dominated ⇒ no answer (degrade cleanly) ──


def test_finalize_stream_drops_repetition_dominated_truncation():
    out = LLMBackend._finalize_stream(REPEATED_TEXT, "", "length", "test-model")
    assert out == ""


def test_finalize_stream_keeps_clean_truncated_answer():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(40))
    out = LLMBackend._finalize_stream(text, "", "length", "test-model")
    assert out == text


def test_finalize_stream_keeps_repetitive_but_complete_answer():
    # finish != length: the model chose to stop — deliver what it wrote.
    out = LLMBackend._finalize_stream(REPEATED_TEXT, "", "stop", "test-model")
    assert out == REPEATED_TEXT


def test_finalize_lmstudio_drops_repetition_dominated_truncation():
    out = _finalize_lmstudio_message({"content": REPEATED_TEXT}, "length", "test-model")
    assert out == ""


def test_finalize_lmstudio_keeps_clean_answer():
    out = _finalize_lmstudio_message({"content": "A short clean answer."}, "stop", "test-model")
    assert out == "A short clean answer."
