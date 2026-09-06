"""Typed evidence receipts (E11.0, ``nerva.evidence.v1``).

A receipt says *what was claimed, what was expected, what was observed, how,
where and when* — and what it does **not** prove. It is evidence for a claim,
never authority over one: ``authority`` is pinned to ``claim_evidence_only``
and no receipt can authorize, execute or mark work complete.

Two honesty rules are enforced by construction (OPS-03 / AUTO-03):

* **CI proof is never owner-hardware proof.** A receipt with
  ``environment="owner_live"`` cannot be minted while ``GITHUB_ACTIONS`` or
  ``CI`` is set (:func:`validate_receipt_environment`), and the store refuses
  to append one. Hermetic tests can never claim ``owner_live`` at all.
* **Green is not success.** ``run_status`` (did the run finish?) and
  ``verified`` (did the observed state match the expected state?) are separate
  fields; ``verified=True`` is only accepted when the two states agree.

The store is an append-only JSONL ledger under ``data_path("evidence")``,
mirroring the reality-evidence and benchmark ledgers. Nothing here reads the
ledger back into runtime behaviour: the consumer is the release gate's owner
rows (:func:`check_evidence_receipts`), which PASS only from verified
``owner_live`` receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.core.cortex_decision import EvidenceValue
from agents.core.paths import data_path

SCHEMA = "nerva.evidence.v1"
REF_SCHEMA = "nerva.evidence.ref.v1"
AUTHORITY = "claim_evidence_only"

METHODS = frozenset(
    {
        "hermetic_test",
        "reality_harness",
        "owner_live_run",
        "drill",
        "soak",
        "design_partner",
        "result_inspection",
        "postcondition",
    }
)
ENVIRONMENTS = frozenset({"ci", "local", "owner_live"})
RUN_STATUSES = frozenset({"completed", "failed", "skipped", "not_run", "unknown"})
# Environment markers that identify a hosted runner. Either one set ⇒ CI.
CI_ENV_MARKERS = ("GITHUB_ACTIONS", "CI")
# Owner-live proof older than this is still evidence, but the gate says "re-run".
RECEIPT_STALE_DAYS = 30.0
_LEDGER_NAME = "receipts.jsonl"
_MAX_LINE = 500
_MAX_LIMITATIONS = 32
_MAX_ARTIFACTS = 64
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/@+-]{0,199}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_FIELDS = {
    "schema": SCHEMA,
    "authority": AUTHORITY,
    "can_authorize": False,
    "can_execute": False,
    "can_mark_complete": False,
}


class ReceiptEnvironmentRefused(ValueError):
    """The receipt's environment claim is not mintable where the process runs."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _line(value: object, name: str, *, limit: int = _MAX_LINE) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single line")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical lowercase identifier")
    return value


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase sha256 hex digest")
    return value


def _epoch(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be epoch seconds")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite epoch")
    return number


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _iso_to_epoch(value: object, name: str) -> float:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return _epoch(parsed.timestamp(), name)


# --------------------------------------------------------------------------- environment


def detect_environment(environ: Mapping[str, str] | None = None) -> str:
    """Return ``ci`` on a hosted runner, else ``local``.

    ``owner_live`` is never *detected*: it is asserted by owner-run tooling and
    then checked by :func:`validate_receipt_environment`.
    """
    source = os.environ if environ is None else environ
    for marker in CI_ENV_MARKERS:
        if str(source.get(marker, "")).strip():
            return "ci"
    return "local"


def validate_receipt_environment(
    environment: str, *, environ: Mapping[str, str] | None = None
) -> str:
    """Refuse an ``owner_live`` claim while the process runs under CI (OPS-03)."""
    if environment not in ENVIRONMENTS:
        raise ValueError("receipt environment is not recognized")
    if environment == "owner_live" and detect_environment(environ) == "ci":
        markers = ", ".join(
            marker
            for marker in CI_ENV_MARKERS
            if str((os.environ if environ is None else environ).get(marker, "")).strip()
        )
        raise ReceiptEnvironmentRefused(
            "ci_cannot_mint_owner_live",
            f"{markers} is set; hosted-runner proof is not owner-hardware proof",
        )
    return environment


# --------------------------------------------------------------------------- contracts


@dataclass(frozen=True)
class EvidenceRef:
    """Content-free pointer to the thing a receipt is about or built from."""

    kind: str
    ref_id: str
    integrity_sha256: str | None = None
    source_schema: str | None = None
    schema: str = field(default=REF_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _identifier(self.kind, "reference kind")
        _line(self.ref_id, "reference id", limit=300)
        if self.integrity_sha256 is not None:
            _sha256(self.integrity_sha256, "integrity_sha256")
        if self.source_schema is not None:
            _line(self.source_schema, "source_schema", limit=120)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> EvidenceRef:
        if not isinstance(payload, Mapping):
            raise ValueError("evidence reference must be an object")
        allowed = {"kind", "ref_id", "integrity_sha256", "source_schema", "schema"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"evidence reference has unknown keys: {sorted(unknown)}")
        if payload.get("schema", REF_SCHEMA) != REF_SCHEMA:
            raise ValueError("evidence reference schema mismatch")
        return cls(
            kind=payload.get("kind"),
            ref_id=payload.get("ref_id"),
            integrity_sha256=payload.get("integrity_sha256"),
            source_schema=payload.get("source_schema"),
        )


@dataclass(frozen=True)
class EvidenceReceipt:
    """One claim, its expected and observed state, and how/where it was checked."""

    claim: str
    target: EvidenceRef
    expected_state: str
    observed_state: str
    method: str
    environment: str
    timestamp: float
    confidence: EvidenceValue
    verified: bool
    run_status: str = "unknown"
    limitations: tuple[str, ...] = ()
    source_artifacts: tuple[EvidenceRef, ...] = ()
    schema: str = field(default=SCHEMA, init=False)
    authority: str = field(default=AUTHORITY, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _line(self.claim, "claim")
        if not isinstance(self.target, EvidenceRef):
            raise ValueError("receipt target must be an EvidenceRef")
        _line(self.expected_state, "expected_state", limit=200)
        _line(self.observed_state, "observed_state", limit=200)
        if self.method not in METHODS:
            raise ValueError("receipt method is not recognized")
        if self.environment not in ENVIRONMENTS:
            raise ValueError("receipt environment is not recognized")
        _epoch(self.timestamp, "timestamp")
        if not isinstance(self.confidence, EvidenceValue):
            raise ValueError("receipt confidence must be an EvidenceValue")
        if self.confidence.status == "measured":
            value = self.confidence.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("measured confidence must be numeric")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError("measured confidence must lie in [0, 1]")
        if not isinstance(self.verified, bool):
            raise ValueError("verified must be a bool")
        if self.run_status not in RUN_STATUSES:
            raise ValueError("run_status is not recognized")
        if not isinstance(self.limitations, tuple) or len(self.limitations) > _MAX_LIMITATIONS:
            raise ValueError("limitations must be a bounded tuple")
        for item in self.limitations:
            _line(item, "limitation", limit=300)
        if not isinstance(self.source_artifacts, tuple) or (
            len(self.source_artifacts) > _MAX_ARTIFACTS
        ):
            raise ValueError("source_artifacts must be a bounded tuple")
        if any(not isinstance(ref, EvidenceRef) for ref in self.source_artifacts):
            raise ValueError("source_artifacts must contain EvidenceRef values")
        # Green ≠ success: a finished run is not a verified claim, and a verified
        # claim cannot disagree with its own observation.
        if self.verified and self.observed_state != self.expected_state:
            raise ValueError("a receipt cannot be verified when observed_state differs")
        if self.verified and self.run_status in {"failed", "skipped", "not_run"}:
            raise ValueError(f"a {self.run_status} run cannot verify a claim")
        if self.method == "hermetic_test" and self.environment == "owner_live":
            raise ValueError("hermetic tests are never owner-hardware proof")
        if self.method == "owner_live_run" and self.environment != "owner_live":
            raise ValueError("owner_live_run receipts must carry environment=owner_live")

    # -- identity ---------------------------------------------------------------
    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return _canonical_json(self.canonical_payload())

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def receipt_id(self) -> str:
        return self.fingerprint

    @property
    def is_owner_live_proof(self) -> bool:
        return self.verified and self.environment == "owner_live"

    # -- construction -----------------------------------------------------------
    @classmethod
    def mint(
        cls,
        *,
        claim: str,
        target: EvidenceRef,
        expected_state: str,
        observed_state: str,
        method: str,
        environment: str,
        confidence: EvidenceValue,
        timestamp: float | None = None,
        run_status: str = "unknown",
        limitations: Iterable[str] = (),
        source_artifacts: Iterable[EvidenceRef] = (),
        environ: Mapping[str, str] | None = None,
    ) -> EvidenceReceipt:
        """Create a new receipt *here*: the environment claim is checked first."""
        validate_receipt_environment(environment, environ=environ)
        return cls(
            claim=claim,
            target=target,
            expected_state=expected_state,
            observed_state=observed_state,
            method=method,
            environment=environment,
            timestamp=time.time() if timestamp is None else timestamp,
            confidence=confidence,
            verified=observed_state == expected_state
            and run_status not in {"failed", "skipped", "not_run"},
            run_status=run_status,
            limitations=tuple(limitations),
            source_artifacts=tuple(source_artifacts),
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> EvidenceReceipt:
        """Strict loader: unknown keys, forged authority flags and bool times fail."""
        if not isinstance(payload, Mapping):
            raise ValueError("evidence receipt must be an object")
        allowed = {
            "claim",
            "target",
            "expected_state",
            "observed_state",
            "method",
            "environment",
            "timestamp",
            "confidence",
            "verified",
            "run_status",
            "limitations",
            "source_artifacts",
            *_AUTHORITY_FIELDS,
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"evidence receipt has unknown keys: {sorted(unknown)}")
        for name, pinned in _AUTHORITY_FIELDS.items():
            if name in payload and (
                type(payload[name]) is not type(pinned) or payload[name] != pinned
            ):
                raise ValueError(f"forged {name} in evidence receipt")
        confidence = payload.get("confidence")
        if not isinstance(confidence, Mapping) or set(confidence) - {"status", "value", "source"}:
            raise ValueError("receipt confidence must be an EvidenceValue object")
        limitations = payload.get("limitations", ())
        artifacts = payload.get("source_artifacts", ())
        if not isinstance(limitations, (list, tuple)) or not isinstance(artifacts, (list, tuple)):
            raise ValueError("limitations and source_artifacts must be arrays")
        return cls(
            claim=payload.get("claim"),
            target=EvidenceRef.from_payload(payload.get("target")),
            expected_state=payload.get("expected_state"),
            observed_state=payload.get("observed_state"),
            method=payload.get("method"),
            environment=payload.get("environment"),
            timestamp=payload.get("timestamp"),
            confidence=EvidenceValue(
                confidence.get("status"), confidence.get("value"), confidence.get("source")
            ),
            verified=payload.get("verified"),
            run_status=payload.get("run_status", "unknown"),
            limitations=tuple(limitations),
            source_artifacts=tuple(EvidenceRef.from_payload(ref) for ref in artifacts),
        )


# --------------------------------------------------------------------------- adapters

_LANE_ENVIRONMENT = {"scheduled": "ci", "dispatch": "ci", "local": "local", "ci": "ci", "cloud": "ci"}


def _lane_environment(lane: object) -> str:
    # Neither ledger runs on owner hardware by construction; ``owner_live`` can
    # only come from owner-run tooling that asserts it explicitly.
    return _LANE_ENVIRONMENT.get(str(lane), "local")


def _capability_receipt(
    record: Mapping[str, Any], capability_id: str, *, environment: str, environ
) -> EvidenceReceipt:
    rows = [
        row
        for row in record.get("cases") or ()
        if isinstance(row, Mapping) and row.get("capability_id") == capability_id
    ]
    if not rows:
        raise ValueError(f"capability {capability_id!r} has no case in this reality run")
    limitations: list[str] = ["promotion_scope:in_process_only", "not_owner_live_proof"]
    off_box = set(record.get("owner_live_not_exercised") or ())
    seam = set(record.get("expected_seam_failures") or ())
    passed = [row for row in rows if row.get("passed") and not row.get("skipped")]
    if passed:
        observed, run_status = "passed", "completed"
    elif all(row.get("skipped") for row in rows):
        observed, run_status = "skipped", "skipped"
    elif capability_id in off_box:
        observed, run_status = "owner_live_not_exercised", "not_run"
        limitations.append("owner_live_not_exercised:probe reported owner opt-in/hardware missing")
    elif capability_id in seam:
        observed, run_status = "expected_seam_failure", "completed"
        limitations.append("expected_seam_failure:capability registered without runtime")
    else:
        observed, run_status = "failed", "completed"
    harness_id = str(record.get("harness_id") or "reality")
    return EvidenceReceipt.mint(
        claim=f"capability {capability_id} probe passed in reality harness {harness_id}",
        target=EvidenceRef("capability", capability_id, source_schema=record.get("schema")),
        expected_state="passed",
        observed_state=observed,
        method="reality_harness",
        environment=environment,
        timestamp=_iso_to_epoch(record.get("finished_at"), "finished_at"),
        confidence=EvidenceValue(
            "measured", 1.0 if passed else 0.0, "reality_evidence.cases.passed"
        ),
        run_status=run_status,
        limitations=limitations,
        source_artifacts=(_reality_run_ref(record),),
        environ=environ,
    )


def _reality_run_ref(record: Mapping[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        "reality_run",
        f"{record.get('harness_id') or 'reality'}@{record.get('finished_at')}",
        integrity_sha256=_digest(record),
        source_schema=str(record.get("schema") or ""),
    )


def from_reality_run(
    record: Mapping[str, Any],
    *,
    capability_id: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> EvidenceReceipt:
    """Receipt for one ``nerva.reality.run.v1`` record (or one capability in it).

    Off-box owner-live cases and expected seam failures are excused by the
    run's verdict, but they are carried as *limitations*: an excused run is a
    green transcript, not owner-hardware proof.
    """
    if not isinstance(record, Mapping):
        raise ValueError("reality run record must be an object")
    environment = _lane_environment(record.get("lane"))
    if capability_id is not None:
        return _capability_receipt(record, capability_id, environment=environment, environ=environ)
    totals = dict(record.get("totals") or {})
    passed = int(totals.get("passed") or 0)
    total = int(totals.get("total") or 0)
    seam = list(record.get("expected_seam_failures") or ())
    off_box = list(record.get("owner_live_not_exercised") or ())
    excused = passed + len(seam) + len(off_box)
    limitations = ["promotion_scope:in_process_only", "not_owner_live_proof"]
    if off_box:
        limitations.append("owner_live_not_exercised:" + ",".join(sorted(map(str, off_box))))
    if seam:
        limitations.append("expected_seam_failures:" + ",".join(sorted(map(str, seam))))
    unexcused = max(total - excused, 0)
    harness_id = str(record.get("harness_id") or "reality")
    return EvidenceReceipt.mint(
        claim=f"reality harness {harness_id}: {passed}/{total} cases passed",
        target=EvidenceRef("reality_harness", harness_id, source_schema=record.get("schema")),
        expected_state="all_cases_passed_or_excused",
        observed_state=(
            "all_cases_passed_or_excused" if not unexcused else f"unexcused_failures:{unexcused}"
        ),
        method="reality_harness",
        environment=environment,
        timestamp=_iso_to_epoch(record.get("finished_at"), "finished_at"),
        confidence=(
            EvidenceValue("measured", round(passed / total, 6), "reality_evidence.totals")
            if total > 0
            else EvidenceValue("not_measured")
        ),
        run_status="completed",
        limitations=limitations,
        source_artifacts=(_reality_run_ref(record),),
        environ=environ,
    )


def from_benchmark_run(run: Any, *, environ: Mapping[str, str] | None = None) -> EvidenceReceipt:
    """Receipt for one ``nerva.benchmark.v1`` run (duck-typed; evaluation only)."""
    summary = dict(getattr(run, "summary", None) or {})
    total = int(summary.get("total") or 0)
    scored = int(summary.get("scored") or 0)
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    errors = int(summary.get("errors") or 0)
    unscored = int(summary.get("unscored") or 0)
    if scored == 0:
        observed = "no_scored_cases"
    elif failed or errors:
        observed = f"failed:{failed},errors:{errors}"
    else:
        observed = "all_scored_cases_passed"
    limitations = ["authority:evaluation_only", "not_owner_live_proof"]
    if unscored:
        limitations.append(f"unscored_cases:{unscored}")
    lane = str(getattr(run, "lane", "local"))
    if lane == "cloud":
        limitations.append("lane:cloud")
    quality_mean = summary.get("quality_mean")
    suite = f"{getattr(run, 'suite_name', 'benchmark')} v{getattr(run, 'suite_version', 0)}"
    run_id = str(getattr(run, "run_id", "run"))
    schema = str(getattr(run, "schema", "nerva.benchmark.v1"))
    artifacts = [
        EvidenceRef(
            "benchmark_run",
            run_id,
            integrity_sha256=hashlib.sha256(run.to_json().encode("utf-8")).hexdigest(),
            source_schema=schema,
        )
    ]
    artifacts.extend(
        EvidenceRef("artifact", str(ref)) for ref in getattr(run, "artifact_refs", ()) or ()
    )
    return EvidenceReceipt.mint(
        claim=f"benchmark {suite} run {run_id}: {passed}/{total} cases passed",
        target=EvidenceRef("benchmark_suite", str(run.suite_name), source_schema=schema),
        expected_state="all_scored_cases_passed",
        observed_state=observed,
        method="reality_harness",
        environment=_lane_environment(lane),
        timestamp=_iso_to_epoch(getattr(run, "finished_at", None), "finished_at"),
        confidence=(
            EvidenceValue("measured", float(quality_mean), "benchmark.summary.quality_mean")
            if isinstance(quality_mean, (int, float)) and not isinstance(quality_mean, bool)
            else EvidenceValue("not_measured")
        ),
        run_status="completed",
        limitations=limitations,
        source_artifacts=artifacts,
        environ=environ,
    )


# --------------------------------------------------------------------------- store


@dataclass(frozen=True)
class ReceiptLoad:
    receipts: tuple[EvidenceReceipt, ...]
    rejected: int
    reasons: tuple[str, ...]


def load_receipt_lines(lines: Iterable[str]) -> ReceiptLoad:
    """Parse JSONL lines strictly; a torn or forged line is counted, never trusted."""
    receipts: list[EvidenceReceipt] = []
    reasons: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            receipts.append(EvidenceReceipt.from_payload(json.loads(text)))
        except (ValueError, TypeError) as exc:
            reasons.append(str(exc)[:160])
    return ReceiptLoad(tuple(receipts), len(reasons), tuple(reasons))


class ReceiptStore:
    """Append-only JSONL receipts ledger under ``data_path("evidence")``."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path(data_path("evidence"))
        self._path = self._root / _LEDGER_NAME
        if self._path.resolve().parent != self._root.resolve():
            raise ValueError("receipt store path escapes its root")
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self, receipt: EvidenceReceipt, *, environ: Mapping[str, str] | None = None
    ) -> str:
        """Persist one receipt; returns its fingerprint. Duplicates are not re-written."""
        if not isinstance(receipt, EvidenceReceipt):
            raise ValueError("only EvidenceReceipt values can be stored")
        validate_receipt_environment(receipt.environment, environ=environ)
        fingerprint = receipt.fingerprint
        with self._lock:
            if any(existing.fingerprint == fingerprint for existing in self._load().receipts):
                return fingerprint
            self._root.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(receipt.to_json() + "\n")
        return fingerprint

    def _load(self) -> ReceiptLoad:
        if not self._path.exists():
            return ReceiptLoad((), 0, ())
        return load_receipt_lines(self._path.read_text(encoding="utf-8").splitlines())

    def load(self) -> ReceiptLoad:
        with self._lock:
            return self._load()

    def receipts(self) -> list[EvidenceReceipt]:
        return list(self.load().receipts)

    def latest(
        self,
        *,
        target_kind: str | None = None,
        target_id: str | None = None,
        method: str | None = None,
        environment: str | None = None,
        verified: bool | None = None,
    ) -> EvidenceReceipt | None:
        matches = [
            receipt
            for receipt in self.receipts()
            if (target_kind is None or receipt.target.kind == target_kind)
            and (target_id is None or receipt.target.ref_id == target_id)
            and (method is None or receipt.method == method)
            and (environment is None or receipt.environment == environment)
            and (verified is None or receipt.verified is verified)
        ]
        return max(matches, key=lambda receipt: receipt.timestamp) if matches else None


# --------------------------------------------------------------------------- release gate

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass(frozen=True)
class GateRow:
    """One E11 owner row: which receipts may satisfy it, and how many."""

    name: str
    methods: frozenset[str]
    target_kind: str
    target_id: str | None
    required: int
    hint: str


E11_ROWS: tuple[GateRow, ...] = (
    GateRow(
        "restore-drill",
        frozenset({"drill"}),
        "drill",
        "restore",
        1,
        "run the restore drill on the owner box and record its receipt",
    ),
    GateRow(
        "multi-day-soak",
        frozenset({"soak"}),
        "soak",
        None,
        1,
        "record a completed multi-day soak receipt from the owner box",
    ),
    GateRow(
        "recurring-workflows",
        frozenset({"owner_live_run", "postcondition", "result_inspection"}),
        "workflow",
        None,
        3,
        "record verified owner_live receipts for three distinct recurring workflows",
    ),
)


def _row_result(name: str, status: str, detail: str) -> dict:
    return {"tier": "owner", "name": name, "status": status, "detail": detail}


def evaluate_release_rows(
    receipts: Iterable[EvidenceReceipt],
    *,
    now: float | None = None,
    stale_days: float = RECEIPT_STALE_DAYS,
    rejected: int = 0,
) -> list[dict]:
    """Grade the E11 owner rows from receipts alone.

    PASS needs ``required`` distinct targets with a fresh, verified
    ``owner_live`` receipt; verified but stale ⇒ WARN; anything else — ci/local
    evidence included — FAILs with the reason spelled out (OPS-03).
    """
    moment = float(time.time() if now is None else now)
    pool = list(receipts)
    results = []
    for row in E11_ROWS:
        candidates = [
            receipt
            for receipt in pool
            if receipt.method in row.methods
            and receipt.target.kind == row.target_kind
            and (row.target_id is None or receipt.target.ref_id == row.target_id)
        ]
        owner_proofs = [receipt for receipt in candidates if receipt.is_owner_live_proof]
        fresh: dict[str, float] = {}
        stale: dict[str, float] = {}
        for receipt in owner_proofs:
            age = (moment - receipt.timestamp) / 86400
            bucket = fresh if age <= stale_days else stale
            key = receipt.target.ref_id
            bucket[key] = min(age, bucket.get(key, age))
        suffix = f" ({rejected} unreadable/forged receipt line(s) ignored)" if rejected else ""
        if len(fresh) >= row.required:
            listing = ", ".join(f"{key} {age:.1f}d ago" for key, age in sorted(fresh.items()))
            results.append(_row_result(row.name, PASS, f"owner_live receipt(s): {listing}{suffix}"))
            continue
        if len(fresh) + len(stale) >= row.required:
            listing = ", ".join(
                f"{key} {age:.1f}d ago" for key, age in sorted({**stale, **fresh}.items())
            )
            results.append(
                _row_result(row.name, WARN, f"owner_live receipt(s) stale — re-run: {listing}{suffix}")
            )
            continue
        have = len(fresh) + len(stale)
        non_owner = [receipt for receipt in candidates if receipt.verified and receipt.environment != "owner_live"]
        failed_live = [
            receipt
            for receipt in candidates
            if receipt.environment == "owner_live" and not receipt.verified
        ]
        if non_owner:
            detail = (
                f"only {len(non_owner)} verified ci/local receipt(s); CI proof is not "
                f"owner-hardware proof (OPS-03) — {row.hint}"
            )
        elif failed_live:
            latest = max(failed_live, key=lambda receipt: receipt.timestamp)
            detail = (
                f"owner_live receipt observed {latest.observed_state!r}, expected "
                f"{latest.expected_state!r} — {row.hint}"
            )
        elif have:
            detail = f"{have}/{row.required} owner_live target(s) recorded — {row.hint}"
        else:
            detail = f"no receipt recorded — {row.hint}"
        results.append(_row_result(row.name, FAIL, detail + suffix))
    return results


def check_evidence_receipts(*, store_root: Path | None = None, now: float | None = None) -> list[dict]:
    """Release-gate entry point: E11 owner rows read the receipts ledger, never ticks."""
    loaded = ReceiptStore(store_root).load()
    return evaluate_release_rows(loaded.receipts, now=now, rejected=loaded.rejected)


__all__ = [
    "AUTHORITY",
    "CI_ENV_MARKERS",
    "E11_ROWS",
    "ENVIRONMENTS",
    "METHODS",
    "RECEIPT_STALE_DAYS",
    "RUN_STATUSES",
    "SCHEMA",
    "EvidenceReceipt",
    "EvidenceRef",
    "EvidenceValue",
    "GateRow",
    "ReceiptEnvironmentRefused",
    "ReceiptLoad",
    "ReceiptStore",
    "check_evidence_receipts",
    "detect_environment",
    "evaluate_release_rows",
    "from_benchmark_run",
    "from_reality_run",
    "load_receipt_lines",
    "validate_receipt_environment",
]
