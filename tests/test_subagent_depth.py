"""ORIZONT-24 K3 — recursion-depth cap on agent-initiated sub-agent delegation.

The concurrency cap stops an agent forking *wide*; this stops it forking *deep* — a
sub-agent that spawns a sub-agent that spawns a sub-agent can't tower up unbounded
(OWASP unbounded-consumption). Depth is inferred from the recorded parent-chain, so it
needs no runner cooperation. Default cap = 8; None = unbounded.
"""
import asyncio

from agents.core.subagents import SubAgentManager


def _run(coro):
    return asyncio.run(coro)


def test_recursion_depth_cap_rejects_deep_chains():
    m = SubAgentManager(max_depth=3)
    r0 = _run(m.spawn("t"))                        # top-level → depth 0
    r1 = _run(m.spawn("t", parent=r0["id"]))       # depth 1
    r2 = _run(m.spawn("t", parent=r1["id"]))       # depth 2
    assert all(r["ok"] for r in (r0, r1, r2))
    r3 = _run(m.spawn("t", parent=r2["id"]))       # depth 3 → rejected (>= max_depth)
    assert r3["ok"] is False and r3["reason"] == "recursion_depth_cap"
    assert r3["depth"] == 3 and r3["max_depth"] == 3


def test_flat_spawns_never_hit_depth_cap():
    m = SubAgentManager(max_depth=2, max_concurrent=10)
    for _ in range(6):
        assert _run(m.spawn("t"))["ok"] is True    # all top-level (parent=root) → depth 0


def test_none_depth_is_unbounded():
    m = SubAgentManager(max_depth=None)
    pid = ""
    for _ in range(12):
        r = _run(m.spawn("t", parent=pid))
        assert r["ok"] is True
        pid = r["id"]


def test_stats_and_normalization():
    assert SubAgentManager(max_depth=5).stats()["max_depth"] == 5
    assert SubAgentManager(max_depth=0).stats()["max_depth"] is None    # <=0 → unbounded
    assert SubAgentManager().stats()["max_depth"] == 8                  # sane default guard
