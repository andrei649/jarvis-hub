"""Strict owner-local route labels bound to E9 evaluation suites only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
    BenchmarkRunner,
    BenchmarkStore,
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
_MAX_RETAINED_RUNS = 1_000_000


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
        existing = store.runs(suite_name, last_n=_MAX_RETAINED_RUNS)
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
        if _has_incomplete_results(run):
            raise RuntimeError("measured retained run did not complete every case")
        run = replace(run, artifact_refs=artifact_refs)
        expected_fingerprint = run_fingerprint(run)
        store.record_run(run)

        matches = tuple(
            candidate
            for candidate in store.runs(
                suite_name,
                last_n=_MAX_RETAINED_RUNS,
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


__all__ = [
    "CANDIDATE_ID",
    "LABEL_SCHEMA",
    "MIN_OWNER_TASKS",
    "MeasuredRunBatch",
    "REPORT_SCHEMA",
    "RETAINED_REPETITIONS",
    "RouteLabelCase",
    "RouteLabelSet",
    "build_owner_route_suite",
    "ensure_owner_route_suite",
    "load_route_label_set",
    "measured_current_router_runner",
    "run_measured_comparison",
]
