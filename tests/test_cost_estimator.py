"""Tests for LLM cost estimator."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.cost_estimator import estimate_cost, estimate_monthly, MODELS


def test_estimate_cost_local_is_free():
    cost = estimate_cost("qwen3:7b", 1000, 500)
    assert cost["total"] == 0.0
    assert cost["input_cost"] == 0.0
    assert cost["output_cost"] == 0.0


def test_estimate_cost_gemini_flash():
    cost = estimate_cost("gemini-2.5-flash", 1000, 500, cached_tokens=800)
    expected_input = (1000 - 800) / 1_000_000 * 0.15
    expected_output = 500 / 1_000_000 * 0.60
    assert cost["input_cost"] == round(expected_input, 10)
    assert cost["output_cost"] == round(expected_output, 10)
    assert cost["total"] == round(expected_input + expected_output, 10)
    assert cost["cached_input"] == 800
    assert cost["savings"] == round(800 / 1_000_000 * 0.15, 10)


def test_estimate_cost_gemini_pro():
    cost = estimate_cost("gemini-2.5-pro", 100_000, 2000)
    assert cost["total"] == 100_000 / 1_000_000 * 2.00 + 2000 / 1_000_000 * 10.00


def test_estimate_cost_claude():
    cost = estimate_cost("claude-sonnet-4-20250514", 5000, 1000)
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
    """cached_tokens > input_tokens doesn't produce negative cost."""
    cost = estimate_cost("gemini-2.5-flash", 100, 50, cached_tokens=200)
    assert cost["input_cost"] >= 0
    assert cost["total"] >= 0
    assert cost["cached_input"] == 200


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
