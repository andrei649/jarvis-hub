from types import SimpleNamespace

import pytest

from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
from agents.core.observability import capability_registry as cr
from agents.core.observability.reality_harness import (
    ACTION_CAPABILITY_CASES,
    TOOL_CAPABILITY_CASES,
    RealityCase,
    run_reality,
)
from agents.core.tool_rpc import ToolRPCServer


def teardown_function():
    cr.clear_verifications()


def _tool_orch():
    server = ToolRPCServer()
    server.register_tool(
        "echo", lambda args: args, description="Echo.", capability_id="tool:echo"
    )
    server.register_tool(
        "time", lambda args: args, description="Time.", capability_id="tool:time"
    )
    return SimpleNamespace(
        tool_rpc=server,
        components=SimpleNamespace(status={}),
        skills=SimpleNamespace(skills={}),
    )


def test_reality_case_has_stable_reference():
    async def probe():
        return True

    case = RealityCase("tool:x", "tool-x-protocol", "works", probe)
    assert case.ref == "reality-v1:tool-x-protocol"


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

    assert result["total"] == 14
    assert result["passed"] == 14
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
