import json
from dataclasses import FrozenInstanceError, replace

import pytest

from agents.core.capability_manifests import (
    ACTION_CAPABILITY_MANIFESTS,
    CapabilityManifest,
    RollbackContract,
    manifest_for_action,
    plugin_capability_manifest,
    validate_manifest,
)
from agents.core.capability_verification import action_verification_ref
from agents.core.kernel.registry import ACTION_REGISTRY
from agents.core.observability.capability_registry import (
    GA,
    VERIFIED,
    WIRED,
    CapabilityRecord,
)
from agents.core.plugin_gate import BUILTIN_PLUGINS
from agents.core.synapse_manifest import (
    ManifestRevision,
    adapt_capability_manifest,
    adapt_capability_record,
    validate_synapse_manifest,
)


def _manifest(**overrides):
    values = {
        "id": "action:example.run",
        "description": "Run a bounded example action.",
        "inputs": {"type": "object", "required": ["value"]},
        "risk": "reversible",
        "requires": ("action-kernel",),
        "supports": ("execute",),
        "verification": "action-auth:example.run",
        "rollback": RollbackContract(
            mode="restore",
            description="Restore the previous value.",
            automatic=True,
            handler_ref="example.module:restore",
        ),
        "confidence": 0.5,
        "implementation": "example.module:run",
        "action_kind": "example.run",
    }
    values.update(overrides)
    return CapabilityManifest(**values)


def test_manifest_is_frozen_and_validates_confidence_and_risk():
    manifest = _manifest()
    assert validate_manifest(manifest) is manifest
    with pytest.raises(FrozenInstanceError):
        manifest.confidence = 0.9

    with pytest.raises(ValueError, match="confidence"):
        _manifest(confidence=1.01)
    with pytest.raises(ValueError, match="risk"):
        _manifest(risk="whatever")
    with pytest.raises(ValueError, match="object"):
        _manifest(inputs={"type": "array"})

    synapse = adapt_capability_manifest(manifest)
    assert validate_synapse_manifest(synapse) is synapse
    assert synapse.schema_version == "nerva.capability.v1"
    assert json.loads(json.dumps(synapse.to_payload()))["id"] == manifest.id
    assert synapse.permissions.grants_authority is False
    assert synapse.readiness == "declared"
    assert synapse.telemetry.reliability is None
    with pytest.raises(TypeError):
        synapse.inputs["type"] = "array"
    nested = adapt_capability_manifest(
        manifest,
        outputs={
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
    )
    with pytest.raises(TypeError):
        nested.outputs["properties"]["value"]["type"] = "number"

    with pytest.raises(ValueError, match="permissions"):
        replace(synapse, permissions=replace(synapse.permissions, required=()))
    with pytest.raises(ValueError, match="verifier"):
        replace(synapse, verifier=replace(synapse.verifier, verifier_ref=""))
    with pytest.raises(ValueError, match="never grant authority"):
        replace(synapse, permissions=replace(synapse.permissions, grants_authority=True))
    with pytest.raises(ValueError, match="never grant authority"):
        replace(synapse, permissions=replace(synapse.permissions, grants_authority=0))
    with pytest.raises(ValueError, match="capability risk"):
        replace(synapse, permissions=replace(synapse.permissions, risk="whatever"))
    with pytest.raises(ValueError, match="boolean"):
        replace(synapse, failure=replace(synapse.failure, retryable=1))
    with pytest.raises(ValueError, match="mapping"):
        adapt_capability_manifest(manifest, outputs=[("type", "object")])
    with pytest.raises(ValueError, match="object schema"):
        adapt_capability_manifest(manifest, outputs={})
    with pytest.raises(ValueError, match="preconditions"):
        adapt_capability_manifest(manifest, preconditions=())
    with pytest.raises(ValueError, match="privacy class"):
        adapt_capability_manifest(manifest, privacy_class="")
    with pytest.raises(ValueError, match="JSON-compatible"):
        adapt_capability_manifest(manifest, outputs={"type": "object", "bad": {1, 2}})
    with pytest.raises(ValueError, match="finite"):
        replace(
            synapse,
            telemetry=replace(
                synapse.telemetry,
                reliability=float("nan"),
                measurement_source="fixture",
            ),
        )

    for implementation in (
        ":",
        "module:",
        ":member",
        " module:member",
        "module:member ",
        "module::member",
    ):
        with pytest.raises(ValueError, match="module:member"):
            adapt_capability_manifest(_manifest(implementation=implementation))

    dotted = "example.module:Runner.execute"
    assert (
        adapt_capability_manifest(_manifest(implementation=dotted)).executor.implementation
        == dotted
    )

    for timestamp in (
        "2026-08-03T18:00+00:00",
        "2026-08-03T18:00:00+0000",
        "2026-W32-1T18:00:00+00:00",
        "2026-08-03T18:00:00,5+00:00",
        "2026-08-03T18:00:00+00:00:30",
        "2026-08-03 18:00:00+00:00",
        "2026-08-03T18:00:00",
    ):
        with pytest.raises(ValueError, match="RFC 3339"):
            replace(
                synapse,
                verifier=replace(synapse.verifier, last_verified_at=timestamp),
            )

    for timestamp in (
        "2026-08-03T18:00:00Z",
        "2026-08-03T18:00:00+03:00",
        "2026-08-03T18:00:00.123456-04:30",
    ):
        updated = replace(
            synapse,
            verifier=replace(synapse.verifier, last_verified_at=timestamp),
        )
        assert updated.verifier.last_verified_at == timestamp


def test_rollback_contract_rejects_false_or_contradictory_promises():
    with pytest.raises(ValueError, match="mode"):
        RollbackContract(mode="magic", description="Pretend to undo.")
    with pytest.raises(ValueError, match="description"):
        RollbackContract(mode="restore", description=" ")
    with pytest.raises(ValueError, match="handler"):
        RollbackContract(mode="restore", description="Restore it.", automatic=True)
    with pytest.raises(ValueError, match="none"):
        RollbackContract(
            mode="none",
            description="Nothing to undo.",
            automatic=True,
            handler_ref="example:undo",
        )

    previous = adapt_capability_manifest(_manifest())
    candidate = replace(previous, capability_version="1.0.1")
    revision = ManifestRevision(previous=previous, candidate=candidate)
    assert revision.rollback() is previous
    with pytest.raises(ValueError, match="capability id"):
        ManifestRevision(previous=previous, candidate=replace(candidate, id="action:other"))
    with pytest.raises(ValueError, match="Synapse manifests"):
        ManifestRevision(previous=object(), candidate=candidate)
    with pytest.raises(ValueError, match="SynapseManifest"):
        validate_synapse_manifest(object())
    malformed_rollback = RollbackContract(
        mode="restore",
        description="Restore the value.",
        automatic=1,
        handler_ref="example:restore",
    )
    with pytest.raises(ValueError, match="automatic flag"):
        replace(previous, rollback=malformed_rollback)


def test_action_manifest_coverage_exactly_matches_action_auth_registry():
    assert set(ACTION_CAPABILITY_MANIFESTS) == set(ACTION_REGISTRY)


@pytest.mark.parametrize("kind", sorted(ACTION_REGISTRY))
def test_every_action_manifest_is_complete_and_kernel_grounded(kind):
    manifest = ACTION_CAPABILITY_MANIFESTS[kind]
    assert manifest.id == f"action:{kind}"
    assert manifest.action_kind == kind
    assert manifest.description
    assert manifest.inputs["type"] == "object"
    assert manifest.risk in {
        "read_only",
        "reversible",
        "sensitive",
        "irreversible_or_money",
    }
    assert "action-kernel" in manifest.requires
    assert manifest.supports
    assert manifest.verification == action_verification_ref(kind)
    assert manifest.rollback.description
    assert manifest.rollback.mode in {
        "none",
        "cancel",
        "compensate",
        "restore",
        "revoke",
        "disable",
        "implementation_specific",
    }
    if manifest.rollback.automatic:
        assert manifest.rollback.handler_ref
    assert manifest.confidence == 0.0  # H27.7 earns this from real outcomes
    assert ":" in manifest.implementation

    synapse = adapt_capability_manifest(manifest)
    assert validate_synapse_manifest(synapse) is synapse
    assert synapse.inputs["type"] == "object"
    assert synapse.outputs["type"] == "object"
    assert synapse.preconditions == manifest.requires
    assert synapse.effects == manifest.supports
    assert synapse.permissions.required == manifest.requires
    assert synapse.permissions.grants_authority is False
    assert synapse.executor.implementation == manifest.implementation
    assert synapse.verifier.verifier_ref == manifest.verification
    assert synapse.rollback is manifest.rollback
    assert synapse.readiness == "declared"
    if kind == "media.present":
        assert synapse.permissions.approval_floor == "session"
        wired = CapabilityRecord(
            id=manifest.id,
            kind="action",
            state=WIRED,
            description=manifest.description,
            inputs=manifest.inputs,
            risk=manifest.risk,
            requires=manifest.requires,
            supports=manifest.supports,
            verification=manifest.verification,
            rollback=manifest.rollback,
            confidence=manifest.confidence,
            implementation=manifest.implementation,
        )
        assert adapt_capability_record(wired).readiness == "declared"
        demoted_with_stale_evidence = replace(
            wired,
            harness_id="stale-harness",
            last_verified="2026-08-03T17:00:00Z",
        )
        projected_demoted = adapt_capability_record(demoted_with_stale_evidence)
        assert projected_demoted.verifier.last_verified_at is None
        with pytest.raises(ValueError, match="verification"):
            adapt_capability_record(replace(wired, verification=None))
        with pytest.raises(ValueError, match="confidence"):
            adapt_capability_record(replace(wired, confidence=float("nan")))
        with pytest.raises(ValueError, match="harness evidence"):
            adapt_capability_record(replace(wired, state=VERIFIED))
        verified = replace(
            wired,
            state=VERIFIED,
            harness_id="media-present-ci",
            last_verified="2026-08-03T18:00:00Z",
        )
        projected = adapt_capability_record(verified)
        with pytest.raises(ValueError, match="last_verified"):
            adapt_capability_record(replace(verified, last_verified=1))
        assert projected.readiness == "hermetic_verified"
        assert projected.verifier.evidence_refs == ("reality-harness:media-present-ci",)
        assert adapt_capability_record(replace(verified, state=GA)).readiness == (
            "hermetic_verified"
        )
        with pytest.raises(ValueError, match="RFC 3339"):
            replace(
                projected,
                verifier=replace(projected.verifier, last_verified_at="yesterday"),
            )
        with pytest.raises(ValueError, match="reality-harness"):
            replace(
                projected,
                verifier=replace(
                    projected.verifier,
                    evidence_refs=("sandbox:media-present-ci",),
                ),
            )
        with pytest.raises(ValueError, match="owner-live"):
            replace(projected, readiness="live_verified")
    if kind == "payment":
        assert synapse.permissions.approval_floor == "permanent_owner"
        assert synapse.permissions.privacy_class == "restricted"
        with pytest.raises(ValueError, match="below the minimum"):
            adapt_capability_manifest(manifest, approval_floor="session")


def test_manifest_for_action_resolves_exact_and_wildcard_kinds():
    assert manifest_for_action("payment") is ACTION_CAPABILITY_MANIFESTS["payment"]
    assert manifest_for_action("social.post") is ACTION_CAPABILITY_MANIFESTS["social.*"]
    assert manifest_for_action("writeback.notion") is ACTION_CAPABILITY_MANIFESTS["writeback.*"]
    assert manifest_for_action("unknown.action") is None


def test_desktop_step_manifest_describes_kernel_mediated_host_action():
    manifest = ACTION_CAPABILITY_MANIFESTS["desktop.step"]
    assert manifest.id == "action:desktop.step"
    assert manifest.inputs["required"] == ["action", "args"]
    assert manifest.risk == "sensitive"
    assert set(manifest.supports) == {"observe", "mutate"}
    assert (
        manifest.implementation == "agents.core.desktop_operator:DesktopActionExecutor.perform"
    )
    assert manifest.contract_ref == "agents.core.desktop_operator:DESKTOP_STEP_CONTRACT"


def test_every_governed_plugin_derives_complete_v1_metadata():
    for plugin in BUILTIN_PLUGINS.values():
        manifest = plugin_capability_manifest(plugin)
        assert manifest.id == f"plugin:{plugin.id}"
        assert manifest.description == plugin.description
        assert manifest.inputs["type"] == "object"
        assert manifest.risk in {
            "read_only",
            "reversible",
            "sensitive",
            "irreversible_or_money",
        }
        assert "plugin.enabled" in manifest.requires
        assert "plugin-call" in manifest.supports
        assert manifest.verification == f"reality-v1:plugin:{plugin.id}"
        assert plugin.id in manifest.rollback.description
        assert manifest.rollback.mode == "disable"
        assert manifest.rollback.automatic is False
        assert manifest.confidence == 0.0  # no fabricated trust before H27.7
        assert manifest.implementation.startswith("agents.core.plugin_gate:")

        synapse = adapt_capability_manifest(manifest)
        assert validate_synapse_manifest(synapse) is synapse
        assert synapse.permissions.required == manifest.requires
        assert synapse.permissions.grants_authority is False
        assert synapse.verifier.verifier_ref == manifest.verification
        assert synapse.readiness == "declared"
        if plugin.id == "weather":
            assert synapse.permissions.approval_floor == "explicit"
            assert synapse.permissions.privacy_class == "sensitive"
            assert synapse.failure.codes == ("unknown",)


def test_plugin_defaults_are_conservative_for_transmitted_and_disabled_plugins():
    cloud = BUILTIN_PLUGINS["cloud-llm"]
    assert plugin_capability_manifest(cloud).risk == "sensitive"
    assert plugin_capability_manifest(BUILTIN_PLUGINS["system-control"]).risk == "sensitive"

    disabled = replace(BUILTIN_PLUGINS["weather"], enabled=False)
    assert plugin_capability_manifest(disabled).confidence == 0.0

    source = ACTION_CAPABILITY_MANIFESTS["tool.rpc"]
    with pytest.raises(ValueError, match="quarantined"):
        adapt_capability_manifest(source, generated=True, trust_state="builtin")
    quarantined = adapt_capability_manifest(
        source,
        generated=True,
        trust_state="quarantined",
        source_ref="agents.core.acquisition",
    )
    assert quarantined.provenance.generated is True
    assert quarantined.provenance.trust_state == "quarantined"
    assert quarantined.readiness == "discovered"
    with pytest.raises(ValueError, match="dated evidence"):
        replace(quarantined, readiness="sandboxed")
    sandboxed = replace(
        quarantined,
        readiness="sandboxed",
        verifier=replace(
            quarantined.verifier,
            evidence_refs=("sandbox:acquisition-receipt",),
            last_verified_at="2026-08-03T18:00:00Z",
        ),
    )
    assert sandboxed.readiness == "sandboxed"
    with pytest.raises(ValueError, match="generated flag"):
        replace(
            quarantined,
            provenance=replace(quarantined.provenance, generated=1),
        )
