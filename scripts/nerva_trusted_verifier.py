"""B2 trusted-verifier bootstrap for the Nerva 2.0 program manifest.

This module is deliberately NON-ENFORCING and read-only:

- it never activates or requires any check, workflow, rule, or status,
- it never writes or mutates repository state,
- it never calls GitHub and never grants or claims execution authority,
- its CLI exit code is always 0 for a produced verdict (a verdict is a
  report, not a gate); exit 0 is informational and must never be wired as
  a CI gate.

It performs strict, deterministic, fail-closed verification of the offline
Nerva v1 program manifest (``docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json``)
by reusing the canonical loader and validator primitives from
``check_nerva_program_manifest``, then reports an honest per-stream verdict
(``DONE``/``BUILDING``/``OPEN``/``BLOCKED``/``PARTIAL``/``UNKNOWN``), the
declared authority posture, whether release readiness is derived, and whether
the generated Markdown is byte-identical to the committed document.

Hostile input (non-object roots, unknown fields, contradictory eligibility,
forged authority, duplicate JSON keys, non-finite numbers, missing files)
produces a failed verdict instead of raising, so a human or later live step
can audit why the manifest is not trustworthy.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from check_nerva_program_manifest import (
    DOCUMENT_RELATIVE,
    MANIFEST_RELATIVE,
    PROGRAM_STATES,
    REGISTRY_RELATIVE,
    ManifestError,
    _derive_eligibility,
    load_json_strict,
    render_markdown,
    validate_manifest,
)

REPO = Path(__file__).resolve().parent.parent
ACTIVE_STATUSES = frozenset({"discovery", "building", "verifying"})

_CHECKER_SHA256 = "a57c2d06fcecf75b3b693733e6d7fa2059190752365c85086c2972c0dcd3af58"
_SELF_PIN = b'_VERIFIER_SHA256 = "<self>"'
_SELF_PIN_RE = re.compile(rb'_VERIFIER_SHA256\s*=\s*"[0-9a-f]{64}"')
_VERIFIER_SHA256 = "a1b4e3381717e826329af0070b85e4b30f5f526dc408973a90df3c4010e9e0d8"


@dataclass(frozen=True)
class StreamAssessment:
    """Honest, independently-derived verdict for a single program stream."""

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
    """A total, deterministic verdict over the manifest (never raises)."""

    manifest_id: str
    schema_version: int
    structurally_valid: bool
    errors: tuple[str, ...]
    streams: tuple[StreamAssessment, ...]
    authority: AuthorityPosture | None
    release_ready: bool
    all_streams_done: bool = False
    trusted_source: bool = True
    source_errors: tuple[str, ...] = ()
    render_current: bool | None = None


def verdict_label(program_status: str, derived_eligibility: str) -> str:
    """Map a (program status, derived eligibility) pair to a human verdict label."""

    if program_status == "done":
        return "DONE" if derived_eligibility == "satisfied" else "PARTIAL"
    if program_status == "blocked":
        return "BLOCKED"
    if program_status in ACTIVE_STATUSES:
        return "BUILDING"
    if program_status == "not_started":
        return "OPEN" if derived_eligibility == "eligible" else "BLOCKED"
    return "UNKNOWN"


def assess_stream(stream: Any) -> StreamAssessment:
    """Assess one stream without throwing on hostile shapes."""

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
    """Report the declared authority block as found; ``None`` when absent."""

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
            raw.get("ultron_remains_sole_action_authority", True) is True
        ),
    )


def _normalized_source_bytes(path: Path) -> tuple[bytes, str]:
    """Return LF-normalized source bytes plus a stable digest for a file.

    The verifier's own digest is computed over the file with its self-pin
    literal blanked out, so embedding the accepted digest never circularly
    changes the value that must match it.
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if path.resolve() == Path(__file__).resolve():
        raw = _SELF_PIN_RE.sub(_SELF_PIN, raw)
    return raw, hashlib.sha256(raw).hexdigest()


def verify_trusted_source() -> tuple[bool, tuple[str, ...]]:
    """Verify that the accepted verifier/checker bytes match the pins.

    Anti-counterfeit proof: the verifier and the canonical checker must be
    byte-identical (LF-normalized) to the versions accepted at release time.
    Returns ``(trusted, errors)``; a failure is reported, never enforced.
    """
    errors: list[str] = []
    for label, path, expected in (
        ("checker", Path(checker_module.__file__), _CHECKER_SHA256),
        ("verifier", Path(__file__), _VERIFIER_SHA256),
    ):
        try:
            _normalized, digest = _normalized_source_bytes(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{label} unreadable: {exc}")
            continue
        if digest != expected:
            errors.append(f"{label} sha256 mismatch: expected {expected}, got {digest}")
    return (not errors, tuple(errors))


def verify_data(
    data: Any,
    *,
    registry: Any = None,
    root: Path = REPO,
    verify_git: bool = False,
) -> ManifestVerdict:
    """Verify an already-parsed manifest value and return a total verdict."""

    if registry is None:
        registry = load_json_strict(root / REGISTRY_RELATIVE)
    errors = validate_manifest(data, root=root, registry=registry, verify_git=verify_git)
    structurally_valid = not errors
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
    release_ready = (
        structurally_valid
        and all_streams_done
        and authority is not None
        and authority.release_ready is True
    )
    trusted_source, source_errors = verify_trusted_source()
    return ManifestVerdict(
        manifest_id=manifest_id,
        schema_version=schema_version,
        structurally_valid=structurally_valid,
        errors=tuple(errors),
        streams=streams,
        authority=authority,
        release_ready=release_ready,
        all_streams_done=all_streams_done,
        trusted_source=trusted_source,
        source_errors=source_errors,
        render_current=None,
    )


def _discover_repo_root(manifest_path: Path) -> Path | None:
    """Walk upward from the manifest to find the repository root.

    The root is the nearest ancestor containing a ``.git`` entry (a directory
    in a working copy, or a ``gitdir:`` file in a linked worktree). ``None``
    when no repository is discoverable.
    """
    current = manifest_path.resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def verify_path(
    manifest_path: Path,
    *,
    registry_path: Path | None = None,
    document_path: Path | None = None,
    root: Path | None = None,
    verify_git: bool = False,
) -> ManifestVerdict:
    """Verify a manifest from disk, failing closed on unreadable input."""

    if root is None:
        root = _discover_repo_root(manifest_path)
        if root is None:
            return ManifestVerdict(
                manifest_id="",
                schema_version=0,
                structurally_valid=False,
                errors=(f"unable to discover repository root from {manifest_path}",),
                streams=(),
                authority=None,
                release_ready=False,
            )
    if registry_path is None:
        registry_path = root / REGISTRY_RELATIVE
    try:
        data = load_json_strict(manifest_path)
        registry = load_json_strict(registry_path)
    except (OSError, ValueError, ManifestError) as exc:
        return ManifestVerdict(
            manifest_id="",
            schema_version=0,
            structurally_valid=False,
            errors=(f"failed to load manifest or registry: {exc}",),
            streams=(),
            authority=None,
            release_ready=False,
            render_current=None,
        )
    verdict = verify_data(data, registry=registry, root=root, verify_git=verify_git)
    render_current: bool | None = None
    if verdict.structurally_valid and document_path is not None:
        try:
            render_current = render_markdown(data) == document_path.read_text(encoding="utf-8")
        except (KeyError, TypeError, UnicodeError, OSError):
            render_current = None
    return replace(verdict, render_current=render_current)


def _print_verdict(verdict: ManifestVerdict) -> None:
    labels = ("DONE", "BUILDING", "OPEN", "BLOCKED", "PARTIAL", "UNKNOWN")
    counts = [sum(1 for item in verdict.streams if item.verdict_label == label) for label in labels]
    print(f"manifest_id={verdict.manifest_id or '(unreadable)'}")
    print(f"schema_version={verdict.schema_version}")
    print(f"structurally_valid={'yes' if verdict.structurally_valid else 'no'}")
    print(f"release_ready={'yes' if verdict.release_ready else 'no'}")
    print(f"all_streams_done={'yes' if verdict.all_streams_done else 'no'}")
    print(f"trusted_source={'yes' if verdict.trusted_source else 'no'}")
    if verdict.source_errors:
        for error in verdict.source_errors:
            print(f"source-error: {error}")
    if verdict.authority is not None:
        posture = "non_enforcing" if verdict.authority.non_enforcing else "reports_authority"
        print(f"authority={posture}")
    else:
        print("authority=missing")
    if verdict.streams:
        summary = ", ".join(
            f"{label}={count}" for label, count in zip(labels, counts, strict=True) if count
        )
        print(f"streams={len(verdict.streams)} ({summary})")
    if verdict.render_current is not None:
        print(f"render_current={'yes' if verdict.render_current else 'no'}")
    if verdict.errors:
        print("errors:")
        for error in verdict.errors:
            print(f"- {error}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=REPO / MANIFEST_RELATIVE)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--document", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root if args.root is not None else REPO
    document = args.document if args.document is not None else root / DOCUMENT_RELATIVE
    verdict = verify_path(
        args.manifest,
        registry_path=args.registry,
        document_path=document,
        root=root,
        verify_git=False,
    )
    _print_verdict(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
