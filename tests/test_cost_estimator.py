"""Tests for LLM cost estimator."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.cost_estimator import estimate_cost, estimate_monthly, MODELS
from core.llm.model_config import DEFAULT_CLAUDE_MODEL


def test_estimate_cost_local_is_free():
    cost = estimate_cost("qwen3:7b", 1000, 500)
    assert cost["total"] == 0.0
    assert cost["input_cost"] == 0.0
    assert cost["output_cost"] == 0.0


def test_estimate_cost_gemini_flash():
    """DRA-24: cached input is BILLED at the cached rate, not given away free.

    This test previously encoded the old, wrong arithmetic — cached tokens cost $0 and
    the whole non-cached rate counted as a saving. Google bills cached input at
    $0.03/M for gemini-2.5-flash, so the bill was under-reported and the saving
    over-reported by the cached rate on every cached token.
    """
    cost = estimate_cost("gemini-2.5-flash", 1000, 500, cached_tokens=800)
    expected_input = (200 * 0.30 + 800 * 0.03) / 1_000_000
    expected_output = 500 / 1_000_000 * 2.50
    assert cost["input_cost"] == round(expected_input, 10)
    assert cost["output_cost"] == round(expected_output, 10)
    assert cost["total"] == round(expected_input + expected_output, 10)
    assert cost["cached_input"] == 800
    assert cost["savings"] == round(800 * (0.30 - 0.03) / 1_000_000, 10)


def test_cached_tokens_are_never_free_when_the_vendor_publishes_no_cache_rate():
    """A row with no published cached rate bills cached tokens at the FULL input rate.

    Inventing a discount for a model whose vendor publishes none is exactly the
    over-reporting this row exists to stop, so the honest direction is: charge full,
    claim nothing saved.
    """
    cost = estimate_cost("gemini-3.5-flash-lite", 1000, 0, cached_tokens=800)
    assert MODELS["gemini-3.5-flash-lite"]["cached"] is None
    assert cost["total"] == round(1000 * 0.30 / 1_000_000, 10)
    assert cost["savings"] == 0.0


def test_every_model_row_carries_a_cached_rate():
    """Schema pin: the cached rate is part of the price row, not an afterthought."""
    for model, row in MODELS.items():
        assert "cached" in row, f"{model} has no cached-input rate"
        cached = row["cached"]
        assert cached is None or (
            isinstance(cached, int | float) and 0 <= cached <= row["input"]
        ), f"{model} cached rate {cached!r} is not a plausible discount on {row['input']}"


def test_cached_and_non_cached_input_sum_to_the_full_input():
    """No token is billed twice and none escapes billing."""
    row = MODELS["claude-opus-5"]
    cost = estimate_cost("claude-opus-5", 10_000, 0, cached_tokens=4_000)
    expected = (6_000 * row["input"] + 4_000 * row["cached"]) / 1_000_000
    assert cost["input_cost"] == round(expected, 10)
    assert cost["savings"] == round(4_000 * (row["input"] - row["cached"]) / 1_000_000, 10)


def test_estimate_cost_gemini_pro():
    cost = estimate_cost("gemini-2.5-pro", 100_000, 2000)
    assert cost["total"] == 100_000 / 1_000_000 * 1.25 + 2000 / 1_000_000 * 10.00


def test_estimate_cost_claude():
    cost = estimate_cost(DEFAULT_CLAUDE_MODEL, 5000, 1000)
    assert cost["total"] > 0


def test_estimate_cost_unknown_model_returns_zero():
    cost = estimate_cost("unknown-model", 1000, 500)
    assert cost["total"] == 0.0


def test_estimate_monthly_empty():
    assert estimate_monthly([])["total"] == 0.0


def test_estimate_monthly_with_records():
    records = [
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 0},
        {"model": "local", "input_tokens": 2000, "output_tokens": 1000, "cached_tokens": 0},
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 900},
    ]
    result = estimate_monthly(records)
    assert result["total_interactions"] == 3
    assert result["total"] > 0
    assert result["total_savings"] > 0
    assert "gemini-2.5-flash" in result["per_model"]
    assert "local" in result["per_model"]
    assert result["per_model"]["local"]["total"] == 0.0


def test_estimate_cost_negative_tokens_raises():
    with pytest.raises(ValueError, match="Negative token"):
        estimate_cost("gemini-2.5-flash", -100, 50)
    with pytest.raises(ValueError, match="Negative token"):
        estimate_cost("gemini-2.5-flash", 100, -50)


def test_estimate_cost_over_cached():
    """cached_tokens > input_tokens doesn't produce negative cost.

    The clamp holds at the cached rate: every one of the 100 real input tokens is
    billed as cached, and the phantom 100 extra cached tokens bill nothing.
    """
    cost = estimate_cost("gemini-2.5-flash", 100, 50, cached_tokens=200)
    assert cost["input_cost"] == round(100 * 0.03 / 1_000_000, 10)
    assert cost["total"] >= 0
    assert cost["cached_input"] == 200
    assert cost["savings"] == round(100 * (0.30 - 0.03) / 1_000_000, 10)


def test_estimate_monthly_missing_fields():
    """Records missing optional fields default to zero."""
    records = [{"model": "gemini-2.5-flash"}]  # no input/output/cached keys
    result = estimate_monthly(records)
    assert result["total"] == 0.0
    assert result["total_interactions"] == 1


def test_MODELS_has_entries():
    assert len(MODELS) >= 5
    assert "local" in MODELS
    assert "gemini-2.5-flash" in MODELS


def test_estimate_monthly_bills_more_and_claims_less_than_the_free_cache_model():
    """The rollup must move in the honest direction: higher spend, smaller saving."""
    records = [
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 0},
        {"model": "local", "input_tokens": 2000, "output_tokens": 1000, "cached_tokens": 0},
        {"model": "gemini-2.5-flash", "input_tokens": 1000, "output_tokens": 500, "cached_tokens": 900},
    ]
    result = estimate_monthly(records)
    # What the old "cached input is free" arithmetic produced for this exact set.
    pre_fix_total = round((1000 * 0.30 + 500 * 2.50 + 100 * 0.30 + 500 * 2.50) / 1_000_000, 10)
    pre_fix_savings = round(900 * 0.30 / 1_000_000, 10)
    assert result["total"] > pre_fix_total
    assert result["total_savings"] < pre_fix_savings
    assert result["total"] == round(
        (1000 * 0.30 + 500 * 2.50 + 100 * 0.30 + 900 * 0.03 + 500 * 2.50) / 1_000_000, 10
    )
    assert result["total_savings"] == round(900 * (0.30 - 0.03) / 1_000_000, 10)
