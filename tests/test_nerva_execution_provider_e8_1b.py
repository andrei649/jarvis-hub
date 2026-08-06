"""E8.1b provider-neutral execution-contract checks.

The contract is deliberately inert: these tests exercise value construction,
strict serialization, and hostile boundary inputs without registering or
executing a provider.
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys

import pytest

MODULE = "agents.core.execution_provider_contract"
REVISION = "a" * 40
STARTED = "2026-08-06T00:00:00Z"
FINISHED = "2026-08-06T00:00:01Z"


def _contract():
    return __import__(MODULE, fromlist=["SCHEMA_VERSION"])


def _environment(*, network=None, secret_refs=("{{secret:fixture_token}}",)):
    contract = _contract()
    return contract.EnvironmentPolicy(
        sandbox=contract.SandboxPolicy(backends=("docker",)),
        filesystem=contract.FilesystemPolicy(
            mode="workspace_write",
            read_refs=("artifact:fixture-input",),
            write_refs=("workspace:fixture-output",),
        ),
        network=network or contract.NetworkPolicy(mode="deny"),
        secret_refs=secret_refs,
    )


def _descriptor(*, environment=None, lifecycle=None, source_revision=REVISION):
    contract = _contract()
    return contract.ProviderDescriptor(
        provider_id="provider:fixture",
        provider_version="1.2.3",
        source_revision=source_revision,
        capability_ids=("tool:echo",),
        environment_requirements=environment or _environment(),
        lifecycle=lifecycle
        or contract.LifecycleSupport(
            cancellation=True,
            checkpointing=True,
            idempotency=True,
            partial_effect_modes=("compensate", "none", "report"),
        ),
    )


def _request(
    *,
    descriptor=None,
    inputs=None,
    budget=None,
    lifecycle=None,
    environment=None,
):
    contract = _contract()
    descriptor = descriptor or _descriptor()
    return contract.ExecutionRequest(
        request_id="request:fixture",
        provider_id=descriptor.provider_id,
        provider_version=descriptor.provider_version,
        source_revision=descriptor.source_revision,
        descriptor_fingerprint=descriptor.fingerprint,
        capability_id="tool:echo",
        inputs={"message": "hello"} if inputs is None else inputs,
        environment=environment or descriptor.environment_requirements,
        budget=budget
        or contract.ExecutionBudget(
            wall_time_ms=30_000,
            max_cost_microunits=0,
            max_tokens=1_000,
            max_retries=2,
        ),
        lifecycle=lifecycle
        or contract.ExecutionLifecycle(
            idempotency_key="idempotency:fixture",
            cancellation_ref="cancellation:fixture",
            checkpoint_ref=None,
            partial_effect_mode="compensate",
        ),
        verification=contract.VerificationPolicy(
            verifier_refs=("verifier:fixture",),
            evidence_kinds=("artifact_digest", "observed_output"),
            rollback_ref="rollback:native",
        ),
    )


def _result(
    *,
    request=None,
    status="succeeded",
    error_code=None,
    partial_effects=None,
    checkpoint_ref=None,
    usage=None,
    output=None,
):
    contract = _contract()
    request = request or _request()
    return contract.ExecutionResult(
        request_id=request.request_id,
        request_fingerprint=request.fingerprint,
        provider_id=request.provider_id,
        provider_version=request.provider_version,
        source_revision=request.source_revision,
        descriptor_fingerprint=request.descriptor_fingerprint,
        status=status,
        started_at=STARTED,
        finished_at=FINISHED,
        attempt=1,
        output={"echo": "hello"} if output is None else output,
        error_code=error_code,
        checkpoint_ref=checkpoint_ref,
        partial_effects=partial_effects
        or contract.PartialEffectReport(state="none", effect_refs=(), rollback_required=False),
        evidence_kinds=("artifact_digest", "observed_output"),
        evidence_refs=("evidence:fixture",),
        artifact_refs=("artifact:fixture-output",),
        usage=usage
        or contract.BudgetUsage(
            wall_time_ms=1_000,
            cost_microunits=0,
            tokens=10,
            retries_used=0,
        ),
    )


def test_execution_provider_contract_module_and_schema_exist() -> None:
    spec = importlib.util.find_spec(MODULE)

    assert spec is not None
    contract = __import__(MODULE, fromlist=["SCHEMA_VERSION"])
    assert contract.SCHEMA_VERSION == "nerva.execution-provider.v1"


def test_descriptor_is_strict_versioned_and_authority_free() -> None:
    contract = _contract()
    descriptor = _descriptor()

    assert descriptor.schema == contract.SCHEMA_VERSION
    assert descriptor.kind == "descriptor"
    assert descriptor.grants_authority is False
    assert descriptor.can_authorize is False
    assert descriptor.can_approve is False
    assert descriptor.can_mark_complete is False
    assert descriptor.can_write_canonical_state is False
    assert descriptor.requires_external_verification is True
    assert contract.ProviderDescriptor.from_json(descriptor.to_json()) == descriptor
    assert len(descriptor.fingerprint) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "Fixture Provider"),
        ("provider_version", "v1.2.3"),
        ("provider_version", "1\u0662.2.3"),
        ("source_revision", "main"),
        ("provider_id", "provider:fixture*"),
        ("capability_ids", ("tool:echo", "tool:echo")),
        ("capability_ids", ("TOOL:ECHO",)),
        ("capability_ids", ("tool:e*",)),
        ("capability_ids", tuple(f"tool:x{index:04d}" for index in range(65))),
    ],
)
def test_descriptor_rejects_noncanonical_identity_and_capabilities(field, value) -> None:
    contract = _contract()
    values = {
        "provider_id": "provider:fixture",
        "provider_version": "1.2.3",
        "source_revision": REVISION,
        "capability_ids": ("tool:echo",),
        "environment_requirements": _environment(),
        "lifecycle": contract.LifecycleSupport(
            cancellation=True,
            checkpointing=True,
            idempotency=True,
            partial_effect_modes=("compensate", "none", "report"),
        ),
    }
    values[field] = value

    with pytest.raises(ValueError):
        contract.ProviderDescriptor(**values)


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_lifecycle_support_rejects_boolean_lookalikes(value) -> None:
    contract = _contract()

    with pytest.raises(ValueError, match="boolean"):
        contract.LifecycleSupport(
            cancellation=value,
            checkpointing=True,
            idempotency=True,
            partial_effect_modes=("none",),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"backends": ()},
        {"backends": ("subprocess-host",)},
        {"backends": ("docker", "docker")},
        {"backends": ("DOCKER",)},
    ],
)
def test_sandbox_policy_accepts_only_unique_isolated_backends(kwargs) -> None:
    contract = _contract()

    with pytest.raises(ValueError):
        contract.SandboxPolicy(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "deny", "allowed_origins": ("https://api.example.com",)},
        {"mode": "allowlist", "allowed_origins": ()},
        {"mode": "allowlist", "allowed_origins": ("https://*.example.com",)},
        {"mode": "allowlist", "allowed_origins": ("https://user:pass@example.com",)},
        {"mode": "allowlist", "allowed_origins": ("https://example.com/path",)},
        {"mode": "allowlist", "allowed_origins": ("http://example.com",)},
        {"mode": "allowlist", "allowed_origins": ("https://EXAMPLE.com",)},
        {"mode": "allowlist", "allowed_origins": ("https:// example.com",)},
        {"mode": "allowlist", "allowed_origins": ("https://example.com ",)},
        {"mode": "allowlist", "allowed_origins": ("https://example..com",)},
        {"mode": "allowlist", "allowed_origins": ("https://-bad.example",)},
        {"mode": "allowlist", "allowed_origins": ("https://bad_.example",)},
        {"mode": "allowlist", "allowed_origins": ("https://example.com.",)},
    ],
)
def test_network_policy_fails_closed_on_unsafe_or_contradictory_origins(kwargs) -> None:
    contract = _contract()

    with pytest.raises(ValueError):
        contract.NetworkPolicy(**kwargs)


def test_network_policy_allows_canonical_https_and_loopback_origins() -> None:
    contract = _contract()

    assert contract.NetworkPolicy(
        mode="allowlist",
        allowed_origins=("http://127.0.0.1:8080", "https://api.example.com"),
    ).allowed_origins == ("http://127.0.0.1:8080", "https://api.example.com")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "none", "read_refs": ("artifact:input",)},
        {"mode": "read_only", "write_refs": ("workspace:output",)},
        {"mode": "workspace_write", "write_refs": ()},
        {"mode": "workspace_write", "write_refs": ("C:\\private\\output",)},
        {"mode": "workspace_write", "write_refs": ("workspace:../escape",)},
        {"mode": "workspace_write", "write_refs": ("artifact:not-writable",)},
    ],
)
def test_filesystem_policy_uses_only_bounded_opaque_refs(kwargs) -> None:
    contract = _contract()

    with pytest.raises(ValueError):
        contract.FilesystemPolicy(**kwargs)


@pytest.mark.parametrize(
    "secret_refs",
    [
        ("plaintext-token",),
        ("{{secret:fixture_token}}", "{{secret:fixture_token}}"),
        ("{{ secret:fixture_token }}",),
        ("{{secret:fixture/token}}",),
        (1,),
    ],
)
def test_environment_rejects_plaintext_malformed_or_duplicate_secret_refs(secret_refs) -> None:
    with pytest.raises(ValueError, match="secret"):
        _environment(secret_refs=secret_refs)


def test_environment_rejects_unbounded_secret_handles() -> None:
    with pytest.raises(ValueError, match="secret|size"):
        _environment(secret_refs=("{{secret:" + ("x" * 200_000) + "}}",))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wall_time_ms", True),
        ("wall_time_ms", 0),
        ("wall_time_ms", 3_600_001),
        ("max_cost_microunits", -1),
        ("max_tokens", math.inf),
        ("max_retries", -1),
        ("max_retries", 11),
        ("currency", "usd"),
    ],
)
def test_budget_rejects_unbounded_noncanonical_and_boolean_values(field, value) -> None:
    contract = _contract()
    values = {
        "wall_time_ms": 30_000,
        "max_cost_microunits": 0,
        "max_tokens": 1_000,
        "max_retries": 2,
        "currency": "USD",
    }
    values[field] = value

    with pytest.raises(ValueError):
        contract.ExecutionBudget(**values)


def test_request_deep_freezes_json_and_has_stable_round_trip_fingerprint() -> None:
    contract = _contract()
    inputs = {"nested": {"steps": ["one", {"ok": True}]}}
    request = _request(inputs=inputs)
    fingerprint = request.fingerprint
    inputs["nested"]["steps"].append("mutated")

    assert request.to_dict()["inputs"] == {"nested": {"steps": ["one", {"ok": True}]}}
    assert request.fingerprint == fingerprint
    assert contract.ExecutionRequest.from_json(request.to_json()) == request
    assert request.grants_authority is False
    assert request.can_authorize is False
    assert request.can_approve is False
    assert request.can_mark_complete is False
    assert request.can_write_canonical_state is False
    assert request.requires_external_verification is True


def test_request_deserialization_rejects_ambiguous_or_oversized_wire_json() -> None:
    contract = _contract()
    canonical = _request().to_json()
    duplicate = canonical.replace(
        '"inputs":{"message":"hello"}',
        '"inputs":{"message":"hello","message":"hello"}',
    )

    with pytest.raises(ValueError, match="duplicate"):
        contract.ExecutionRequest.from_json(duplicate)
    duplicate_authority = canonical.replace(
        '"grants_authority":false',
        '"grants_authority":true,"grants_authority":false',
    )
    with pytest.raises(ValueError, match="duplicate"):
        contract.ExecutionRequest.from_json(duplicate_authority)
    with pytest.raises(ValueError, match="string"):
        contract.ExecutionRequest.from_json(canonical.encode("utf-8"))
    with pytest.raises(ValueError, match="size"):
        contract.ExecutionRequest.from_json(canonical[:-1] + ',"padding":"' + ("x" * 70_000) + '"}')
    nested = "{}"
    for _ in range(20):
        nested = '{"child":' + nested + "}"
    with pytest.raises(ValueError, match="depth"):
        contract.ExecutionRequest.from_json(canonical[:-1] + ',"padding":' + nested + "}")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, b"bytes", {"set"}])
def test_request_rejects_non_json_and_nonfinite_inputs(bad) -> None:
    with pytest.raises(ValueError):
        _request(inputs={"bad": bad})


def test_request_rejects_oversized_or_overdeep_inputs() -> None:
    too_deep = value = {}
    for _ in range(20):
        child = {}
        value["child"] = child
        value = child

    with pytest.raises(ValueError, match="depth"):
        _request(inputs=too_deep)
    with pytest.raises(ValueError, match="size"):
        _request(inputs={"text": "x" * 70_000})
    with pytest.raises(ValueError, match="item"):
        _request(inputs={"items": list(range(1_025))})


def test_request_rejects_retry_without_idempotency_and_bad_refs() -> None:
    contract = _contract()

    with pytest.raises(ValueError, match="idempotency"):
        _request(
            lifecycle=contract.ExecutionLifecycle(
                idempotency_key=None,
                cancellation_ref="cancellation:fixture",
                checkpoint_ref=None,
                partial_effect_mode="report",
            )
        )
    with pytest.raises(ValueError, match="reference"):
        contract.ExecutionLifecycle(
            idempotency_key="../escape",
            cancellation_ref="cancellation:fixture",
            checkpoint_ref=None,
            partial_effect_mode="report",
        )


@pytest.mark.parametrize(
    "change",
    [
        {"idempotency_key": "checkpoint:wrong"},
        {"cancellation_ref": "verifier:wrong"},
        {"checkpoint_ref": "artifact:wrong"},
    ],
)
def test_lifecycle_references_reject_confused_deputy_namespaces(change) -> None:
    contract = _contract()
    values = {
        "idempotency_key": "idempotency:fixture",
        "cancellation_ref": "cancellation:fixture",
        "checkpoint_ref": "checkpoint:fixture",
        "partial_effect_mode": "report",
    }
    values.update(change)

    with pytest.raises(ValueError, match="reference|namespace"):
        contract.ExecutionLifecycle(**values)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"provider_id": "provider:other"}, "provider"),
        ({"provider_version": "9.9.9"}, "provider"),
        ({"source_revision": "b" * 40}, "revision"),
        ({"descriptor_fingerprint": "b" * 64}, "fingerprint"),
        ({"capability_id": "tool:other"}, "capability"),
    ],
)
def test_request_descriptor_binding_rejects_identity_and_capability_drift(change, message) -> None:
    contract = _contract()
    descriptor = _descriptor()
    payload = _request(descriptor=descriptor).to_dict()
    payload.update(change)
    request = contract.ExecutionRequest.from_json(json.dumps(payload))

    with pytest.raises(ValueError, match=message):
        contract.validate_request_against_descriptor(request, descriptor)


def test_request_binding_rejects_same_version_with_different_source_revision() -> None:
    contract = _contract()
    descriptor = _descriptor()
    request = _request(descriptor=descriptor)
    drifted = _descriptor(source_revision="b" * 40)

    with pytest.raises(ValueError, match="revision|fingerprint"):
        contract.validate_request_against_descriptor(request, drifted)


def test_request_descriptor_binding_rejects_environment_and_lifecycle_widening() -> None:
    contract = _contract()
    descriptor = _descriptor(
        lifecycle=contract.LifecycleSupport(
            cancellation=False,
            checkpointing=False,
            idempotency=False,
            partial_effect_modes=("none",),
        )
    )
    request = _request(
        descriptor=descriptor,
        budget=contract.ExecutionBudget(
            wall_time_ms=30_000,
            max_cost_microunits=0,
            max_tokens=1_000,
            max_retries=0,
        ),
        lifecycle=contract.ExecutionLifecycle(
            idempotency_key=None,
            cancellation_ref="cancellation:fixture",
            checkpoint_ref="checkpoint:fixture",
            partial_effect_mode="report",
        ),
    )

    with pytest.raises(ValueError, match="lifecycle"):
        contract.validate_request_against_descriptor(request, descriptor)

    wider = _request(
        descriptor=descriptor,
        budget=contract.ExecutionBudget(
            wall_time_ms=30_000,
            max_cost_microunits=0,
            max_tokens=1_000,
            max_retries=0,
        ),
        lifecycle=contract.ExecutionLifecycle(
            idempotency_key=None,
            cancellation_ref=None,
            checkpoint_ref=None,
            partial_effect_mode="none",
        ),
        environment=_environment(
            network=contract.NetworkPolicy(
                mode="allowlist", allowed_origins=("https://api.example.com",)
            )
        ),
    )
    with pytest.raises(ValueError, match="environment"):
        contract.validate_request_against_descriptor(wider, descriptor)


def test_strict_request_deserialization_rejects_unknown_and_authority_forgery() -> None:
    contract = _contract()
    payload = _request().to_dict()
    payload["unexpected"] = "field"
    with pytest.raises(ValueError, match="fields"):
        contract.ExecutionRequest.from_json(json.dumps(payload))

    for field, value in (
        ("grants_authority", True),
        ("can_authorize", 0),
        ("can_approve", "false"),
        ("can_mark_complete", True),
        ("can_write_canonical_state", True),
        ("requires_external_verification", 1),
    ):
        forged = _request().to_dict()
        forged[field] = value
        with pytest.raises(ValueError, match="authority"):
            contract.ExecutionRequest.from_json(json.dumps(forged))


def test_result_is_provider_local_unverified_and_strictly_round_trips() -> None:
    contract = _contract()
    result = _result()

    assert result.schema == contract.SCHEMA_VERSION
    assert result.kind == "result"
    assert result.verification_status == "unverified"
    assert result.grants_authority is False
    assert result.can_authorize is False
    assert result.can_approve is False
    assert result.can_mark_complete is False
    assert result.can_write_canonical_state is False
    assert result.requires_external_verification is True
    assert contract.ExecutionResult.from_json(result.to_json()) == result
    assert len(result.fingerprint) == 64


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "succeeded", "error_code": "provider_error"},
        {"status": "failed", "error_code": None},
        {"status": "cancelled", "error_code": None},
        {"status": "timed_out", "error_code": None},
        {"status": "unknown", "error_code": "provider_error"},
    ],
)
def test_result_rejects_status_error_contradictions(kwargs) -> None:
    with pytest.raises(ValueError):
        _result(**kwargs)


def test_partial_result_requires_effect_report_and_rollback() -> None:
    contract = _contract()

    with pytest.raises(ValueError, match="partial"):
        _result(status="partial", error_code="partial_effect")
    with pytest.raises(ValueError, match="rollback"):
        contract.PartialEffectReport(state="possible", effect_refs=(), rollback_required=False)
    with pytest.raises(ValueError, match="effect"):
        contract.PartialEffectReport(state="reported", effect_refs=(), rollback_required=True)
    with pytest.raises(ValueError, match="boolean"):
        contract.PartialEffectReport(state="possible", effect_refs=(), rollback_required=1)

    result = _result(
        status="partial",
        error_code="partial_effect",
        partial_effects=contract.PartialEffectReport(
            state="reported",
            effect_refs=("effect:fixture",),
            rollback_required=True,
        ),
    )
    assert result.status == "partial"


@pytest.mark.parametrize(
    ("started", "finished"),
    [
        ("not-a-time", FINISHED),
        (STARTED, "2026-08-05T23:59:59Z"),
        ("2026-08-06T00:00:00", FINISHED),
        ("2026-08-06 00:00:00+00:00", FINISHED),
        ("2026-08-06T00:00:00+0000", FINISHED),
        ("2026-08-06T02:00:00+02:00", FINISHED),
    ],
)
def test_result_rejects_invalid_or_reversed_chronology(started, finished) -> None:
    contract = _contract()
    payload = _result().to_dict()
    payload["started_at"] = started
    payload["finished_at"] = finished

    with pytest.raises(ValueError, match="time"):
        contract.ExecutionResult.from_json(json.dumps(payload))


def test_result_deep_freezes_output_and_rejects_hostile_json() -> None:
    output = {"nested": ["stable"]}
    result = _result(output=output)
    output["nested"].append("mutated")
    assert result.to_dict()["output"] == {"nested": ["stable"]}

    with pytest.raises(ValueError):
        _result(output={"bad": math.nan})
    with pytest.raises(ValueError, match="size"):
        _result(output={"bad": "x" * 70_000})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wall_time_ms", True),
        ("wall_time_ms", -1),
        ("cost_microunits", -1),
        ("tokens", math.inf),
        ("retries_used", 11),
    ],
)
def test_budget_usage_rejects_boolean_nonfinite_and_out_of_bounds(field, value) -> None:
    contract = _contract()
    values = {
        "wall_time_ms": 1_000,
        "cost_microunits": 0,
        "tokens": 10,
        "retries_used": 0,
    }
    values[field] = value
    with pytest.raises(ValueError):
        contract.BudgetUsage(**values)


def test_result_binding_enforces_identity_fingerprint_budget_and_evidence() -> None:
    contract = _contract()
    descriptor = _descriptor()
    request = _request(descriptor=descriptor)
    result = _result(request=request)
    assert contract.validate_result_for_request(result, request, descriptor) is result

    for field, value, message in (
        ("provider_id", "provider:other", "provider"),
        ("source_revision", "b" * 40, "revision"),
        ("descriptor_fingerprint", "b" * 64, "fingerprint"),
        ("request_fingerprint", "b" * 64, "fingerprint"),
        ("evidence_kinds", ("artifact_digest",), "evidence"),
    ):
        payload = result.to_dict()
        payload[field] = value
        changed = contract.ExecutionResult.from_json(json.dumps(payload))
        with pytest.raises(ValueError, match=message):
            contract.validate_result_for_request(changed, request, descriptor)

    over_budget = _result(
        request=request,
        usage=contract.BudgetUsage(
            wall_time_ms=request.budget.wall_time_ms + 1,
            cost_microunits=0,
            tokens=10,
            retries_used=0,
        ),
    )
    with pytest.raises(ValueError, match="budget"):
        contract.validate_result_for_request(over_budget, request, descriptor)


def test_result_binding_rejects_checkpoint_cancellation_and_partial_effect_drift() -> None:
    contract = _contract()
    descriptor = _descriptor(
        lifecycle=contract.LifecycleSupport(
            cancellation=False,
            checkpointing=False,
            idempotency=True,
            partial_effect_modes=("none",),
        )
    )
    request = _request(
        descriptor=descriptor,
        lifecycle=contract.ExecutionLifecycle(
            idempotency_key="idempotency:fixture",
            cancellation_ref=None,
            checkpoint_ref=None,
            partial_effect_mode="none",
        ),
    )
    contract.validate_request_against_descriptor(request, descriptor)

    cancelled = _result(request=request, status="cancelled", error_code="cancelled")
    with pytest.raises(ValueError, match="cancellation"):
        contract.validate_result_for_request(cancelled, request, descriptor)

    checkpointed = _result(request=request, checkpoint_ref="checkpoint:fixture")
    with pytest.raises(ValueError, match="checkpoint"):
        contract.validate_result_for_request(checkpointed, request, descriptor)

    partial = _result(
        request=request,
        status="partial",
        error_code="partial_effect",
        partial_effects=contract.PartialEffectReport(
            state="possible", effect_refs=(), rollback_required=True
        ),
    )
    with pytest.raises(ValueError, match="partial"):
        contract.validate_result_for_request(partial, request, descriptor)


def test_result_checkpoint_must_match_the_exact_request_handle() -> None:
    contract = _contract()
    descriptor = _descriptor()
    no_checkpoint = _request(
        descriptor=descriptor,
        lifecycle=contract.ExecutionLifecycle(
            idempotency_key="idempotency:fixture",
            cancellation_ref="cancellation:fixture",
            checkpoint_ref=None,
            partial_effect_mode="report",
        ),
    )
    with pytest.raises(ValueError, match="checkpoint"):
        contract.validate_result_for_request(
            _result(request=no_checkpoint, checkpoint_ref="checkpoint:unexpected"),
            no_checkpoint,
            descriptor,
        )

    requested = _request(
        descriptor=descriptor,
        lifecycle=contract.ExecutionLifecycle(
            idempotency_key="idempotency:fixture",
            cancellation_ref="cancellation:fixture",
            checkpoint_ref="checkpoint:authorized",
            partial_effect_mode="report",
        ),
    )
    with pytest.raises(ValueError, match="checkpoint"):
        contract.validate_result_for_request(
            _result(request=requested, checkpoint_ref="checkpoint:different"),
            requested,
            descriptor,
        )
    assert (
        contract.validate_result_for_request(
            _result(request=requested, checkpoint_ref="checkpoint:authorized"),
            requested,
            descriptor,
        ).checkpoint_ref
        == "checkpoint:authorized"
    )


def test_result_deserialization_rejects_unknown_verification_and_completion_forgery() -> None:
    contract = _contract()
    payload = _result().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="fields"):
        contract.ExecutionResult.from_json(json.dumps(payload))

    for field, value in (
        ("verification_status", "verified"),
        ("grants_authority", True),
        ("can_authorize", True),
        ("can_approve", 0),
        ("can_mark_complete", True),
        ("can_write_canonical_state", "false"),
        ("requires_external_verification", False),
    ):
        forged = _result().to_dict()
        forged[field] = value
        with pytest.raises(ValueError, match="authority|verification"):
            contract.ExecutionResult.from_json(json.dumps(forged))


def test_health_snapshot_round_trip_retains_external_evidence_boundary() -> None:
    contract = _contract()
    descriptor = _descriptor()
    health = contract.ProviderHealthSnapshot(
        provider_id=descriptor.provider_id,
        provider_version=descriptor.provider_version,
        source_revision=descriptor.source_revision,
        descriptor_fingerprint=descriptor.fingerprint,
        observed_at=FINISHED,
        status="ready",
        capability_ids=("tool:echo",),
        reliability=contract.ReliabilityEvidence(
            status="measured",
            value=0.99,
            source_ref="benchmark:e9-fixture",
            evidence_refs=("evidence:reliability",),
        ),
        evidence_refs=("evidence:health",),
        error_code=None,
    )

    assert health.can_mark_complete is False
    assert health.requires_external_verification is True
    assert contract.ProviderHealthSnapshot.from_json(health.to_json()) == health
    assert contract.validate_health_against_descriptor(health, descriptor) is health


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "status": "measured",
            "value": True,
            "source_ref": "benchmark:x",
            "evidence_refs": ("evidence:x",),
        },
        {
            "status": "measured",
            "value": math.nan,
            "source_ref": "benchmark:x",
            "evidence_refs": ("evidence:x",),
        },
        {
            "status": "measured",
            "value": 1.1,
            "source_ref": "benchmark:x",
            "evidence_refs": ("evidence:x",),
        },
        {"status": "measured", "value": 0.9, "source_ref": None, "evidence_refs": ("evidence:x",)},
        {"status": "measured", "value": 0.9, "source_ref": "benchmark:x", "evidence_refs": ()},
        {"status": "not_measured", "value": 0.0, "source_ref": None, "evidence_refs": ()},
        {"status": "failed", "value": None, "source_ref": None, "evidence_refs": ()},
    ],
)
def test_reliability_evidence_never_fabricates_or_hides_measurement_state(kwargs) -> None:
    contract = _contract()

    with pytest.raises(ValueError):
        contract.ReliabilityEvidence(**kwargs)


def test_health_rejects_readiness_without_evidence_and_unavailable_without_error() -> None:
    contract = _contract()
    descriptor = _descriptor()
    unknown_reliability = contract.ReliabilityEvidence(
        status="not_measured", value=None, source_ref=None, evidence_refs=()
    )

    with pytest.raises(ValueError, match="evidence"):
        contract.ProviderHealthSnapshot(
            provider_id=descriptor.provider_id,
            provider_version=descriptor.provider_version,
            source_revision=descriptor.source_revision,
            descriptor_fingerprint=descriptor.fingerprint,
            observed_at=FINISHED,
            status="ready",
            capability_ids=("tool:echo",),
            reliability=unknown_reliability,
            evidence_refs=(),
            error_code=None,
        )
    with pytest.raises(ValueError, match="error"):
        contract.ProviderHealthSnapshot(
            provider_id=descriptor.provider_id,
            provider_version=descriptor.provider_version,
            source_revision=descriptor.source_revision,
            descriptor_fingerprint=descriptor.fingerprint,
            observed_at=FINISHED,
            status="unavailable",
            capability_ids=("tool:echo",),
            reliability=unknown_reliability,
            evidence_refs=("evidence:health",),
            error_code=None,
        )


def test_health_binding_and_deserialization_reject_drift_and_authority_forgery() -> None:
    contract = _contract()
    descriptor = _descriptor()
    health = contract.ProviderHealthSnapshot(
        provider_id=descriptor.provider_id,
        provider_version=descriptor.provider_version,
        source_revision=descriptor.source_revision,
        descriptor_fingerprint=descriptor.fingerprint,
        observed_at=FINISHED,
        status="degraded",
        capability_ids=("tool:echo",),
        reliability=contract.ReliabilityEvidence(
            status="failed",
            value=None,
            source_ref="benchmark:e9-fixture",
            evidence_refs=("evidence:failure",),
        ),
        evidence_refs=("evidence:health",),
        error_code="measurement_failed",
    )
    payload = health.to_dict()
    payload["capability_ids"] = ["tool:other"]
    drifted = contract.ProviderHealthSnapshot.from_json(json.dumps(payload))
    with pytest.raises(ValueError, match="capability"):
        contract.validate_health_against_descriptor(drifted, descriptor)

    revision_drift = _descriptor(source_revision="b" * 40)
    with pytest.raises(ValueError, match="revision|fingerprint"):
        contract.validate_health_against_descriptor(health, revision_drift)

    declaration_drift = _descriptor(
        lifecycle=contract.LifecycleSupport(
            cancellation=False,
            checkpointing=False,
            idempotency=False,
            partial_effect_modes=("none",),
        )
    )
    with pytest.raises(ValueError, match="fingerprint"):
        contract.validate_health_against_descriptor(health, declaration_drift)

    for field, value in (
        ("can_mark_complete", True),
        ("grants_authority", 0),
        ("requires_external_verification", "true"),
    ):
        forged = health.to_dict()
        forged[field] = value
        with pytest.raises(ValueError, match="authority"):
            contract.ProviderHealthSnapshot.from_json(json.dumps(forged))


def test_semantic_changes_change_request_and_result_fingerprints() -> None:
    first = _request(inputs={"message": "one"})
    second = _request(inputs={"message": "two"})
    assert first.fingerprint != second.fingerprint

    first_result = _result(request=first)
    second_result = _result(request=second)
    assert first_result.fingerprint != second_result.fingerprint


def test_protocol_is_structural_and_module_import_has_no_runtime_side_effects() -> None:
    contract = _contract()
    assert getattr(contract.ExecutionProvider, "_is_protocol", False) is True

    probe = (
        "import sys\n"
        "import agents.core.execution_provider_contract\n"
        "blocked = ["
        "'agents.core.capability_actions', 'agents.core.kernel', "
        "'agents.core.sandbox', 'agents.core.skills.importer', "
        "'agents.core.tool_rpc']\n"
        "print([name for name in blocked if name in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
