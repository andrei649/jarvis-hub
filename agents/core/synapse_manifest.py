"""Versioned Synapse capability contract and compatibility adapters.

The contract describes capabilities for planning, conformance, and evidence review.
It never grants permission, promotes packages, or bypasses the Action Kernel.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from agents.core.capability_manifests import (
    RISK_LEVELS,
    CapabilityManifest,
    RollbackContract,
)

SCHEMA_VERSION = "nerva.capability.v1"
READINESS_LEVELS = (
    "unknown",
    "discovered",
    "declared",
    "sandboxed",
    "hermetic_verified",
    "live_verified",
    "reliable",
)
PRIVACY_CLASSES = frozenset({"public", "local", "sensitive", "restricted"})
APPROVAL_LEVELS = ("none", "session", "explicit", "permanent_owner")
APPROVAL_FLOORS = frozenset(APPROVAL_LEVELS)
MINIMUM_APPROVAL = {
    "read_only": "none",
    "reversible": "session",
    "sensitive": "explicit",
    "irreversible_or_money": "permanent_owner",
}
TRUST_STATES = frozenset({"builtin", "signed", "quarantined"})
UNKNOWN = "unknown"
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CAPABILITY_ID = re.compile(
    r"^[a-z][a-z0-9_-]*:[a-z0-9](?:[a-z0-9._*-]*[a-z0-9*])?$"
)
_PACKAGE_DIGEST = re.compile(r"^(?:sha256|hmac-sha256):[0-9a-f]{64}$")
_AUTHENTICATED_PACKAGE_DIGEST = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class FailureSemantics:
    codes: tuple[str, ...]
    retryable: bool | str
    partial_effects_possible: bool | str
    description: str


@dataclass(frozen=True)
class PermissionContract:
    required: tuple[str, ...]
    privacy_class: str
    risk: str
    approval_floor: str
    grants_authority: bool = False


@dataclass(frozen=True)
class ExecutorContract:
    implementation: str
    environments: tuple[str, ...]
    credentials: tuple[str, ...] = ()
    hardware: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifierContract:
    verifier_ref: str
    evidence_refs: tuple[str, ...] = ()
    last_verified_at: str | None = None


@dataclass(frozen=True)
class TelemetryContract:
    reliability: float | None = None
    latency_ms_p50: float | None = None
    cost_per_call: float | None = None
    measurement_source: str = UNKNOWN


@dataclass(frozen=True)
class ProvenanceContract:
    source_ref: str
    maintainer: str
    trust_state: str
    generated: bool = False
    package_digest: str | None = None


@dataclass(frozen=True)
class SynapseManifest:
    schema_version: str
    capability_version: str
    id: str
    description: str
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    preconditions: tuple[str, ...]
    effects: tuple[str, ...]
    failure: FailureSemantics
    permissions: PermissionContract
    executor: ExecutorContract
    verifier: VerifierContract
    rollback: RollbackContract
    telemetry: TelemetryContract
    provenance: ProvenanceContract
    readiness: str = "declared"
    source_kind: str = "legacy_manifest"

    def __post_init__(self) -> None:
        validate_synapse_manifest(self)
        object.__setattr__(self, "inputs", _freeze_json(self.inputs))
        object.__setattr__(self, "outputs", _freeze_json(self.outputs))

    def to_payload(self) -> dict[str, Any]:
        """Return the deterministic JSON-compatible v1 representation."""
        encoded = json.dumps(
            _contract_payload(self),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise ValueError("Synapse payload must be a JSON object")
        return payload


@dataclass(frozen=True)
class ManifestRevision:
    """Atomic candidate change with an exact in-memory rollback value."""

    previous: SynapseManifest
    candidate: SynapseManifest

    def __post_init__(self) -> None:
        if not isinstance(self.previous, SynapseManifest) or not isinstance(
            self.candidate, SynapseManifest
        ):
            raise ValueError("manifest revision values must be Synapse manifests")
        if self.previous.id != self.candidate.id:
            raise ValueError("manifest revision cannot change capability id")
        if self.previous == self.candidate:
            raise ValueError("manifest revision must change the candidate")

    def rollback(self) -> SynapseManifest:
        return self.previous


def validate_synapse_manifest(manifest: SynapseManifest) -> SynapseManifest:
    """Fail closed on incomplete authority, evidence, and rollback declarations."""
    if not isinstance(manifest, SynapseManifest):
        raise ValueError("Synapse validation requires a SynapseManifest")
    if manifest.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported capability schema: {manifest.schema_version}")
    if not isinstance(manifest.capability_version, str) or not _SEMVER.fullmatch(
        manifest.capability_version
    ):
        raise ValueError("capability_version must be semantic version x.y.z")
    if not isinstance(manifest.id, str) or not isinstance(manifest.description, str):
        raise ValueError("capability id and description must be strings")
    if _CAPABILITY_ID.fullmatch(manifest.id) is None:
        raise ValueError("capability id must use canonical namespace:name syntax")
    if not manifest.description.strip():
        raise ValueError("capability description is required")
    _validate_schema(manifest.inputs, "inputs")
    _validate_schema(manifest.outputs, "outputs")
    _non_empty_strings(manifest.preconditions, "preconditions")
    _non_empty_strings(manifest.effects, "effects")
    if not isinstance(manifest.failure, FailureSemantics):
        raise ValueError("failure semantics declaration is required")
    if not isinstance(manifest.permissions, PermissionContract):
        raise ValueError("permission declaration is required")
    _validate_failure(manifest.failure)
    _validate_permissions(manifest.permissions)
    if manifest.id.startswith("action:") and "action-kernel" not in manifest.permissions.required:
        raise ValueError("action capability permissions must include action-kernel")
    if not isinstance(manifest.executor, ExecutorContract):
        raise ValueError("executor declaration is required")
    if not isinstance(manifest.verifier, VerifierContract):
        raise ValueError("verifier declaration is required")
    if not isinstance(manifest.telemetry, TelemetryContract):
        raise ValueError("telemetry declaration is required")
    if not isinstance(manifest.provenance, ProvenanceContract):
        raise ValueError("provenance declaration is required")
    _validate_executor(manifest.executor)
    _validate_verifier(manifest.verifier)
    _validate_telemetry(manifest.telemetry)
    _validate_provenance(manifest.provenance)
    if not isinstance(manifest.rollback, RollbackContract):
        raise ValueError("rollback declaration is required")
    _validate_rollback(manifest.rollback)
    if not isinstance(manifest.readiness, str) or manifest.readiness not in READINESS_LEVELS:
        raise ValueError(f"unsupported readiness: {manifest.readiness}")
    _validate_readiness_evidence(manifest)
    if not isinstance(manifest.source_kind, str) or not manifest.source_kind.strip():
        raise ValueError("source_kind is required")
    return manifest


def adapt_capability_manifest(
    manifest: CapabilityManifest,
    *,
    capability_version: str = "1.0.0",
    outputs: Mapping[str, Any] | None = None,
    preconditions: tuple[str, ...] | None = None,
    effects: tuple[str, ...] | None = None,
    failure: FailureSemantics | None = None,
    privacy_class: str | None = None,
    approval_floor: str | None = None,
    environments: tuple[str, ...] = ("local",),
    credentials: tuple[str, ...] = (),
    hardware: tuple[str, ...] = (),
    source_ref: str = "agents.core.capability_manifests",
    maintainer: str = "jarvis-hub",
    trust_state: str = "builtin",
    generated: bool = False,
    package_digest: str | None = None,
) -> SynapseManifest:
    """Adapt a current manifest without claiming runtime verification or authority."""
    if not isinstance(manifest, CapabilityManifest):
        raise ValueError("manifest adapter requires a CapabilityManifest")
    if outputs is not None and not isinstance(outputs, Mapping):
        raise ValueError("outputs override must be a mapping")
    return SynapseManifest(
        schema_version=SCHEMA_VERSION,
        capability_version=capability_version,
        id=manifest.id,
        description=manifest.description,
        inputs=dict(manifest.inputs),
        outputs=dict(outputs)
        if outputs is not None
        else {"type": "object", "additionalProperties": True},
        preconditions=preconditions if preconditions is not None else tuple(manifest.requires),
        effects=effects if effects is not None else tuple(manifest.supports),
        failure=failure
        if failure is not None
        else FailureSemantics(
            codes=(UNKNOWN,),
            retryable=UNKNOWN,
            partial_effects_possible=UNKNOWN,
            description="Legacy manifest does not yet expose typed failure semantics.",
        ),
        permissions=PermissionContract(
            required=tuple(manifest.requires),
            privacy_class=(
                privacy_class if privacy_class is not None else _privacy_for_risk(manifest.risk)
            ),
            risk=manifest.risk,
            approval_floor=(
                approval_floor if approval_floor is not None else _approval_for_risk(manifest.risk)
            ),
            grants_authority=False,
        ),
        executor=ExecutorContract(
            implementation=manifest.implementation,
            environments=environments,
            credentials=credentials,
            hardware=hardware,
        ),
        verifier=VerifierContract(verifier_ref=manifest.verification),
        rollback=manifest.rollback,
        telemetry=TelemetryContract(),
        provenance=ProvenanceContract(
            source_ref=source_ref,
            maintainer=maintainer,
            trust_state=trust_state,
            generated=generated,
            package_digest=package_digest,
        ),
        readiness="discovered" if generated else "declared",
        source_kind="legacy_manifest",
    )


def adapt_capability_record(
    record: Any,
    *,
    capability_version: str = "1.0.0",
    outputs: Mapping[str, Any] | None = None,
) -> SynapseManifest:
    """Project a Capability Registry record without overstating its evidence level."""
    _validate_record_shape(record)
    manifest = CapabilityManifest(
        id=record.id,
        description=record.description,
        inputs=dict(record.inputs),
        risk=record.risk,
        requires=record.requires,
        supports=record.supports,
        verification=record.verification,
        rollback=record.rollback,
        confidence=record.confidence,
        implementation=record.implementation,
        contract_ref=getattr(record, "contract_ref", None),
    )
    result = adapt_capability_manifest(
        manifest,
        capability_version=capability_version,
        outputs=outputs,
        source_ref="agents.core.observability.capability_registry",
    )
    state = getattr(record, "state", "missing")
    harness_id = getattr(record, "harness_id", None)
    last_verified = getattr(record, "last_verified", None)
    readiness, evidence_refs = _readiness_from_registry(state, harness_id, last_verified)
    return replace(
        result,
        readiness=readiness,
        verifier=replace(
            result.verifier,
            evidence_refs=evidence_refs,
            last_verified_at=last_verified if evidence_refs else None,
        ),
        source_kind=f"capability_record:{record.kind}",
    )


def _validate_record_shape(record: Any) -> None:
    string_fields = ("id", "kind", "description", "risk", "verification", "implementation")
    for field in string_fields:
        value = getattr(record, field, None)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"capability record {field} must be a non-empty string")
    if not isinstance(getattr(record, "inputs", None), Mapping):
        raise ValueError("capability record inputs must be a mapping")
    for field in ("requires", "supports"):
        value = getattr(record, field, None)
        if not isinstance(value, tuple):
            raise ValueError(f"capability record {field} must be a tuple")
    confidence = getattr(record, "confidence", None)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("capability record confidence must be numeric")
    if not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        raise ValueError("capability record confidence must be finite and between zero and one")
    if not isinstance(getattr(record, "rollback", None), RollbackContract):
        raise ValueError("capability record rollback must be declared")
    contract_ref = getattr(record, "contract_ref", None)
    if contract_ref is not None and (not isinstance(contract_ref, str) or not contract_ref.strip()):
        raise ValueError("capability record contract_ref must be a non-empty string or null")


def _readiness_from_registry(
    state: str,
    harness_id: str | None,
    last_verified: str | None,
) -> tuple[str, tuple[str, ...]]:
    if not isinstance(state, str):
        raise ValueError("capability registry state must be a string")
    if harness_id is not None and (not isinstance(harness_id, str) or not harness_id.strip()):
        raise ValueError("capability registry harness_id must be a non-empty string or null")
    if last_verified is not None and (
        not isinstance(last_verified, str) or not last_verified.strip()
    ):
        raise ValueError("capability registry last_verified must be a non-empty string or null")
    if state == "missing":
        return "unknown", ()
    if state in {"seam", "wired"}:
        return "declared", ()
    if state in {"verified", "ga"}:
        if not harness_id or not last_verified:
            raise ValueError("verified registry state requires harness evidence")
        return "hermetic_verified", (f"reality-harness:{harness_id}",)
    raise ValueError(f"unsupported registry state: {state}")


def _validate_readiness_evidence(manifest: SynapseManifest) -> None:
    rank = READINESS_LEVELS.index(manifest.readiness)
    sandbox_rank = READINESS_LEVELS.index("sandboxed")
    hermetic_rank = READINESS_LEVELS.index("hermetic_verified")
    live_rank = READINESS_LEVELS.index("live_verified")
    refs = manifest.verifier.evidence_refs
    if rank >= sandbox_rank:
        if not refs or not manifest.verifier.last_verified_at:
            raise ValueError("sandboxed readiness requires dated evidence")
        if not any(
            ref.startswith(("sandbox:", "reality-harness:", "owner-live:"))
            for ref in refs
        ):
            raise ValueError("sandboxed readiness requires sandbox evidence")
    if rank >= hermetic_rank and not any(ref.startswith("reality-harness:") for ref in refs):
        raise ValueError("hermetic readiness requires reality-harness evidence")
    if rank >= live_rank and not any(ref.startswith("owner-live:") for ref in refs):
        raise ValueError("live readiness requires owner-live evidence")
    if manifest.readiness == "reliable" and manifest.telemetry.reliability is None:
        raise ValueError("reliable readiness requires measured reliability")


def _validate_failure(value: FailureSemantics) -> None:
    _non_empty_strings(value.codes, "failure codes")
    if not isinstance(value.retryable, bool) and not (
        isinstance(value.retryable, str) and value.retryable == UNKNOWN
    ):
        raise ValueError("failure retryable must be boolean or unknown")
    if not isinstance(value.partial_effects_possible, bool) and not (
        isinstance(value.partial_effects_possible, str)
        and value.partial_effects_possible == UNKNOWN
    ):
        raise ValueError("partial-effects flag must be boolean or unknown")
    if not isinstance(value.description, str) or not value.description.strip():
        raise ValueError("failure description is required")


def _validate_permissions(value: PermissionContract) -> None:
    _non_empty_strings(value.required, "permissions")
    if not isinstance(value.privacy_class, str) or value.privacy_class not in PRIVACY_CLASSES:
        raise ValueError(f"unsupported privacy class: {value.privacy_class}")
    if not isinstance(value.risk, str) or value.risk not in RISK_LEVELS:
        raise ValueError(f"unsupported capability risk: {value.risk}")
    if not isinstance(value.approval_floor, str) or value.approval_floor not in APPROVAL_FLOORS:
        raise ValueError(f"unsupported approval floor: {value.approval_floor}")
    if value.grants_authority is not False:
        raise ValueError("capability manifests describe permission and never grant authority")
    minimum = MINIMUM_APPROVAL[value.risk]
    if APPROVAL_LEVELS.index(value.approval_floor) < APPROVAL_LEVELS.index(minimum):
        raise ValueError(f"approval floor is below the minimum for risk {value.risk}")


def _validate_rollback(value: RollbackContract) -> None:
    if not isinstance(value.automatic, bool):
        raise ValueError("rollback automatic flag must be boolean")
    if value.handler_ref is not None and (
        not isinstance(value.handler_ref, str) or not value.handler_ref.strip()
    ):
        raise ValueError("rollback handler reference must be a non-empty string or null")
    if not isinstance(value.limitations, str):
        raise ValueError("rollback limitations must be a string")


def _validate_executor(value: ExecutorContract) -> None:
    implementation = value.implementation
    if not isinstance(implementation, str) or implementation.count(":") != 1:
        raise ValueError("executor implementation must be a module:member reference")
    module_ref, member_ref = implementation.split(":", 1)
    if (
        not module_ref
        or not member_ref
        or module_ref != module_ref.strip()
        or member_ref != member_ref.strip()
    ):
        raise ValueError("executor implementation must be a module:member reference")
    _non_empty_strings(value.environments, "executor environments")
    _all_strings(value.credentials, "executor credentials")
    _all_strings(value.hardware, "executor hardware")


def _validate_verifier(value: VerifierContract) -> None:
    if not isinstance(value.verifier_ref, str) or not value.verifier_ref.strip():
        raise ValueError("verifier declaration is required")
    _all_strings(value.evidence_refs, "verifier evidence")
    if value.last_verified_at is not None:
        _validate_timestamp(value.last_verified_at, "last_verified_at")


def _validate_timestamp(value: str, label: str) -> None:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError(f"{label} must be an RFC 3339 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")


def _validate_telemetry(value: TelemetryContract) -> None:
    metrics = (
        ("reliability", value.reliability),
        ("latency_ms_p50", value.latency_ms_p50),
        ("cost_per_call", value.cost_per_call),
    )
    for name, metric in metrics:
        if isinstance(metric, bool):
            raise ValueError(f"{name} must be numeric or unknown")
        if metric is not None and not isinstance(metric, (int, float)):
            raise ValueError(f"{name} must be numeric or unknown")
        if metric is not None and not math.isfinite(float(metric)):
            raise ValueError(f"{name} must be finite")
        if metric is not None and float(metric) < 0:
            raise ValueError(f"{name} cannot be negative")
    if value.reliability is not None and float(value.reliability) > 1:
        raise ValueError("reliability must be between zero and one")
    if not isinstance(value.measurement_source, str) or not value.measurement_source.strip():
        raise ValueError("telemetry measurement_source is required")
    if any(metric is not None for _, metric in metrics) and value.measurement_source == UNKNOWN:
        raise ValueError("measured telemetry requires a non-unknown source")


def _validate_provenance(value: ProvenanceContract) -> None:
    if (
        not isinstance(value.source_ref, str)
        or not value.source_ref.strip()
        or not isinstance(value.maintainer, str)
        or not value.maintainer.strip()
    ):
        raise ValueError("provenance source and maintainer are required")
    if not isinstance(value.trust_state, str) or value.trust_state not in TRUST_STATES:
        raise ValueError(f"unsupported trust state: {value.trust_state}")
    if not isinstance(value.generated, bool):
        raise ValueError("provenance generated flag must be boolean")
    if value.generated and value.trust_state != "quarantined":
        raise ValueError("generated capabilities must remain quarantined")
    if value.package_digest is not None and (
        not isinstance(value.package_digest, str)
        or _PACKAGE_DIGEST.fullmatch(value.package_digest) is None
    ):
        raise ValueError(
            "package digest must be sha256:<64 lowercase hex> or "
            "hmac-sha256:<64 lowercase hex>"
        )
    if value.trust_state == "signed" and (
        not value.package_digest
        or _AUTHENTICATED_PACKAGE_DIGEST.fullmatch(value.package_digest) is None
    ):
        raise ValueError(
            "signed capability requires authenticated HMAC-SHA256 package evidence"
        )


def _validate_schema(value: Mapping[str, Any], label: str) -> None:
    if not isinstance(value, Mapping) or value.get("type") != "object":
        raise ValueError(f"{label} must be an object schema")
    try:
        _canonical_json_value(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON-compatible") from exc


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = _canonical_json_value(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_canonical_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("JSON numbers must be finite")
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    canonical = _canonical_json_value(value)
    if isinstance(canonical, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in canonical.items()})
    if isinstance(canonical, list):
        return tuple(_freeze_json(item) for item in canonical)
    return canonical


def _contract_payload(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _contract_payload(getattr(value, field.name))
            for field in fields(value)
        }
    return _canonical_json_value(value)


def _all_strings(values: tuple[str, ...], label: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{label} must contain non-empty strings")


def _non_empty_strings(values: tuple[str, ...], label: str) -> None:
    _all_strings(values, label)
    if not values:
        raise ValueError(f"{label} must be non-empty")


def _privacy_for_risk(risk: str) -> str:
    if risk == "read_only":
        return "local"
    if risk == "irreversible_or_money":
        return "restricted"
    return "sensitive"


def _approval_for_risk(risk: str) -> str:
    return MINIMUM_APPROVAL.get(risk, "explicit")
