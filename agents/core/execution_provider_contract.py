"""Inert, provider-neutral execution contract for Nerva E8.1b.

This module contains value types only.  It does not register, select, import,
or execute an execution provider, and it grants no action authority.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlsplit

SCHEMA_VERSION = "nerva.execution-provider.v1"
MAX_JSON_BYTES = 65_536
MAX_JSON_DEPTH = 16
MAX_JSON_ITEMS = 1_024

_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CANONICAL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_OPAQUE_REF = re.compile(r"^[a-z][a-z0-9._-]{0,31}:[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_REF = re.compile(r"^\{\{secret:[A-Za-z0-9_.-]{1,128}\}\}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_EVIDENCE_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RFC3339_UTC_SECONDS = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_AUTHORITY_VALUES = {
    "grants_authority": False,
    "can_authorize": False,
    "can_approve": False,
    "can_mark_complete": False,
    "can_write_canonical_state": False,
    "requires_external_verification": True,
}
_AUTHORITY_FIELDS = set(_AUTHORITY_VALUES)


def _strict_keys(raw: Mapping[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError(f"{label} fields do not match the versioned schema")


def _exact_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _bounded_int(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _canonical_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded opaque reference")
    return value


def _prefixed_ref(value: Any, label: str, prefix: str) -> str:
    reference = _canonical_ref(value, label)
    if not reference.startswith(f"{prefix}:"):
        raise ValueError(f"{label} must use the {prefix}: namespace")
    return reference


def _canonical_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _CANONICAL_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical namespaced identifier")
    return value


def _canonical_tuple(
    values: Any,
    label: str,
    *,
    nonempty: bool = False,
    validator=None,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    if nonempty and not values:
        raise ValueError(f"{label} cannot be empty")
    if len(values) > 64:
        raise ValueError(f"{label} exceeds the maximum item count")
    if any(not isinstance(value, str) for value in values):
        raise ValueError(f"{label} must contain strings")
    if tuple(sorted(values)) != values or len(set(values)) != len(values):
        raise ValueError(f"{label} must be sorted and unique")
    if validator is not None:
        for value in values:
            validator(value, label)
    return values


def _freeze_json(value: Any, *, depth: int = 0, counter: list[int] | None = None) -> Any:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("JSON payload exceeds the maximum depth")
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_ITEMS:
        raise ValueError("JSON payload exceeds the maximum item count")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON payload cannot contain NaN or Infinity")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        frozen: dict[str, Any] = {}
        for key in sorted(value):
            frozen[key] = _freeze_json(value[key], depth=depth + 1, counter=counter)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, depth=depth + 1, counter=counter) for item in value)
    raise ValueError("payload must contain JSON-compatible values")


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: Any, *, bounded: bool = False) -> str:
    try:
        encoded = json.dumps(
            _json_value(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("contract payload must be canonical JSON") from exc
    try:
        encoded_size = len(encoded.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("contract payload must be valid UTF-8") from exc
    if bounded and encoded_size > MAX_JSON_BYTES:
        raise ValueError("JSON payload exceeds the maximum encoded size")
    return encoded


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON object contains duplicate field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON payload cannot contain {value}")


def _load_object(payload: str, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, str):
        raise ValueError(f"{label} must be a JSON string")
    try:
        payload_size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if payload_size > MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds the maximum encoded size")
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    _freeze_json(raw)
    return raw


def _validate_authority(raw: Mapping[str, Any]) -> None:
    for name, expected in _AUTHORITY_VALUES.items():
        if type(raw.get(name)) is not bool or raw[name] is not expected:
            raise ValueError("execution-provider authority flags are immutable")


class _TopLevelContract:
    def to_dict(self) -> dict[str, Any]:
        payload = _json_value(self)
        if not isinstance(payload, dict):  # pragma: no cover - dataclass invariant
            raise ValueError("contract record must encode as an object")
        return payload

    def to_json(self) -> str:
        return _canonical_json(self, bounded=True)

    def _validate_envelope(self) -> None:
        payload = self.to_dict()
        _freeze_json(payload)
        _canonical_json(payload, bounded=True)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """The v1 contract permits isolated execution backends only."""

    backends: tuple[str, ...]
    required: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _canonical_tuple(self.backends, "sandbox backends", nonempty=True)
        if any(backend not in {"docker", "wasm"} for backend in self.backends):
            raise ValueError("sandbox backend must be docker or wasm")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SandboxPolicy:
        _strict_keys(raw, {"backends", "required"}, "sandbox policy")
        if raw["required"] is not True:
            raise ValueError("sandbox isolation requirement is immutable")
        return cls(
            backends=tuple(raw["backends"])
            if isinstance(raw["backends"], list)
            else raw["backends"]
        )


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    mode: str
    read_refs: tuple[str, ...] = ()
    write_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"none", "read_only", "workspace_write"}:
            raise ValueError("unsupported filesystem policy")
        _canonical_tuple(self.read_refs, "filesystem read references", validator=_canonical_ref)
        _canonical_tuple(self.write_refs, "filesystem write references", validator=_canonical_ref)
        if any(not ref.startswith(("artifact:", "workspace:")) for ref in self.read_refs):
            raise ValueError("filesystem reads require artifact or workspace references")
        if any(not ref.startswith("workspace:") for ref in self.write_refs):
            raise ValueError("filesystem writes require workspace references")
        if self.mode == "none" and (self.read_refs or self.write_refs):
            raise ValueError("filesystem none policy cannot carry references")
        if self.mode == "read_only" and self.write_refs:
            raise ValueError("read-only filesystem policy cannot write")
        if self.mode == "workspace_write" and not self.write_refs:
            raise ValueError("workspace-write policy requires a write reference")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> FilesystemPolicy:
        _strict_keys(raw, {"mode", "read_refs", "write_refs"}, "filesystem policy")
        return cls(
            mode=raw["mode"],
            read_refs=tuple(raw["read_refs"])
            if isinstance(raw["read_refs"], list)
            else raw["read_refs"],
            write_refs=tuple(raw["write_refs"])
            if isinstance(raw["write_refs"], list)
            else raw["write_refs"],
        )


def _canonical_origin(origin: str) -> None:
    if (
        not isinstance(origin, str)
        or len(origin) > 253
        or not origin.isascii()
        or not origin.isprintable()
        or any(char.isspace() for char in origin)
    ):
        raise ValueError("network origin must be a bounded printable string")
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError as exc:
        raise ValueError("network origin is malformed") from exc
    host = parts.hostname
    if (
        parts.scheme not in {"http", "https"}
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
        or "*" in host
    ):
        raise ValueError("network origin must be a credential-free origin")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if all(char in "0123456789." for char in host) or any(
            _DNS_LABEL.fullmatch(label) is None for label in labels
        ):
            raise ValueError(
                "network origin host must be a canonical DNS name or IP address"
            ) from None
    else:
        if "%" in host or str(address) != host:
            raise ValueError("network origin IP address must use canonical form")
    rendered_host = f"[{host}]" if ":" in host else host
    canonical = f"{parts.scheme}://{rendered_host}"
    if port is not None:
        canonical += f":{port}"
    if origin != canonical:
        raise ValueError("network origin must use canonical lowercase form")
    if parts.scheme == "http" and host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("plain HTTP is allowed only for loopback origins")


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    mode: str
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"deny", "allowlist"}:
            raise ValueError("unsupported network policy")
        _canonical_tuple(
            self.allowed_origins,
            "network origins",
            validator=lambda value, _label: _canonical_origin(value),
        )
        if self.mode == "deny" and self.allowed_origins:
            raise ValueError("deny network policy cannot carry origins")
        if self.mode == "allowlist" and not self.allowed_origins:
            raise ValueError("allowlist network policy requires origins")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> NetworkPolicy:
        _strict_keys(raw, {"mode", "allowed_origins"}, "network policy")
        return cls(
            mode=raw["mode"],
            allowed_origins=(
                tuple(raw["allowed_origins"])
                if isinstance(raw["allowed_origins"], list)
                else raw["allowed_origins"]
            ),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentPolicy:
    sandbox: SandboxPolicy
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    secret_refs: tuple[str, ...] = ()
    secret_values_serialized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.sandbox, SandboxPolicy):
            raise ValueError("environment requires a sandbox policy")
        if not isinstance(self.filesystem, FilesystemPolicy):
            raise ValueError("environment requires a filesystem policy")
        if not isinstance(self.network, NetworkPolicy):
            raise ValueError("environment requires a network policy")
        _canonical_tuple(self.secret_refs, "secret references")
        if any(_SECRET_REF.fullmatch(ref) is None for ref in self.secret_refs):
            raise ValueError("secret references must use {{secret:name}} handles")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> EnvironmentPolicy:
        _strict_keys(
            raw,
            {"sandbox", "filesystem", "network", "secret_refs", "secret_values_serialized"},
            "environment policy",
        )
        if (
            type(raw["secret_values_serialized"]) is not bool
            or raw["secret_values_serialized"] is not False
        ):
            raise ValueError("secret values cannot be serialized")
        return cls(
            sandbox=SandboxPolicy.from_dict(raw["sandbox"]),
            filesystem=FilesystemPolicy.from_dict(raw["filesystem"]),
            network=NetworkPolicy.from_dict(raw["network"]),
            secret_refs=tuple(raw["secret_refs"])
            if isinstance(raw["secret_refs"], list)
            else raw["secret_refs"],
        )


@dataclass(frozen=True, slots=True)
class LifecycleSupport:
    cancellation: bool
    checkpointing: bool
    idempotency: bool
    partial_effect_modes: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.cancellation, "cancellation support"),
            (self.checkpointing, "checkpoint support"),
            (self.idempotency, "idempotency support"),
        ):
            _exact_bool(value, label)
        _canonical_tuple(self.partial_effect_modes, "partial-effect modes", nonempty=True)
        if any(mode not in {"none", "report", "compensate"} for mode in self.partial_effect_modes):
            raise ValueError("unsupported partial-effect mode")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> LifecycleSupport:
        _strict_keys(
            raw,
            {"cancellation", "checkpointing", "idempotency", "partial_effect_modes"},
            "lifecycle support",
        )
        return cls(
            cancellation=raw["cancellation"],
            checkpointing=raw["checkpointing"],
            idempotency=raw["idempotency"],
            partial_effect_modes=(
                tuple(raw["partial_effect_modes"])
                if isinstance(raw["partial_effect_modes"], list)
                else raw["partial_effect_modes"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    wall_time_ms: int
    max_cost_microunits: int
    max_tokens: int
    max_retries: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        _bounded_int(self.wall_time_ms, "wall-time budget", minimum=1, maximum=3_600_000)
        _bounded_int(
            self.max_cost_microunits,
            "cost budget",
            minimum=0,
            maximum=10**15,
        )
        _bounded_int(self.max_tokens, "token budget", minimum=0, maximum=10_000_000)
        _bounded_int(self.max_retries, "retry budget", minimum=0, maximum=10)
        if not isinstance(self.currency, str) or _CURRENCY.fullmatch(self.currency) is None:
            raise ValueError("budget currency must be an uppercase ISO-style code")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ExecutionBudget:
        _strict_keys(
            raw,
            {"wall_time_ms", "max_cost_microunits", "max_tokens", "max_retries", "currency"},
            "execution budget",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ExecutionLifecycle:
    idempotency_key: str | None
    cancellation_ref: str | None
    checkpoint_ref: str | None
    partial_effect_mode: str

    def __post_init__(self) -> None:
        for value, label, prefix in (
            (self.idempotency_key, "idempotency reference", "idempotency"),
            (self.cancellation_ref, "cancellation reference", "cancellation"),
            (self.checkpoint_ref, "checkpoint reference", "checkpoint"),
        ):
            if value is not None:
                _prefixed_ref(value, label, prefix)
        if self.partial_effect_mode not in {"none", "report", "compensate"}:
            raise ValueError("unsupported partial-effect mode")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ExecutionLifecycle:
        _strict_keys(
            raw,
            {"idempotency_key", "cancellation_ref", "checkpoint_ref", "partial_effect_mode"},
            "execution lifecycle",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    verifier_refs: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    rollback_ref: str
    external_required: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _canonical_tuple(
            self.verifier_refs,
            "verifier references",
            nonempty=True,
            validator=lambda value, label: _prefixed_ref(value, label, "verifier"),
        )
        _canonical_tuple(self.evidence_kinds, "evidence kinds", nonempty=True)
        if any(_EVIDENCE_KIND.fullmatch(kind) is None for kind in self.evidence_kinds):
            raise ValueError("evidence kinds must be canonical identifiers")
        _prefixed_ref(self.rollback_ref, "rollback reference", "rollback")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> VerificationPolicy:
        _strict_keys(
            raw,
            {"verifier_refs", "evidence_kinds", "rollback_ref", "external_required"},
            "verification policy",
        )
        if type(raw["external_required"]) is not bool or raw["external_required"] is not True:
            raise ValueError("external verification requirement is immutable")
        return cls(
            verifier_refs=tuple(raw["verifier_refs"])
            if isinstance(raw["verifier_refs"], list)
            else raw["verifier_refs"],
            evidence_kinds=tuple(raw["evidence_kinds"])
            if isinstance(raw["evidence_kinds"], list)
            else raw["evidence_kinds"],
            rollback_ref=raw["rollback_ref"],
        )


@dataclass(frozen=True, slots=True)
class ProviderDescriptor(_TopLevelContract):
    provider_id: str
    provider_version: str
    source_revision: str
    capability_ids: tuple[str, ...]
    environment_requirements: EnvironmentPolicy
    lifecycle: LifecycleSupport
    schema: str = field(default=SCHEMA_VERSION, init=False)
    kind: str = field(default="descriptor", init=False)
    grants_authority: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_approve: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    can_write_canonical_state: bool = field(default=False, init=False)
    requires_external_verification: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.startswith("provider:"):
            raise ValueError("provider id must use provider:name syntax")
        _canonical_id(self.provider_id, "provider id")
        if (
            not isinstance(self.provider_version, str)
            or _SEMVER.fullmatch(self.provider_version) is None
        ):
            raise ValueError("provider version must be semantic version x.y.z")
        if (
            not isinstance(self.source_revision, str)
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("provider source revision must be an exact lowercase digest")
        _canonical_tuple(
            self.capability_ids, "provider capability ids", nonempty=True, validator=_canonical_id
        )
        if not isinstance(self.environment_requirements, EnvironmentPolicy):
            raise ValueError("provider environment requirements are required")
        if not isinstance(self.lifecycle, LifecycleSupport):
            raise ValueError("provider lifecycle support is required")
        self._validate_envelope()

    @classmethod
    def from_json(cls, payload: str) -> ProviderDescriptor:
        raw = _load_object(payload, "provider descriptor")
        expected = {
            "provider_id",
            "provider_version",
            "source_revision",
            "capability_ids",
            "environment_requirements",
            "lifecycle",
            "schema",
            "kind",
            *_AUTHORITY_FIELDS,
        }
        _strict_keys(raw, expected, "provider descriptor")
        if raw["schema"] != SCHEMA_VERSION or raw["kind"] != "descriptor":
            raise ValueError("unsupported provider descriptor schema")
        _validate_authority(raw)
        return cls(
            provider_id=raw["provider_id"],
            provider_version=raw["provider_version"],
            source_revision=raw["source_revision"],
            capability_ids=tuple(raw["capability_ids"])
            if isinstance(raw["capability_ids"], list)
            else raw["capability_ids"],
            environment_requirements=EnvironmentPolicy.from_dict(raw["environment_requirements"]),
            lifecycle=LifecycleSupport.from_dict(raw["lifecycle"]),
        )


@dataclass(frozen=True, slots=True)
class ExecutionRequest(_TopLevelContract):
    request_id: str
    provider_id: str
    provider_version: str
    source_revision: str
    descriptor_fingerprint: str
    capability_id: str
    inputs: Mapping[str, Any]
    environment: EnvironmentPolicy
    budget: ExecutionBudget
    lifecycle: ExecutionLifecycle
    verification: VerificationPolicy
    schema: str = field(default=SCHEMA_VERSION, init=False)
    kind: str = field(default="request", init=False)
    grants_authority: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_approve: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    can_write_canonical_state: bool = field(default=False, init=False)
    requires_external_verification: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _prefixed_ref(self.request_id, "request id", "request")
        if not isinstance(self.provider_id, str) or not self.provider_id.startswith("provider:"):
            raise ValueError("provider id must use provider:name syntax")
        _canonical_id(self.provider_id, "provider id")
        if (
            not isinstance(self.provider_version, str)
            or _SEMVER.fullmatch(self.provider_version) is None
        ):
            raise ValueError("provider version must be semantic version x.y.z")
        if (
            not isinstance(self.source_revision, str)
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("request source revision must be an exact lowercase digest")
        if (
            not isinstance(self.descriptor_fingerprint, str)
            or _SHA256.fullmatch(self.descriptor_fingerprint) is None
        ):
            raise ValueError("request descriptor fingerprint must be a lowercase SHA-256 digest")
        _canonical_id(self.capability_id, "capability id")
        if not isinstance(self.inputs, Mapping):
            raise ValueError("execution inputs must be a JSON object")
        frozen = _freeze_json(self.inputs)
        _canonical_json(frozen, bounded=True)
        object.__setattr__(self, "inputs", frozen)
        if not isinstance(self.environment, EnvironmentPolicy):
            raise ValueError("execution environment is required")
        if not isinstance(self.budget, ExecutionBudget):
            raise ValueError("execution budget is required")
        if not isinstance(self.lifecycle, ExecutionLifecycle):
            raise ValueError("execution lifecycle is required")
        if not isinstance(self.verification, VerificationPolicy):
            raise ValueError("verification policy is required")
        if self.budget.max_retries > 0 and self.lifecycle.idempotency_key is None:
            raise ValueError("retry budget requires an idempotency key")
        if (
            self.lifecycle.partial_effect_mode == "compensate"
            and not self.verification.rollback_ref
        ):
            raise ValueError("compensating partial effects require rollback")
        self._validate_envelope()

    @classmethod
    def from_json(cls, payload: str) -> ExecutionRequest:
        raw = _load_object(payload, "execution request")
        expected = {
            "request_id",
            "provider_id",
            "provider_version",
            "source_revision",
            "descriptor_fingerprint",
            "capability_id",
            "inputs",
            "environment",
            "budget",
            "lifecycle",
            "verification",
            "schema",
            "kind",
            *_AUTHORITY_FIELDS,
        }
        _strict_keys(raw, expected, "execution request")
        if raw["schema"] != SCHEMA_VERSION or raw["kind"] != "request":
            raise ValueError("unsupported execution request schema")
        _validate_authority(raw)
        return cls(
            request_id=raw["request_id"],
            provider_id=raw["provider_id"],
            provider_version=raw["provider_version"],
            source_revision=raw["source_revision"],
            descriptor_fingerprint=raw["descriptor_fingerprint"],
            capability_id=raw["capability_id"],
            inputs=raw["inputs"],
            environment=EnvironmentPolicy.from_dict(raw["environment"]),
            budget=ExecutionBudget.from_dict(raw["budget"]),
            lifecycle=ExecutionLifecycle.from_dict(raw["lifecycle"]),
            verification=VerificationPolicy.from_dict(raw["verification"]),
        )


def validate_request_against_descriptor(
    request: ExecutionRequest,
    descriptor: ProviderDescriptor,
) -> ExecutionRequest:
    """Fail closed when a request widens one provider declaration."""

    if not isinstance(request, ExecutionRequest) or not isinstance(descriptor, ProviderDescriptor):
        raise ValueError("provider binding requires typed request and descriptor")
    if (request.provider_id, request.provider_version) != (
        descriptor.provider_id,
        descriptor.provider_version,
    ):
        raise ValueError("request provider identity does not match descriptor")
    if request.source_revision != descriptor.source_revision:
        raise ValueError("request provider revision does not match descriptor")
    if request.descriptor_fingerprint != descriptor.fingerprint:
        raise ValueError("request descriptor fingerprint does not match descriptor")
    if request.capability_id not in descriptor.capability_ids:
        raise ValueError("request capability is not declared by provider")
    if request.environment != descriptor.environment_requirements:
        raise ValueError("request environment widens provider requirements")
    support = descriptor.lifecycle
    lifecycle = request.lifecycle
    unsupported = (
        (lifecycle.cancellation_ref is not None and not support.cancellation)
        or (lifecycle.checkpoint_ref is not None and not support.checkpointing)
        or (lifecycle.idempotency_key is not None and not support.idempotency)
        or lifecycle.partial_effect_mode not in support.partial_effect_modes
    )
    if unsupported:
        raise ValueError("request lifecycle exceeds provider support")
    return request


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or _RFC3339_UTC_SECONDS.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical UTC RFC 3339 timestamp")
    candidate = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    wall_time_ms: int
    cost_microunits: int
    tokens: int
    retries_used: int

    def __post_init__(self) -> None:
        _bounded_int(self.wall_time_ms, "used wall time", minimum=0, maximum=3_600_000)
        _bounded_int(self.cost_microunits, "used cost", minimum=0, maximum=10**15)
        _bounded_int(self.tokens, "used tokens", minimum=0, maximum=10_000_000)
        _bounded_int(self.retries_used, "used retries", minimum=0, maximum=10)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BudgetUsage:
        _strict_keys(
            raw,
            {"wall_time_ms", "cost_microunits", "tokens", "retries_used"},
            "budget usage",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class PartialEffectReport:
    state: str
    effect_refs: tuple[str, ...]
    rollback_required: bool

    def __post_init__(self) -> None:
        if self.state not in {"none", "possible", "reported"}:
            raise ValueError("unsupported partial-effect state")
        _canonical_tuple(
            self.effect_refs,
            "effect references",
            validator=lambda value, label: _prefixed_ref(value, label, "effect"),
        )
        _exact_bool(self.rollback_required, "partial-effect rollback flag")
        if self.state == "none" and (self.effect_refs or self.rollback_required):
            raise ValueError("no-effect report cannot carry effects or rollback")
        if self.state == "possible" and not self.rollback_required:
            raise ValueError("possible partial effects require rollback")
        if self.state == "reported" and not self.effect_refs:
            raise ValueError("reported partial effects require effect references")
        if self.state == "reported" and not self.rollback_required:
            raise ValueError("reported partial effects require rollback")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PartialEffectReport:
        _strict_keys(
            raw,
            {"state", "effect_refs", "rollback_required"},
            "partial-effect report",
        )
        return cls(
            state=raw["state"],
            effect_refs=(
                tuple(raw["effect_refs"])
                if isinstance(raw["effect_refs"], list)
                else raw["effect_refs"]
            ),
            rollback_required=raw["rollback_required"],
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult(_TopLevelContract):
    """Unverified provider-local outcome; never a Nerva completion claim."""

    request_id: str
    request_fingerprint: str
    provider_id: str
    provider_version: str
    source_revision: str
    descriptor_fingerprint: str
    status: str
    started_at: str
    finished_at: str
    attempt: int
    output: Mapping[str, Any]
    error_code: str | None
    checkpoint_ref: str | None
    partial_effects: PartialEffectReport
    evidence_kinds: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    usage: BudgetUsage
    schema: str = field(default=SCHEMA_VERSION, init=False)
    kind: str = field(default="result", init=False)
    verification_status: str = field(default="unverified", init=False)
    grants_authority: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_approve: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    can_write_canonical_state: bool = field(default=False, init=False)
    requires_external_verification: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _prefixed_ref(self.request_id, "request id", "request")
        if (
            not isinstance(self.request_fingerprint, str)
            or _SHA256.fullmatch(self.request_fingerprint) is None
        ):
            raise ValueError("request fingerprint must be a lowercase SHA-256 digest")
        if not isinstance(self.provider_id, str) or not self.provider_id.startswith("provider:"):
            raise ValueError("provider id must use provider:name syntax")
        _canonical_id(self.provider_id, "provider id")
        if (
            not isinstance(self.provider_version, str)
            or _SEMVER.fullmatch(self.provider_version) is None
        ):
            raise ValueError("provider version must be semantic version x.y.z")
        if (
            not isinstance(self.source_revision, str)
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("result source revision must be an exact lowercase digest")
        if (
            not isinstance(self.descriptor_fingerprint, str)
            or _SHA256.fullmatch(self.descriptor_fingerprint) is None
        ):
            raise ValueError("result descriptor fingerprint must be a lowercase SHA-256 digest")
        if self.status not in {"succeeded", "failed", "cancelled", "timed_out", "partial"}:
            raise ValueError("unsupported provider-local result status")
        started = _timestamp(self.started_at, "result start time")
        finished = _timestamp(self.finished_at, "result finish time")
        if finished < started:
            raise ValueError("result finish time cannot precede start time")
        _bounded_int(self.attempt, "result attempt", minimum=1, maximum=11)
        if not isinstance(self.output, Mapping):
            raise ValueError("result output must be a JSON object")
        frozen = _freeze_json(self.output)
        _canonical_json(frozen, bounded=True)
        object.__setattr__(self, "output", frozen)
        if self.status == "succeeded" and self.error_code is not None:
            raise ValueError("succeeded provider result cannot carry an error")
        if self.status != "succeeded" and self.error_code is None:
            raise ValueError("non-success provider result requires an error code")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or _EVIDENCE_KIND.fullmatch(self.error_code) is None
        ):
            raise ValueError("result error code must be a canonical identifier")
        if self.checkpoint_ref is not None:
            _prefixed_ref(self.checkpoint_ref, "checkpoint reference", "checkpoint")
        if not isinstance(self.partial_effects, PartialEffectReport):
            raise ValueError("result requires a partial-effect report")
        if self.status == "succeeded" and self.partial_effects.state != "none":
            raise ValueError("succeeded provider result cannot claim partial effects")
        if self.status == "partial" and self.partial_effects.state == "none":
            raise ValueError("partial provider result requires a partial-effect report")
        _canonical_tuple(self.evidence_kinds, "result evidence kinds", nonempty=True)
        if any(_EVIDENCE_KIND.fullmatch(kind) is None for kind in self.evidence_kinds):
            raise ValueError("result evidence kinds must be canonical identifiers")
        _canonical_tuple(
            self.evidence_refs,
            "result evidence references",
            nonempty=True,
            validator=lambda value, label: _prefixed_ref(value, label, "evidence"),
        )
        _canonical_tuple(
            self.artifact_refs,
            "result artifact references",
            validator=_canonical_ref,
        )
        if any(not ref.startswith("artifact:") for ref in self.artifact_refs):
            raise ValueError("result artifacts require artifact references")
        if not isinstance(self.usage, BudgetUsage):
            raise ValueError("result budget usage is required")
        if self.attempt != self.usage.retries_used + 1:
            raise ValueError("result attempt must match used retries")
        self._validate_envelope()

    @classmethod
    def from_json(cls, payload: str) -> ExecutionResult:
        raw = _load_object(payload, "execution result")
        expected = {
            "request_id",
            "request_fingerprint",
            "provider_id",
            "provider_version",
            "source_revision",
            "descriptor_fingerprint",
            "status",
            "started_at",
            "finished_at",
            "attempt",
            "output",
            "error_code",
            "checkpoint_ref",
            "partial_effects",
            "evidence_kinds",
            "evidence_refs",
            "artifact_refs",
            "usage",
            "schema",
            "kind",
            "verification_status",
            *_AUTHORITY_FIELDS,
        }
        _strict_keys(raw, expected, "execution result")
        if raw["schema"] != SCHEMA_VERSION or raw["kind"] != "result":
            raise ValueError("unsupported execution result schema")
        if raw["verification_status"] != "unverified":
            raise ValueError("provider result verification status is immutable")
        _validate_authority(raw)
        return cls(
            request_id=raw["request_id"],
            request_fingerprint=raw["request_fingerprint"],
            provider_id=raw["provider_id"],
            provider_version=raw["provider_version"],
            source_revision=raw["source_revision"],
            descriptor_fingerprint=raw["descriptor_fingerprint"],
            status=raw["status"],
            started_at=raw["started_at"],
            finished_at=raw["finished_at"],
            attempt=raw["attempt"],
            output=raw["output"],
            error_code=raw["error_code"],
            checkpoint_ref=raw["checkpoint_ref"],
            partial_effects=PartialEffectReport.from_dict(raw["partial_effects"]),
            evidence_kinds=(
                tuple(raw["evidence_kinds"])
                if isinstance(raw["evidence_kinds"], list)
                else raw["evidence_kinds"]
            ),
            evidence_refs=(
                tuple(raw["evidence_refs"])
                if isinstance(raw["evidence_refs"], list)
                else raw["evidence_refs"]
            ),
            artifact_refs=(
                tuple(raw["artifact_refs"])
                if isinstance(raw["artifact_refs"], list)
                else raw["artifact_refs"]
            ),
            usage=BudgetUsage.from_dict(raw["usage"]),
        )


def validate_result_for_request(
    result: ExecutionResult,
    request: ExecutionRequest,
    descriptor: ProviderDescriptor,
) -> ExecutionResult:
    """Bind untrusted provider output to its exact bounded request."""

    if not isinstance(result, ExecutionResult):
        raise ValueError("result binding requires an ExecutionResult")
    validate_request_against_descriptor(request, descriptor)
    if (result.provider_id, result.provider_version) != (
        request.provider_id,
        request.provider_version,
    ):
        raise ValueError("result provider identity does not match request")
    if result.source_revision != request.source_revision:
        raise ValueError("result provider revision does not match request")
    if result.descriptor_fingerprint != request.descriptor_fingerprint:
        raise ValueError("result descriptor fingerprint does not match request")
    if result.request_id != request.request_id:
        raise ValueError("result request id does not match request")
    if result.request_fingerprint != request.fingerprint:
        raise ValueError("result request fingerprint does not match request")
    usage = result.usage
    budget = request.budget
    if (
        usage.wall_time_ms > budget.wall_time_ms
        or usage.cost_microunits > budget.max_cost_microunits
        or usage.tokens > budget.max_tokens
        or usage.retries_used > budget.max_retries
    ):
        raise ValueError("result exceeds the declared execution budget")
    if not set(request.verification.evidence_kinds).issubset(result.evidence_kinds):
        raise ValueError("result omits required evidence kinds")
    if result.status == "cancelled" and request.lifecycle.cancellation_ref is None:
        raise ValueError("cancelled result lacks a request cancellation reference")
    if result.checkpoint_ref is not None:
        if not descriptor.lifecycle.checkpointing:
            raise ValueError("result checkpoint exceeds provider lifecycle support")
        if request.lifecycle.checkpoint_ref != result.checkpoint_ref:
            raise ValueError("result checkpoint does not match the request checkpoint handle")
    mode = request.lifecycle.partial_effect_mode
    state = result.partial_effects.state
    if mode == "none" and state != "none":
        raise ValueError("result partial effects exceed the request policy")
    if mode == "compensate" and state != "none" and not result.partial_effects.rollback_required:
        raise ValueError("result partial effects require rollback")
    return result


@dataclass(frozen=True, slots=True)
class ReliabilityEvidence:
    status: str
    value: float | None
    source_ref: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"measured", "not_measured", "failed"}:
            raise ValueError("unsupported reliability evidence status")
        _canonical_tuple(
            self.evidence_refs,
            "reliability evidence references",
            validator=lambda value, label: _prefixed_ref(value, label, "evidence"),
        )
        if self.status == "measured":
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, (int, float))
                or not math.isfinite(float(self.value))
                or not 0 <= float(self.value) <= 1
            ):
                raise ValueError("measured reliability must be a finite ratio")
            if self.source_ref is None or not self.evidence_refs:
                raise ValueError("measured reliability requires source and evidence")
            _prefixed_ref(self.source_ref, "reliability source reference", "benchmark")
        elif self.status == "not_measured":
            if self.value is not None or self.source_ref is not None or self.evidence_refs:
                raise ValueError("unmeasured reliability cannot claim evidence")
        else:
            if self.value is not None or self.source_ref is None or not self.evidence_refs:
                raise ValueError("failed reliability requires source and failure evidence")
            _prefixed_ref(self.source_ref, "reliability source reference", "benchmark")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReliabilityEvidence:
        _strict_keys(
            raw,
            {"status", "value", "source_ref", "evidence_refs"},
            "reliability evidence",
        )
        return cls(
            status=raw["status"],
            value=raw["value"],
            source_ref=raw["source_ref"],
            evidence_refs=(
                tuple(raw["evidence_refs"])
                if isinstance(raw["evidence_refs"], list)
                else raw["evidence_refs"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot(_TopLevelContract):
    provider_id: str
    provider_version: str
    source_revision: str
    descriptor_fingerprint: str
    observed_at: str
    status: str
    capability_ids: tuple[str, ...]
    reliability: ReliabilityEvidence
    evidence_refs: tuple[str, ...]
    error_code: str | None
    schema: str = field(default=SCHEMA_VERSION, init=False)
    kind: str = field(default="health", init=False)
    grants_authority: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_approve: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)
    can_write_canonical_state: bool = field(default=False, init=False)
    requires_external_verification: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.startswith("provider:"):
            raise ValueError("provider id must use provider:name syntax")
        _canonical_id(self.provider_id, "provider id")
        if (
            not isinstance(self.provider_version, str)
            or _SEMVER.fullmatch(self.provider_version) is None
        ):
            raise ValueError("provider version must be semantic version x.y.z")
        if (
            not isinstance(self.source_revision, str)
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("health source revision must be an exact lowercase digest")
        if (
            not isinstance(self.descriptor_fingerprint, str)
            or _SHA256.fullmatch(self.descriptor_fingerprint) is None
        ):
            raise ValueError("health descriptor fingerprint must be a lowercase SHA-256 digest")
        _timestamp(self.observed_at, "health observation time")
        if self.status not in {"unknown", "ready", "degraded", "unavailable"}:
            raise ValueError("unsupported provider health status")
        _canonical_tuple(
            self.capability_ids,
            "health capability ids",
            nonempty=True,
            validator=_canonical_id,
        )
        if not isinstance(self.reliability, ReliabilityEvidence):
            raise ValueError("health requires reliability evidence")
        _canonical_tuple(
            self.evidence_refs,
            "health evidence references",
            validator=lambda value, label: _prefixed_ref(value, label, "evidence"),
        )
        if self.status in {"ready", "degraded", "unavailable"} and not self.evidence_refs:
            raise ValueError("health readiness requires evidence")
        if self.status == "unavailable" and self.error_code is None:
            raise ValueError("unavailable provider health requires an error code")
        if self.status == "ready" and self.error_code is not None:
            raise ValueError("ready provider health cannot carry an error")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or _EVIDENCE_KIND.fullmatch(self.error_code) is None
        ):
            raise ValueError("health error code must be a canonical identifier")
        self._validate_envelope()

    @classmethod
    def from_json(cls, payload: str) -> ProviderHealthSnapshot:
        raw = _load_object(payload, "provider health snapshot")
        expected = {
            "provider_id",
            "provider_version",
            "source_revision",
            "descriptor_fingerprint",
            "observed_at",
            "status",
            "capability_ids",
            "reliability",
            "evidence_refs",
            "error_code",
            "schema",
            "kind",
            *_AUTHORITY_FIELDS,
        }
        _strict_keys(raw, expected, "provider health snapshot")
        if raw["schema"] != SCHEMA_VERSION or raw["kind"] != "health":
            raise ValueError("unsupported provider health schema")
        _validate_authority(raw)
        return cls(
            provider_id=raw["provider_id"],
            provider_version=raw["provider_version"],
            source_revision=raw["source_revision"],
            descriptor_fingerprint=raw["descriptor_fingerprint"],
            observed_at=raw["observed_at"],
            status=raw["status"],
            capability_ids=(
                tuple(raw["capability_ids"])
                if isinstance(raw["capability_ids"], list)
                else raw["capability_ids"]
            ),
            reliability=ReliabilityEvidence.from_dict(raw["reliability"]),
            evidence_refs=(
                tuple(raw["evidence_refs"])
                if isinstance(raw["evidence_refs"], list)
                else raw["evidence_refs"]
            ),
            error_code=raw["error_code"],
        )


def validate_health_against_descriptor(
    health: ProviderHealthSnapshot,
    descriptor: ProviderDescriptor,
) -> ProviderHealthSnapshot:
    if not isinstance(health, ProviderHealthSnapshot) or not isinstance(
        descriptor, ProviderDescriptor
    ):
        raise ValueError("health binding requires typed health and descriptor")
    if (health.provider_id, health.provider_version) != (
        descriptor.provider_id,
        descriptor.provider_version,
    ):
        raise ValueError("health provider identity does not match descriptor")
    if health.source_revision != descriptor.source_revision:
        raise ValueError("health provider revision does not match descriptor")
    if health.descriptor_fingerprint != descriptor.fingerprint:
        raise ValueError("health descriptor fingerprint does not match descriptor")
    if not set(health.capability_ids).issubset(descriptor.capability_ids):
        raise ValueError("health claims an undeclared provider capability")
    return health


class ExecutionProvider(Protocol):
    """Structural adapter seam; this module supplies no implementation."""

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def health(self) -> ProviderHealthSnapshot: ...

    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...

    async def cancel(self, request: ExecutionRequest) -> None: ...
