"""Public Nerva E9.0 benchmark contract with fail-closed evidence boundaries.

The implementation remains evaluation-only. This facade preserves the reviewed
E9.0 contract while enforcing the two cross-record/provenance invariants found
by independent integration review.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _benchmark_e9_0_base as _base

BenchmarkLane = _base.BenchmarkLane
PrivacyClass = _base.PrivacyClass
ResultStatus = _base.ResultStatus
MeasurementStatus = _base.MeasurementStatus
PrivacyEffect = _base.PrivacyEffect
Measurement = _base.Measurement
ResourceMeasurement = _base.ResourceMeasurement
BenchmarkCriterion = _base.BenchmarkCriterion
BenchmarkCase = _base.BenchmarkCase
BenchmarkObservation = _base.BenchmarkObservation
BenchmarkEvidence = _base.BenchmarkEvidence
BenchmarkRunner = _base.BenchmarkRunner
BenchmarkResult = _base.BenchmarkResult


class BenchmarkRun(_base.BenchmarkRun):
    """A benchmark run whose baseline identity matches every retained result."""

    def __post_init__(self) -> None:
        super().__post_init__()
        for result in self.results:
            if result.status == "error" and (
                result.baseline is not None
                or result.baseline_error_type is not None
                or result.baseline_quality.status != "not_measured"
            ):
                raise ValueError(
                    "candidate-error runs require an explicitly unmeasured skipped baseline"
                )

            if self.baseline_id is None:
                if (
                    result.baseline is not None
                    or result.baseline_error_type is not None
                    or result.baseline_quality.status in {"measured", "failed"}
                ):
                    raise ValueError(
                        "baseline evidence requires a declared baseline identity"
                    )
            elif result.baseline_quality.status == "not_applicable":
                raise ValueError(
                    "declared baseline identity cannot use not_applicable evidence"
                )


# Existing stores and harnesses resolve BenchmarkRun from their module globals.
# Bind that name once so construction and deserialization both enforce the
# public cross-record contract without duplicating the mature E9.0 machinery.
_base.BenchmarkRun = BenchmarkRun
BenchmarkStore = _base.BenchmarkStore
BenchmarkHarness = _base.BenchmarkHarness
KeywordRouteBaseline = _base.KeywordRouteBaseline


def _require_deterministic_router(router: Any) -> None:
    if not hasattr(router, "llm_classifier"):
        raise TypeError(
            "current-router deterministic adapter requires an explicit "
            "llm_classifier attribute"
        )
    if router.llm_classifier is not None:
        raise ValueError(
            "current-router deterministic adapter requires llm_classifier=None"
        )


def current_router_runner(
    router: Any,
    agents: Mapping[str, Any],
    *,
    host_id: str = "in-process",
) -> BenchmarkRunner:
    """Observe only the router's deterministic path with truthful provenance.

    A configured or subsequently injected LLM fallback fails closed before the
    prompt can reach ``classify``. An unexpected LLM provenance result is also
    rejected rather than retained as local/no-disclosure evidence.
    """

    _base._identifier(host_id, "host id")
    _require_deterministic_router(router)

    async def run(prompt: str) -> BenchmarkObservation:
        _require_deterministic_router(router)
        intent = await router.classify(prompt, dict(agents))
        if getattr(intent, "context", {}).get("source") == "llm_fallback":
            raise RuntimeError(
                "current-router deterministic adapter rejected LLM fallback provenance"
            )
        route_id = str(getattr(intent, "primary", "jarvis"))
        return BenchmarkObservation(
            response=route_id,
            route_id=route_id,
            model_id="none",
            provider_id="local-deterministic",
            host_id=host_id,
            hardware_profile="not-measured",
            cost_usd=0.0,
            reliability=1.0,
            privacy_effect="no_external_disclosure",
        )

    return run


__all__ = [
    "BenchmarkCase",
    "BenchmarkCriterion",
    "BenchmarkEvidence",
    "BenchmarkHarness",
    "BenchmarkLane",
    "BenchmarkObservation",
    "BenchmarkResult",
    "BenchmarkRun",
    "BenchmarkRunner",
    "BenchmarkStore",
    "KeywordRouteBaseline",
    "Measurement",
    "MeasurementStatus",
    "PrivacyClass",
    "PrivacyEffect",
    "ResourceMeasurement",
    "ResultStatus",
    "current_router_runner",
]
