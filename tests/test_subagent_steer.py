"""co-subagent-steer — steerable sub-agents: steer/stop, typed output, per-spawn
cost, spawn persistence (observability only), agent-origin approval refusal,
and the /api/subagents/{id}/steer|stop routes. All offline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from agents.core.iteration_budget import IterationBudget
from agents.core.subagents import (
    SPAWN_TRANSITIONS,
    SteerChannel,
    SteerMessage,
    SubAgentManager,
    validate_output,
)

_NO_COST = lambda: {}  # noqa: E731 — hermetic: never touch the live cost tracker


def _mgr(**kw):
    kw.setdefault("cost_probe", _NO_COST)
    kw.setdefault("persist", False)
    return SubAgentManager(**kw)


class _SteerableRunner:
    """Waits for one steer message, echoes it back as its output."""

    def __init__(self):
        self.seen = []

    async def __call__(self, task, session_id, agent, blocked=None, steer=None):
        msg = await steer.get()
        self.seen.append(msg)
        return {"output": f"steered:{msg['text']}", "origin": msg["origin"]}


# ── steer ──────────────────────────────────────────────────────────

async def test_steer_delivered_to_running_child():
    runner = _SteerableRunner()
    m = _mgr(runner=runner)
    t = asyncio.create_task(m.spawn("long job"))
    await asyncio.sleep(0.01)
    spawn_id = m.list()[0]["id"]
    out = m.steer(spawn_id, "focus on Q3", origin="agent")
    assert out["ok"] is True and out["delivered"] is True and out["origin"] == "agent"
    res = await t
    assert res["ok"] is True and res["result"]["output"] == "steered:focus on Q3"
    assert runner.seen[0]["can_approve"] is False
    rec = m.get(spawn_id)
    assert rec["steers"][0]["text"] == "focus on Q3" and rec["steerable"] is True


async def test_steer_legacy_runner_is_recorded_but_not_delivered():
    release = asyncio.Event()

    async def runner(task, session_id, agent):
        await release.wait()
        return {"output": "ok"}

    m = _mgr(runner=runner)
    t = asyncio.create_task(m.spawn("x"))
    await asyncio.sleep(0.01)
    sid = m.list()[0]["id"]
    out = m.steer(sid, "hello")
    assert out["ok"] is True and out["delivered"] is False
    assert m.get(sid)["steers"][0]["origin"] == "user"
    release.set()
    await t


async def test_steer_unknown_and_finished_spawns_refuse():
    m = _mgr()
    assert m.steer("nope", "x")["reason"] == "unknown_spawn"
    done = await m.spawn("t")
    out = m.steer(done["id"], "late")
    assert out["ok"] is False and out["reason"] == "not_running" and out["status"] == "done"


async def test_steer_rejects_bad_origin_and_empty_text():
    release = asyncio.Event()

    async def runner(task, session_id, agent, steer=None):
        await release.wait()
        return {"output": "ok"}

    m = _mgr(runner=runner)
    t = asyncio.create_task(m.spawn("x"))
    await asyncio.sleep(0.01)
    sid = m.list()[0]["id"]
    assert m.steer(sid, "x", origin="system")["reason"] == "invalid_steer"
    assert m.steer(sid, "   ")["reason"] == "invalid_steer"
    with pytest.raises(ValueError):
        SteerMessage(spawn_id=sid, text="x", origin="operator")
    release.set()
    await t


async def test_steer_channel_poll_drains_in_order():
    chan = SteerChannel("s")
    chan.push(SteerMessage(spawn_id="s", text="a"))
    chan.push(SteerMessage(spawn_id="s", text="b", origin="agent"))
    assert chan.pending == 2
    got = chan.poll()
    assert [g["text"] for g in got] == ["a", "b"] and chan.pending == 0
    assert await chan.get(timeout=0.01) is None


# ── stop ───────────────────────────────────────────────────────────

async def test_stop_cancels_running_child():
    started = asyncio.Event()
    cancelled = {"seen": False}

    async def runner(task, session_id, agent, steer=None):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled["seen"] = True
            assert steer.stop_requested is True
            raise
        return {"output": "never"}

    m = _mgr(runner=runner)
    t = asyncio.create_task(m.spawn("slow"))
    await started.wait()
    sid = m.list()[0]["id"]
    out = m.stop(sid)
    assert out["ok"] is True and out["status"] == "stopping"
    res = await t                                  # spawn() unwinds, not raises
    assert res["ok"] is False and res["status"] == "stopped"
    assert cancelled["seen"] is True
    rec = m.get(sid)
    assert rec["status"] == "stopped" and rec["stop_reason"] == "operator"
    assert rec["result"] == {"error": "stopped", "reason": "operator"}
    assert m.stats()["active"] == 0 and m.stats()["by_status"] == {"stopped": 1}
    # a second stop is a no-op refusal
    assert m.stop(sid)["reason"] == "not_running"


async def test_parent_cancellation_marks_stopped_and_propagates():
    started = asyncio.Event()

    async def runner(task, session_id, agent):
        started.set()
        await asyncio.sleep(30)
        return {"output": "never"}

    m = _mgr(runner=runner)
    t = asyncio.create_task(m.spawn("slow"))
    await started.wait()
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    rec = m.list()[0]
    assert rec["status"] == "stopped" and rec["stop_reason"] == "parent_cancelled"
    assert m.stats()["active"] == 0


def test_transition_table_is_strict():
    assert "stopped" in SPAWN_TRANSITIONS["running"]
    assert SPAWN_TRANSITIONS["done"] == frozenset()
    m = _mgr()
    rec = {"status": "done"}
    with pytest.raises(ValueError):
        m._set_status(rec, "running")


# ── typed output ───────────────────────────────────────────────────

def test_validate_output_type_required_enum_nested():
    schema = {"type": "object", "required": ["summary", "verdict"],
              "properties": {"summary": {"type": "string"},
                             "verdict": {"type": "string", "enum": ["ship", "hold"]},
                             "items": {"type": "array", "items": {"type": "integer"}}}}
    assert validate_output({"summary": "ok", "verdict": "ship", "items": [1, 2]}, schema) == []
    bad = validate_output({"summary": 3, "verdict": "maybe", "items": [1, "x"]}, schema)
    assert any("$.summary" in v and "string" in v for v in bad)
    assert any("$.verdict" in v and "enum" in v for v in bad)
    assert any("$.items[1]" in v for v in bad)
    assert validate_output("str", schema) == ["$: expected type 'object', got str"]
    assert validate_output({}, schema)[:2] == ["$: missing required property 'summary'",
                                               "$: missing required property 'verdict'"]
    assert validate_output(True, {"type": "integer"})        # bool is not an integer
    assert validate_output(1, {"type": ["string", "integer"]}) == []
    assert validate_output(1, {"type": "wat"}) == ["$: unknown type 'wat'"]
    assert validate_output(1, "nope") == ["$: schema must be an object"]


async def test_schema_violation_surfaces_as_failed_output():
    async def runner(task, session_id, agent):
        return {"output": "free text", "verdict": "maybe"}

    m = _mgr(runner=runner)
    schema = {"type": "object", "required": ["verdict", "score"],
              "properties": {"verdict": {"enum": ["ship", "hold"]}}}
    out = await m.spawn("judge", output_schema=schema)
    assert out["ok"] is False and out["status"] == "failed"
    assert out["result"]["error"] == "output_schema_violation"
    assert "$: missing required property 'score'" in out["result"]["violations"]
    assert any("enum" in v for v in out["result"]["violations"])
    assert out["result"]["output"]["output"] == "free text"     # original kept for inspection
    assert m.stats()["active"] == 0


async def test_schema_valid_output_is_done_and_recorded():
    async def runner(task, session_id, agent):
        return {"verdict": "ship", "score": 9}

    m = _mgr(runner=runner)
    schema = {"type": "object", "required": ["verdict", "score"]}
    out = await m.spawn("judge", output_schema=schema)
    assert out["ok"] is True and out["result"] == {"verdict": "ship", "score": 9}
    assert m.get(out["id"])["output_schema"] == schema


async def test_invalid_schema_is_refused_without_spending_budget():
    m = _mgr(budget=IterationBudget(1))
    out = await m.spawn("t", output_schema="not-a-schema")
    assert out["ok"] is False and out["reason"] == "invalid_output_schema"
    assert m.budget.used == 0


# ── budget ─────────────────────────────────────────────────────────

async def test_spawn_budget_exhausted_refuses_further_spawns():
    m = _mgr(budget=IterationBudget(2))
    assert (await m.spawn("a"))["ok"] and (await m.spawn("b"))["ok"]
    out = await m.spawn("c")
    assert out == {"ok": False, "reason": "spawn_budget_exhausted", "used": 2, "max_total": 2}
    assert m.stats()["budget"] == {"max_total": 2, "used": 2, "remaining": 0}


# ── approval seam: agent origin can never satisfy approval ─────────

async def test_agent_origin_rejected_before_decision_hook():
    calls = []

    async def hook(task_id, action, decided_by="user"):
        calls.append((task_id, action, decided_by))
        return type("T", (), {"status": "approved"})()

    m = _mgr(decision_hook=hook)
    done = await m.spawn("t")
    out = await m.decide(done["id"], 12, "accept", origin="agent")
    assert out == {"ok": False, "reason": "agent_origin_cannot_approve",
                   "origin": "agent", "task_id": 12, "action": "accept"}
    assert calls == []                                  # hook never consulted
    # default origin is agent: a bare call from a spawn context is refused too
    assert (await m.decide(done["id"], 12, "accept"))["reason"] == "agent_origin_cannot_approve"
    # a user-origin request goes through the human-decision hook, attributed
    ok = await m.decide(done["id"], 12, "accept", origin="user")
    assert ok["ok"] is True and ok["status"] == "approved"
    assert calls == [(12, "accept", f"user:via-subagent:{done['id']}")]


async def test_decide_without_hook_or_spawn_refuses():
    m = _mgr()
    assert (await m.decide("x", 1, "accept", origin="user"))["reason"] == "decision_hook_unavailable"

    async def hook(task_id, action, decided_by="user"):
        raise RuntimeError("queue down")

    m2 = _mgr(decision_hook=hook)
    assert (await m2.decide("ghost", 1, "accept", origin="user"))["reason"] == "unknown_spawn"
    done = await m2.spawn("t")
    assert (await m2.decide(done["id"], 1, "accept", origin="user"))["reason"] == "decision_failed"


# ── cost per delegation ────────────────────────────────────────────

async def test_cost_from_runner_usage_is_exact():
    async def runner(task, session_id, agent):
        return {"output": "x", "usage": {"input_tokens": 120, "output_tokens": 30,
                                         "cost_usd": 0.0015}}

    m = _mgr(runner=runner)
    out = await m.spawn("t")
    assert out["cost"] == {"input_tokens": 120, "output_tokens": 30,
                           "cost_usd": 0.0015, "source": "runner_usage"}
    assert m.stats()["cost_usd"] == 0.0015


async def test_cost_from_tracker_delta_when_runner_reports_none():
    tracker = {"agents": {"jarvis": {"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.01}}}

    async def runner(task, session_id, agent):
        tracker["agents"]["jarvis"] = {"input_tokens": 400, "output_tokens": 60, "cost_usd": 0.04}
        return {"output": "x"}

    m = _mgr(runner=runner, cost_probe=lambda: tracker)
    out = await m.spawn("t")
    assert out["cost"] == {"input_tokens": 300, "output_tokens": 50,
                           "cost_usd": 0.03, "source": "tracker_delta"}


async def test_cost_probe_failure_is_best_effort():
    def boom():
        raise RuntimeError("no tracker")

    m = _mgr(cost_probe=boom)
    out = await m.spawn("t")
    assert out["ok"] is True and out["cost"] is None


# ── persistence (observability only) ───────────────────────────────

async def test_spawn_records_persist_to_jsonl_when_enabled(tmp_path):
    log = tmp_path / "sub" / "spawns.jsonl"

    async def runner(task, session_id, agent):
        return {"output": "y" * 5000}

    m = _mgr(runner=runner, persist=True, spawn_log=log)
    a = await m.spawn("first")
    b = await m.spawn("second", output_schema={"type": "string"})    # violation → failed
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in lines] == [a["id"], b["id"]]
    assert lines[0]["status"] == "done" and lines[1]["status"] == "failed"
    assert len(lines[0]["result"]["output"]) == 2001          # previewed, not whole
    assert lines[1]["result"]["error"] == "output_schema_violation"
    assert m.stats()["persist"] is True


async def test_spawn_persistence_default_off(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SUBAGENT_SPAWN_LOG", raising=False)
    log = tmp_path / "spawns.jsonl"
    m = SubAgentManager(cost_probe=_NO_COST, spawn_log=log)
    await m.spawn("t")
    assert m.persist is False and not log.exists()
    monkeypatch.setenv("JARVIS_SUBAGENT_SPAWN_LOG", "1")
    assert SubAgentManager(cost_probe=_NO_COST, spawn_log=log).persist is True


def test_default_spawn_log_lives_under_data_path():
    from agents.core.paths import data_path
    m = _mgr()
    assert m.spawn_log_path() == data_path("subagents", "spawns.jsonl")


# ── routes ─────────────────────────────────────────────────────────

class _Orch:
    def __init__(self, subagents):
        self.subagents = subagents


def _app(orch, monkeypatch):
    """The mesh router on a bare FastAPI app, guards overridden, orch injected
    both where the router reads it and where `require_component` does."""
    from agents.core.routers import _component, mesh
    from agents.core.routers._deps import admin_guard, user_guard
    monkeypatch.setattr(mesh, "get_orch", lambda: orch)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(mesh.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    return app


@pytest.fixture
def harness(monkeypatch):
    started = asyncio.Event()

    async def runner(task, session_id, agent, steer=None):
        if task == "wait":
            started.set()
            msg = await steer.get()
            return {"output": msg["text"], "origin": msg["origin"]}
        return {"output": task}

    m = _mgr(runner=runner)
    app = _app(_Orch(m), monkeypatch)
    return m, started, httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://test")


async def test_route_steer_and_stop_lifecycle(harness):
    m, started, client = harness
    async with client:
        t = asyncio.create_task(m.spawn("wait"))
        await asyncio.wait_for(started.wait(), 2)
        sid = m.list()[0]["id"]
        # unknown → 404, steer → 200 with origin=user, recorded on the spawn
        r = await client.post("/api/subagents/ghost/steer", json={"message": "x"})
        assert r.status_code == 404
        r = await client.post(f"/api/subagents/{sid}/steer", json={"message": "go left"})
        assert r.status_code == 200 and r.json()["origin"] == "user" and r.json()["delivered"]
        res = await t
        assert res["result"]["output"] == "go left" and res["result"]["origin"] == "user"
        # finished → 409 for both steer and stop; validation 422 on empty message
        r = await client.post(f"/api/subagents/{sid}/steer", json={"message": "late"})
        assert r.status_code == 409
        assert (await client.post(f"/api/subagents/{sid}/stop")).status_code == 409
        r = await client.post(f"/api/subagents/{sid}/steer", json={"message": ""})
        assert r.status_code == 422
        assert (await client.post("/api/subagents/ghost/stop")).status_code == 404


async def test_route_stop_running_child(harness):
    m, started, client = harness
    async with client:
        t = asyncio.create_task(m.spawn("wait"))
        await asyncio.wait_for(started.wait(), 2)
        sid = m.list()[0]["id"]
        r = await client.post(f"/api/subagents/{sid}/stop")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert r.json()["status"] in {"stopping", "stopped"}
        res = await t
        assert res["status"] == "stopped"
        listing = (await client.get("/api/subagents")).json()
        assert listing["spawns"][0]["status"] == "stopped"
        assert listing["stats"]["by_status"] == {"stopped": 1}


async def test_route_spawn_schema_violation_is_422_not_429(harness):
    _, _, client = harness
    async with client:
        r = await client.post("/api/subagents/spawn",
                              json={"task": "judge", "output_schema": {"type": "object",
                                                                       "required": ["verdict"]}})
        assert r.status_code == 422
        assert r.json()["result"]["error"] == "output_schema_violation"
        ok = await client.post("/api/subagents/spawn", json={"task": "plain"})
        assert ok.status_code == 200 and ok.json()["result"]["output"] == "plain"


async def test_route_spawn_budget_exhausted_is_429(harness):
    m, _, client = harness
    m.budget = IterationBudget(0)
    async with client:
        r = await client.post("/api/subagents/spawn", json={"task": "x"})
        assert r.status_code == 429 and r.json()["reason"] == "spawn_budget_exhausted"


async def test_routes_503_without_component(monkeypatch):
    app = _app(None, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        assert (await c.post("/api/subagents/s/steer", json={"message": "x"})).status_code == 503
        assert (await c.post("/api/subagents/s/stop")).status_code == 503
        assert (await c.get("/api/subagents")).json() == {"spawns": [], "stats": {}}
