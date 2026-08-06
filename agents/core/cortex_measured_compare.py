"""Strict owner-local route labels bound to E9 evaluation suites only."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import unicodedata
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.cortex_decision import (
    DecisionRecord,
    DecisionRequest,
    ShadowDecisionRouter,
)
from agents.core.observability.benchmark import (
    BenchmarkCase,
    BenchmarkCriterion,
    BenchmarkHarness,
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkStore,
    Measurement,
    current_router_runner,
)
from agents.core.observability.scheduled_report import (
    EnvironmentProfile,
    run_fingerprint,
)

MIN_OWNER_TASKS = 20
RETAINED_REPETITIONS = 5
LABEL_SCHEMA = "nerva.cortex.route-label-set.v1"
REPORT_SCHEMA = "nerva.cortex.measured-comparison.v1"
CANDIDATE_ID = "current-router-e1.2a"

_IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_NONCE_RE = re.compile(r"[a-z0-9][a-z0-9._]{0,47}\Z")
_PLATFORM_RE = re.compile(r"[a-z][a-z0-9]*-[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_PYTHON_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}\Z")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_MAX_TEXT_LENGTH = 10_000
_MAX_METADATA_LENGTH = 128
_ROOT_FIELDS = {
    "schema",
    "label_set_id",
    "sampling_rule",
    "source_window",
    "owner_attested",
    "retention_policy_id",
    "cases",
}
_WINDOW_FIELDS = {"start", "end"}
_CASE_FIELDS = {
    "case_id",
    "text",
    "privacy_class",
    "acceptable_primary_routes",
    "task_category",
    "source_record_digest",
}
_MEASURED_BATCH_GUARD = object()
_MEASURED_REPORT_GUARD = object()

LIMITATION_CODES = (
    "route_adequacy_only",
    "latency_is_harness_only",
    "provider_charge_requires_deterministic_local_evidence",
    "resource_dimensions_not_measured",
    "real_task_outcome_quality_not_measured",
    "fingerprints_are_pseudonymous",
)
OWNER_GATE_CODES = (
    "owner_historical_task_dataset",
    "owner_route_labels_and_categories",
    "owner_sampling_and_exclusion_rule",
    "owner_retention_access_deletion_policy",
    "owner_local_execution_permission",
)

_ENVIRONMENT_FIELDS = {
    "schema",
    "runner_id",
    "platform",
    "python_version",
    "hardware_profile",
}
_ENVIRONMENT_EVIDENCE_FIELDS = _ENVIRONMENT_FIELDS | {"content_fingerprint"}
_MEASUREMENT_FIELDS = {"status", "value", "unit", "source"}
_ROUTE_AGGREGATE_FIELDS = {
    "route_id",
    "sample_count",
    "accepted_count",
    "rejected_count",
    "incomplete_count",
    "adequacy",
}
_REPORT_FIELDS = {
    "schema",
    "label_set_id",
    "label_set_fingerprint",
    "suite_name",
    "suite_version",
    "source_revision",
    "candidate_id",
    "baseline_id",
    "environment",
    "environment_fingerprint",
    "run_fingerprints",
    "repetition_count",
    "task_count",
    "sample_count",
    "accepted_count",
    "rejected_count",
    "error_count",
    "incomplete_count",
    "overall_adequacy",
    "per_actual_route",
    "latency_median",
    "latency_p95",
    "provider_charge",
    "compute",
    "energy",
    "hardware",
    "downstream_agent",
    "tool",
    "action",
    "executed_task_outcome",
    "limitations",
    "owner_gates",
    "complete",
    "authority",
    "can_change_routing",
    "can_authorize",
    "can_execute",
    "can_promote",
    "can_mark_complete",
    "content_fingerprint",
}


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _has_forbidden_characters(value: str) -> bool:
    return any(
        character in {"/", "\\"}
        or unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    )


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_METADATA_LENGTH
        or _has_forbidden_characters(value)
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise ValueError(f"{label} must be a bounded canonical identifier")
    return value


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TEXT_LENGTH
        or _has_forbidden_characters(value)
    ):
        raise ValueError("case text must be bounded, non-empty, and single-line")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or len(value) != 24:
        raise ValueError(f"{label} must be canonical UTC RFC 3339 milliseconds")
    try:
        parsed = datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be canonical UTC RFC 3339 milliseconds"
        ) from exc
    canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if value != canonical:
        raise ValueError(f"{label} must be canonical UTC RFC 3339 milliseconds")
    return parsed


def _strict_keys(raw: object, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError(f"{label} fields do not match the versioned schema")
    return raw


def _unique_routes(values: Collection[object], label: str) -> tuple[str, ...]:
    routes = tuple(_identifier(value, label) for value in values)
    if len(set(routes)) != len(routes):
        raise ValueError("acceptable routes must not contain duplicates")
    return routes


def _route_collection(allowed_routes: Collection[str]) -> frozenset[str]:
    if isinstance(allowed_routes, str):
        raise ValueError("allowed routes must be a non-empty canonical collection")
    routes = tuple(allowed_routes)
    if not routes:
        raise ValueError("allowed routes must be a non-empty canonical collection")
    return frozenset(_unique_routes(routes, "allowed route"))


def _load_json(path: str | Path) -> Mapping[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("route labels must be read from a regular non-symlink file")
    try:
        payload = candidate.read_bytes()
    except OSError as exc:
        raise ValueError("route labels could not be read") from exc
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("route labels must not use a UTF-8 BOM")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("route labels must use strict UTF-8") from exc

    def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError("route labels must not contain duplicate JSON keys")
            parsed[key] = value
        return parsed

    def _number(_value: str) -> None:
        raise ValueError("route labels do not permit JSON floats")

    try:
        raw = json.loads(
            text,
            object_pairs_hook=_object,
            parse_float=_number,
            parse_constant=_number,
        )
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("route labels must be strict versioned JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("route labels must use a root object")
    return raw


@dataclass(frozen=True, repr=False)
class RouteLabelCase:
    case_id: str
    text: str = field(repr=False)
    acceptable_primary_routes: tuple[str, ...]
    task_category: str
    source_record_digest: str = field(repr=False)
    privacy_class: str = field(default="owner_private_local", init=False)
    request_digest: str = field(init=False)
    content_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case id")
        _text(self.text)
        if (
            not isinstance(self.acceptable_primary_routes, tuple)
            or not self.acceptable_primary_routes
        ):
            raise ValueError("acceptable routes must be a sorted unique tuple")
        routes = _unique_routes(self.acceptable_primary_routes, "acceptable route")
        if routes != tuple(sorted(routes)):
            raise ValueError("acceptable routes must be a sorted unique tuple")
        _identifier(self.task_category, "task category")
        _digest(self.source_record_digest, "source record digest")
        if self.privacy_class != "owner_private_local":
            raise ValueError("route labels must remain owner-private local")
        request_digest = DecisionRequest.from_input(self.text, {}).text_digest
        object.__setattr__(self, "request_digest", request_digest)
        object.__setattr__(
            self,
            "content_fingerprint",
            _fingerprint(
                {
                    "acceptable_primary_routes": list(self.acceptable_primary_routes),
                    "case_id": self.case_id,
                    "privacy_class": self.privacy_class,
                    "request_digest": request_digest,
                    "source_record_digest": self.source_record_digest,
                    "task_category": self.task_category,
                }
            ),
        )


@dataclass(frozen=True)
class RouteLabelSet:
    label_set_id: str
    sampling_rule: str
    source_window_start: str
    source_window_end: str
    owner_attested: bool
    retention_policy_id: str
    cases: tuple[RouteLabelCase, ...]
    schema: str = field(default=LABEL_SCHEMA, init=False)
    content_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.label_set_id, "label set id")
        _identifier(self.sampling_rule, "sampling rule")
        start = _timestamp(self.source_window_start, "source window start")
        end = _timestamp(self.source_window_end, "source window end")
        if start > end:
            raise ValueError("source window start must not follow its end")
        if self.owner_attested is not True:
            raise ValueError("route label sets require explicit owner attestation")
        _identifier(self.retention_policy_id, "retention policy id")
        if (
            not isinstance(self.cases, tuple)
            or len(self.cases) < MIN_OWNER_TASKS
            or any(not isinstance(case, RouteLabelCase) for case in self.cases)
        ):
            raise ValueError("route label sets require at least twenty typed cases")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("route label case ids must be unique")
        if len({case.request_digest for case in self.cases}) != len(self.cases):
            raise ValueError("route label request digests must be unique")
        if len({case.source_record_digest for case in self.cases}) != len(self.cases):
            raise ValueError("route label source record digests must be unique")
        object.__setattr__(
            self,
            "content_fingerprint",
            _fingerprint(
                {
                    "cases": [case.content_fingerprint for case in self.cases],
                    "label_set_id": self.label_set_id,
                    "owner_attested": self.owner_attested,
                    "retention_policy_id": self.retention_policy_id,
                    "sampling_rule": self.sampling_rule,
                    "schema": self.schema,
                    "source_window": {
                        "end": self.source_window_end,
                        "start": self.source_window_start,
                    },
                }
            ),
        )


@dataclass(frozen=True)
class MeasuredRunBatch:
    label_set_fingerprint: str
    suite_name: str
    suite_version: int
    environment: EnvironmentProfile
    environment_fingerprint: str
    source_revision: str
    run_fingerprints: tuple[str, ...]
    store_root: Path = field(repr=False)
    repetitions: int = field(default=RETAINED_REPETITIONS, init=False)
    _guard: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._guard is not _MEASURED_BATCH_GUARD:
            raise ValueError("measured run batches are constructed internally")
        _digest(self.label_set_fingerprint, "label set fingerprint")
        _identifier(self.suite_name, "suite name")
        if (
            isinstance(self.suite_version, bool)
            or not isinstance(self.suite_version, int)
            or self.suite_version < 1
        ):
            raise ValueError("suite version must be a positive integer")
        if not isinstance(self.environment, EnvironmentProfile):
            raise ValueError("measured batches require a detected environment")
        _digest(self.environment_fingerprint, "environment fingerprint")
        if self.environment_fingerprint != _fingerprint(
            self.environment.canonical_payload()
        ):
            raise ValueError("environment fingerprint does not match its profile")
        if (
            not isinstance(self.source_revision, str)
            or _REVISION_RE.fullmatch(self.source_revision) is None
        ):
            raise ValueError("source revision must be an exact lowercase Git commit SHA")
        if (
            not isinstance(self.run_fingerprints, tuple)
            or len(self.run_fingerprints) != RETAINED_REPETITIONS
        ):
            raise ValueError("measured batches require five ordered run fingerprints")
        for fingerprint in self.run_fingerprints:
            _digest(fingerprint, "run fingerprint")
        if len(set(self.run_fingerprints)) != RETAINED_REPETITIONS:
            raise ValueError("measured run fingerprints must be unique")
        if not isinstance(self.store_root, Path) or not self.store_root.is_absolute():
            raise ValueError("measured batches require an absolute store root")
        object.__setattr__(self, "_guard", None)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _bounded_environment_value(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_METADATA_LENGTH
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError(f"environment {label} must be bounded single-line text")
    return value


def _measurement_payload(measurement: Measurement) -> dict[str, Any]:
    if not isinstance(measurement, Measurement):
        raise ValueError("report measurements must use E9 Measurement")
    return {
        "source": measurement.source,
        "status": measurement.status,
        "unit": measurement.unit,
        "value": measurement.value,
    }


def _measurement_from_raw(raw: object, label: str) -> Measurement:
    value = _strict_keys(raw, _MEASUREMENT_FIELDS, label)
    try:
        return Measurement.from_dict(value, label=label)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid E9 measurement evidence") from exc


def _adequacy_measurement(accepted: int, rejected: int) -> Measurement:
    scored = accepted + rejected
    if scored == 0:
        return Measurement("not_measured")
    return Measurement(
        "measured",
        accepted / scored,
        "ratio",
        "benchmark.harness",
    )


@dataclass(frozen=True)
class EnvironmentEvidence:
    """Immutable, serializable snapshot of a detected E9.1 environment."""

    runner_id: str
    platform: str
    python_version: str
    hardware_profile: str
    schema: str
    content_fingerprint: str = field(init=False)
    _guard: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._guard is not _MEASURED_REPORT_GUARD:
            raise ValueError("environment evidence is constructed internally")
        for value, label in (
            (self.runner_id, "runner id"),
            (self.platform, "platform"),
            (self.python_version, "python version"),
        ):
            _bounded_environment_value(value, label)
        if self.runner_id != "owner-local-e1-2a":
            raise ValueError("environment runner id is fixed")
        if _PLATFORM_RE.fullmatch(self.platform) is None:
            raise ValueError("environment platform must be canonical")
        if _PYTHON_VERSION_RE.fullmatch(self.python_version) is None:
            raise ValueError("environment Python version must be numeric dotted text")
        if self.hardware_profile != "not_measured":
            raise ValueError("environment hardware must remain not_measured")
        if self.schema != "nerva.benchmark.environment.v1":
            raise ValueError("unsupported environment evidence schema")
        object.__setattr__(
            self,
            "content_fingerprint",
            _fingerprint(self.canonical_payload()),
        )
        object.__setattr__(self, "_guard", None)

    def canonical_payload(self) -> dict[str, str]:
        return {
            "hardware_profile": self.hardware_profile,
            "platform": self.platform,
            "python_version": self.python_version,
            "runner_id": self.runner_id,
            "schema": self.schema,
        }

    def to_dict(self) -> dict[str, str]:
        return {
            **self.canonical_payload(),
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_profile(cls, profile: EnvironmentProfile) -> EnvironmentEvidence:
        if not isinstance(profile, EnvironmentProfile):
            raise ValueError("environment evidence requires a detected profile")
        payload = _strict_keys(
            profile.canonical_payload(),
            _ENVIRONMENT_FIELDS,
            "environment profile",
        )
        return cls(
            runner_id=payload["runner_id"],
            platform=payload["platform"],
            python_version=payload["python_version"],
            hardware_profile=payload["hardware_profile"],
            schema=payload["schema"],
            _guard=_MEASURED_REPORT_GUARD,
        )

    @classmethod
    def _from_dict(cls, raw: object) -> EnvironmentEvidence:
        payload = _strict_keys(
            raw,
            _ENVIRONMENT_EVIDENCE_FIELDS,
            "environment evidence",
        )
        evidence = cls(
            runner_id=payload["runner_id"],
            platform=payload["platform"],
            python_version=payload["python_version"],
            hardware_profile=payload["hardware_profile"],
            schema=payload["schema"],
            _guard=_MEASURED_REPORT_GUARD,
        )
        if payload["content_fingerprint"] != evidence.content_fingerprint:
            raise ValueError("environment evidence fingerprint mismatch")
        return evidence


@dataclass(frozen=True)
class RouteAdequacyAggregate:
    route_id: str
    sample_count: int
    accepted_count: int
    rejected_count: int
    incomplete_count: int
    adequacy: Measurement

    def __post_init__(self) -> None:
        _identifier(self.route_id, "actual route id")
        for value, label in (
            (self.sample_count, "route sample count"),
            (self.accepted_count, "route accepted count"),
            (self.rejected_count, "route rejected count"),
            (self.incomplete_count, "route incomplete count"),
        ):
            _nonnegative_int(value, label)
        if self.accepted_count + self.rejected_count > self.sample_count:
            raise ValueError("route accepted and rejected counts exceed samples")
        if self.incomplete_count < (
            self.sample_count - self.accepted_count - self.rejected_count
        ):
            raise ValueError("route incomplete count hides unaccounted samples")
        if self.incomplete_count > self.sample_count:
            raise ValueError("route incomplete count exceeds samples")
        if self.adequacy != _adequacy_measurement(
            self.accepted_count,
            self.rejected_count,
        ):
            raise ValueError("route adequacy does not match its evidence counts")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_count": self.accepted_count,
            "adequacy": _measurement_payload(self.adequacy),
            "incomplete_count": self.incomplete_count,
            "rejected_count": self.rejected_count,
            "route_id": self.route_id,
            "sample_count": self.sample_count,
        }

    @classmethod
    def _from_dict(cls, raw: object) -> RouteAdequacyAggregate:
        payload = _strict_keys(
            raw,
            _ROUTE_AGGREGATE_FIELDS,
            "route aggregate",
        )
        return cls(
            route_id=payload["route_id"],
            sample_count=payload["sample_count"],
            accepted_count=payload["accepted_count"],
            rejected_count=payload["rejected_count"],
            incomplete_count=payload["incomplete_count"],
            adequacy=_measurement_from_raw(payload["adequacy"], "route adequacy"),
        )


@dataclass(frozen=True)
class MeasuredComparisonReport:
    label_set_id: str
    label_set_fingerprint: str
    suite_name: str
    suite_version: int
    source_revision: str
    candidate_id: str
    baseline_id: None
    environment: EnvironmentEvidence
    environment_fingerprint: str
    run_fingerprints: tuple[str, ...]
    repetition_count: int
    task_count: int
    sample_count: int
    accepted_count: int
    rejected_count: int
    error_count: int
    incomplete_count: int
    overall_adequacy: Measurement
    per_actual_route: tuple[RouteAdequacyAggregate, ...]
    latency_median: Measurement
    latency_p95: Measurement
    provider_charge: Measurement
    compute: Measurement
    energy: Measurement
    hardware: Measurement
    downstream_agent: Measurement
    tool: Measurement
    action: Measurement
    executed_task_outcome: Measurement
    limitations: tuple[str, ...]
    owner_gates: tuple[str, ...]
    schema: str = field(default=REPORT_SCHEMA, init=False)
    complete: bool = field(init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_promote: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    content_fingerprint: str = field(init=False)
    _guard: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._guard is not _MEASURED_REPORT_GUARD:
            raise ValueError("measured reports are constructed internally")
        _identifier(self.label_set_id, "label set id")
        _digest(self.label_set_fingerprint, "label set fingerprint")
        _identifier(self.suite_name, "suite name")
        if (
            isinstance(self.suite_version, bool)
            or not isinstance(self.suite_version, int)
            or self.suite_version < 1
        ):
            raise ValueError("report suite version must be a positive integer")
        if _REVISION_RE.fullmatch(self.source_revision) is None:
            raise ValueError("report source revision must be an exact Git SHA")
        if self.candidate_id != CANDIDATE_ID or self.baseline_id is not None:
            raise ValueError("report target identity is immutable")
        if not isinstance(self.environment, EnvironmentEvidence):
            raise ValueError("report environment must use EnvironmentEvidence")
        _digest(self.environment_fingerprint, "environment fingerprint")
        if self.environment_fingerprint != self.environment.content_fingerprint:
            raise ValueError("report environment fingerprint mismatch")
        if (
            not isinstance(self.run_fingerprints, tuple)
            or len(self.run_fingerprints) != RETAINED_REPETITIONS
        ):
            raise ValueError("report requires five ordered run fingerprints")
        for fingerprint in self.run_fingerprints:
            _digest(fingerprint, "run fingerprint")
        if len(set(self.run_fingerprints)) != RETAINED_REPETITIONS:
            raise ValueError("report run fingerprints must be unique")
        for value, label in (
            (self.repetition_count, "repetition count"),
            (self.task_count, "task count"),
            (self.sample_count, "sample count"),
            (self.accepted_count, "accepted count"),
            (self.rejected_count, "rejected count"),
            (self.error_count, "error count"),
            (self.incomplete_count, "incomplete count"),
        ):
            _nonnegative_int(value, label)
        if self.repetition_count != RETAINED_REPETITIONS:
            raise ValueError("report repetition count must remain five")
        if self.task_count < MIN_OWNER_TASKS:
            raise ValueError("report requires at least twenty unique tasks")
        if self.sample_count != self.task_count * self.repetition_count:
            raise ValueError("report sample count does not match tasks and repetitions")
        if self.accepted_count + self.rejected_count + self.error_count > self.sample_count:
            raise ValueError("report result counts exceed samples")
        if self.incomplete_count < (
            self.sample_count - self.accepted_count - self.rejected_count
        ):
            raise ValueError("report incomplete count hides unaccounted samples")
        if self.error_count > self.incomplete_count:
            raise ValueError("report errors must remain visible as incomplete evidence")
        if self.incomplete_count > self.sample_count:
            raise ValueError("report incomplete count exceeds samples")
        if self.overall_adequacy != _adequacy_measurement(
            self.accepted_count,
            self.rejected_count,
        ):
            raise ValueError("overall adequacy does not match evidence counts")
        if (
            not isinstance(self.per_actual_route, tuple)
            or any(
                not isinstance(item, RouteAdequacyAggregate)
                for item in self.per_actual_route
            )
        ):
            raise ValueError("per-route evidence must use typed aggregates")
        route_ids = tuple(item.route_id for item in self.per_actual_route)
        if route_ids != tuple(sorted(set(route_ids))):
            raise ValueError("per-route evidence must be sorted and unique")
        if sum(item.sample_count for item in self.per_actual_route) != (
            self.sample_count - self.error_count
        ):
            raise ValueError("per-route samples do not match candidate evidence")
        if sum(item.accepted_count for item in self.per_actual_route) != self.accepted_count:
            raise ValueError("per-route accepted counts do not match the total")
        if sum(item.rejected_count for item in self.per_actual_route) != self.rejected_count:
            raise ValueError("per-route rejected counts do not match the total")
        if (
            self.error_count
            + sum(item.incomplete_count for item in self.per_actual_route)
            != self.incomplete_count
        ):
            raise ValueError("per-route incomplete counts do not match the total")
        self._validate_measurements()
        if self.limitations != LIMITATION_CODES:
            raise ValueError("report limitations are fixed")
        if self.owner_gates != OWNER_GATE_CODES:
            raise ValueError("report owner gates are fixed")
        complete = (
            self.incomplete_count == 0
            and self.latency_median.status == "measured"
            and self.latency_p95.status == "measured"
            and self.provider_charge.status == "measured"
        )
        object.__setattr__(self, "complete", complete)
        object.__setattr__(self, "content_fingerprint", _fingerprint(self._payload()))
        object.__setattr__(self, "_guard", None)

    def _validate_measurements(self) -> None:
        for measurement in (
            self.overall_adequacy,
            self.latency_median,
            self.latency_p95,
            self.provider_charge,
            self.compute,
            self.energy,
            self.hardware,
            self.downstream_agent,
            self.tool,
            self.action,
            self.executed_task_outcome,
        ):
            if not isinstance(measurement, Measurement):
                raise ValueError("report measurements must use E9 Measurement")
        for measurement, label in (
            (self.latency_median, "latency median"),
            (self.latency_p95, "latency p95"),
        ):
            if measurement.status == "measured" and (
                measurement.unit != "ms"
                or measurement.source != "benchmark.harness"
                or isinstance(measurement.value, bool)
                or not isinstance(measurement.value, (int, float))
                or not math.isfinite(float(measurement.value))
                or float(measurement.value) < 0
            ):
                raise ValueError(f"{label} must use measured E9 harness milliseconds")
            if measurement.status not in {"measured", "not_measured"}:
                raise ValueError(f"{label} has an unsupported status")
        if (
            self.latency_median.status == "measured"
            and self.latency_p95.status == "measured"
            and float(self.latency_p95.value) < float(self.latency_median.value)
        ):
            raise ValueError("latency p95 cannot be below the median")
        if self.provider_charge.status == "measured" and (
            self.provider_charge.value != 0.0
            or self.provider_charge.unit != "usd"
            or self.provider_charge.source != "candidate.runner"
        ):
            raise ValueError("provider charge can only claim measured local zero USD")
        if self.provider_charge.status not in {"measured", "not_measured"}:
            raise ValueError("provider charge has an unsupported status")
        for measurement in (
            self.compute,
            self.energy,
            self.hardware,
            self.downstream_agent,
            self.tool,
            self.action,
            self.executed_task_outcome,
        ):
            if measurement != Measurement("not_measured"):
                raise ValueError("unmeasured report dimensions cannot claim evidence")

    def _payload(self) -> dict[str, Any]:
        return {
            "accepted_count": self.accepted_count,
            "action": _measurement_payload(self.action),
            "authority": self.authority,
            "baseline_id": self.baseline_id,
            "can_authorize": self.can_authorize,
            "can_change_routing": self.can_change_routing,
            "can_execute": self.can_execute,
            "can_mark_complete": self.can_mark_complete,
            "can_promote": self.can_promote,
            "candidate_id": self.candidate_id,
            "complete": self.complete,
            "compute": _measurement_payload(self.compute),
            "downstream_agent": _measurement_payload(self.downstream_agent),
            "energy": _measurement_payload(self.energy),
            "environment": self.environment.to_dict(),
            "environment_fingerprint": self.environment_fingerprint,
            "error_count": self.error_count,
            "executed_task_outcome": _measurement_payload(
                self.executed_task_outcome
            ),
            "hardware": _measurement_payload(self.hardware),
            "incomplete_count": self.incomplete_count,
            "label_set_fingerprint": self.label_set_fingerprint,
            "label_set_id": self.label_set_id,
            "latency_median": _measurement_payload(self.latency_median),
            "latency_p95": _measurement_payload(self.latency_p95),
            "limitations": list(self.limitations),
            "overall_adequacy": _measurement_payload(self.overall_adequacy),
            "owner_gates": list(self.owner_gates),
            "per_actual_route": [item.to_dict() for item in self.per_actual_route],
            "provider_charge": _measurement_payload(self.provider_charge),
            "rejected_count": self.rejected_count,
            "repetition_count": self.repetition_count,
            "run_fingerprints": list(self.run_fingerprints),
            "sample_count": self.sample_count,
            "schema": self.schema,
            "source_revision": self.source_revision,
            "suite_name": self.suite_name,
            "suite_version": self.suite_version,
            "task_count": self.task_count,
            "tool": _measurement_payload(self.tool),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "content_fingerprint": self.content_fingerprint}

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> MeasuredComparisonReport:
        def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, value in pairs:
                if key in parsed:
                    raise ValueError("measured report must not contain duplicate JSON keys")
                parsed[key] = value
            return parsed

        def _constant(_value: str) -> None:
            raise ValueError("measured report numbers must be finite")

        try:
            raw = json.loads(
                payload,
                object_pairs_hook=_object,
                parse_constant=_constant,
            )
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, ValueError) and "duplicate JSON keys" in str(exc):
                raise
            raise ValueError("measured report must be strict JSON") from exc
        value = _strict_keys(raw, _REPORT_FIELDS, "measured report")
        immutable = {
            "schema": REPORT_SCHEMA,
            "authority": "evaluation_only",
            "can_change_routing": False,
            "can_authorize": False,
            "can_execute": False,
            "can_promote": False,
            "can_mark_complete": False,
        }
        for key in (
            "can_change_routing",
            "can_authorize",
            "can_execute",
            "can_promote",
            "can_mark_complete",
            "complete",
        ):
            if type(value[key]) is not bool:
                raise ValueError(f"measured report {key} must be an exact Boolean")
        if any(value[key] != expected for key, expected in immutable.items()):
            raise ValueError("measured report authority and schema are immutable")
        if not isinstance(value["run_fingerprints"], list):
            raise ValueError("run fingerprints must use an ordered JSON array")
        if not isinstance(value["per_actual_route"], list):
            raise ValueError("per-route evidence must use an ordered JSON array")
        if not isinstance(value["limitations"], list) or not isinstance(
            value["owner_gates"], list
        ):
            raise ValueError("limitations and owner gates must use JSON arrays")
        report = cls(
            label_set_id=value["label_set_id"],
            label_set_fingerprint=value["label_set_fingerprint"],
            suite_name=value["suite_name"],
            suite_version=value["suite_version"],
            source_revision=value["source_revision"],
            candidate_id=value["candidate_id"],
            baseline_id=value["baseline_id"],
            environment=EnvironmentEvidence._from_dict(value["environment"]),
            environment_fingerprint=value["environment_fingerprint"],
            run_fingerprints=tuple(value["run_fingerprints"]),
            repetition_count=value["repetition_count"],
            task_count=value["task_count"],
            sample_count=value["sample_count"],
            accepted_count=value["accepted_count"],
            rejected_count=value["rejected_count"],
            error_count=value["error_count"],
            incomplete_count=value["incomplete_count"],
            overall_adequacy=_measurement_from_raw(
                value["overall_adequacy"], "overall adequacy"
            ),
            per_actual_route=tuple(
                RouteAdequacyAggregate._from_dict(item)
                for item in value["per_actual_route"]
            ),
            latency_median=_measurement_from_raw(
                value["latency_median"], "latency median"
            ),
            latency_p95=_measurement_from_raw(value["latency_p95"], "latency p95"),
            provider_charge=_measurement_from_raw(
                value["provider_charge"], "provider charge"
            ),
            compute=_measurement_from_raw(value["compute"], "compute"),
            energy=_measurement_from_raw(value["energy"], "energy"),
            hardware=_measurement_from_raw(value["hardware"], "hardware"),
            downstream_agent=_measurement_from_raw(
                value["downstream_agent"], "downstream agent"
            ),
            tool=_measurement_from_raw(value["tool"], "tool"),
            action=_measurement_from_raw(value["action"], "action"),
            executed_task_outcome=_measurement_from_raw(
                value["executed_task_outcome"], "executed task outcome"
            ),
            limitations=tuple(value["limitations"]),
            owner_gates=tuple(value["owner_gates"]),
            _guard=_MEASURED_REPORT_GUARD,
        )
        if value["complete"] is not report.complete:
            raise ValueError("measured report completeness drift")
        if value["content_fingerprint"] != report.content_fingerprint:
            raise ValueError("measured report content fingerprint mismatch")
        return report


def load_route_label_set(
    path: str | Path,
    *,
    allowed_routes: Collection[str],
) -> RouteLabelSet:
    """Load one exact owner-attested, local-only route-label document."""

    canonical_routes = _route_collection(allowed_routes)
    raw = _strict_keys(_load_json(path), _ROOT_FIELDS, "route label set")
    if raw["schema"] != LABEL_SCHEMA:
        raise ValueError("unsupported route label schema")
    window = _strict_keys(raw["source_window"], _WINDOW_FIELDS, "source window")
    cases_raw = raw["cases"]
    if not isinstance(cases_raw, list):
        raise ValueError("route label cases must be an ordered JSON array")
    cases: list[RouteLabelCase] = []
    for index, raw_case in enumerate(cases_raw, start=1):
        case = _strict_keys(raw_case, _CASE_FIELDS, f"route label case {index}")
        routes = case["acceptable_primary_routes"]
        if not isinstance(routes, list) or not routes:
            raise ValueError("acceptable routes must be a non-empty JSON array")
        routes = _unique_routes(routes, "acceptable route")
        for route in routes:
            if route not in canonical_routes:
                raise ValueError("acceptable route is not registered")
        if case["privacy_class"] != "owner_private_local":
            raise ValueError("route labels must remain owner-private local")
        cases.append(
            RouteLabelCase(
                case_id=case["case_id"],
                text=case["text"],
                acceptable_primary_routes=tuple(sorted(routes)),
                task_category=case["task_category"],
                source_record_digest=case["source_record_digest"],
            )
        )
    return RouteLabelSet(
        label_set_id=raw["label_set_id"],
        sampling_rule=raw["sampling_rule"],
        source_window_start=window["start"],
        source_window_end=window["end"],
        owner_attested=raw["owner_attested"],
        retention_policy_id=raw["retention_policy_id"],
        cases=tuple(cases),
    )


def _suite_name(label_set: RouteLabelSet) -> str:
    label_digest = hashlib.sha256(label_set.label_set_id.encode("utf-8")).hexdigest()
    return f"owner-route-{label_digest[:32]}"


def build_owner_route_suite(label_set: RouteLabelSet) -> tuple[BenchmarkCase, ...]:
    """Convert strict labels into local-only E9 cases without routing authority."""

    if not isinstance(label_set, RouteLabelSet):
        raise ValueError("owner route suites require a RouteLabelSet")
    return tuple(
        BenchmarkCase(
            case_id=case.case_id,
            task_type=case.task_category,
            input_text=case.text,
            privacy_class="owner_private_local",
            allowed_lanes=("local",),
            criterion=BenchmarkCriterion("exact", "accepted"),
            artifact_refs=(
                f"label-fingerprint:{label_set.content_fingerprint}",
                f"case-fingerprint:{case.content_fingerprint}",
            ),
        )
        for case in label_set.cases
    )


def ensure_owner_route_suite(
    store: BenchmarkStore,
    label_set: RouteLabelSet,
) -> tuple[str, int, tuple[BenchmarkCase, ...]]:
    """Reuse an exact current suite version or persist the next local version."""

    if not isinstance(store, BenchmarkStore):
        raise ValueError("owner route suites require a BenchmarkStore")
    cases = build_owner_route_suite(label_set)
    name = _suite_name(label_set)
    versions = store.versions(name)
    if versions:
        version = versions[-1]
        stored = store.load_suite(name, version)
        if tuple(
            (case.case_id, case.content_fingerprint) for case in stored
        ) == tuple((case.case_id, case.content_fingerprint) for case in cases):
            return name, version, stored
    return name, store.save_suite(name, cases, lane="local"), cases


def measured_current_router_runner(
    router: Any,
    agents: Mapping[str, Any],
    label_set: RouteLabelSet,
    *,
    host_id: str = "in-process",
) -> BenchmarkRunner:
    """Score one observed deterministic route against retained owner labels."""

    if not isinstance(label_set, RouteLabelSet):
        raise ValueError("measured route runner requires a RouteLabelSet")
    current_router_runner(router, agents, host_id=host_id)

    labels_by_request: dict[str, RouteLabelCase] = {}
    for case in label_set.cases:
        if case.request_digest in labels_by_request:
            raise ValueError("measured route labels must have unique request digests")
        labels_by_request[case.request_digest] = case

    async def run(prompt: str):
        request_digest = DecisionRequest.from_input(prompt, {}).text_digest
        label = labels_by_request.get(request_digest)
        if label is None:
            raise ValueError("measured route runner requires a known route label")

        records: list[DecisionRecord] = []
        shadow_router = ShadowDecisionRouter(router, records.append)
        observation = await current_router_runner(
            shadow_router,
            agents,
            host_id=host_id,
        )(prompt)
        if len(records) != 1:
            raise RuntimeError("measured route runner requires exactly one decision record")
        record = records[0]
        if record.selected_route != observation.route_id:
            raise RuntimeError("measured route runner requires matching route evidence")
        score = (
            "accepted"
            if observation.route_id in label.acceptable_primary_routes
            else "rejected"
        )
        return replace(
            observation,
            response=score,
            artifact_refs=(f"decision:{record.replay_fingerprint}",),
        )

    return run


def _validated_store_root(store_root: Path) -> Path:
    if not isinstance(store_root, Path):
        raise TypeError("store root must be an explicitly supplied Path")
    if not store_root.is_absolute():
        raise ValueError("store root must be absolute")

    current = Path(store_root.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in store_root.parts[1:]:
        if part == "..":
            raise ValueError("store root must not traverse parent components")
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise ValueError("store root must be an existing directory") from exc
        is_reparse = bool(
            getattr(metadata, "st_file_attributes", 0) & reparse_flag
        )
        if stat.S_ISLNK(metadata.st_mode) or is_reparse:
            raise ValueError("store root must not cross a symlink or reparse boundary")

    if not store_root.is_dir():
        raise ValueError("store root must be an existing directory")
    try:
        resolved = store_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("store root could not be resolved") from exc
    if not resolved.is_dir():
        raise ValueError("store root must resolve to a directory")
    return resolved


def _validate_measured_preflight(
    *,
    router: Any,
    agents: Mapping[str, Any],
    label_set: RouteLabelSet,
    source_revision: str,
) -> BenchmarkRunner:
    if (
        not isinstance(source_revision, str)
        or _REVISION_RE.fullmatch(source_revision) is None
    ):
        raise ValueError("source revision must be an exact lowercase Git commit SHA")
    if not isinstance(label_set, RouteLabelSet):
        raise ValueError("measured comparisons require a RouteLabelSet")
    if not isinstance(agents, Mapping):
        raise ValueError("route registry must be a mapping")
    registered_routes = _route_collection(tuple(agents))
    for case in label_set.cases:
        if not set(case.acceptable_primary_routes).issubset(registered_routes):
            raise ValueError("every acceptable route must be registered")
    return measured_current_router_runner(router, agents, label_set)


def _run_id(
    label_set_fingerprint: str,
    nonce_factory: Callable[[], str],
    repetition: int,
) -> str:
    nonce = nonce_factory()
    if not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None:
        raise ValueError("run nonce must be a bounded lowercase identifier component")
    run_id = f"run-{label_set_fingerprint[:12]}-{nonce}-{repetition}"
    return _identifier(run_id, "run id")


def _has_incomplete_results(run: Any) -> bool:
    return any(result.status in {"error", "unscored"} for result in run.results)


async def run_measured_comparison(
    *,
    router: Any,
    agents: Mapping[str, Any],
    label_set: RouteLabelSet,
    store_root: Path,
    source_revision: str,
    run_nonce: Callable[[], str] | None = None,
) -> MeasuredRunBatch:
    """Warm the deterministic router, then retain five owner-local E9 runs.

    The accepted E9 store is an owner-local, single-writer store. This guarded
    path detects collisions and verifies its own append, but does not claim
    safety for concurrent writers.
    """

    resolved_root = _validated_store_root(store_root)
    runner = _validate_measured_preflight(
        router=router,
        agents=agents,
        label_set=label_set,
        source_revision=source_revision,
    )
    if run_nonce is not None and not callable(run_nonce):
        raise ValueError("run nonce must be callable")
    nonce_factory = run_nonce or (lambda: uuid.uuid4().hex[:12])

    store = BenchmarkStore(resolved_root)
    suite_name, suite_version, cases = ensure_owner_route_suite(store, label_set)
    environment = EnvironmentProfile.detect(runner_id="owner-local-e1-2a")
    environment_fingerprint = _fingerprint(environment.canonical_payload())
    harness = BenchmarkHarness(runner, candidate_id=CANDIDATE_ID)

    warmup = await harness.run(
        cases,
        suite_name=suite_name,
        suite_version=suite_version,
        lane="local",
        source_revision=source_revision,
    )
    if _has_incomplete_results(warmup):
        raise RuntimeError("measured route warm-up did not complete every case")

    artifact_refs = (
        f"label-fingerprint:{label_set.content_fingerprint}",
        f"environment-fingerprint:{environment_fingerprint}",
    )
    fingerprints: list[str] = []
    for repetition in range(1, RETAINED_REPETITIONS + 1):
        retained_run_id = _run_id(
            label_set.content_fingerprint,
            nonce_factory,
            repetition,
        )
        existing = store.runs(suite_name, last_n=sys.maxsize)
        if any(run.run_id == retained_run_id for run in existing):
            raise ValueError("measured run id collision")

        run = await harness.run(
            cases,
            suite_name=suite_name,
            suite_version=suite_version,
            lane="local",
            source_revision=source_revision,
            run_id=retained_run_id,
        )
        run = replace(run, artifact_refs=artifact_refs)
        expected_fingerprint = run_fingerprint(run)
        store.record_run(run)

        matches = tuple(
            candidate
            for candidate in store.runs(
                suite_name,
                last_n=sys.maxsize,
            )
            if candidate.run_id == retained_run_id
        )
        if (
            len(matches) != 1
            or run_fingerprint(matches[0]) != expected_fingerprint
        ):
            raise RuntimeError("recorded measured run is not canonically retrievable")
        fingerprints.append(expected_fingerprint)

    return MeasuredRunBatch(
        label_set_fingerprint=label_set.content_fingerprint,
        suite_name=suite_name,
        suite_version=suite_version,
        environment=environment,
        environment_fingerprint=environment_fingerprint,
        source_revision=source_revision,
        run_fingerprints=tuple(fingerprints),
        store_root=resolved_root,
        _guard=_MEASURED_BATCH_GUARD,
    )


def _exact_retained_runs(
    batch: MeasuredRunBatch,
    store: BenchmarkStore,
) -> tuple[BenchmarkRun, ...]:
    retained = store.runs(batch.suite_name, last_n=sys.maxsize)
    by_fingerprint: dict[str, list[BenchmarkRun]] = {}
    for run in retained:
        fingerprint = run_fingerprint(run)
        by_fingerprint.setdefault(fingerprint, []).append(run)
    ordered: list[BenchmarkRun] = []
    for fingerprint in batch.run_fingerprints:
        matches = by_fingerprint.get(fingerprint, [])
        if len(matches) != 1:
            raise ValueError(
                "each measured run fingerprint must identify one retained run"
            )
        ordered.append(matches[0])
    if len({run.run_id for run in ordered}) != RETAINED_REPETITIONS:
        raise ValueError("measured repetitions must identify unique retained runs")
    return tuple(ordered)


def _validate_decision_artifact(result: Any) -> None:
    if result.status == "error":
        if result.candidate is not None:
            raise ValueError("error evidence cannot carry a candidate identity")
        return
    if result.candidate is None:
        raise ValueError("non-error evidence requires a candidate identity")
    artifacts = result.candidate.artifact_refs
    if len(artifacts) != 1 or not artifacts[0].startswith("decision:"):
        raise ValueError("candidate evidence requires one decision fingerprint")
    _digest(artifacts[0].removeprefix("decision:"), "decision fingerprint")


def _is_harness_latency(measurement: Measurement) -> bool:
    return (
        measurement.status == "measured"
        and measurement.unit == "ms"
        and measurement.source == "benchmark.harness"
        and isinstance(measurement.value, (int, float))
        and not isinstance(measurement.value, bool)
        and math.isfinite(float(measurement.value))
        and float(measurement.value) >= 0
    )


def _is_zero_local_charge(run: BenchmarkRun, result: Any) -> bool:
    candidate = result.candidate
    cost = result.cost
    return (
        run.baseline_id is None
        and candidate is not None
        and candidate.model_id == "none"
        and candidate.provider_id == "local-deterministic"
        and cost.status == "measured"
        and cost.value == 0.0
        and cost.unit == "usd"
        and cost.source == "candidate.runner"
    )


def _is_candidate_cost_measurement(measurement: Measurement) -> bool:
    return (
        measurement.status == "measured"
        and measurement.unit == "usd"
        and measurement.source == "candidate.runner"
        and isinstance(measurement.value, (int, float))
        and not isinstance(measurement.value, bool)
        and math.isfinite(float(measurement.value))
        and float(measurement.value) >= 0
    )


def _latency_measurements(values: list[float]) -> tuple[Measurement, Measurement]:
    if not values:
        unknown = Measurement("not_measured")
        return unknown, unknown
    ordered = sorted(values)
    size = len(ordered)
    midpoint = size // 2
    median = (
        ordered[midpoint]
        if size % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    )
    p95 = ordered[math.ceil(0.95 * size) - 1]
    return (
        Measurement("measured", median, "ms", "benchmark.harness"),
        Measurement("measured", p95, "ms", "benchmark.harness"),
    )


def _derive_measured_report(
    batch: MeasuredRunBatch,
    store: BenchmarkStore,
    label_set: RouteLabelSet,
) -> MeasuredComparisonReport:
    if not isinstance(batch, MeasuredRunBatch):
        raise ValueError("report evidence requires a MeasuredRunBatch")
    if not isinstance(store, BenchmarkStore):
        raise ValueError("report evidence requires a BenchmarkStore")
    if not isinstance(label_set, RouteLabelSet):
        raise ValueError("report evidence requires a RouteLabelSet")
    if store.root.resolve() != batch.store_root:
        raise ValueError("report store does not match the measured batch")
    if batch.label_set_fingerprint != label_set.content_fingerprint:
        raise ValueError("measured batch does not match the supplied label set")
    if batch.suite_name != _suite_name(label_set):
        raise ValueError("measured batch suite identity does not match its labels")

    expected_cases = build_owner_route_suite(label_set)
    stored_cases = store.load_suite(batch.suite_name, batch.suite_version)
    expected_sequence = tuple(
        (case.case_id, case.content_fingerprint) for case in expected_cases
    )
    stored_sequence = tuple(
        (case.case_id, case.content_fingerprint) for case in stored_cases
    )
    if stored_sequence != expected_sequence:
        raise ValueError("stored suite does not match the ordered measured labels")

    environment = EnvironmentEvidence.from_profile(batch.environment)
    if environment.content_fingerprint != batch.environment_fingerprint:
        raise ValueError("measured batch environment fingerprint mismatch")
    runs = _exact_retained_runs(batch, store)
    label_by_id = {case.case_id: case for case in label_set.cases}

    accepted_count = 0
    rejected_count = 0
    error_count = 0
    incomplete_count = 0
    latency_values: list[float] = []
    deterministic_charge = True
    route_counts: dict[str, list[int]] = {}
    expected_artifacts = (
        f"label-fingerprint:{label_set.content_fingerprint}",
        f"environment-fingerprint:{batch.environment_fingerprint}",
    )

    for repetition, run in enumerate(runs, start=1):
        if (
            run.suite_name != batch.suite_name
            or run.suite_version != batch.suite_version
            or run.source_revision != batch.source_revision
            or run.candidate_id != CANDIDATE_ID
            or run.baseline_id is not None
            or run.lane != "local"
        ):
            raise ValueError("retained measured runs have mixed identities")
        if not run.run_id.endswith(f"-{repetition}"):
            raise ValueError("retained measured runs do not form the ordered repetitions")
        if not run.run_id.startswith(f"run-{label_set.content_fingerprint[:12]}-"):
            raise ValueError("retained measured run identity does not match its labels")
        if run.artifact_refs != expected_artifacts:
            raise ValueError("retained measured run artifact fingerprints mismatch")
        if tuple(result.case_id for result in run.results) != tuple(
            case.case_id for case in expected_cases
        ):
            raise ValueError("retained measured run result coverage mismatch")

        for stored_case, result in zip(stored_cases, run.results, strict=True):
            label = label_by_id[result.case_id]
            if (
                result.task_type != stored_case.task_type
                or result.privacy_class != "owner_private_local"
                or result.case_fingerprint != stored_case.content_fingerprint
            ):
                raise ValueError("retained result identity or case fingerprint mismatch")
            _validate_decision_artifact(result)

            incomplete = result.status in {"error", "unscored"}
            if result.status == "error":
                error_count += 1
                deterministic_charge = False
            else:
                candidate = result.candidate
                if candidate is None:
                    raise ValueError("non-error evidence requires a candidate identity")
                if candidate.hardware_profile != "not-measured":
                    raise ValueError(
                        "candidate hardware provenance must remain separately unmeasured"
                    )
                route = candidate.route_id
                counts = route_counts.setdefault(route, [0, 0, 0, 0])
                counts[0] += 1
                route_is_accepted = route in label.acceptable_primary_routes
                if result.status == "passed":
                    if not route_is_accepted:
                        raise ValueError("passed route evidence contradicts its label")
                    accepted_count += 1
                    counts[1] += 1
                elif result.status == "failed":
                    if route_is_accepted:
                        raise ValueError("failed route evidence contradicts its label")
                    rejected_count += 1
                    counts[2] += 1
                elif result.status != "unscored":
                    raise ValueError("unsupported retained result status")

                if _is_harness_latency(result.latency):
                    latency_values.append(float(result.latency.value))
                else:
                    incomplete = True
                if not _is_candidate_cost_measurement(result.cost):
                    incomplete = True
                if not _is_zero_local_charge(run, result):
                    deterministic_charge = False
                if incomplete:
                    counts[3] += 1
            if incomplete:
                incomplete_count += 1

    sample_count = len(runs) * len(stored_cases)
    if sample_count != len(label_set.cases) * RETAINED_REPETITIONS:
        raise ValueError("retained measured sample coverage mismatch")
    latency_median, latency_p95 = _latency_measurements(latency_values)
    per_actual_route = tuple(
        RouteAdequacyAggregate(
            route_id=route_id,
            sample_count=counts[0],
            accepted_count=counts[1],
            rejected_count=counts[2],
            incomplete_count=counts[3],
            adequacy=_adequacy_measurement(counts[1], counts[2]),
        )
        for route_id, counts in sorted(route_counts.items())
    )
    unmeasured = Measurement("not_measured")
    return MeasuredComparisonReport(
        label_set_id=label_set.label_set_id,
        label_set_fingerprint=label_set.content_fingerprint,
        suite_name=batch.suite_name,
        suite_version=batch.suite_version,
        source_revision=batch.source_revision,
        candidate_id=CANDIDATE_ID,
        baseline_id=None,
        environment=environment,
        environment_fingerprint=batch.environment_fingerprint,
        run_fingerprints=batch.run_fingerprints,
        repetition_count=RETAINED_REPETITIONS,
        task_count=len(label_set.cases),
        sample_count=sample_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        error_count=error_count,
        incomplete_count=incomplete_count,
        overall_adequacy=_adequacy_measurement(accepted_count, rejected_count),
        per_actual_route=per_actual_route,
        latency_median=latency_median,
        latency_p95=latency_p95,
        provider_charge=(
            Measurement("measured", 0.0, "usd", "candidate.runner")
            if deterministic_charge
            else unmeasured
        ),
        compute=unmeasured,
        energy=unmeasured,
        hardware=unmeasured,
        downstream_agent=unmeasured,
        tool=unmeasured,
        action=unmeasured,
        executed_task_outcome=unmeasured,
        limitations=LIMITATION_CODES,
        owner_gates=OWNER_GATE_CODES,
        _guard=_MEASURED_REPORT_GUARD,
    )


def build_measured_report(
    batch: MeasuredRunBatch,
    store: BenchmarkStore,
    label_set: RouteLabelSet,
) -> MeasuredComparisonReport:
    """Build a privacy-minimised aggregate from exact retained evidence."""

    return _derive_measured_report(batch, store, label_set)


def validate_measured_report_against_evidence(
    report: MeasuredComparisonReport,
    batch: MeasuredRunBatch,
    store: BenchmarkStore,
    label_set: RouteLabelSet,
) -> None:
    """Bind a structural report to the exact batch, store, and labels."""

    if not isinstance(report, MeasuredComparisonReport):
        raise ValueError("evidence validation requires a MeasuredComparisonReport")
    expected = _derive_measured_report(batch, store, label_set)
    if report != expected:
        raise ValueError("measured report does not match the retained evidence")


def _render_measurement(measurement: Measurement) -> str:
    if measurement.status != "measured":
        return measurement.status
    return (
        f"{measurement.status} value={measurement.value} "
        f"unit={measurement.unit} source={measurement.source}"
    )


def render_measured_report(report: MeasuredComparisonReport) -> str:
    """Render only bounded aggregate evidence, fixed limits, and owner gates."""

    if not isinstance(report, MeasuredComparisonReport):
        raise ValueError("rendering requires a MeasuredComparisonReport")
    lines = [
        "# Measured route adequacy report",
        "",
        f"- schema: {report.schema}",
        f"- label set: {report.label_set_id}",
        f"- label fingerprint: {report.label_set_fingerprint}",
        f"- suite: {report.suite_name} v{report.suite_version}",
        f"- source revision: {report.source_revision}",
        f"- candidate: {report.candidate_id}",
        "- baseline: none",
        f"- environment fingerprint: {report.environment_fingerprint}",
        f"- environment hardware: {report.environment.hardware_profile}",
        f"- repetitions: {report.repetition_count}",
        f"- tasks: {report.task_count}",
        f"- samples: {report.sample_count}",
        f"- accepted: {report.accepted_count}",
        f"- rejected: {report.rejected_count}",
        f"- errors: {report.error_count}",
        f"- incomplete: {report.incomplete_count}",
        f"- complete: {str(report.complete).lower()}",
        f"- overall adequacy: {_render_measurement(report.overall_adequacy)}",
        f"- latency median: {_render_measurement(report.latency_median)}",
        f"- latency p95: {_render_measurement(report.latency_p95)}",
        f"- provider charge: {_render_measurement(report.provider_charge)}",
        f"- compute: {_render_measurement(report.compute)}",
        f"- energy: {_render_measurement(report.energy)}",
        f"- hardware: {_render_measurement(report.hardware)}",
        f"- downstream agent: {_render_measurement(report.downstream_agent)}",
        f"- tool: {_render_measurement(report.tool)}",
        f"- action: {_render_measurement(report.action)}",
        "- real task-outcome quality: not_measured",
        f"- authority: {report.authority}",
        "",
        "## Retained run fingerprints",
        "",
        *(f"- {fingerprint}" for fingerprint in report.run_fingerprints),
        "",
        "## Per-actual-route adequacy",
        "",
    ]
    for aggregate in report.per_actual_route:
        lines.append(
            f"- {aggregate.route_id}: samples={aggregate.sample_count} "
            f"accepted={aggregate.accepted_count} "
            f"rejected={aggregate.rejected_count} "
            f"incomplete={aggregate.incomplete_count} "
            f"adequacy={_render_measurement(aggregate.adequacy)}"
        )
    lines.extend(["", "## Fixed limitations", ""])
    lines.extend(f"- {code}" for code in report.limitations)
    lines.extend(["", "## Owner gates", "", "Owner evidence: blocked"])
    lines.extend(f"- {code}: blocked" for code in report.owner_gates)
    return "\n".join(lines) + "\n"


__all__ = [
    "CANDIDATE_ID",
    "EnvironmentEvidence",
    "LABEL_SCHEMA",
    "LIMITATION_CODES",
    "MIN_OWNER_TASKS",
    "MeasuredComparisonReport",
    "MeasuredRunBatch",
    "OWNER_GATE_CODES",
    "REPORT_SCHEMA",
    "RETAINED_REPETITIONS",
    "RouteAdequacyAggregate",
    "RouteLabelCase",
    "RouteLabelSet",
    "build_measured_report",
    "build_owner_route_suite",
    "ensure_owner_route_suite",
    "load_route_label_set",
    "measured_current_router_runner",
    "render_measured_report",
    "run_measured_comparison",
    "validate_measured_report_against_evidence",
]
