"""Successor-local hostile regression for the E9 totals semantic invariant.

Provenance: closed #854 (ADV-09). A summary cannot claim scored cases while
reporting a null quality_mean: under the accepted BenchmarkResult contract a
passed or failed result has measured quality, so scored > 0 implies a real
quality_mean exists. _validate_totals enforces the reverse (scored == 0 with a
non-null quality_mean is rejected) but must also reject the forward violation.
"""

from __future__ import annotations

import pytest

from agents.core.observability.scheduled_report import _validate_totals


def test_e91_totals_cannot_say_scored_without_quality() -> None:
    with pytest.raises(ValueError):
        _validate_totals(
            {
                "total": 2,
                "scored": 2,
                "passed": 2,
                "failed": 0,
                "unscored": 0,
                "errors": 0,
                "quality_mean": None,
                "baseline_quality_mean": None,
            }
        )


def test_e91_scored_run_with_quality_is_accepted() -> None:
    _validate_totals(
        {
            "total": 2,
            "scored": 2,
            "passed": 2,
            "failed": 0,
            "unscored": 0,
            "errors": 0,
            "quality_mean": 0.75,
            "baseline_quality_mean": None,
        }
    )


def test_e91_unscored_run_without_quality_is_accepted() -> None:
    _validate_totals(
        {
            "total": 2,
            "scored": 0,
            "passed": 0,
            "failed": 0,
            "unscored": 2,
            "errors": 0,
            "quality_mean": None,
            "baseline_quality_mean": None,
        }
    )
