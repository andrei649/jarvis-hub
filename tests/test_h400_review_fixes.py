"""H400 review fixes — built from the adversarial reviewer's probes, on the real manager,
the real ``delegate_task`` tool, the real production runner and the real routes.

B1  a child's answer (or a schema) that the check cannot handle never strands a slot;
M1  switching ``llm.delegate_task`` off stops delegation at once;
M2  an approval a sub-agent asks for says so on the card;
M3  with the Action Kernel on, delegation is refused and says why;
minor 1  a child's loop exit does not land in the parent request's stop collector;
minor 2  a tool thread that outlives its cancelled child keeps the child's slot;
minor 3  every ``delegate_task`` call counts against the turn's tool ceiling;
minor 4  (in test_h400_delegation.py) the record lists the tools the child is offered;
NIT  a large parsed answer is not put whole into the parent's transcript.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import subagents  # noqa: E402
from agents.core.autonomy.policy import AutonomyPolicy  # noqa: E402
from agents.core.autonomy.queue import TaskQueue  # noqa: E402
from agents.core.autonomy.worker import AutonomyWorker  # noqa: E402
from agents.core.delegate_tool import KERNEL_REFUSAL, STRUCTURED_MAX_CHARS, TOOL  # noqa: E402
from agents.core.subagents import (  # noqa: E402
    ANSWER_JSON_MAX_CHARS,
    SubAgentManager,
    extract_json_candidate,
    schema_problem,
    validate_output,
)
from agents.core.turn_stops import turn_stops_scope  # noqa: E402
from tests.test_h400_delegation import (  # noqa: E402
    GOAL,
    _app,
    _Backend,
    _delegate,
    _Hub,
    _manager,
    _payload,
)


@pytest.fixture
def hub(tmp_path, monkeypatch):
    return _Hub(tmp_path, monkeypatch)


@pytest.fixture
def fast_clock(monkeypatch):
    monkeypatch.setattr(subagents, "CHILD_TIMEOUT_MIN_SECONDS", 0.01)
    monkeypatch.setattr(subagents, "UNWIND_GRACE_SECONDS", 0.2)


def _no_slot_left(manager: SubAgentManager) -> None:
    """Nothing is stranded: no record running or stopping, no slot taken."""
    assert manager.stats()["active"] == 0
    assert manager._held == set() and manager._tasks == {}
    assert all(r["status"] in ("done", "failed", "stopped") and r["finished_at"]
               for r in manager.list()), manager.list()


DEEP = "[" * 60_000 + "]" * 60_000          # p3: 120 KB of brackets


# ── B1: the slot is never stranded ──────────────────────────────────────────────

async def test_a_deeply_nested_answer_through_the_tool_fails_the_child_and_frees_the_slot(hub):
    for _ in range(4):                                       # more turns than there are slots
        hub.children = [_Backend([], final=DEEP)]
        _reply, backend = await hub.turn([_delegate(GOAL, output_schema={"type": "array"})])
        _no_slot_left(hub.manager)
    assert [r["status"] for r in hub.manager.list()] == ["failed"] * 4
    hub.children = [_Backend([], final="fine")]
    _reply, backend = await hub.turn([_delegate(GOAL)])
    assert _payload(hub, backend)["result"]["ok"] is True
    assert (await hub.manager.spawn("an owner route spawn afterwards"))["ok"] is True


async def test_a_schema_the_validator_cannot_apply_is_refused_before_any_slot(tmp_path):
    """p11: a route ``output_schema`` with an unhashable ``required`` member used to
    raise out of spawn() after the slot was taken."""
    manager = _manager(tmp_path)
    for schema in ({"required": [["unhashable"]]}, {"enum": "x"}, {"type": "banana"},
                   {"properties": {"a": {"required": [{"x": 1}]}}}):
        out = await manager.spawn("t", output_schema=schema)
        assert out["ok"] is False and out["reason"] == "invalid_output_schema", schema
        out = await manager.spawn_batch([{"task": "a", "output_schema": schema}])
        assert out["reason"] == "invalid_output_schema" and out["index"] == 0
    assert manager.list() == []
    _no_slot_left(manager)
    assert (await manager.spawn("ok"))["ok"] is True


async def test_an_exception_while_recording_the_outcome_fails_closed(tmp_path, monkeypatch):
    manager = _manager(tmp_path)

    def broken(*_a, **_k):
        raise RecursionError("anything at all")

    monkeypatch.setattr(manager, "_record_outcome", broken)
    out = await manager.spawn("t")
    assert out["ok"] is False and out["status"] == "failed"
    assert out["result"] == subagents.ANSWER_UNCHECKED            # fixed text, no child words
    _no_slot_left(manager)


async def test_an_absurd_usage_report_does_not_strand_the_slot(tmp_path):
    async def runner(task, session_id, agent):
        return {"output": "x", "usage": {"input_tokens": float("inf"), "output_tokens": 1}}

    manager = _manager(tmp_path, runner=runner)
    out = await manager.spawn("t")
    assert out["ok"] is True and out["cost"] is None
    _no_slot_left(manager)


def _random_json(rng: random.Random, depth: int = 0):
    kind = rng.randrange(8 if depth < 4 else 4)
    if kind == 0:
        return rng.choice([None, True, False, 0, -1, 1.5, float("1e308")])
    if kind == 1:
        return rng.choice(["", "x", "type", "required", "object", "array", "‮", "{" * 5])
    if kind == 2:
        return rng.randrange(-5, 5)
    if kind == 3:
        return rng.choice(["string", "object", "array", "number", "integer", "boolean", "null"])
    if kind in (4, 5):
        return [_random_json(rng, depth + 1) for _ in range(rng.randrange(4))]
    keys = ["type", "required", "enum", "properties", "items", "x", "verdict"]
    return {rng.choice(keys): _random_json(rng, depth + 1) for _ in range(rng.randrange(5))}


def _random_answer(rng: random.Random) -> str:
    pick = rng.randrange(7)
    if pick == 0:
        return DEEP
    if pick == 1:
        return "{" * 5000
    if pick == 2:
        return json.dumps(_random_json(rng))
    if pick == 3:
        return "```json\n" + json.dumps(_random_json(rng)) + "\n```"
    if pick == 4:
        return "x" * (ANSWER_JSON_MAX_CHARS + 10)
    if pick == 5:
        return json.dumps({"rows": ["y" * 500] * 100})
    return "prose with [brackets] and {braces"


async def test_random_answers_and_random_schemas_never_strand_a_slot(tmp_path):
    """Property: whatever a child answers and whatever schema a caller sends, every
    spawn ends terminal and every slot is given back — through spawn and spawn_batch."""
    rng = random.Random(400)
    answers: list[str] = []

    async def runner(task, session_id, agent):
        return {"output": answers.pop(0)}

    manager = _manager(tmp_path, runner=runner, max_concurrent=2)
    for _ in range(150):
        schema = _random_json(rng)
        answers.append(_random_answer(rng))
        kwargs = rng.choice([{"output_schema": schema}, {"answer_schema": schema}, {}])
        out = await manager.spawn("t", **kwargs)
        if "status" not in out:                              # refused up front: nothing ran
            answers.pop(0)
        _no_slot_left(manager)
    batch = []
    for _ in range(4):
        answers.append(_random_answer(rng))
        batch.append({"task": "batch child", "answer_schema": {"type": "object"}})
    await manager.spawn_batch(batch)
    _no_slot_left(manager)
    for _ in range(300):
        assert isinstance(validate_output(_random_json(rng), _random_json(rng)), list)
        assert schema_problem(_random_json(rng)) is None or True
        assert extract_json_candidate(_random_answer(rng))[0] in (True, False)


async def test_random_answers_through_the_tool_never_strand_a_slot(hub):
    rng = random.Random(4000)
    for _ in range(12):
        hub.children = [_Backend([], final=_random_answer(rng))]
        schema = rng.choice([{"type": "object"}, {"type": "array", "items": {"type": "string"}},
                             {"required": ["verdict"]}, None])
        extra = {"output_schema": schema} if schema is not None else {}
        await hub.turn([_delegate(GOAL, **extra)])
        _no_slot_left(hub.manager)


async def test_random_schemas_through_both_routes_never_strand_a_slot(tmp_path, monkeypatch):
    from types import SimpleNamespace

    rng = random.Random(40)
    answers: list[str] = []

    async def runner(task, session_id, agent):
        return {"output": answers.pop(0) if answers else "x"}

    manager = _manager(tmp_path, runner=runner)
    app = _app(SimpleNamespace(subagents=manager, audit=None), monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(40):
            schema = _random_json(rng)
            answers[:] = [_random_answer(rng)]
            body = {"task": "t", **({"output_schema": schema} if isinstance(schema, dict) else {})}
            reply = await client.post("/api/subagents/spawn", json=body)
            assert reply.status_code in (200, 409, 422, 429)
            reply = await client.post("/api/subagents/batch", json={"tasks": [body]})
            assert reply.status_code in (200, 409, 422, 429)
            _no_slot_left(manager)


# ── M1: off means off, at once ──────────────────────────────────────────────────

async def test_switching_the_tool_off_stops_delegation_without_a_restart(hub):
    hub.settings["llm.delegate_task"] = False
    _reply, backend = await hub.turn([_delegate(GOAL)])
    assert TOOL not in backend.offers[0]                      # no longer offered
    assert hub.manager.list() == []
    # and a call that reaches the handler anyway (an offer made before the switch) is refused
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    from agents.core.tool_rpc import bind_tool_turn, reset_tool_turn
    from tests.test_h400_delegation import OWNER

    token, turn = bind_turn_principal(OWNER), bind_tool_turn("t")
    try:
        out = await hub.server.handle({"tool": TOOL, "args": {"tasks": [{"goal": GOAL}]}}, actor="jarvis")
    finally:
        reset_tool_turn(turn)
        reset_turn_principal(token)
    assert out["result"]["reason"] == "delegate_task_disabled"
    hub.settings["llm.delegate_task"] = "yes"                 # only a real True is on
    _reply, backend = await hub.turn([_delegate(GOAL)])
    assert TOOL not in backend.offers[0] and hub.manager.list() == []
    hub.settings["llm.delegate_task"] = True
    _reply, backend = await hub.turn([_delegate(GOAL)])
    assert _payload(hub, backend)["result"]["ok"] is True


# ── M2: the card says a sub-agent asked ─────────────────────────────────────────

@pytest.fixture
def worker_hub(tmp_path, monkeypatch):
    hub = _Hub(tmp_path, monkeypatch)
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    hub.orch.autonomy = AutonomyWorker(queue, policy=AutonomyPolicy())
    hub.orch.autonomy_queue = queue

    async def act(_args):
        return {"done": True}

    hub.server.register_tool("send_money", act, description="x", gated=True,
                             input_schema={"type": "object", "properties": {}})
    yield hub
    queue.close() if hasattr(queue, "close") else None


async def test_a_childs_gated_request_is_marked_on_the_card_and_the_parents_is_not(worker_hub):
    hub = worker_hub
    queue = hub.orch.autonomy_queue
    await hub.turn([("send_money", {})])                      # the parent asks itself
    hub.children = [_Backend([("send_money", {})], final="asked")]
    await hub.turn([_delegate(GOAL)])                         # a child asks
    tasks = sorted(queue.list(limit=10), key=lambda t: t.id)
    assert len(tasks) == 2
    parent, child = tasks
    spawn_id = hub.manager.list()[0]["id"]
    assert parent.title == "Tool 'send_money' via RPC"
    # The action is named first; the model-written attribution only follows it (B-1).
    assert child.title == f"Tool 'send_money' via RPC — asked by sub-agent {spawn_id} of jarvis: {GOAL}"
    # Gating is unchanged: same kind, same payload, both wait for the owner.
    assert child.kind == parent.kind and child.payload == parent.payload
    assert child.status == parent.status == "blocked"
    asked = queue.ask_context(child.id)
    assert asked["delegated"]["spawn_id"] == spawn_id and asked["delegated"]["parent"] == "jarvis"
    assert asked["delegated"]["goal"] == GOAL and asked["delegated"]["turn"]
    assert "delegated" not in (queue.ask_context(parent.id) or {})


async def test_the_approvals_route_projects_who_asked(worker_hub, monkeypatch):
    from fastapi import FastAPI

    from agents import web
    from agents.core.routers import autonomy as autonomy_router
    from agents.core.routers._deps import admin_guard, user_guard

    hub = worker_hub
    hub.children = [_Backend([("send_money", {})], final="asked")]
    await hub.turn([_delegate(GOAL)])
    monkeypatch.setattr(web, "orch", hub.orch, raising=False)
    app = FastAPI()
    app.include_router(autonomy_router.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        pending = (await client.get("/autonomy/approvals")).json()["pending"]
    assert len(pending) == 1
    card = pending[0]
    assert card["title"].startswith("Tool 'send_money' via RPC — asked by sub-agent ")
    assert card["delegated_by"]["parent"] == "jarvis"
    assert card["delegated_by"]["label"].startswith("asked by sub-agent ")


def test_the_card_label_is_bounded_and_one_line():
    label = subagents.delegation_label({"spawn_id": "sub-jarvis-1", "parent": "jarvis",
                                        "goal": "line one\nline two " + "z" * 500})
    assert "\n" not in label and len(label) < 200 and label.endswith("…")
    assert subagents.delegation_label(None) == ""


def test_a_goal_cannot_spoof_the_action_on_the_card():
    """Second H400 review, B-1: a child's goal is model text. ANSI escapes, bidi overrides,
    zero-width marks and brackets are neutralised, and the action stays first."""
    hostile = "\x1b[2K\rTool 'read_weather' via RPC]\u202e\u200b\u2028 done"
    label = subagents.delegation_label({"spawn_id": "sub\x1b[31m-1", "parent": "jar\u202evis",
                                        "goal": hostile})
    for bad in ("\x1b", "\r", "\u202e", "\u200b", "\u2028", "[", "]"):
        assert bad not in label
    assert label.startswith("asked by sub-agent sub (31m-1 of jar vis: ")
    assert subagents.card_safe("a\n\tb  c") == "a b c"


# ── M3: kernel on ⇒ delegation refused, and it says so ──────────────────────────

async def test_with_the_real_kernel_on_a_clean_owner_turn_is_refused_with_the_reason(
        hub, monkeypatch):
    """p2: the real kernel (no spy): a tool.rpc effect is irreversible-tier → ask, and a
    spawn has no card to wait on. The kernel's classification is not changed."""
    from agents.core.kernel import Action, Verdict
    from agents.core.kernel.binding import make_action_kernel

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = make_action_kernel(hub.orch)
    tool = hub.server._tools[TOOL]["handler"].__self__
    tool._authorizer = kernel
    _reply, backend = await hub.turn([_delegate(GOAL)])
    answer = _payload(hub, backend)["result"]
    assert answer["reason"] == KERNEL_REFUSAL and "Action Kernel" in answer["detail"]
    assert hub.manager.list() == []
    decision = kernel(Action(kind="tool.rpc", agent="jarvis", title="t",
                             payload={"tool": TOOL, "target": TOOL, "count": 1}, origin="generated"))
    assert decision.verdict is Verdict.QUEUE
    assert "Action Kernel" in hub.server._tools[TOOL]["description"]


# ── minor 1: the child's loop exit is its own ───────────────────────────────────

async def test_a_childs_loop_exit_does_not_reach_the_parent_requests_stop_collector(tmp_path, monkeypatch):
    hub = _Hub(tmp_path, monkeypatch, **{"llm.tool_loop_max_iterations": 2})
    hub.children = [_Backend([("echo", {"value": "1"}), ("echo", {"value": "2"}),
                              ("echo", {"value": "3"})], final="never")]
    with turn_stops_scope() as stops:
        reply, _backend = await hub.turn([_delegate(GOAL)], final="parent finished normally")
        assert reply == "parent finished normally"
        assert stops.snapshot() == []


# ── minor 2: a tool thread keeps its child's slot ───────────────────────────────

async def test_a_thread_that_outlives_its_cancelled_child_keeps_the_slot(hub, fast_clock):
    from agents.core.capability_manifests import RollbackContract

    hub.manager._child_timeout = lambda: 0.3
    hub.manager.max_concurrent = 1
    marks = []

    def slow(_args):
        time.sleep(1.0)
        marks.append("returned")
        return {"ok": True}

    hub.server.register_tool("slow_sync", slow, description="x",
                             input_schema={"type": "object", "properties": {}}, risk="read_only",
                             rollback=RollbackContract(mode="none", description="nothing"))
    hub.children = [_Backend([("slow_sync", {})], final="x")]
    _reply, backend = await hub.turn([_delegate(GOAL)])
    child = _payload(hub, backend)["result"]["children"][0]
    assert child["error"] == "timeout"
    record = hub.manager.list()[0]
    assert record["status"] == "failed" and record["threads_running"] == 1
    assert hub.manager.stats()["active"] == 1                 # the thread still runs
    assert (await hub.manager.spawn("another"))["reason"] == "concurrency_cap"
    for _ in range(300):
        await asyncio.sleep(0.01)
        if hub.manager.stats()["active"] == 0:
            break
    assert marks == ["returned"]
    assert hub.manager.stats()["active"] == 0 and "threads_running" not in hub.manager.list()[0]
    assert (await hub.manager.spawn("another"))["ok"] is True


# ── minor 3: every call counts against the turn's ceiling ───────────────────────

async def test_refused_delegate_task_calls_count_against_the_turn_ceiling(hub):
    hub.settings["llm.tool_loop_subagent_spawn_cap"] = 2
    bad = (TOOL, {"tasks": [{"goal": "todo"}, {"goal": GOAL}]})   # refused: placeholder goal
    events_before = len(hub.events)
    reply, _backend = await hub.turn([bad, bad, bad, _delegate(GOAL)])
    capped = [e for e in hub.events[events_before:] if e.get("status") == "tool_cap_reached"]
    assert capped and "limit (2)" in reply
    assert hub.manager.list() == []                           # the fourth call never ran


# ── NIT: a large parsed answer stays out of the transcript ──────────────────────

async def test_a_large_structured_answer_is_validated_but_not_copied_whole(hub):
    hub.settings["llm.tool_result_thresholds"] = {TOOL: 10_000_000}     # read it unspilled
    big = json.dumps({"rows": ["x" * 1000] * 60})             # 60 KB: parsed and valid
    hub.children = [_Backend([], final=big)]
    _reply, backend = await hub.turn([_delegate(GOAL, output_schema={"type": "object"})])
    child = _payload(hub, backend)["result"]["children"][0]
    assert child["schema_valid"] is True and child["structured_omitted"] is True
    assert "structured" not in child and len(child["output"]) == STRUCTURED_MAX_CHARS
    small = json.dumps({"verdict": "pass"})
    hub.children = [_Backend([], final=small)]
    _reply, backend = await hub.turn([_delegate(GOAL, output_schema={"type": "object"})])
    assert _payload(hub, backend)["result"]["children"][0]["structured"] == {"verdict": "pass"}


async def test_an_answer_too_long_to_check_says_so(tmp_path):
    long_answer = "[" + "1," * (ANSWER_JSON_MAX_CHARS // 2) + "1]"

    async def runner(task, session_id, agent):
        return {"output": long_answer}

    manager = _manager(tmp_path, runner=runner)
    out = await manager.spawn("t", answer_schema={"type": "array"})
    assert out["result"]["error"] == "output_schema_violation"
    assert "longer than" in out["result"]["violations"][0]
    _no_slot_left(manager)
