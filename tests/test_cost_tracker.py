"""Tests for H7.10 — Cost tracker module and /api/analytics/cost endpoint."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(autouse=True)
def reset_tracker():
    """Reset cost tracker state before each test to avoid cross-test pollution."""
    from agents.core import cost_tracker
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── Unit tests for cost_tracker module ───────────────────────────

def test_record_accumulates_tokens():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=100, output_tokens=50, model="default")
    cost_tracker.record("jarvis", input_tokens=200, output_tokens=100, model="default")
    summary = cost_tracker.get_summary()
    assert summary["agents"]["jarvis"]["input_tokens"] == 300
    assert summary["agents"]["jarvis"]["output_tokens"] == 150
    assert summary["agents"]["jarvis"]["calls"] == 2


def test_record_multiple_agents():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500, model="gpt-4o")
    cost_tracker.record("friday", input_tokens=500, output_tokens=250, model="gpt-4o-mini")
    summary = cost_tracker.get_summary()
    assert "jarvis" in summary["agents"]
    assert "friday" in summary["agents"]


def test_get_summary_calculates_cost_default():
    from agents.core import cost_tracker
    # 1M input tokens @ $3.00, 1M output @ $15.00
    cost_tracker.record("agent-x", input_tokens=1_000_000, output_tokens=1_000_000, model="default")
    summary = cost_tracker.get_summary()
    cost = summary["agents"]["agent-x"]["cost_usd"]
    assert abs(cost - 18.0) < 0.001  # $3 input + $15 output


def test_get_summary_calculates_cost_haiku():
    from agents.core import cost_tracker
    # claude-haiku: $1.00 input / $5.00 output per 1M tokens (Haiku 4.5 list price)
    cost_tracker.record("agent-y", input_tokens=1_000_000, output_tokens=1_000_000, model="claude-haiku")
    summary = cost_tracker.get_summary()
    cost = summary["agents"]["agent-y"]["cost_usd"]
    assert abs(cost - 6.00) < 0.001  # $1.00 + $5.00


def test_get_summary_calculates_cost_opus():
    from agents.core import cost_tracker
    # claude-opus: $5.00 input / $25.00 output per 1M tokens (Opus 5 / 4.8 list price)
    cost_tracker.record("agent-o", input_tokens=1_000_000, output_tokens=1_000_000, model="claude-opus")
    summary = cost_tracker.get_summary()
    assert abs(summary["agents"]["agent-o"]["cost_usd"] - 30.00) < 0.001


def _cost_of(model: str) -> float:
    """Cost of 1M input + 1M output tokens on `model`, i.e. its input+output rate."""
    from agents.core import cost_tracker
    cost_tracker.reset()
    cost_tracker.record("a", input_tokens=1_000_000, output_tokens=1_000_000, model=model)
    return cost_tracker.get_summary()["agents"]["a"]["cost_usd"]


def test_versioned_model_ids_resolve_to_their_family_price():
    """A concrete model id must price at its family rate, not the $3/$15 `default`.

    The orchestrator records the model that actually ran (e.g. "claude-opus-5"), never a
    bare family name, so this substring fallback is the path every real call takes.
    """
    for model, expected in (
        ("claude-fable-5", 60.00),     # $10 + $50
        ("claude-opus-5", 30.00),      # $5 + $25
        ("claude-opus-4-8", 30.00),
        ("claude-sonnet-5", 12.00),    # $2 + $10
        ("claude-haiku-4-5", 6.00),    # $1 + $5
        ("gemini-2.5-pro", 11.25),     # $1.25 + $10
        ("gpt-5", 11.25),              # $1.25 + $10
        ("gpt-4o", 12.50),             # $2.50 + $10
    ):
        cost = _cost_of(model)
        assert abs(cost - expected) < 0.001, f"{model} priced at {cost}, expected {expected}"


def test_two_live_generations_of_one_family_price_apart():
    """Sonnet 5 is $2/$10 while Sonnet 4.5/4.6 are still $3/$15.

    One coarse `claude-sonnet` family row cannot express both, so the exact per-model
    table has to win over it. If family fallback ever overrides the exact rate again,
    4.6 silently bills a third under.
    """
    assert abs(_cost_of("claude-sonnet-5") - 12.00) < 0.001    # $2 + $10
    assert abs(_cost_of("claude-sonnet-4-6") - 18.00) < 0.001  # $3 + $15
    assert abs(_cost_of("claude-sonnet-4-5") - 18.00) < 0.001
    # An id nobody has priced yet still meters, via the family row (newest member).
    assert abs(_cost_of("claude-sonnet-9-unreleased") - 12.00) < 0.001


def test_more_specific_family_wins_over_a_shorter_prefix():
    """Longest-match, not first-match.

    `gpt-4o-mini` and `gpt-4o` both substring-match a dated mini snapshot; the cheaper,
    more specific row has to win. First-match would bill it at the `gpt-4o` rate purely
    because of dict insertion order.
    """
    assert abs(_cost_of("gpt-4o-mini-2024-07-18") - 0.75) < 0.001   # $0.15 + $0.60
    assert abs(_cost_of("gpt-4o-2024-11-20") - 12.50) < 0.001       # $2.50 + $10
    assert abs(_cost_of("gemini-3.1-flash-lite") - 1.75) < 0.001    # $0.25 + $1.50
    assert abs(_cost_of("gemini-2.5-flash") - 2.80) < 0.001         # $0.30 + $2.50


def test_local_models_are_free_not_billed_at_cloud_rates():
    """The `record()` caller in orchestrator.py documents "A local route prices at zero".

    A bare local id matches no cloud family, so before these rows existed it fell
    through to the $3/$15 `default` and a local-only install was billed for nothing.
    """
    for model in (
        "google/gemma-4-31b-a4b",
        "google/gemma-4-12b",
        "qwen3:7b",
        "howard-lora-qwen-14b",
        "deepseek-r1-distill-qwen-32b",
        "local",
    ):
        assert _cost_of(model) == 0.0, f"{model} should be free"


def test_price_tables_do_not_drift():
    """Each `cost_tracker` family row must match its newest member in `cost_estimator`.

    Two tables price the same models — one coarse, one exact. Without this they drift
    the moment someone updates a price in only one place, which is how the stale rows
    this table started with survived several model generations.
    """
    from agents.core.cost_tracker import MODEL_PRICES
    from agents.core.llm.cost_estimator import MODELS
    for family, newest in (
        ("claude-fable", "claude-fable-5"),
        ("claude-opus", "claude-opus-5"),
        ("claude-sonnet", "claude-sonnet-5"),
        ("claude-haiku", "claude-haiku-4-5"),
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("gpt-4o", "gpt-4o"),
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-5", "gpt-5"),
    ):
        assert MODEL_PRICES[family] == MODELS[newest], (
            f"cost_tracker[{family}] {MODEL_PRICES[family]} != "
            f"cost_estimator[{newest}] {MODELS[newest]}"
        )


def test_get_summary_local_model_zero_cost():
    from agents.core import cost_tracker
    cost_tracker.record("local-agent", input_tokens=100_000, output_tokens=100_000, model="local")
    summary = cost_tracker.get_summary()
    assert summary["agents"]["local-agent"]["cost_usd"] == 0.0


def test_get_summary_total_cost():
    from agents.core import cost_tracker
    cost_tracker.record("a1", input_tokens=1_000_000, output_tokens=0, model="gpt-4o")
    cost_tracker.record("a2", input_tokens=0, output_tokens=1_000_000, model="gpt-4o")
    summary = cost_tracker.get_summary()
    # a1: 1M input @ $2.50 = $2.50; a2: 1M output @ $10.00 = $10.00; total $12.50
    assert abs(summary["total_cost_usd"] - 12.5) < 0.001


def test_reset_clears_state():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500)
    cost_tracker.reset()
    summary = cost_tracker.get_summary()
    assert summary["agents"] == {}
    assert summary["total_cost_usd"] == 0.0


def test_get_summary_empty():
    from agents.core import cost_tracker
    summary = cost_tracker.get_summary()
    assert "agents" in summary
    assert "total_cost_usd" in summary
    assert summary["total_cost_usd"] == 0.0


# ── Endpoint test ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def test_cost_analytics_endpoint_returns_200(client):
    """GET /api/analytics/cost must return 200 with expected keys."""
    resp = client.get("/api/analytics/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "total_cost_usd" in data


def test_cost_analytics_endpoint_total_is_float(client):
    """total_cost_usd must be a number."""
    resp = client.get("/api/analytics/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["total_cost_usd"], (int, float))
