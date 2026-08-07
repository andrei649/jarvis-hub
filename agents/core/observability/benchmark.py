"""Nerva E9.0 versioned, evaluation-only benchmark contracts.

This module is the single canonical implementation. It composes the existing
offline EvalHarness, retains bounded evidence, binds every stored result to the
immutable suite-case content it evaluated, and has no production-routing or
privileged-action authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agents.core.paths import data_path

from .eval import EvalCase, EvalHarness

BenchmarkLane = Literal["ci", "local", "cloud"]
PrivacyClass = Literal["synthetic_public", "sanitized_public", "owner_private_local"]
ResultStatus = Literal["passed", "failed", "unscored", "error"]
MeasurementStatus = Literal["measured", "not_measured", "not_applicable", "failed"]
PrivacyEffect = Literal[
    "no_external_disclosure",
    "sanitized_before_external_use",
    "local_only",
    "unknown",
]

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_SUITE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_UNIT_RE = re.compile(r"[a-z][a-z0-9._/-]{0,31}\Z")
_EXCEPTION_TYPE_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63}){0,3}\Z"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_MAX_VERSION = 1_000_000
_EVAL_PASS_THRESHOLD = 0.5
_PRIVACY_EFFECTS = {
    "no_external_disclosure",
    "sanitized_before_external_use",
    "local_only",
    "unknown",
}
_EVIDENCE_FIELDS = (
    "route_id",
    "model_id",
    "provider_id",
    "host_id",
    "hardware_profile",
    "response_digest",
    "response_length",
    "artifact_refs",
)
_MEASUREMENT_FIELDS = {"status", "value", "unit", "source"}
_RESULT_FIELDS = {
    "case_id",
    "task_type",
    "privacy_class",
    "status",
    "passed",
    "candidate",
    "baseline",
    "quality",
    "baseline_quality",
    "latency",
    "cost",
    "reliability",
    "privacy",
    "resources",
    "error_type",
    "baseline_error_type",
    "case_fingerprint",
}


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical lowercase identifier")
    return value


def _suite_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or _SUITE_RE.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ValueError("suite name must be a bounded path-free identifier")
    return value


def _version(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_VERSION
    ):
        raise ValueError("suite version must be a bounded positive integer")
    return value


def _finite(value: object, label: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite non-negative number")
    number = float(value)
    if (
        not math.isfinite(number)
        or number < 0
        or (maximum is not None and number > maximum)
    ):
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("benchmark timestamps must be canonical UTC RFC 3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("benchmark timestamps must be canonical UTC RFC 3339") from exc
    canonical = (
        parsed.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    if value != canonical:
        raise ValueError("benchmark timestamps must use millisecond precision")
    return parsed


def _source_revision(value: object) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ValueError("source revision must be an exact lowercase Git commit SHA")
    return value


def _strict_keys(raw: Mapping[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError(f"{label} fields do not match the versioned schema")


def _artifact(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError("artifact references must be bounded single-line strings")
    return value


def _source(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_RE.fullmatch(value) is None:
        raise ValueError("measurement source must be a bounded canonical identifier")
    return value


def _unit(value: object) -> str:
    if not isinstance(value, str) or _UNIT_RE.fullmatch(value) is None:
        raise ValueError("measurement unit must be a bounded canonical identifier")
    return value


def _exception_type(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 255
        or _EXCEPTION_TYPE_RE.fullmatch(value) is None
    ):
        raise ValueError(f"{label} must be a canonical exception class identifier")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _direct_child(base: Path, child: str) -> Path:
    resolved_base = os.path.realpath(os.fspath(base))
    candidate = os.path.realpath(os.path.join(resolved_base, child))
    if os.path.dirname(candidate) != resolved_base:
        raise ValueError("benchmark path must remain inside the store root")
    return Path(candidate)


@dataclass(frozen=True)
class Measurement:
    status: MeasurementStatus
    value: Any = None
    unit: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "measured",
            "not_measured",
            "not_applicable",
            "failed",
        }:
            raise ValueError("unsupported measurement status")
        if self.status == "measured":
            if self.value is None or self.unit is None or self.source is None:
                raise ValueError("measured evidence requires value, unit and source")
            if isinstance(self.value, bool):
                raise ValueError("measured evidence cannot use a boolean value")
            _unit(self.unit)
            _source(self.source)
            if isinstance(self.value, (int, float)):
                _finite(
                    self.value,
                    "measurement",
                    maximum=1 if self.unit == "ratio" else None,
                )
            elif not isinstance(self.value, str):
                raise ValueError("measured evidence must use a scalar value")
        elif self.value is not None:
            raise ValueError("unmeasured evidence cannot carry a value")
        elif self.status == "failed":
            if self.unit is not None:
                raise ValueError("failed evidence cannot claim a unit")
            if self.source is None:
                raise ValueError("failed evidence requires a source")
            _source(self.source)
        elif self.unit is not None or self.source is not None:
            raise ValueError("unknown evidence cannot claim a unit or source")

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        label: str = "measurement",
    ) -> Measurement:
        _strict_keys(raw, _MEASUREMENT_FIELDS, label)
        return cls(
            status=raw["status"],
            value=raw["value"],
            unit=raw["unit"],
            source=raw["source"],
        )


@dataclass(frozen=True)
class ResourceMeasurement:
    name: str
    measurement: Measurement

    def __post_init__(self) -> None:
        _identifier(self.name, "resource name")
        if not isinstance(self.measurement, Measurement):
            raise ValueError("resource evidence must use Measurement")
        if self.measurement.status == "measured":
            _finite(self.measurement.value, f"resource {self.name}")
        elif self.measurement.status == "failed" and self.measurement.unit is not None:
            raise ValueError("failed resource evidence cannot claim a unit")


@dataclass(frozen=True)
class BenchmarkCriterion:
    kind: Literal["contains", "exact"]
    expected: str

    def __post_init__(self) -> None:
        if self.kind not in {"contains", "exact"}:
            raise ValueError("unsupported benchmark criterion")
        if (
            not isinstance(self.expected, str)
            or not self.expected
            or len(self.expected) > 10_000
        ):
            raise ValueError("criterion expectation must be bounded and non-empty")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkCriterion:
        _strict_keys(raw, {"kind", "expected"}, "benchmark criterion")
        return cls(kind=raw["kind"], expected=raw["expected"])


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    task_type: str
    input_text: str
    privacy_class: PrivacyClass
    allowed_lanes: tuple[BenchmarkLane, ...]
    criterion: BenchmarkCriterion | None = None
    tags: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    schema: str = field(default="nerva.benchmark.v1", init=False)
    kind: str = field(default="case", init=False)

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case id")
        _identifier(self.task_type, "task type")
        if (
            not isinstance(self.input_text, str)
            or not self.input_text
            or len(self.input_text) > 100_000
        ):
            raise ValueError("benchmark input must be bounded and non-empty")
        if self.privacy_class not in {
            "synthetic_public",
            "sanitized_public",
            "owner_private_local",
        }:
            raise ValueError("unsupported benchmark privacy class")
        if not isinstance(self.allowed_lanes, tuple) or not self.allowed_lanes:
            raise ValueError("allowed lanes must be a non-empty tuple")
        if len(set(self.allowed_lanes)) != len(self.allowed_lanes):
            raise ValueError("allowed lanes must be unique")
        if any(lane not in {"ci", "local", "cloud"} for lane in self.allowed_lanes):
            raise ValueError("unsupported benchmark lane")
        if (
            self.privacy_class == "owner_private_local"
            and self.allowed_lanes != ("local",)
        ):
            raise ValueError("owner-private cases are local-only")
        if self.criterion is not None and not isinstance(
            self.criterion, BenchmarkCriterion
        ):
            raise ValueError("benchmark criterion must use the typed schema")
        if not isinstance(self.tags, tuple) or not isinstance(
            self.artifact_refs, tuple
        ):
            raise ValueError("case tags and artifact references must be tuples")
        for tag in self.tags:
            _identifier(tag, "tag")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("benchmark tags must be unique")
        for ref in self.artifact_refs:
            _artifact(ref)

    @property
    def input_digest(self) -> str:
        return hashlib.sha256(self.input_text.encode("utf-8")).hexdigest()

    @property
    def content_fingerprint(self) -> str:
        """Bind retained evidence to all immutable case semantics."""

        content = {
            "schema": self.schema,
            "kind": self.kind,
            "case_id": self.case_id,
            "task_type": self.task_type,
            "input_digest": self.input_digest,
            "privacy_class": self.privacy_class,
            "allowed_lanes": list(self.allowed_lanes),
            "criterion": asdict(self.criterion) if self.criterion is not None else None,
            "tags": list(self.tags),
            "artifact_refs": list(self.artifact_refs),
        }
        encoded = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def enforce_lane(self, lane: BenchmarkLane) -> None:
        if lane not in self.allowed_lanes:
            raise PermissionError(
                f"case {self.case_id!r} with privacy class "
                f"{self.privacy_class!r} cannot run in {lane!r}"
            )

    def to_dict(self, *, lane: BenchmarkLane | None = None) -> dict[str, Any]:
        if self.privacy_class == "owner_private_local" and lane is None:
            raise PermissionError(
                "owner-private cases require an explicit local serialization lane"
            )
        if lane is not None:
            self.enforce_lane(lane)
        payload = asdict(self)
        payload["input_digest"] = self.input_digest
        payload["content_fingerprint"] = self.content_fingerprint
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkCase:
        _strict_keys(
            raw,
            {
                "case_id",
                "task_type",
                "input_text",
                "privacy_class",
                "allowed_lanes",
                "criterion",
                "tags",
                "artifact_refs",
                "schema",
                "kind",
                "input_digest",
                "content_fingerprint",
            },
            "benchmark case",
        )
        if raw["schema"] != "nerva.benchmark.v1" or raw["kind"] != "case":
            raise ValueError("unsupported benchmark case schema")
        criterion_raw = raw["criterion"]
        criterion = (
            BenchmarkCriterion.from_dict(criterion_raw)
            if criterion_raw is not None
            else None
        )
        case = cls(
            case_id=raw["case_id"],
            task_type=raw["task_type"],
            input_text=raw["input_text"],
            privacy_class=raw["privacy_class"],
            allowed_lanes=tuple(raw["allowed_lanes"]),
            criterion=criterion,
            tags=tuple(raw["tags"]),
            artifact_refs=tuple(raw["artifact_refs"]),
        )
        if raw["input_digest"] != case.input_digest:
            raise ValueError("benchmark case input digest mismatch")
        if raw["content_fingerprint"] != case.content_fingerprint:
            raise ValueError("benchmark case content fingerprint mismatch")
        return case


@dataclass(frozen=True)
class BenchmarkObservation:
    """Raw output; response text is scored but omitted from retained run evidence."""

    response: str
    route_id: str
    model_id: str | None = None
    provider_id: str | None = None
    host_id: str | None = None
    hardware_profile: str | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    reliability: float | None = None
    privacy_effect: PrivacyEffect = "unknown"
    resources: tuple[ResourceMeasurement, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.response, str):
            raise ValueError("benchmark response must be text")
        _identifier(self.route_id, "route id")
        for label, value in (
            ("model id", self.model_id),
            ("provider id", self.provider_id),
            ("host id", self.host_id),
            ("hardware profile", self.hardware_profile),
        ):
            if value is not None:
                _identifier(value, label)
        if self.latency_ms is not None:
            _finite(self.latency_ms, "latency")
        if self.cost_usd is not None:
            _finite(self.cost_usd, "cost")
        if self.reliability is not None:
            _finite(self.reliability, "reliability", maximum=1)
        if self.privacy_effect not in _PRIVACY_EFFECTS:
            raise ValueError("unsupported privacy effect")
        if not isinstance(self.resources, tuple) or any(
            not isinstance(item, ResourceMeasurement) for item in self.resources
        ):
            raise ValueError("resource measurements must use the typed schema")
        names = [item.name for item in self.resources]
        if len(set(names)) != len(names):
            raise ValueError("resource measurements must be unique")
        if not isinstance(self.artifact_refs, tuple):
            raise ValueError("artifact references must be a tuple")
        for ref in self.artifact_refs:
            _artifact(ref)

    def retained_evidence(self) -> BenchmarkEvidence:
        return BenchmarkEvidence(
            route_id=self.route_id,
            model_id=self.model_id,
            provider_id=self.provider_id,
            host_id=self.host_id,
            hardware_profile=self.hardware_profile,
            response_digest=hashlib.sha256(
                self.response.encode("utf-8")
            ).hexdigest(),
            response_length=len(self.response),
            artifact_refs=self.artifact_refs,
        )


@dataclass(frozen=True)
class BenchmarkEvidence(Mapping[str, Any]):
    route_id: str
    model_id: str | None
    provider_id: str | None
    host_id: str | None
    hardware_profile: str | None
    response_digest: str
    response_length: int
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.route_id, "route id")
        for label, value in (
            ("model id", self.model_id),
            ("provider id", self.provider_id),
            ("host id", self.host_id),
            ("hardware profile", self.hardware_profile),
        ):
            if value is not None:
                _identifier(value, label)
        _digest(self.response_digest, "response digest")
        if (
            isinstance(self.response_length, bool)
            or not isinstance(self.response_length, int)
            or self.response_length < 0
        ):
            raise ValueError("response length must be a non-negative integer")
        if not isinstance(self.artifact_refs, tuple):
            raise ValueError("artifact references must be a tuple")
        for ref in self.artifact_refs:
            _artifact(ref)

    def __getitem__(self, key: str) -> Any:
        if key not in _EVIDENCE_FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(_EVIDENCE_FIELDS)

    def __len__(self) -> int:
        return len(_EVIDENCE_FIELDS)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkEvidence:
        _strict_keys(raw, set(_EVIDENCE_FIELDS), "benchmark evidence")
        return cls(
            route_id=raw["route_id"],
            model_id=raw["model_id"],
            provider_id=raw["provider_id"],
            host_id=raw["host_id"],
            hardware_profile=raw["hardware_profile"],
            response_digest=raw["response_digest"],
            response_length=raw["response_length"],
            artifact_refs=tuple(raw["artifact_refs"]),
        )


BenchmarkRunner = Callable[[str], Awaitable[BenchmarkObservation]]


def _validate_ratio(
    measurement: Measurement,
    label: str,
    *,
    statuses: set[str],
) -> None:
    if not isinstance(measurement, Measurement):
        raise ValueError(f"{label} evidence must use Measurement")
    if measurement.status not in statuses:
        raise ValueError(f"{label} has an inconsistent measurement status")
    if measurement.status == "measured":
        if measurement.unit != "ratio":
            raise ValueError(f"{label} must use ratio units")
        _finite(measurement.value, label, maximum=1)


def _validate_numeric_measurement(
    measurement: Measurement,
    label: str,
    unit: str,
    *,
    statuses: set[str],
) -> None:
    if not isinstance(measurement, Measurement):
        raise ValueError(f"{label} evidence must use Measurement")
    if measurement.status not in statuses:
        raise ValueError(f"{label} has an inconsistent measurement status")
    if measurement.status == "measured":
        if measurement.unit != unit:
            raise ValueError(f"{label} must use {unit} units")
        _finite(measurement.value, label)


def _validate_privacy(
    measurement: Measurement,
    *,
    statuses: set[str],
) -> None:
    if not isinstance(measurement, Measurement):
        raise ValueError("privacy evidence must use Measurement")
    if measurement.status not in statuses:
        raise ValueError("privacy has an inconsistent measurement status")
    if (
        measurement.status == "measured"
        and (
            measurement.unit != "classification"
            or measurement.value not in _PRIVACY_EFFECTS
        )
    ):
        raise ValueError("privacy must use a supported classification")


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    task_type: str
    privacy_class: PrivacyClass
    status: ResultStatus
    passed: bool | None
    candidate: BenchmarkEvidence | None
    baseline: BenchmarkEvidence | None
    quality: Measurement
    baseline_quality: Measurement
    latency: Measurement
    cost: Measurement
    reliability: Measurement
    privacy: Measurement
    resources: tuple[ResourceMeasurement, ...] = ()
    error_type: str | None = None
    baseline_error_type: str | None = None
    case_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case id")
        _identifier(self.task_type, "task type")
        if self.privacy_class not in {
            "synthetic_public",
            "sanitized_public",
            "owner_private_local",
        }:
            raise ValueError("unsupported benchmark privacy class")
        if self.status not in {"passed", "failed", "unscored", "error"}:
            raise ValueError("unsupported benchmark result status")
        if self.case_fingerprint is not None:
            _digest(self.case_fingerprint, "case fingerprint")
        if self.candidate is not None and not isinstance(
            self.candidate, BenchmarkEvidence
        ):
            raise ValueError("candidate evidence must use the strict retained schema")
        if self.baseline is not None and not isinstance(
            self.baseline, BenchmarkEvidence
        ):
            raise ValueError("baseline evidence must use the strict retained schema")
        if not isinstance(self.resources, tuple) or any(
            not isinstance(item, ResourceMeasurement) for item in self.resources
        ):
            raise ValueError("resources must use the typed resource schema")
        resource_names = [item.name for item in self.resources]
        if len(set(resource_names)) != len(resource_names):
            raise ValueError("resource measurements must be unique")

        if self.status == "passed":
            if self.passed is not True:
                raise ValueError("passed results require passed=true")
            if self.candidate is None:
                raise ValueError("non-error results require candidate evidence")
            _validate_ratio(self.quality, "quality", statuses={"measured"})
        elif self.status == "failed":
            if self.passed is not False:
                raise ValueError("failed results require passed=false")
            if self.candidate is None:
                raise ValueError("non-error results require candidate evidence")
            _validate_ratio(self.quality, "quality", statuses={"measured"})
        elif self.status == "unscored":
            if self.passed is not None:
                raise ValueError("unscored results cannot claim pass or fail")
            if self.candidate is None:
                raise ValueError("non-error results require candidate evidence")
            _validate_ratio(self.quality, "quality", statuses={"not_measured"})
        else:
            if self.passed is not None:
                raise ValueError("error results cannot claim pass or fail")
            if self.candidate is not None:
                raise ValueError("error results cannot claim candidate evidence")
            _validate_ratio(self.quality, "quality", statuses={"failed"})

        if self.status in {"passed", "failed"}:
            score_passed = float(self.quality.value) >= _EVAL_PASS_THRESHOLD
            if score_passed != (self.status == "passed"):
                raise ValueError(
                    "result status and pass flag must agree with measured quality "
                    "at the EvalHarness pass threshold"
                )

        if self.error_type is not None:
            _exception_type(self.error_type, "error type")
        if self.status == "error" and self.error_type is None:
            raise ValueError("error results require a sanitized exception type")
        if self.status != "error" and self.error_type is not None:
            raise ValueError("only error results can retain an error type")

        if self.baseline_error_type is not None:
            _exception_type(self.baseline_error_type, "baseline error type")
            if self.baseline is not None or self.baseline_quality.status != "failed":
                raise ValueError(
                    "baseline errors require absent evidence and failed quality"
                )
        if (
            self.baseline_quality.status == "failed"
            and self.baseline_error_type is None
        ):
            raise ValueError(
                "failed baseline quality requires a sanitized exception type"
            )
        if self.baseline is not None and self.baseline_error_type is not None:
            raise ValueError(
                "baseline evidence and baseline error are mutually exclusive"
            )

        if self.baseline is None:
            allowed_baseline = {"not_applicable", "failed"}
            if self.status == "error":
                allowed_baseline.add("not_measured")
            _validate_ratio(
                self.baseline_quality,
                "baseline quality",
                statuses=allowed_baseline,
            )
        elif self.status in {"passed", "failed"}:
            _validate_ratio(
                self.baseline_quality,
                "baseline quality",
                statuses={"measured"},
            )
        elif self.status == "unscored":
            _validate_ratio(
                self.baseline_quality,
                "baseline quality",
                statuses={"not_measured"},
            )
        else:
            raise ValueError("error results cannot retain baseline evidence")

        if self.status == "error":
            _validate_numeric_measurement(
                self.latency,
                "latency",
                "ms",
                statuses={"failed"},
            )
            _validate_numeric_measurement(
                self.cost,
                "cost",
                "usd",
                statuses={"not_measured", "not_applicable"},
            )
            _validate_ratio(
                self.reliability,
                "reliability",
                statuses={"measured", "not_measured", "failed"},
            )
            _validate_privacy(
                self.privacy,
                statuses={"failed", "not_measured"},
            )
        else:
            _validate_numeric_measurement(
                self.latency,
                "latency",
                "ms",
                statuses={"measured"},
            )
            _validate_numeric_measurement(
                self.cost,
                "cost",
                "usd",
                statuses={"measured", "not_measured"},
            )
            _validate_ratio(
                self.reliability,
                "reliability",
                statuses={"measured", "not_measured"},
            )
            _validate_privacy(self.privacy, statuses={"measured"})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkResult:
        _strict_keys(raw, _RESULT_FIELDS, "benchmark result")

        def measurement(key: str) -> Measurement:
            value = raw[key]
            if not isinstance(value, Mapping):
                raise ValueError(f"{key} evidence must use the versioned schema")
            return Measurement.from_dict(value, label=key)

        raw_resources = raw["resources"]
        if not isinstance(raw_resources, list):
            raise ValueError("resources must use the versioned schema")
        resources: list[ResourceMeasurement] = []
        for item in raw_resources:
            _strict_keys(item, {"name", "measurement"}, "resource measurement")
            resources.append(
                ResourceMeasurement(
                    name=item["name"],
                    measurement=Measurement.from_dict(
                        item["measurement"],
                        label="resource measurement",
                    ),
                )
            )
        return cls(
            case_id=raw["case_id"],
            task_type=raw["task_type"],
            privacy_class=raw["privacy_class"],
            status=raw["status"],
            passed=raw["passed"],
            candidate=(
                BenchmarkEvidence.from_dict(raw["candidate"])
                if raw["candidate"] is not None
                else None
            ),
            baseline=(
                BenchmarkEvidence.from_dict(raw["baseline"])
                if raw["baseline"] is not None
                else None
            ),
            quality=measurement("quality"),
            baseline_quality=measurement("baseline_quality"),
            latency=measurement("latency"),
            cost=measurement("cost"),
            reliability=measurement("reliability"),
            privacy=measurement("privacy"),
            resources=tuple(resources),
            error_type=raw["error_type"],
            baseline_error_type=raw["baseline_error_type"],
            case_fingerprint=raw["case_fingerprint"],
        )


@dataclass(frozen=True)
class BenchmarkRun:
    suite_name: str
    suite_version: int
    lane: BenchmarkLane
    run_id: str
    started_at: str
    finished_at: str
    source_revision: str
    candidate_id: str
    baseline_id: str | None
    results: tuple[BenchmarkResult, ...]
    artifact_refs: tuple[str, ...] = ()
    schema: str = field(default="nerva.benchmark.v1", init=False)
    kind: str = field(default="run", init=False)
    authority: str = field(default="evaluation_only", init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _suite_name(self.suite_name)
        _version(self.suite_version)
        if self.lane not in {"ci", "local", "cloud"}:
            raise ValueError("unsupported benchmark lane")
        _identifier(self.run_id, "run id")
        started = _validate_timestamp(self.started_at)
        finished = _validate_timestamp(self.finished_at)
        if finished < started:
            raise ValueError("benchmark finish time cannot precede start time")
        _source_revision(self.source_revision)
        _identifier(self.candidate_id, "candidate id")
        if self.baseline_id is not None:
            _identifier(self.baseline_id, "baseline id")
        if not isinstance(self.results, tuple) or not self.results:
            raise ValueError("benchmark runs require at least one result")
        if any(not isinstance(result, BenchmarkResult) for result in self.results):
            raise ValueError("benchmark runs require typed results")
        if len({result.case_id for result in self.results}) != len(self.results):
            raise ValueError("benchmark result case ids must be unique")
        if not isinstance(self.artifact_refs, tuple):
            raise ValueError("artifact references must be a tuple")
        for ref in self.artifact_refs:
            _artifact(ref)

        for result in self.results:
            if result.status == "error" and (
                result.baseline is not None
                or result.baseline_error_type is not None
                or result.baseline_quality.status != "not_measured"
            ):
                raise ValueError(
                    "candidate-error runs require an explicitly unmeasured "
                    "skipped baseline"
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

    @property
    def summary(self) -> dict[str, Any]:
        candidate = [
            float(result.quality.value)
            for result in self.results
            if result.quality.status == "measured"
        ]
        baseline = [
            float(result.baseline_quality.value)
            for result in self.results
            if result.baseline_quality.status == "measured"
        ]
        return {
            "total": len(self.results),
            "scored": len(candidate),
            "passed": sum(result.status == "passed" for result in self.results),
            "failed": sum(result.status == "failed" for result in self.results),
            "unscored": sum(
                result.status == "unscored" for result in self.results
            ),
            "errors": sum(result.status == "error" for result in self.results),
            "quality_mean": (
                round(sum(candidate) / len(candidate), 6) if candidate else None
            ),
            "baseline_quality_mean": (
                round(sum(baseline) / len(baseline), 6) if baseline else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> BenchmarkRun:
        def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, value in pairs:
                if key in parsed:
                    raise ValueError("benchmark run must not contain duplicate JSON keys")
                parsed[key] = value
            return parsed

        try:
            raw = json.loads(payload, object_pairs_hook=_object)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("benchmark run must be valid JSON") from exc
        _strict_keys(
            raw,
            {
                "suite_name",
                "suite_version",
                "lane",
                "run_id",
                "started_at",
                "finished_at",
                "source_revision",
                "candidate_id",
                "baseline_id",
                "results",
                "artifact_refs",
                "schema",
                "kind",
                "authority",
                "can_change_routing",
                "can_authorize",
                "can_execute",
                "can_mark_complete",
                "summary",
            },
            "benchmark run",
        )
        if raw["schema"] != "nerva.benchmark.v1" or raw["kind"] != "run":
            raise ValueError("unsupported benchmark run schema")
        immutable = {
            "authority": "evaluation_only",
            "can_change_routing": False,
            "can_authorize": False,
            "can_execute": False,
            "can_mark_complete": False,
        }
        if (
            raw["authority"] != immutable["authority"]
            or any(type(raw[key]) is not bool or raw[key] is not False for key in (
                "can_change_routing",
                "can_authorize",
                "can_execute",
                "can_mark_complete",
            ))
        ):
            raise ValueError("benchmark authority flags are immutable")
        if not isinstance(raw["results"], list):
            raise ValueError("benchmark results must use the versioned schema")
        run = cls(
            suite_name=raw["suite_name"],
            suite_version=raw["suite_version"],
            lane=raw["lane"],
            run_id=raw["run_id"],
            started_at=raw["started_at"],
            finished_at=raw["finished_at"],
            source_revision=raw["source_revision"],
            candidate_id=raw["candidate_id"],
            baseline_id=raw["baseline_id"],
            results=tuple(
                BenchmarkResult.from_dict(item) for item in raw["results"]
            ),
            artifact_refs=tuple(raw["artifact_refs"]),
        )
        if raw["summary"] != run.summary:
            raise ValueError("benchmark summary mismatch")
        return run

    @property
    def structure_fingerprint(self) -> str:
        structure = {
            "suite": [self.suite_name, self.suite_version, self.lane],
            "targets": [self.candidate_id, self.baseline_id],
            "results": [
                {
                    "case_id": result.case_id,
                    "task_type": result.task_type,
                    "privacy_class": result.privacy_class,
                    "case_fingerprint_present": result.case_fingerprint is not None,
                    "candidate_fields": sorted(
                        (result.candidate or {}).keys()
                    ),
                    "baseline_fields": sorted(
                        (result.baseline or {}).keys()
                    ),
                    "measurement_fields": [
                        "quality",
                        "baseline_quality",
                        "latency",
                        "cost",
                        "reliability",
                        "privacy",
                    ],
                    "resources": [item.name for item in result.resources],
                }
                for result in self.results
            ],
        }
        encoded = json.dumps(
            structure,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class BenchmarkStore:
    """Versioned suites plus append-only positive, negative and failed evidence."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else data_path("benchmarks")
        self.suites_dir = self.root / "suites"

    def _suite_dir(self, name: str) -> Path:
        return _direct_child(self.suites_dir, _suite_name(name))

    def _version_file(self, name: str, version: int) -> Path:
        return _direct_child(
            self._suite_dir(name),
            f"v{_version(version)}.jsonl",
        )

    def _runs_file(self, name: str) -> Path:
        return _direct_child(self._suite_dir(name), "runs.jsonl")

    def versions(self, name: str) -> list[int]:
        directory = self._suite_dir(name)
        if not directory.exists():
            return []
        versions: list[int] = []
        for path in directory.glob("v*.jsonl"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                versions.append(_version(int(path.stem[1:])))
            except ValueError:
                continue
        return sorted(versions)

    def save_suite(
        self,
        name: str,
        cases: Sequence[BenchmarkCase],
        *,
        lane: BenchmarkLane,
    ) -> int:
        if not cases or len({case.case_id for case in cases}) != len(cases):
            raise ValueError("benchmark suites require unique cases")
        for case in cases:
            if not isinstance(case, BenchmarkCase):
                raise ValueError("benchmark suites require typed cases")
            case.enforce_lane(lane)
        directory = self._suite_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        versions = self.versions(name)
        version = (versions[-1] if versions else 0) + 1
        with self._version_file(name, version).open(
            "x",
            encoding="utf-8",
        ) as handle:
            for case in cases:
                handle.write(
                    json.dumps(
                        case.to_dict(lane=lane),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        return version

    def load_suite(
        self,
        name: str,
        version: int,
    ) -> tuple[BenchmarkCase, ...]:
        path = self._version_file(name, version)
        if not path.exists():
            return ()
        return tuple(
            BenchmarkCase.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def record_run(self, run: BenchmarkRun) -> None:
        if not isinstance(run, BenchmarkRun):
            raise ValueError("run evidence must use BenchmarkRun")
        cases = self.load_suite(run.suite_name, run.suite_version)
        if not cases:
            raise ValueError("cannot record a run for a missing suite version")
        for case in cases:
            case.enforce_lane(run.lane)
        expected = {case.case_id: case for case in cases}
        actual = {result.case_id: result for result in run.results}
        if set(actual) != set(expected):
            raise ValueError("run results must cover the suite case ids exactly")
        for case_id, result in actual.items():
            case = expected[case_id]
            if (
                result.task_type != case.task_type
                or result.privacy_class != case.privacy_class
            ):
                raise ValueError(
                    "run result metadata must match the stored suite case"
                )
            if result.case_fingerprint != case.content_fingerprint:
                raise ValueError(
                    "run result fingerprint must match the stored suite case content"
                )
        directory = self._suite_dir(run.suite_name)
        directory.mkdir(parents=True, exist_ok=True)
        with self._runs_file(run.suite_name).open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(run.to_json() + "\n")

    def runs(
        self,
        name: str,
        *,
        last_n: int = 20,
    ) -> tuple[BenchmarkRun, ...]:
        if (
            isinstance(last_n, bool)
            or not isinstance(last_n, int)
            or last_n < 1
        ):
            raise ValueError("last_n must be a positive integer")
        path = self._runs_file(name)
        if not path.exists():
            return ()
        records = [
            BenchmarkRun.from_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return tuple(reversed(records[-last_n:]))


class BenchmarkHarness:
    def __init__(
        self,
        candidate: BenchmarkRunner,
        *,
        candidate_id: str,
        baseline: BenchmarkRunner | None = None,
        baseline_id: str | None = None,
    ) -> None:
        if not callable(candidate):
            raise ValueError("candidate must be callable")
        if baseline is not None and not callable(baseline):
            raise ValueError("baseline must be callable")
        self.candidate = candidate
        self.candidate_id = _identifier(candidate_id, "candidate id")
        self.baseline = baseline
        self.baseline_id = (
            _identifier(baseline_id, "baseline id")
            if baseline_id is not None
            else None
        )
        if (baseline is None) != (baseline_id is None):
            raise ValueError("baseline and baseline_id must be supplied together")

    async def run(
        self,
        cases: Sequence[BenchmarkCase],
        *,
        suite_name: str,
        suite_version: int,
        lane: BenchmarkLane,
        source_revision: str,
        run_id: str | None = None,
        now: Callable[[], str] = _now,
    ) -> BenchmarkRun:
        if not cases or len({case.case_id for case in cases}) != len(cases):
            raise ValueError("benchmark runs require unique cases")
        for case in cases:
            if not isinstance(case, BenchmarkCase):
                raise ValueError("benchmark runs require typed cases")
            case.enforce_lane(lane)
        started_at = now()
        results = tuple([await self._run_case(case) for case in cases])
        return BenchmarkRun(
            suite_name=_suite_name(suite_name),
            suite_version=_version(suite_version),
            lane=lane,
            run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
            started_at=started_at,
            finished_at=now(),
            source_revision=_source_revision(source_revision),
            candidate_id=self.candidate_id,
            baseline_id=self.baseline_id,
            results=results,
        )

    async def _run_case(self, case: BenchmarkCase) -> BenchmarkResult:
        try:
            candidate = await self._observe(self.candidate, case.input_text)
        except Exception as exc:
            return BenchmarkResult(
                case_id=case.case_id,
                task_type=case.task_type,
                privacy_class=case.privacy_class,
                status="error",
                passed=None,
                candidate=None,
                baseline=None,
                quality=Measurement("failed", source="candidate.runner"),
                baseline_quality=Measurement("not_measured"),
                latency=Measurement("failed", source="candidate.runner"),
                cost=Measurement("not_measured"),
                reliability=Measurement(
                    "measured",
                    0.0,
                    "ratio",
                    "candidate.runner",
                ),
                privacy=Measurement("failed", source="candidate.runner"),
                error_type=type(exc).__name__,
                case_fingerprint=case.content_fingerprint,
            )

        baseline = None
        baseline_error = None
        if self.baseline is not None:
            try:
                baseline = await self._observe(
                    self.baseline,
                    case.input_text,
                )
            except Exception as exc:
                baseline_error = type(exc).__name__

        quality, passed, status = await _quality(case, candidate.response)
        if baseline is not None:
            baseline_quality, _, _ = await _quality(
                case,
                baseline.response,
            )
        elif self.baseline is None:
            baseline_quality = Measurement("not_applicable")
        else:
            baseline_quality = Measurement(
                "failed",
                source="baseline.runner",
            )

        return BenchmarkResult(
            case_id=case.case_id,
            task_type=case.task_type,
            privacy_class=case.privacy_class,
            status=status,
            passed=passed,
            candidate=candidate.retained_evidence(),
            baseline=baseline.retained_evidence() if baseline else None,
            quality=quality,
            baseline_quality=baseline_quality,
            latency=_measure(
                candidate.latency_ms,
                "ms",
                "benchmark.harness",
            ),
            cost=_measure(
                candidate.cost_usd,
                "usd",
                "candidate.runner",
            ),
            reliability=_measure(
                candidate.reliability,
                "ratio",
                "candidate.runner",
            ),
            privacy=Measurement(
                "measured",
                candidate.privacy_effect,
                "classification",
                "candidate.runner",
            ),
            resources=candidate.resources,
            baseline_error_type=baseline_error,
            case_fingerprint=case.content_fingerprint,
        )

    @staticmethod
    async def _observe(
        runner: BenchmarkRunner,
        prompt: str,
    ) -> BenchmarkObservation:
        started = time.perf_counter()
        observation = await runner(prompt)
        if not isinstance(observation, BenchmarkObservation):
            raise TypeError(
                "benchmark runners must return BenchmarkObservation"
            )
        if observation.latency_ms is None:
            observation = replace(
                observation,
                latency_ms=(time.perf_counter() - started) * 1_000,
            )
        return observation


async def _quality(
    case: BenchmarkCase,
    response: str,
) -> tuple[Measurement, bool | None, ResultStatus]:
    if case.criterion is None:
        return Measurement("not_measured"), None, "unscored"

    async def observed(_prompt: str) -> str:
        return response

    if case.criterion.kind == "contains":
        eval_case = EvalCase(
            case.case_id,
            case.input_text,
            expect_contains=case.criterion.expected,
        )
    else:
        expected = case.criterion.expected

        def exact(_prompt: str, actual: str) -> float:
            return 1.0 if actual.strip() == expected else 0.0

        eval_case = EvalCase(
            case.case_id,
            case.input_text,
            scorer=exact,
        )
    row = (await EvalHarness(observed).run([eval_case]))["results"][0]
    passed = bool(row["passed"])
    return (
        Measurement(
            "measured",
            float(row["score"]),
            "ratio",
            "observability.eval.EvalHarness",
        ),
        passed,
        "passed" if passed else "failed",
    )


def _measure(
    value: float | None,
    unit: str,
    source: str,
) -> Measurement:
    if value is None:
        return Measurement("not_measured")
    return Measurement(
        "measured",
        _finite(value, unit),
        unit,
        source,
    )


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
    if not callable(getattr(router, "classify_deterministic", None)):
        raise TypeError(
            "current-router deterministic adapter requires classify_deterministic"
        )


def current_router_runner(
    router: Any,
    agents: Mapping[str, Any],
    *,
    host_id: str = "in-process",
) -> BenchmarkRunner:
    """Observe only the current router's deterministic path.

    Configured or subsequently injected LLM fallback fails before classification.
    Unexpected fallback provenance is rejected instead of being mislabeled as
    local, free, and private.
    """

    _identifier(host_id, "host id")
    if not isinstance(agents, Mapping):
        raise ValueError("agents must be a mapping")
    _require_deterministic_router(router)
    classify_deterministic = router.classify_deterministic

    async def run(prompt: str) -> BenchmarkObservation:
        _require_deterministic_router(router)
        intent = await classify_deterministic(prompt, dict(agents))
        context = getattr(intent, "context", {})
        if not isinstance(context, Mapping):
            raise RuntimeError(
                "current-router deterministic adapter requires inspectable provenance"
            )
        if context.get("source") in {"llm", "llm_fallback"}:
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


class KeywordRouteBaseline:
    """Transparent exact-token/phrase baseline for router comparisons."""

    def __init__(
        self,
        rules: Mapping[str, str],
        *,
        fallback_route: str = "jarvis",
    ) -> None:
        if not isinstance(rules, Mapping) or not rules:
            raise ValueError("keyword baseline requires at least one rule")
        self.rules = tuple(
            (
                phrase.casefold().strip(),
                _identifier(route, "baseline route"),
            )
            for phrase, route in rules.items()
        )
        if any(not phrase for phrase, _ in self.rules):
            raise ValueError("baseline phrases must be non-empty")
        self.fallback_route = _identifier(
            fallback_route,
            "fallback route",
        )

    async def __call__(self, prompt: str) -> BenchmarkObservation:
        if not isinstance(prompt, str):
            raise ValueError("benchmark prompt must be text")
        normalized = " ".join(prompt.casefold().split())
        route_id = self.fallback_route
        for phrase, candidate in self.rules:
            if re.search(
                rf"(?<!\w){re.escape(phrase)}(?!\w)",
                normalized,
            ):
                route_id = candidate
                break
        return BenchmarkObservation(
            response=route_id,
            route_id=route_id,
            model_id="keyword-baseline.v1",
            provider_id="local-deterministic",
            host_id="in-process",
            hardware_profile="not-applicable",
            cost_usd=0.0,
            reliability=1.0,
            privacy_effect="no_external_disclosure",
        )


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
