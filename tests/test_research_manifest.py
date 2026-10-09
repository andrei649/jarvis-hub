"""The exact research declaration describes its governed executor."""

from __future__ import annotations

import importlib

from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS, manifest_for_action


def test_research_manifest_has_optional_query_and_resolvable_executor_owner():
    manifest = ACTION_CAPABILITY_MANIFESTS["research"]
    assert manifest_for_action("research") is manifest
    assert manifest_for_action("research.extra") is None
    assert manifest.inputs["required"] == []
    assert manifest.risk == "read_only"
    assert manifest.rollback.mode == "cancel"
    assert manifest.rollback.automatic is False
    assert manifest.confidence == 0.0
    module_name, member_path = manifest.implementation.split(":", 1)
    owner = importlib.import_module(module_name)
    for part in member_path.split("."):
        owner = getattr(owner, part)
    assert callable(owner)
