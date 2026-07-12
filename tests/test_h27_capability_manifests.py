from dataclasses import FrozenInstanceError

import pytest

from agents.core.capability_manifests import (
    ACTION_CAPABILITY_MANIFESTS,
    CapabilityManifest,
    manifest_for_action,
    validate_manifest,
)
from agents.core.kernel.registry import ACTION_REGISTRY


def _manifest(**overrides):
    values = {
        "id": "action:example.run",
        "description": "Run a bounded example action.",
        "inputs": {"type": "object", "required": ["value"]},
        "risk": "reversible",
        "requires": ("action-kernel",),
        "supports": ("execute",),
        "verification": "action-auth:example.run",
        "rollback": "restore the previous value",
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
    assert manifest.verification == f"action-auth:{kind}"
    assert manifest.rollback
    assert 0.0 <= manifest.confidence <= 1.0
    assert ":" in manifest.implementation


def test_manifest_for_action_resolves_exact_and_wildcard_kinds():
    assert manifest_for_action("payment") is ACTION_CAPABILITY_MANIFESTS["payment"]
    assert manifest_for_action("social.post") is ACTION_CAPABILITY_MANIFESTS["social.*"]
    assert manifest_for_action("writeback.notion") is ACTION_CAPABILITY_MANIFESTS["writeback.*"]
    assert manifest_for_action("unknown.action") is None
