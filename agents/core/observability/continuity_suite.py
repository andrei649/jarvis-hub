"""Continuity Core (#731) evaluation suite on the accepted E9.0 benchmark harness.

``docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md`` maps #731's evaluation suite
onto the accepted ``nerva.benchmark.v1`` store as a separately scoped
``evaluation_only`` suite package. This module is that package.

Each case is a synthetic-public *scenario*: a bounded sequence of memory events
(observe / correct / forget / restart / identity governance) followed by one
question. The prompt handed to the E9.0 harness is the scenario's canonical
JSON; the criterion is an exact expected answer. A ``ContinuitySubject`` is the
system under evaluation. The transparent in-process ``ReferenceContinuityMemory``
models the #731 semantics and ``NaiveRecallBaseline`` is the deliberately weak
comparison that admits everything, leaks across people, forgets on restart and
lies about purges — so the suite can visibly fail.

Authority is ``evaluation_only`` end to end. Nothing here imports the Action
Kernel, the approval queue or the promotion path; a passing run cannot mark any
epic accepted. Acceptance ownership of every metric stays with its destination
epic (E3/E6/E12 for recall, contradiction and abstention; E4 #1008 for identity;
E11 for migration parity), exactly as the reconciliation records.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from agents.core.observability.benchmark import (
    BenchmarkCase,
    BenchmarkCriterion,
    BenchmarkHarness,
    BenchmarkLane,
    BenchmarkObservation,
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkStore,
    PrivacyEffect,
)
from agents.core.observability.benchmark import (
    _identifier as _validate_identifier,
)
from agents.core.observability.benchmark import (
    _source_revision as _validate_exact_revision,
)
from agents.core.observability.benchmark import (
    _suite_name as _validate_suite_name,
)
from agents.core.observability.benchmark import (
    _version as _validate_version,
)
from agents.core.observability.scheduled_report import (
    # The E9.1 lane's step-summary append and atomic single-document write.
    _append,
    _write_document,
)

SUITE_NAME = "continuity-core-v1"
SCENARIO_SCHEMA = "nerva.continuity.scenario.v1"
REPORT_SCHEMA = "nerva.continuity.report.v1"
CANDIDATE_ID = "reference-continuity-memory.v1"
BASELINE_ID = "naive-recall-baseline.v1"
PRIVACY_CLASS = "synthetic_public"
ALLOWED_LANES: tuple[BenchmarkLane, ...] = ("ci", "local")
AUTHORITY = "evaluation_only"

#: Environment variables consulted, in order, when no revision is passed.
REVISION_ENV_VARS = ("NERVA_SOURCE_REVISION", "GITHUB_SHA")

Criterion = Literal[
    "multi-session-recall",
    "recall-precision-under-taint",
    "contradiction-retraction",
    "cross-person-leakage",
    "abstention-calibration",
    "identity-stability",
    "forget-purge-honesty",
]

#: #731 evaluation criteria and the epic that owns their *acceptance*. The suite
#: measures; it never accepts. Keys double as ``BenchmarkCase.task_type``.
CRITERIA: Mapping[str, str] = {
    "multi-session-recall": "E3 Episodes (#761)",
    "recall-precision-under-taint": "E3 admission reason (#761) + RISKS MEM-03/SEC-05",
    "contradiction-retraction": "E3.0 supersession + E6 Reflection",
    "cross-person-leakage": "RISKS PRIV-02 (E2 #760 primary)",
    "abstention-calibration": "E12 Hybrid Cognition (advisory only)",
    "identity-stability": "E4 Identity Manifest (#1008)",
    "forget-purge-honesty": "E3 tombstones + E11 migration parity",
}

EventOp = Literal[
    "observe", "correct", "forget", "restart",
    "identity_set", "identity_propose", "identity_approve",
]
Source = Literal["owner", "untrusted", "inferred"]
Ask = Literal["recall", "audit", "identity", "explain"]

_SOURCES = frozenset({"owner", "untrusted", "inferred"})
_ASKS = frozenset({"recall", "audit", "identity", "explain"})
_FACT_FIELDS = ("person", "subject", "predicate")
#: op -> (required fields, permitted fields). Anything else set is rejected.
_EVENT_SHAPE: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "observe": ((*_FACT_FIELDS, "value", "source"), (*_FACT_FIELDS, "value", "source")),
    "correct": ((*_FACT_FIELDS, "value", "source"), (*_FACT_FIELDS, "value", "source")),
    "forget": (_FACT_FIELDS, _FACT_FIELDS),
    "restart": ((), ()),
    "identity_set": (("key", "value"), ("key", "value")),
    "identity_propose": (("key", "value"), ("key", "value")),
    "identity_approve": (("key",), ("key",)),
}
_FACT_OPS = frozenset({"observe", "correct"})
_IDENTITY_VALUE_OPS = frozenset({"identity_set", "identity_propose"})
_EVENT_KEYS = ("op", "person", "subject", "predicate", "value", "source", "key")
_QUERY_KEYS = ("ask", "person", "subject", "predicate", "key")
_MAX_EVENTS = 64
_MAX_TEXT = 256

#: Answer vocabulary shared by subjects and expectations.
UNKNOWN = "unknown"
PURGED = "purged"
KNOWN = "known"
_SHA256_HEX_LENGTH = 64
_REPORT_GUARD = object()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _token(value: object, label: str) -> str:
    """A bounded single-line synthetic token. Never owner data."""

    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError(f"scenario {label} must be a bounded non-empty string")
    if value != value.strip() or any(ch in value for ch in "\r\n\t"):
        raise ValueError(f"scenario {label} must be a single trimmed line")
    return value


def _optional_token(value: object, label: str) -> str | None:
    return None if value is None else _token(value, label)


@dataclass(frozen=True)
class ScenarioEvent:
    """One memory event in a scenario."""

    op: EventOp
    person: str | None = None
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    source: Source | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        if self.op not in _EVENT_SHAPE:
            raise ValueError("unsupported scenario event op")
        required, permitted = _EVENT_SHAPE[self.op]
        for name in ("person", "subject", "predicate", "value", "source", "key"):
            value = getattr(self, name)
            if value is None:
                if name in required:
                    raise ValueError(f"{self.op} requires {name}")
                continue
            if name not in permitted:
                raise ValueError(f"{self.op} cannot carry {name}")
            if name == "source":
                if value not in _SOURCES:
                    raise ValueError("unsupported scenario event source")
            else:
                _token(value, name)

    @property
    def fact_key(self) -> tuple[str, str, str]:
        if self.person is None or self.subject is None or self.predicate is None:
            raise ValueError("event has no fact key")
        return (self.person, self.subject, self.predicate)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ScenarioEvent:
        if not isinstance(raw, Mapping) or not set(raw) <= set(_EVENT_KEYS):
            raise ValueError("scenario event fields do not match the versioned schema")
        return cls(**{name: raw.get(name) for name in _EVENT_KEYS})


@dataclass(frozen=True)
class ScenarioQuery:
    """The single question asked after the events."""

    ask: Ask
    person: str | None = None
    subject: str | None = None
    predicate: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        if self.ask not in _ASKS:
            raise ValueError("unsupported scenario query")
        for name in _QUERY_KEYS[1:]:
            _optional_token(getattr(self, name), name)
        fact = (self.person, self.subject, self.predicate)
        if self.ask == "identity":
            if self.key is None or any(item is not None for item in fact):
                raise ValueError("identity queries carry exactly a key")
        elif None in fact or self.key is not None:
            raise ValueError(f"{self.ask} queries require person, subject, predicate")

    @property
    def fact_key(self) -> tuple[str, str, str]:
        if self.person is None or self.subject is None or self.predicate is None:
            raise ValueError("query has no fact key")
        return (self.person, self.subject, self.predicate)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ScenarioQuery:
        if not isinstance(raw, Mapping) or not set(raw) <= set(_QUERY_KEYS):
            raise ValueError("scenario query fields do not match the versioned schema")
        return cls(**{name: raw.get(name) for name in _QUERY_KEYS})


@dataclass(frozen=True)
class ContinuityScenario:
    """A bounded, synthetic, canonical-JSON scenario bound to one #731 criterion."""

    scenario_id: str
    criterion: Criterion
    events: tuple[ScenarioEvent, ...]
    query: ScenarioQuery
    expected: str
    schema: str = field(default=SCENARIO_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.scenario_id, "scenario id")
        if self.criterion not in CRITERIA:
            raise ValueError("scenario criterion is not a #731 evaluation criterion")
        if not isinstance(self.events, tuple) or len(self.events) > _MAX_EVENTS:
            raise ValueError("scenario events must be a bounded tuple")
        if any(not isinstance(event, ScenarioEvent) for event in self.events):
            raise ValueError("scenario events must be typed")
        if not isinstance(self.query, ScenarioQuery):
            raise ValueError("scenario query must be typed")
        _token(self.expected, "expected answer")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [
            {key: value for key, value in asdict(event).items() if value is not None}
            for event in self.events
        ]
        payload["query"] = {
            key: value for key, value in asdict(self.query).items() if value is not None
        }
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, payload: str) -> ContinuityScenario:
        if not isinstance(payload, str) or len(payload) > 100_000:
            raise ValueError("scenario payload must be bounded text")
        try:
            raw = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("scenario payload must be valid JSON") from exc
        expected_keys = {"schema", "scenario_id", "criterion", "events", "query", "expected"}
        if not isinstance(raw, Mapping) or set(raw) != expected_keys:
            raise ValueError("scenario fields do not match the versioned schema")
        if raw["schema"] != SCENARIO_SCHEMA:
            raise ValueError("unsupported scenario schema")
        if not isinstance(raw["events"], list):
            raise ValueError("scenario events must be a list")
        return cls(
            scenario_id=raw["scenario_id"],
            criterion=raw["criterion"],
            events=tuple(ScenarioEvent.from_dict(item) for item in raw["events"]),
            query=ScenarioQuery.from_dict(raw["query"]),
            expected=raw["expected"],
        )

    def to_case(self) -> BenchmarkCase:
        return BenchmarkCase(
            case_id=self.scenario_id,
            task_type=self.criterion,
            input_text=self.to_json(),
            privacy_class=PRIVACY_CLASS,
            allowed_lanes=ALLOWED_LANES,
            criterion=BenchmarkCriterion("exact", self.expected),
            tags=("continuity", self.criterion),
        )


class ContinuitySubject(Protocol):
    """The system under evaluation. One fresh instance per scenario."""

    def apply(self, event: ScenarioEvent) -> None: ...

    def answer(self, query: ScenarioQuery) -> str: ...


@dataclass
class _Fact:
    value: str | None
    source: str
    superseded: bool = False
    purged: bool = False


class ReferenceContinuityMemory:
    """Transparent in-process model of the #731 continuity semantics.

    - facts are keyed per person; recall never crosses people;
    - only owner and inferred sources are admitted as current truth, and the
      admission reason is inspectable;
    - untrusted sources are retained as evidence but never recalled as truth,
      and cannot supersede an admitted fact;
    - corrections supersede; a superseded value never resurfaces;
    - forget purges the value and leaves an honest tombstone;
    - restart preserves everything (a durable store), including identity;
    - identity changes apply only after an explicit approval of a proposal.
    """

    def __init__(self) -> None:
        self._facts: dict[tuple[str, str, str], list[_Fact]] = {}
        self._identity: dict[str, str] = {}
        self._proposals: dict[str, str] = {}

    def apply(self, event: ScenarioEvent) -> None:
        if event.op == "observe":
            self._facts.setdefault(event.fact_key, []).append(
                _Fact(event.value, str(event.source))
            )
        elif event.op == "correct":
            if event.source == "untrusted":
                # An untrusted correction is evidence, never a supersession.
                self._facts.setdefault(event.fact_key, []).append(
                    _Fact(event.value, "untrusted")
                )
                return
            history = self._facts.setdefault(event.fact_key, [])
            for fact in history:
                if not fact.purged:
                    fact.superseded = True
            history.append(_Fact(event.value, str(event.source)))
        elif event.op == "forget":
            for fact in self._facts.get(event.fact_key, []):
                fact.value = None
                fact.purged = True
        elif event.op == "restart":
            return
        elif event.op == "identity_set":
            self._identity[str(event.key)] = str(event.value)
        elif event.op == "identity_propose":
            self._proposals[str(event.key)] = str(event.value)
        elif event.op == "identity_approve":
            proposed = self._proposals.pop(str(event.key), None)
            if proposed is not None:
                self._identity[str(event.key)] = proposed

    def _current(self, key: tuple[str, str, str]) -> _Fact | None:
        for fact in reversed(self._facts.get(key, [])):
            if fact.purged or fact.superseded:
                continue
            if fact.source in {"owner", "inferred"}:
                return fact
        return None

    def answer(self, query: ScenarioQuery) -> str:
        if query.ask == "identity":
            return self._identity.get(str(query.key), UNKNOWN)
        history = self._facts.get(query.fact_key, [])
        current = self._current(query.fact_key)
        if query.ask == "recall":
            return current.value if current is not None and current.value else UNKNOWN
        if query.ask == "audit":
            if current is not None:
                return KNOWN
            return PURGED if any(fact.purged for fact in history) else UNKNOWN
        # explain: the admission reason behind the recall answer
        if current is not None:
            return f"admitted:{current.source}"
        if any(fact.purged for fact in history):
            return f"abstain:{PURGED}"
        if any(fact.source == "untrusted" for fact in history):
            return "rejected:untrusted"
        return f"abstain:{UNKNOWN}"


class NaiveRecallBaseline:
    """Deliberately weak comparison: last write wins, no people, no taint, no tombstones.

    It admits every source, keys facts without the person, applies identity
    proposals immediately, forgets everything on restart and reports a purged
    fact as never known. It exists so the suite has something to fail.
    """

    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], str] = {}
        self._identity: dict[str, str] = {}

    def apply(self, event: ScenarioEvent) -> None:
        if event.op in _FACT_OPS:
            self._facts[(str(event.subject), str(event.predicate))] = str(event.value)
        elif event.op == "forget":
            self._facts.pop((str(event.subject), str(event.predicate)), None)
        elif event.op == "restart":
            self._facts.clear()
            self._identity.clear()
        elif event.op in _IDENTITY_VALUE_OPS:
            self._identity[str(event.key)] = str(event.value)

    def answer(self, query: ScenarioQuery) -> str:
        if query.ask == "identity":
            return self._identity.get(str(query.key), UNKNOWN)
        value = self._facts.get((str(query.subject), str(query.predicate)))
        if query.ask == "recall":
            return value if value is not None else UNKNOWN
        if query.ask == "audit":
            return KNOWN if value is not None else UNKNOWN
        return "admitted:owner" if value is not None else f"abstain:{UNKNOWN}"


def subject_runner(
    factory: Callable[[], ContinuitySubject],
    *,
    subject_id: str,
    host_id: str = "in-process",
    model_id: str = "none",
    provider_id: str = "local-deterministic",
    privacy_effect: PrivacyEffect = "no_external_disclosure",
) -> BenchmarkRunner:
    """Adapt a ``ContinuitySubject`` factory to the E9.0 runner envelope.

    The defaults describe an in-process deterministic subject. A caller that
    wraps a model-backed memory must pass truthful ``model_id``, ``provider_id``
    and ``privacy_effect`` values; the suite never infers provenance.
    """

    if not callable(factory):
        raise ValueError("subject factory must be callable")
    _validate_identifier(subject_id, "subject id")
    _validate_identifier(host_id, "host id")
    _validate_identifier(model_id, "model id")
    _validate_identifier(provider_id, "provider id")

    async def run(prompt: str) -> BenchmarkObservation:
        scenario = ContinuityScenario.from_json(prompt)
        subject = factory()
        for event in scenario.events:
            subject.apply(event)
        answer = subject.answer(scenario.query)
        if not isinstance(answer, str):
            raise TypeError("continuity subjects must answer with text")
        return BenchmarkObservation(
            response=answer,
            route_id=subject_id,
            model_id=model_id,
            provider_id=provider_id,
            host_id=host_id,
            hardware_profile="not-measured",
            cost_usd=0.0,
            reliability=1.0,
            privacy_effect=privacy_effect,
        )

    return run


# ── the versioned scenario set ──────────────────────────────────────────────

_H = "howard"
_G = "guest"


def _observe(value: str, *, source: str = "owner", person: str = _H) -> ScenarioEvent:
    return ScenarioEvent(
        "observe", person=person, subject="coffee", predicate="preference", value=value, source=source
    )


def _correct(value: str, *, source: str = "owner") -> ScenarioEvent:
    return ScenarioEvent(
        "correct", person=_H, subject="coffee", predicate="preference", value=value, source=source
    )


_FORGET = ScenarioEvent("forget", person=_H, subject="coffee", predicate="preference")
_RESTART = ScenarioEvent("restart")


def _query(ask: str, *, person: str = _H) -> ScenarioQuery:
    return ScenarioQuery(ask, person=person, subject="coffee", predicate="preference")


def _identity(op: str, value: str | None = None) -> ScenarioEvent:
    return ScenarioEvent(op, key="name", value=value)


_IDENTITY_QUERY = ScenarioQuery("identity", key="name")


_RECALL, _AUDIT, _EXPLAIN = _query("recall"), _query("audit"), _query("explain")
_OWNER_BLACK = _observe("black")
_UNTRUSTED = _observe("1234", source="untrusted")
_NAME = _identity("identity_set", "nerva")

#: (scenario id, criterion, events, query, expected answer)
_SCENARIOS: tuple[tuple[str, str, tuple[ScenarioEvent, ...], ScenarioQuery, str], ...] = (
    # multi-session recall
    ("recall-single-session", "multi-session-recall", (_OWNER_BLACK,), _RECALL, "black"),
    ("recall-across-restart", "multi-session-recall",
     (_OWNER_BLACK, _RESTART, _RESTART), _RECALL, "black"),
    # recall precision under taint
    ("taint-untrusted-only", "recall-precision-under-taint", (_UNTRUSTED,), _RECALL, UNKNOWN),
    ("taint-cannot-override-owner", "recall-precision-under-taint",
     (_OWNER_BLACK, _observe("with-sugar", source="untrusted")), _RECALL, "black"),
    ("taint-explain-rejection", "recall-precision-under-taint",
     (_UNTRUSTED,), _EXPLAIN, "rejected:untrusted"),
    ("taint-inferred-is-labelled", "recall-precision-under-taint",
     (_observe("black", source="inferred"),), _EXPLAIN, "admitted:inferred"),
    # contradiction / retraction
    ("correct-latest-wins", "contradiction-retraction",
     (_OWNER_BLACK, _correct("oat-milk")), _RECALL, "oat-milk"),
    ("correct-old-never-resurfaces-after-restart", "contradiction-retraction",
     (_OWNER_BLACK, _correct("oat-milk"), _RESTART), _RECALL, "oat-milk"),
    ("correct-untrusted-cannot-correct", "contradiction-retraction",
     (_OWNER_BLACK, _correct("poisoned", source="untrusted")), _RECALL, "black"),
    # cross-person leakage
    ("leak-other-person", "cross-person-leakage",
     (_OWNER_BLACK,), _query("recall", person=_G), UNKNOWN),
    ("leak-other-person-isolated-store", "cross-person-leakage",
     (_OWNER_BLACK, _observe("tea", person=_G)), _RECALL, "black"),
    # abstention calibration
    ("abstain-never-observed", "abstention-calibration", (), _RECALL, UNKNOWN),
    ("abstain-explain", "abstention-calibration", (), _EXPLAIN, f"abstain:{UNKNOWN}"),
    # identity stability
    ("identity-survives-restart", "identity-stability",
     (_NAME, _RESTART, _RESTART), _IDENTITY_QUERY, "nerva"),
    ("identity-proposal-not-authoritative", "identity-stability",
     (_NAME, _identity("identity_propose", "ultron")), _IDENTITY_QUERY, "nerva"),
    ("identity-approved-proposal-applies", "identity-stability",
     (_NAME, _identity("identity_propose", "nerva-2"), _identity("identity_approve")),
     _IDENTITY_QUERY, "nerva-2"),
    # forget / purge honesty
    ("forget-recall-unknown", "forget-purge-honesty", (_OWNER_BLACK, _FORGET), _RECALL, UNKNOWN),
    ("forget-audit-says-purged", "forget-purge-honesty", (_OWNER_BLACK, _FORGET), _AUDIT, PURGED),
    ("forget-does-not-resurface-after-restart", "forget-purge-honesty",
     (_OWNER_BLACK, _FORGET, _RESTART), _RECALL, UNKNOWN),
    ("forget-explain-purged", "forget-purge-honesty",
     (_OWNER_BLACK, _FORGET), _EXPLAIN, f"abstain:{PURGED}"),
)


def continuity_scenarios() -> tuple[ContinuityScenario, ...]:
    """The versioned synthetic-public scenario set. No owner or sanitized data."""

    return tuple(ContinuityScenario(*row) for row in _SCENARIOS)


def continuity_cases() -> tuple[BenchmarkCase, ...]:
    """The suite as immutable ``nerva.benchmark.v1`` cases."""

    return tuple(scenario.to_case() for scenario in continuity_scenarios())


def suite_fingerprint(cases: Sequence[BenchmarkCase] | None = None) -> str:
    """SHA-256 over the ordered case content fingerprints: same inputs, same suite."""

    encoded = json.dumps(
        [case.content_fingerprint for case in (cases or continuity_cases())],
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PrerequisiteError(RuntimeError):
    """A declared prerequisite is missing; the lane fails visibly, never passes."""


def source_revision(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Bind a run to an exact commit SHA or fail; never shell out to guess one."""

    candidate = (explicit or "").strip()
    if not candidate:
        source = os.environ if env is None else env
        for name in REVISION_ENV_VARS:
            value = (source.get(name) or "").strip()
            if value:
                candidate = value
                break
    if not candidate:
        raise PrerequisiteError(
            "cannot resolve source revision: pass --revision or set "
            + " or ".join(REVISION_ENV_VARS)
        )
    try:
        return _validate_exact_revision(candidate)
    except ValueError as exc:
        raise PrerequisiteError(f"source revision is not an exact commit SHA: {exc}") from exc


def ensure_suite(store: BenchmarkStore, *, lane: BenchmarkLane = "ci") -> int:
    """Return the stored version for the current cases, saving only on change."""

    if lane not in ALLOWED_LANES:
        raise PermissionError(f"continuity suite cannot run in {lane!r}")
    cases = continuity_cases()
    versions = store.versions(SUITE_NAME)
    if versions:
        latest = versions[-1]
        if suite_fingerprint(store.load_suite(SUITE_NAME, latest)) == suite_fingerprint(cases):
            return latest
    return store.save_suite(SUITE_NAME, cases, lane=lane)


async def run_continuity_suite(
    store: BenchmarkStore,
    *,
    revision: str,
    lane: BenchmarkLane = "ci",
    run_id: str | None = None,
    candidate: BenchmarkRunner | None = None,
    candidate_id: str = CANDIDATE_ID,
    host_id: str = "in-process",
) -> BenchmarkRun:
    """Run the suite against a subject, retain the evidence, return the run.

    Without an explicit ``candidate`` the reference memory is measured: that
    validates the suite contract, it proves nothing about production memory.
    The naive baseline is always measured alongside so a run shows what the
    suite discriminates.
    """

    revision = source_revision(revision)
    version = ensure_suite(store, lane=lane)
    cases = store.load_suite(SUITE_NAME, version)
    runner = candidate or subject_runner(
        ReferenceContinuityMemory, subject_id=CANDIDATE_ID, host_id=host_id
    )
    harness = BenchmarkHarness(
        runner,
        candidate_id=candidate_id,
        baseline=subject_runner(NaiveRecallBaseline, subject_id=BASELINE_ID, host_id=host_id),
        baseline_id=BASELINE_ID,
    )
    run = await harness.run(
        cases,
        suite_name=SUITE_NAME,
        suite_version=version,
        lane=lane,
        source_revision=revision,
        run_id=run_id,
    )
    # Negative, failed and unscored results are retained exactly as produced.
    store.record_run(run)
    return run


# ── per-criterion report ────────────────────────────────────────────────────


def run_fingerprint(run: BenchmarkRun) -> str:
    return hashlib.sha256(run.to_json().encode("utf-8")).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


@dataclass(frozen=True)
class CriterionSummary:
    """Measured outcome of one #731 criterion; acceptance stays with its owner."""

    criterion: str
    acceptance_owner: str
    total: int
    passed: int
    failed: int
    errors: int
    pass_ratio: float | None
    baseline_pass_ratio: float | None

    def __post_init__(self) -> None:
        if self.criterion not in CRITERIA or CRITERIA[self.criterion] != self.acceptance_owner:
            raise ValueError("criterion summary must name a #731 criterion and its owner")
        for name in ("total", "passed", "failed", "errors"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"criterion {name} must be a non-negative integer")
        if self.passed + self.failed + self.errors > self.total:
            raise ValueError("criterion counts exceed its total")
        for name in ("pass_ratio", "baseline_pass_ratio"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"criterion {name} must be a ratio in [0, 1]")
        if self.pass_ratio != _ratio(self.passed, self.passed + self.failed):
            raise ValueError("criterion pass ratio must equal passed over scored")


@dataclass(frozen=True)
class ContinuityReport:
    """Deterministic ``nerva.continuity.report.v1`` summary of one retained run."""

    suite_name: str
    suite_version: int
    suite_fingerprint: str
    run_id: str
    source_revision: str
    candidate_id: str
    baseline_id: str
    totals: dict[str, Any]
    criteria: tuple[CriterionSummary, ...]
    run_fingerprint: str
    previous_run_id: str | None
    regressed_criteria: tuple[str, ...]
    regressed: bool
    guard: Any = field(default=None, compare=False, repr=False)
    schema: str = field(default=REPORT_SCHEMA, init=False)
    authority: str = field(default=AUTHORITY, init=False)
    can_change_routing: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_promote_capability: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    can_accept_epic: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.guard is not _REPORT_GUARD:
            raise ValueError("a report must be derived from a retained run through build_report")
        _validate_suite_name(self.suite_name)
        _validate_version(self.suite_version)
        _validate_identifier(self.run_id, "run id")
        _validate_exact_revision(self.source_revision)
        _validate_identifier(self.candidate_id, "candidate id")
        _validate_identifier(self.baseline_id, "baseline id")
        if self.previous_run_id is not None:
            _validate_identifier(self.previous_run_id, "previous run id")
        for name in ("suite_fingerprint", "run_fingerprint"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != _SHA256_HEX_LENGTH
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"report {name} must be a SHA-256 hex digest")
        if not isinstance(self.criteria, tuple) or any(
            not isinstance(item, CriterionSummary) for item in self.criteria
        ):
            raise ValueError("report criteria must be typed summaries")
        if [item.criterion for item in self.criteria] != list(CRITERIA):
            raise ValueError("report must summarize every #731 criterion exactly once")
        if not isinstance(self.regressed_criteria, tuple) or any(
            name not in CRITERIA for name in self.regressed_criteria
        ):
            raise ValueError("regressed criteria must name #731 criteria")
        if self.regressed != bool(self.regressed_criteria):
            raise ValueError("regressed flag must agree with the regressed criteria")
        if self.previous_run_id is None and self.regressed_criteria:
            raise ValueError("a regression requires a comparable previous run")
        object.__setattr__(self, "guard", None)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("guard", None)
        payload["acceptance"] = "not_claimed"
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    def to_markdown(self) -> str:
        lines = [
            f"### Nerva Continuity Core suite — `{self.suite_name}` v{self.suite_version}",
            "",
            f"- run `{self.run_id}` at `{self.source_revision[:12]}` — "
            f"candidate `{self.candidate_id}` vs baseline `{self.baseline_id}`",
            f"- passed {self.totals['passed']}/{self.totals['scored']} scored, "
            f"{self.totals['errors']} errors; authority `{self.authority}`, acceptance not claimed",
            "",
            "| criterion | candidate | baseline | acceptance owner |",
            "|---|---:|---:|---|",
        ]
        for item in self.criteria:
            flag = " (regressed)" if item.criterion in self.regressed_criteria else ""
            lines.append(
                f"| {item.criterion}{flag} | {_render(item.pass_ratio)} | "
                f"{_render(item.baseline_pass_ratio)} | {item.acceptance_owner} |"
            )
        if self.previous_run_id is None:
            lines.append("")
            lines.append("_No comparable previous run: nothing can be called a regression._")
        return "\n".join(lines)


def _render(value: float | None) -> str:
    return "not_measured" if value is None else f"{value:g}"


def _criterion_summaries(run: BenchmarkRun) -> tuple[CriterionSummary, ...]:
    summaries = []
    for criterion, owner in CRITERIA.items():
        results = [result for result in run.results if result.task_type == criterion]
        passed = sum(result.status == "passed" for result in results)
        failed = sum(result.status == "failed" for result in results)
        errors = sum(result.status == "error" for result in results)
        baseline_scored = [
            result for result in results if result.baseline_quality.status == "measured"
        ]
        baseline_passed = sum(
            float(result.baseline_quality.value) >= 0.5 for result in baseline_scored
        )
        summaries.append(
            CriterionSummary(
                criterion=criterion,
                acceptance_owner=owner,
                total=len(results),
                passed=passed,
                failed=failed,
                errors=errors,
                pass_ratio=_ratio(passed, passed + failed),
                baseline_pass_ratio=_ratio(baseline_passed, len(baseline_scored)),
            )
        )
    return tuple(summaries)


def previous_run(store: BenchmarkStore, *, exclude_run_id: str) -> BenchmarkRun | None:
    for candidate in store.runs(SUITE_NAME, last_n=20):
        if candidate.run_id != exclude_run_id:
            return candidate
    return None


def build_report(
    run: BenchmarkRun,
    *,
    store: BenchmarkStore,
    previous: BenchmarkRun | None = None,
) -> ContinuityReport:
    """Summarize a *retained* run per criterion; compare only comparable runs."""

    if not isinstance(run, BenchmarkRun) or run.suite_name != SUITE_NAME:
        raise ValueError("report requires a retained continuity suite run")
    retained = {run_fingerprint(record) for record in store.runs(SUITE_NAME, last_n=50)}
    if run_fingerprint(run) not in retained:
        raise ValueError("report requires a run retained in the benchmark store")
    cases = store.load_suite(SUITE_NAME, run.suite_version)
    if not cases:
        raise ValueError("report requires the retained suite version")
    comparable = (
        previous is not None
        and run_fingerprint(previous) in retained
        and previous.suite_version == run.suite_version
        and previous.candidate_id == run.candidate_id
        and previous.baseline_id == run.baseline_id
    )
    criteria = _criterion_summaries(run)
    regressed: list[str] = []
    if comparable and previous is not None:
        before = {item.criterion: item.pass_ratio for item in _criterion_summaries(previous)}
        for item in criteria:
            prior = before.get(item.criterion)
            if item.pass_ratio is not None and prior is not None and item.pass_ratio < prior:
                regressed.append(item.criterion)
    return ContinuityReport(
        suite_name=run.suite_name,
        suite_version=run.suite_version,
        suite_fingerprint=suite_fingerprint(cases),
        run_id=run.run_id,
        source_revision=run.source_revision,
        candidate_id=run.candidate_id,
        baseline_id=str(run.baseline_id),
        totals=run.summary,
        criteria=criteria,
        run_fingerprint=run_fingerprint(run),
        previous_run_id=previous.run_id if comparable and previous is not None else None,
        regressed_criteria=tuple(regressed),
        regressed=bool(regressed),
        guard=_REPORT_GUARD,
    )


# ── CLI (the eval-nightly lane entry) ───────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Nerva Continuity Core (#731) evaluation-only suite.",
    )
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--lane", choices=list(ALLOWED_LANES), default="ci")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit non-zero when a criterion pass ratio dropped against the previous run.",
    )
    args = parser.parse_args(argv)

    try:
        revision = source_revision(args.revision)
        store = BenchmarkStore(args.store_root)
        run = asyncio.run(
            run_continuity_suite(store, revision=revision, lane=args.lane, run_id=args.run_id)
        )
    except (PrerequisiteError, PermissionError) as exc:
        message = f"Continuity Core suite could not run: {exc}"
        print(message, file=sys.stderr)
        _append(args.summary, f"### Nerva Continuity Core suite — FAILED\n\n{message}\n")
        return 2

    report = build_report(
        run, store=store, previous=previous_run(store, exclude_run_id=run.run_id)
    )
    _append(args.summary, report.to_markdown() + "\n")
    _write_document(args.json_out, report.to_json() + "\n")
    print(report.to_markdown())
    if report.regressed and args.fail_on_regression:
        return 1
    return 0


__all__ = [
    "ALLOWED_LANES",
    "AUTHORITY",
    "BASELINE_ID",
    "CANDIDATE_ID",
    "CRITERIA",
    "PRIVACY_CLASS",
    "REPORT_SCHEMA",
    "SCENARIO_SCHEMA",
    "SUITE_NAME",
    "ContinuityReport",
    "ContinuityScenario",
    "ContinuitySubject",
    "CriterionSummary",
    "NaiveRecallBaseline",
    "PrerequisiteError",
    "ReferenceContinuityMemory",
    "ScenarioEvent",
    "ScenarioQuery",
    "build_report",
    "continuity_cases",
    "continuity_scenarios",
    "ensure_suite",
    "main",
    "previous_run",
    "run_continuity_suite",
    "run_fingerprint",
    "source_revision",
    "subject_runner",
    "suite_fingerprint",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
