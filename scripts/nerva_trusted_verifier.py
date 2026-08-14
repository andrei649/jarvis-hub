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
only after an explicit ``--trust-anchor`` outside the candidate repository
authenticates both this verifier and ``check_nerva_program_manifest``. The
checker is compiled from the authenticated byte snapshot instead of imported
before trust is established. With no accepted external anchor, source trust
and structural validation fail closed. A later control-plane step remains
responsible for provisioning and protecting the anchor itself.

After source authentication, the verifier reuses the canonical loader and
validator primitives and reports an honest per-stream verdict
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
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ACTIVE_STATUSES = frozenset({"discovery", "building", "verifying"})
PROGRAM_STATES = frozenset(
    {"not_started", "discovery", "building", "verifying", "blocked", "done"}
)
MANIFEST_RELATIVE = Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json")
DOCUMENT_RELATIVE = Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md")
REGISTRY_RELATIVE = Path("docs/nerva2/CONTRACT_REGISTRY.json")
VERIFIER_RELATIVE = Path("scripts/nerva_trusted_verifier.py")
CHECKER_RELATIVE = Path("scripts/check_nerva_program_manifest.py")
TRUSTED_SOURCE_PATHS = (VERIFIER_RELATIVE, CHECKER_RELATIVE)


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
    trusted_source: bool = False
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


def _derive_eligibility(status: str, has_open_gate_or_blocker: bool) -> str:
    if status == "done":
        return "blocked" if has_open_gate_or_blocker else "satisfied"
    if status == "blocked":
        return "blocked"
    if status in ACTIVE_STATUSES:
        return "in_progress"
    return "blocked" if has_open_gate_or_blocker else "eligible"


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
            raw.get("ultron_remains_sole_action_authority", False) is True
        ),
    )


def _normalized_source_bytes(path: Path) -> tuple[bytes, str]:
    """Return LF-normalized source bytes plus a stable SHA-256 digest."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return raw, hashlib.sha256(raw).hexdigest()


def _strict_json_data(path: Path) -> Any:
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


def _trusted_checker(
    *, root: Path, trust_anchor_path: Path | None
) -> tuple[ModuleType | None, tuple[str, ...]]:
    """Authenticate source bytes as data, then execute the accepted checker snapshot."""

    if trust_anchor_path is None:
        return None, ("external trust anchor is required",)
    try:
        canonical_root = root.resolve(strict=True)
        canonical_anchor = trust_anchor_path.resolve(strict=True)
    except OSError as exc:
        return None, (f"trust anchor or repository root unreadable: {exc}",)
    if canonical_anchor.is_relative_to(canonical_root):
        return None, ("trust anchor must be outside the candidate repository",)

    try:
        anchor = _strict_json_data(canonical_anchor)
    except (OSError, UnicodeError, ValueError) as exc:
        return None, (f"trust anchor unreadable or invalid: {exc}",)
    expected_top = {"schema_version", "sources"}
    if not isinstance(anchor, dict) or set(anchor) != expected_top:
        return None, ("trust anchor must contain exactly schema_version and sources",)
    if anchor.get("schema_version") != 1:
        return None, ("unsupported trust anchor schema_version",)
    sources = anchor.get("sources")
    expected_paths = {path.as_posix() for path in TRUSTED_SOURCE_PATHS}
    if not isinstance(sources, dict) or set(sources) != expected_paths:
        return None, ("trust anchor source inventory is incomplete or has unknown paths",)

    accepted: dict[str, bytes] = {}
    errors: list[str] = []
    for relative in TRUSTED_SOURCE_PATHS:
        label = relative.as_posix()
        expected = sources.get(label)
        if not (
            isinstance(expected, str)
            and len(expected) == 64
            and all(character in "0123456789abcdef" for character in expected)
        ):
            errors.append(f"{label}: invalid sha256")
            continue
        source_path = canonical_root / relative
        try:
            normalized, digest = _normalized_source_bytes(source_path)
        except (OSError, ValueError) as exc:
            errors.append(f"{label}: unreadable: {exc}")
            continue
        if digest != expected:
            errors.append(f"{label}: sha256 mismatch: expected {expected}, got {digest}")
            continue
        accepted[label] = normalized
    if errors:
        return None, tuple(errors)

    checker_path = canonical_root / CHECKER_RELATIVE
    checker = ModuleType("_nerva_trusted_checker_snapshot")
    checker.__file__ = str(checker_path)
    try:
        code = compile(accepted[CHECKER_RELATIVE.as_posix()], str(checker_path), "exec")
        exec(code, checker.__dict__)  # noqa: S102 - exact externally authenticated snapshot
    except Exception as exc:
        return None, (f"trusted checker snapshot failed to load: {exc}",)
    return checker, ()


def verify_trusted_source(
    *, root: Path = REPO, trust_anchor_path: Path | None = None
) -> tuple[bool, tuple[str, ...]]:
    """Report whether the supplied external anchor authenticates both snapshots.

    This Step-2 function verifies content binding, not the caller's authority to
    provision the anchor. Protecting that input belongs to the separate Step-3
    control-plane package.
    """

    checker, errors = _trusted_checker(root=root, trust_anchor_path=trust_anchor_path)
    return checker is not None, errors


def verify_data(
    data: Any,
    *,
    registry: Any = None,
    root: Path = REPO,
    verify_git: bool = False,
    trust_anchor_path: Path | None = None,
) -> ManifestVerdict:
    """Verify an already-parsed manifest value and return a total verdict."""

    checker, source_errors = _trusted_checker(
        root=root, trust_anchor_path=trust_anchor_path
    )
    if checker is None:
        return ManifestVerdict(
            manifest_id="",
            schema_version=0,
            structurally_valid=False,
            errors=("structural validation unavailable without a trusted checker",),
            streams=(),
            authority=None,
            release_ready=False,
            trusted_source=False,
            source_errors=source_errors,
        )
    return _verify_data_with_checker(
        data,
        checker=checker,
        registry=registry,
        root=root,
        verify_git=verify_git,
    )


def _verify_data_with_checker(
    data: Any,
    *,
    checker: ModuleType,
    registry: Any,
    root: Path,
    verify_git: bool,
) -> ManifestVerdict:
    if registry is None:
        registry = checker.load_json_strict(root / REGISTRY_RELATIVE)
    errors = checker.validate_manifest(
        data, root=root, registry=registry, verify_git=verify_git
    )
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
    return ManifestVerdict(
        manifest_id=manifest_id,
        schema_version=schema_version,
        structurally_valid=structurally_valid,
        errors=tuple(errors),
        streams=streams,
        authority=authority,
        release_ready=release_ready,
        all_streams_done=all_streams_done,
        trusted_source=True,
        source_errors=(),
        render_current=None,
    )


def render_markdown(
    data: Any,
    *,
    root: Path = REPO,
    trust_anchor_path: Path | None = None,
) -> str:
    """Render only through an externally authenticated checker snapshot."""

    checker, errors = _trusted_checker(root=root, trust_anchor_path=trust_anchor_path)
    if checker is None:
        raise ValueError("trusted checker unavailable: " + "; ".join(errors))
    return checker.render_markdown(data)


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
    trust_anchor_path: Path | None = None,
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
                trusted_source=False,
                source_errors=("source trust not evaluated without a repository root",),
            )
    checker, source_errors = _trusted_checker(
        root=root, trust_anchor_path=trust_anchor_path
    )
    if checker is None:
        return ManifestVerdict(
            manifest_id="",
            schema_version=0,
            structurally_valid=False,
            errors=("structural validation unavailable without a trusted checker",),
            streams=(),
            authority=None,
            release_ready=False,
            trusted_source=False,
            source_errors=source_errors,
            render_current=None,
        )
    if registry_path is None:
        registry_path = root / REGISTRY_RELATIVE
    try:
        data = checker.load_json_strict(manifest_path)
        registry = checker.load_json_strict(registry_path)
    except (OSError, ValueError, checker.ManifestError) as exc:
        return ManifestVerdict(
            manifest_id="",
            schema_version=0,
            structurally_valid=False,
            errors=(f"failed to load manifest or registry: {exc}",),
            streams=(),
            authority=None,
            release_ready=False,
            trusted_source=True,
            source_errors=(),
            render_current=None,
        )
    verdict = _verify_data_with_checker(
        data,
        checker=checker,
        registry=registry,
        root=root,
        verify_git=verify_git,
    )
    render_current: bool | None = None
    if verdict.structurally_valid and document_path is not None:
        try:
            render_current = checker.render_markdown(data) == document_path.read_text(
                encoding="utf-8"
            )
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
    parser.add_argument(
        "--trust-anchor",
        type=Path,
        default=None,
        help="strict trusted-source manifest located outside the candidate repository",
    )
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
        trust_anchor_path=args.trust_anchor,
    )
    _print_verdict(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
