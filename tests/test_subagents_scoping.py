"""H20.6 hardening — sub-agent blocked-capability scoping + spawn budget. Offline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.iteration_budget import IterationBudget
from agents.core.subagents import (
    DELEGATE_BLOCKED_CAPABILITIES,
    SubAgentManager,
)


async def test_spawn_records_blocked_capabilities():
    m = SubAgentManager()
    out = await m.spawn("do a thing")
    assert out["ok"] is True
    rec = m.get(out["id"])
    assert rec["blocked"] == sorted(DELEGATE_BLOCKED_CAPABILITIES)
    assert "delegate" in rec["blocked"] and "channel_send" in rec["blocked"]


async def test_runner_receives_blocked_when_it_opts_in():
    seen = {}

    async def runner(task, session_id, agent, blocked=None):
        seen["blocked"] = blocked
        return {"output": "ok"}

    m = SubAgentManager(runner=runner)
    out = await m.spawn("scoped work")
    assert out["ok"] is True
    assert seen["blocked"] == DELEGATE_BLOCKED_CAPABILITIES


async def test_legacy_runner_signature_still_works():
    async def runner(task, session_id, agent):
        return {"output": "legacy"}

    m = SubAgentManager(runner=runner)
    out = await m.spawn("legacy work")
    assert out["ok"] is True and out["result"]["output"] == "legacy"


async def test_custom_blocked_set_overrides_default():
    m = SubAgentManager(blocked=frozenset({"delegate"}))
    out = await m.spawn("t")
    assert m.get(out["id"])["blocked"] == ["delegate"]


async def test_spawn_budget_exhaustion_rejects():
    m = SubAgentManager(budget=IterationBudget(1))
    first = await m.spawn("one")
    assert first["ok"] is True
    second = await m.spawn("two")
    assert second["ok"] is False and second["reason"] == "spawn_budget_exhausted"


async def test_no_budget_keeps_unbounded_totals():
    m = SubAgentManager()
    for i in range(5):
        assert (await m.spawn(f"t{i}"))["ok"] is True
    assert m.stats()["total"] == 5
    assert "budget" not in m.stats()


async def test_stats_include_budget_and_blocked():
    m = SubAgentManager(budget=IterationBudget(2))
    st = m.stats()
    assert st["budget"] == {"max_total": 2, "used": 0, "remaining": 2}
    assert st["blocked"] == sorted(DELEGATE_BLOCKED_CAPABILITIES)
