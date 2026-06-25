"""V4 — counter-metric guardrails (MOONSHOT §6): bounds the north-star can't be gamed past.

Covers the guardrail check (healthy / each breach / None-skipped) and that
compute_north_star surfaces breaches in its payload.
"""

from types import SimpleNamespace

from agents.core.observability.north_star import (
    GUARDRAILS,
    check_guardrails,
    compute_north_star,
)


def test_healthy_metrics_have_no_breaches():
    healthy = {"interrupt_rate_per_day": 2.0, "reject_rate": 0.1, "local_pct": 95.0, "p95_latency_ms": 800.0}
    assert check_guardrails(healthy) == []


def test_each_threshold_breach_is_caught():
    bad = {"interrupt_rate_per_day": 6.0, "reject_rate": 0.9, "local_pct": 10.0, "p95_latency_ms": 5000.0}
    breached = {b["metric"] for b in check_guardrails(bad)}
    assert breached == set(GUARDRAILS)  # all four out of bounds


def test_none_metrics_are_skipped_not_failed():
    # no usage yet → every metric None → no fabricated breach
    nodata = {"interrupt_rate_per_day": None, "reject_rate": None, "local_pct": None, "p95_latency_ms": None}
    assert check_guardrails(nodata) == []


def test_boundary_is_inclusive():
    # exactly at the limit is allowed; just past it breaches
    assert check_guardrails({"p95_latency_ms": 2000.0}) == []
    assert len(check_guardrails({"p95_latency_ms": 2000.1})) == 1
    assert check_guardrails({"local_pct": 50.0}) == []
    assert len(check_guardrails({"local_pct": 49.9})) == 1


def test_compute_north_star_surfaces_guardrails_when_no_data():
    out = compute_north_star(queue=None, run_history=None, tracer=None)
    assert out["guardrails_ok"] is True          # nothing to breach with no data
    assert out["guardrail_breaches"] == []
    assert "p95_latency_ms" in out["counter_metrics"]


def test_compute_north_star_flags_a_real_breach():
    # a tracer reporting 5s turns → p95 breach surfaces in the payload
    tracer = SimpleNamespace(list=lambda n: [{"ts": None, "total_ms": 5000} for _ in range(5)])
    out = compute_north_star(queue=None, run_history=None, tracer=tracer)
    assert out["guardrails_ok"] is False
    assert any(b["metric"] == "p95_latency_ms" for b in out["guardrail_breaches"])
