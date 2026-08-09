"""Successor-local hostile regression for the E9.1 authority ceiling.

Provenance: closed #854 (ADV-03). The scheduled-report summary must serialize
the evaluation_only ceiling as constants, never its mutable can_* fields, so a
tampered in-memory report (flags flipped via object.__setattr__ after
construction) cannot emit elevated authority.
"""

from __future__ import annotations

import asyncio

from agents.core.observability.benchmark import BenchmarkStore
from agents.core.observability.scheduled_report import (
    EnvironmentProfile,
    build_report,
    run_scheduled_suite,
)

_REVISION = "a" * 40


def _environment() -> EnvironmentProfile:
    return EnvironmentProfile.detect(runner_id="qa-e9-successor")


def _build_report(store_root):
    store = BenchmarkStore(store_root)
    run = asyncio.run(
        run_scheduled_suite(store, revision=_REVISION, run_id="run-qa-e9-successor")
    )
    return build_report(run, store=store, environment=_environment(), previous=None)


def test_e91_authority_ceiling_is_immutable(tmp_path) -> None:
    report = _build_report(tmp_path)

    object.__setattr__(report, "can_change_routing", True)
    object.__setattr__(report, "can_authorize", True)
    object.__setattr__(report, "can_execute", True)
    object.__setattr__(report, "can_promote_capability", True)
    object.__setattr__(report, "can_mark_complete", True)

    payload = report.to_dict()
    assert payload["authority"] == "evaluation_only"
    assert payload["can_change_routing"] is False
    assert payload["can_authorize"] is False
    assert payload["can_execute"] is False
    assert payload["can_promote_capability"] is False
    assert payload["can_mark_complete"] is False
