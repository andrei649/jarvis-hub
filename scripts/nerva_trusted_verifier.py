"""Candidate-side Step-2 reporting for the Nerva program manifest.

This module is deliberately NON-ENFORCING and permanently fail-closed:

- candidate repository code cannot authenticate itself,
- no candidate path, hash, signature, or trust anchor can grant source trust,
- no checker module is imported, compiled, or executed,
- structural validation and release readiness are always unavailable here,
- the CLI is informational and returns zero after producing a verdict.

The module may strictly decode the raw manifest and report its declared fields so
that a human can inspect them. Those fields are untrusted evidence labels, not an
authorization, execution, completion, or release decision. Real source
authentication and checker execution require a future Step-3 launcher whose code
and trust material are independently sourced outside the candidate repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ACTIVE_STATUSES = frozenset({"discovery", "building", "verifying"})
PROGRAM_STATES = frozenset({"not_started", "discovery", "building", "verifying", "blocked", "done"})
MANIFEST_RELATIVE = Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json")
STRUCTURAL_VALIDATION_ERROR = "structural validation unavailable in candidate-side Step 2"
SOURCE_TRUST_ERROR = "source authentication requires an independently sourced Step-3 launcher"


@dataclass(frozen=True)
class StreamAssessment:
    """Informational assessment of one untrusted manifest stream."""

    stream_id: str
    program_status: str
    delivery_eligibility: str
    derived_eligibility: str
    eligibility_matches: bool
    open_gate_count: int
    open_blocker_count: int
    evidence_count: int
    verdict_label: str


@dataclass(frozen=True)
class AuthorityPosture:
    """Declared authority block, reported as found (never sanitized)."""

    status_is_evidence_label_only: bool
    can_authorize: bool
    can_execute: bool
    completion_authority: bool
    release_ready: bool
    ultron_remains_sole_action_authority: bool

    @property
    def non_enforcing(self) -> bool:
        return (
            self.status_is_evidence_label_only
            and self.ultron_remains_sole_action_authority
            and not any(
                (
                    self.can_authorize,
                    self.can_execute,
                    self.completion_authority,
                    self.release_ready,
                )
            )
        )


@dataclass(frozen=True)
class ManifestVerdict:
    """A total, deterministic, fail-closed verdict over untrusted input."""

    manifest_id: str
    schema_version: int
    structurally_valid: bool
    errors: tuple[str, ...]
    streams: tuple[StreamAssessment, ...]
    authority: AuthorityPosture | None
    release_ready: bool
    all_streams_done: bool = False
    trusted_source: bool = False
    source_errors: tuple[str, ...] = ()
    render_current: bool | None = None


def verdict_label(program_status: str, derived_eligibility: str) -> str:
    """Map a status/eligibility pair to an informational label."""

    if program_status == "done":
        return "DONE" if derived_eligibility == "satisfied" else "PARTIAL"
    if program_status == "blocked":
        return "BLOCKED"
    if program_status in ACTIVE_STATUSES:
        return "BUILDING"
    if program_status == "not_started":
        return "OPEN" if derived_eligibility == "eligible" else "BLOCKED"
    return "UNKNOWN"


def _derive_eligibility(status: str, has_open_gate_or_blocker: bool) -> str:
    if status == "done":
        return "blocked" if has_open_gate_or_blocker else "satisfied"
    if status == "blocked":
        return "blocked"
    if status in ACTIVE_STATUSES:
        return "in_progress"
    return "blocked" if has_open_gate_or_blocker else "eligible"


def assess_stream(stream: Any) -> StreamAssessment:
    """Assess one raw stream without throwing on hostile shapes."""

    if not isinstance(stream, dict):
        return StreamAssessment(
            stream_id="?",
            program_status="unknown",
            delivery_eligibility="unknown",
            derived_eligibility="unknown",
            eligibility_matches=False,
            open_gate_count=0,
            open_blocker_count=0,
            evidence_count=0,
            verdict_label="UNKNOWN",
        )
    raw_id = stream.get("id")
    raw_status = stream.get("program_status")
    raw_eligibility = stream.get("delivery_eligibility")
    program_status = raw_status if isinstance(raw_status, str) else "unknown"
    delivery_eligibility = raw_eligibility if isinstance(raw_eligibility, str) else "unknown"
    edges = stream.get("delivery_prerequisites")
    open_gate_count = sum(
        1
        for edge in (edges if isinstance(edges, list) else [])
        if isinstance(edge, dict) and edge.get("gate_state") == "unsatisfied"
    )
    blockers = stream.get("blockers")
    open_blocker_count = len(blockers) if isinstance(blockers, list) else 0
    has_cause = open_gate_count > 0 or open_blocker_count > 0
    if program_status in PROGRAM_STATES:
        derived_eligibility = _derive_eligibility(program_status, has_cause)
    else:
        derived_eligibility = "unknown"
    evidence = stream.get("completion_evidence")
    evidence_count = len(evidence) if isinstance(evidence, list) else 0
    return StreamAssessment(
        stream_id=raw_id if isinstance(raw_id, str) else "?",
        program_status=program_status,
        delivery_eligibility=delivery_eligibility,
        derived_eligibility=derived_eligibility,
        eligibility_matches=(
            delivery_eligibility != "unknown"
            and derived_eligibility != "unknown"
            and delivery_eligibility == derived_eligibility
        ),
        open_gate_count=open_gate_count,
        open_blocker_count=open_blocker_count,
        evidence_count=evidence_count,
        verdict_label=verdict_label(program_status, derived_eligibility),
    )


def read_authority(data: Any) -> AuthorityPosture | None:
    """Report the declared authority block; absent booleans fail closed."""

    raw = data.get("authority") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    return AuthorityPosture(
        status_is_evidence_label_only=raw.get("status_is_evidence_label_only", False) is True,
        can_authorize=raw.get("can_authorize", False) is True,
        can_execute=raw.get("can_execute", False) is True,
        completion_authority=raw.get("completion_authority", False) is True,
        release_ready=raw.get("release_ready", False) is True,
        ultron_remains_sole_action_authority=(
            raw.get("ultron_remains_sole_action_authority", False) is True
        ),
    )


def _strict_json_data(path: Path) -> Any:
    """Read strict JSON without duplicate keys or non-finite numbers."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


def _informational_verdict(
    data: Any, *, errors: tuple[str, ...] = (STRUCTURAL_VALIDATION_ERROR,)
) -> ManifestVerdict:
    if isinstance(data, dict):
        raw_id = data.get("manifest_id")
        raw_version = data.get("schema_version")
        raw_streams = data.get("streams")
        manifest_id = raw_id if isinstance(raw_id, str) else ""
        schema_version = raw_version if type(raw_version) is int else 0
        streams = tuple(
            assess_stream(item) for item in (raw_streams if isinstance(raw_streams, list) else ())
        )
        authority = read_authority(data)
    else:
        manifest_id = ""
        schema_version = 0
        streams = ()
        authority = None
    all_streams_done = bool(streams) and all(item.verdict_label == "DONE" for item in streams)
    return ManifestVerdict(
        manifest_id=manifest_id,
        schema_version=schema_version,
        structurally_valid=False,
        errors=errors,
        streams=streams,
        authority=authority,
        release_ready=False,
        all_streams_done=all_streams_done,
        trusted_source=False,
        source_errors=(SOURCE_TRUST_ERROR,),
        render_current=None,
    )


def verify_data(data: Any) -> ManifestVerdict:
    """Return a total informational verdict; never authenticate candidate code."""

    return _informational_verdict(data)


def verify_path(manifest_path: Path) -> ManifestVerdict:
    """Strictly load raw JSON, while keeping source and structure untrusted."""

    try:
        data = _strict_json_data(manifest_path)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        return _informational_verdict(
            None,
            errors=(
                STRUCTURAL_VALIDATION_ERROR,
                f"failed to load manifest: {exc}",
            ),
        )
    return _informational_verdict(data)


def _ascii_cli_value(value: object) -> str:
    """Escape one untrusted value as ASCII without embedded line breaks."""

    encoded = json.dumps(str(value), ensure_ascii=True)
    return encoded[1:-1]


def _print_verdict(verdict: ManifestVerdict) -> None:
    labels = ("DONE", "BUILDING", "OPEN", "BLOCKED", "PARTIAL", "UNKNOWN")
    counts = [sum(1 for item in verdict.streams if item.verdict_label == label) for label in labels]
    print(f"manifest_id={_ascii_cli_value(verdict.manifest_id or '(unreadable)')}")
    print(f"schema_version={_ascii_cli_value(verdict.schema_version)}")
    print(f"structurally_valid={'yes' if verdict.structurally_valid else 'no'}")
    print(f"release_ready={'yes' if verdict.release_ready else 'no'}")
    print(f"all_streams_done={'yes' if verdict.all_streams_done else 'no'}")
    print(f"trusted_source={'yes' if verdict.trusted_source else 'no'}")
    for error in verdict.source_errors:
        print(f"source-error: {_ascii_cli_value(error)}")
    if verdict.authority is not None:
        posture = (
            "declares_non_enforcing"
            if verdict.authority.non_enforcing
            else "declares_other_authority"
        )
        print(f"authority={posture}")
    else:
        print("authority=missing")
    if verdict.streams:
        print(
            "declared_verdicts="
            + ",".join(f"{label}:{count}" for label, count in zip(labels, counts, strict=True))
        )
        for item in verdict.streams:
            print(
                f"{_ascii_cli_value(item.stream_id)}: "
                f"{_ascii_cli_value(item.verdict_label)} "
                f"status={_ascii_cli_value(item.program_status)} "
                f"eligibility={_ascii_cli_value(item.delivery_eligibility)} "
                f"derived={_ascii_cli_value(item.derived_eligibility)} "
                f"open_gates={_ascii_cli_value(item.open_gate_count)} "
                f"open_blockers={_ascii_cli_value(item.open_blocker_count)} "
                f"evidence={_ascii_cli_value(item.evidence_count)}"
            )
    for error in verdict.errors:
        print(f"error: {_ascii_cli_value(error)}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=REPO / MANIFEST_RELATIVE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    _print_verdict(verify_path(args.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
