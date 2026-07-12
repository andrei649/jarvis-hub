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
from agents.core.plugin_gate import BUILTIN_PLUGINS


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


def test_rollback_contract_rejects_false_or_contradictory_promises():
    with pytest.raises(ValueError, match="mode"):
        RollbackContract(mode="magic", description="Pretend to undo.")
    with pytest.raises(ValueError, match="description"):
        RollbackContract(mode="restore", description=" ")
    with pytest.raises(ValueError, match="handler"):
        RollbackContract(mode="restore", description="Restore it.", automatic=True)
    with pytest.raises(ValueError, match="none"):
        RollbackContract(mode="none", description="Nothing to undo.", automatic=True,
                         handler_ref="example:undo")


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
        "none", "cancel", "compensate", "restore", "revoke", "disable",
        "implementation_specific",
    }
    if manifest.rollback.automatic:
        assert manifest.rollback.handler_ref
    assert manifest.confidence == 0.0  # H27.7 earns this from real outcomes
    assert ":" in manifest.implementation


def test_manifest_for_action_resolves_exact_and_wildcard_kinds():
    assert manifest_for_action("payment") is ACTION_CAPABILITY_MANIFESTS["payment"]
    assert manifest_for_action("social.post") is ACTION_CAPABILITY_MANIFESTS["social.*"]
    assert manifest_for_action("writeback.notion") is ACTION_CAPABILITY_MANIFESTS["writeback.*"]
    assert manifest_for_action("unknown.action") is None


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


def test_plugin_defaults_are_conservative_for_transmitted_and_disabled_plugins():
    cloud = BUILTIN_PLUGINS["cloud-llm"]
    assert plugin_capability_manifest(cloud).risk == "sensitive"
    assert plugin_capability_manifest(BUILTIN_PLUGINS["system-control"]).risk == "sensitive"

    disabled = replace(BUILTIN_PLUGINS["weather"], enabled=False)
    assert plugin_capability_manifest(disabled).confidence == 0.0
