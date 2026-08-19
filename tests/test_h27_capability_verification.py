from functools import lru_cache
from types import ModuleType, SimpleNamespace

import pytest

from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
from agents.core.observability import capability_registry as cr
from agents.core.observability import reality_harness as rh
from agents.core.observability.reality_harness import (
    ACTION_CAPABILITY_CASES,
    CASES,
    TOOL_CAPABILITY_CASES,
    RealityCase,
    all_reality_cases,
    registry_reality_cases,
    run_reality,
)
from agents.core.tool_rpc import ToolRPCServer


def teardown_function():
    cr.clear_verifications()


def _tool_orch():
    server = ToolRPCServer()
    server.register_tool("echo", lambda args: args, description="Echo.", capability_id="tool:echo")
    server.register_tool("time", lambda args: args, description="Time.", capability_id="tool:time")
    return SimpleNamespace(
        tool_rpc=server,
        components=SimpleNamespace(status={}),
        skills=SimpleNamespace(skills={}),
    )


@lru_cache(maxsize=1)
def _registry_orch():
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator(JarvisConfig())
    orch.skills.discover()
    return orch


def test_reality_case_has_stable_reference():
    async def probe():
        return True

    case = RealityCase("tool:x", "tool-x-protocol", "works", probe)
    assert case.ref == "reality-v1:tool-x-protocol"


def test_reality_coverage_gate_explains_every_invalid_proof_binding():
    async def probe():
        return True

    checker = getattr(rh, "reality_coverage_gaps", None)
    assert checker is not None, "the readiness matrix has no executable coverage gate"

    records = [
        cr.CapabilityRecord(
            id="tool:healthy",
            kind="tool",
            state=cr.WIRED,
            verification="reality-v1:healthy",
        ),
        cr.CapabilityRecord(
            id="tool:missing",
            kind="tool",
            state=cr.WIRED,
            verification="reality-v1:missing",
        ),
        cr.CapabilityRecord(
            id="tool:duplicate",
            kind="tool",
            state=cr.WIRED,
            verification="reality-v1:duplicate",
        ),
        cr.CapabilityRecord(
            id="tool:mismatch",
            kind="tool",
            state=cr.WIRED,
            verification="reality-v1:mismatch",
        ),
        cr.CapabilityRecord(
            id="tool:non-promotable",
            kind="tool",
            state=cr.WIRED,
            verification="reality-v1:non-promotable",
        ),
    ]
    cases = [
        RealityCase("tool:healthy", "healthy", "covered", probe),
        RealityCase("tool:duplicate", "duplicate", "first", probe),
        RealityCase("tool:duplicate", "duplicate", "second", probe),
        RealityCase("tool:someone-else", "mismatch", "wrong capability", probe),
        RealityCase(
            "tool:non-promotable",
            "non-promotable",
            "cannot certify readiness",
            probe,
            metadata={"promotable": False},
        ),
    ]

    assert checker(records, cases) == {
        "tool:missing": "missing-case",
        "tool:duplicate": "duplicate-case",
        "tool:mismatch": "capability-mismatch",
        "tool:non-promotable": "non-promotable-case",
    }


def test_every_action_and_live_tool_verification_ref_matches_a_real_case():
    cases = {case.ref: case for case in ACTION_CAPABILITY_CASES + TOOL_CAPABILITY_CASES}
    assert len(cases) == len(ACTION_CAPABILITY_CASES) + len(TOOL_CAPABILITY_CASES)

    for manifest in ACTION_CAPABILITY_MANIFESTS.values():
        assert manifest.verification in cases
        assert cases[manifest.verification].capability_id == manifest.id

    tools = [record for record in cr.build_records(_tool_orch()) if record.kind == "tool"]
    assert {record.id for record in tools} == {"tool:echo", "tool:time"}
    for record in tools:
        assert record.verification in cases
        assert cases[record.verification].capability_id == record.id


@pytest.mark.asyncio
async def test_all_executable_capability_cases_pass_hermetically_without_flag_leak(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "before")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "before")

    result = await run_reality(
        ACTION_CAPABILITY_CASES + TOOL_CAPABILITY_CASES,
        promote=False,
        now="2026-07-12T00:00:00+00:00",
    )

    assert result["total"] == 23
    assert result["passed"] == 23
    assert result["skipped"] == 0
    assert result["promoted"] == []
    assert all(item["passed"] for item in result["results"])
    assert __import__("os").environ["JARVIS_UNIFIED_ACTION_API"] == "before"
    assert __import__("os").environ["JARVIS_ACTION_KERNEL"] == "before"


@pytest.mark.asyncio
async def test_green_action_case_promotes_only_through_reality_runner():
    case = ACTION_CAPABILITY_CASES[0]
    before = {record.id: record for record in cr.build_records()}[case.capability_id]
    assert before.state == cr.WIRED

    result = await run_reality([case], promote=True, now="2026-07-12T00:00:00+00:00")

    assert result["promoted"] == [case.capability_id]
    after = {record.id: record for record in cr.build_records()}[case.capability_id]
    assert after.state == cr.VERIFIED
    assert after.harness_id == "reality-v1"


def test_every_boot_registry_verification_ref_matches_one_real_case():
    orch = _registry_orch()
    records = [
        record
        for record in cr.build_records(orch)
        if record.kind in {"plugin", "component", "skill"}
    ]
    cases = registry_reality_cases(orch)
    by_ref = {case.ref: case for case in cases}

    assert len(records) == len(cases) == len(by_ref) == 74
    assert {
        kind: sum(case.capability_id.startswith(f"{kind}:") for case in cases)
        for kind in ("plugin", "component", "skill")
    } == {
        "plugin": 38,
        "component": 24,
        "skill": 12,
    }
    assert len({case.capability_id for case in cases}) == 74
    for record in records:
        assert record.verification in by_ref
        assert by_ref[record.verification].capability_id == record.id

    combined = all_reality_cases(orch)
    assert combined[: len(CASES)] == CASES
    assert len(combined) == len(CASES) + 74
    all_refs = [case.ref for case in combined]
    assert len(all_refs) == len(set(all_refs))

    tool_records = [record for record in cr.build_records(_tool_orch()) if record.kind == "tool"]
    verification_pairs = [
        (manifest.verification, manifest.id) for manifest in ACTION_CAPABILITY_MANIFESTS.values()
    ] + [(record.verification, record.id) for record in [*tool_records, *records]]
    assert len(verification_pairs) == 97
    for verification_ref, capability_id in verification_pairs:
        matches = [case for case in combined if case.ref == verification_ref]
        assert len(matches) == 1
        assert matches[0].capability_id == capability_id


@pytest.mark.asyncio
async def test_wired_registry_cases_pass_hermetically_and_seam_fails_honestly(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    orch = _registry_orch()
    records = {record.id: record for record in cr.build_records(orch)}
    cases = registry_reality_cases(orch)

    result = await run_reality(cases, promote=False)
    by_id = {item["capability_id"]: item for item in result["results"]}

    assert result["total"] == 74
    assert result["passed"] == 73
    assert result["skipped"] == 0
    assert all(
        by_id[case.capability_id]["passed"]
        for case in cases
        if records[case.capability_id].state == cr.WIRED
    )
    assert by_id["skill:Weather Intel"]["passed"] is False
    assert __import__("os").environ["JARVIS_STRICT_EGRESS"] == "0"


@pytest.mark.asyncio
async def test_intentional_skill_seam_cannot_be_promoted():
    orch = _registry_orch()
    case = next(
        case for case in registry_reality_cases(orch) if case.capability_id == "skill:Weather Intel"
    )

    result = await run_reality([case], promote=True, now="2026-07-12T00:00:00+00:00")

    assert result["passed"] == 0
    assert result["promoted"] == []
    after = {record.id: record for record in cr.build_records(orch)}[case.capability_id]
    assert after.state == cr.SEAM
    assert after.harness_id is None


@pytest.mark.asyncio
async def test_component_and_skill_construction_mismatches_fail_closed():
    fake_orch = SimpleNamespace(
        components=SimpleNamespace(status={"broken": "ok"}),
        broken=None,
        skills=SimpleNamespace(
            skills={
                "Missing Module": SimpleNamespace(module=None),
                "Loaded Module": SimpleNamespace(module=ModuleType("loaded")),
            }
        ),
    )
    cases = {
        case.capability_id: case
        for case in registry_reality_cases(fake_orch)
        if case.capability_id in {"component:broken", "skill:Missing Module", "skill:Loaded Module"}
    }

    result = await run_reality(list(cases.values()), promote=False)
    by_id = {item["capability_id"]: item["passed"] for item in result["results"]}

    assert by_id == {
        "component:broken": False,
        "skill:Missing Module": False,
        "skill:Loaded Module": True,
    }


@pytest.mark.asyncio
async def test_action_case_fails_closed_when_manifest_implementation_is_missing():
    """ADV-087: a green action case must certify the declared actuator exists —
    a manifest whose implementation does not resolve may not pass its rail probe."""
    from dataclasses import replace

    from agents.core.observability.reality_harness import _make_action_kernel_probe

    manifest = ACTION_CAPABILITY_MANIFESTS["node.dispatch"]
    broken = replace(manifest, implementation="agents.core.node_mesh:NodeMesh.no_such_actuator")
    case = RealityCase(
        broken.id,
        "action-broken-implementation",
        "a manifest whose declared implementation does not resolve must not certify",
        _make_action_kernel_probe(broken),
    )

    result = await run_reality([case], promote=False, now="2026-08-11T00:00:00+00:00")

    assert result["passed"] == 0
    assert result["results"][0]["passed"] is False


@pytest.mark.asyncio
async def test_action_case_records_the_implementation_it_certified():
    """The green case's evidence names the resolved actuator, not just the refusal."""
    case = ACTION_CAPABILITY_CASES[0]

    result = await run_reality([case], promote=False, now="2026-08-11T00:00:00+00:00")

    item = result["results"][0]
    assert item["passed"] is True
    assert item["metadata"]["implementation_resolves"] is True
    assert ":" in item["metadata"]["implementation"]
