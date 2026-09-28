"""H315 — the agent keeps a visible checklist of what it is doing.

Hermes' `todo` manages the session's task checklist and always returns the full
current list, so the model re-reads its own plan on every change. Nerva had no
model-maintained plan at all. Now:

- `todo` is a session-scoped ToolRPC tool: items {id, content, status}, status one
  of pending / in_progress / completed / cancelled. A call replaces the list, or
  with merge=true updates items by id and appends new ones; a call with no todos
  reads it. Every call returns the whole list and its counts.
- It is bounded (50 items, 200 characters, at most one item in progress) and every
  refusal is named.
- It is ungated and writes only the session's own list. It is offered to every
  posture, a guest's through the guest allowlist, except that on the owner's shared
  session only an owner's turn keeps a list (tests/test_h315b_todo_review.py). The tool
  loop never replaces its result with a "same as call N" stub: the model re-reads the
  list every time.
- The owner sees the plan: a `todo_updated` tool event (ids and statuses, never the
  text), GET /sessions/todo and /sessions/{id}/todo, `nerva todo`, and the Decision
  Inbox. A memory purge forgets every plan.
"""
from __future__ import annotations

import json

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.observability.tool_events import TOOL_EVENTS
from agents.core.todo_tool import (
    MAX_CONTENT,
    MAX_ITEMS,
    STATUSES,
    TodoError,
    TodoStore,
    register_todo_tool,
)
from agents.core.tool_rpc import ToolRPCServer


def _items(*rows):
    return [{"id": str(i), "content": text, "status": status} for i, (text, status) in enumerate(rows, 1)]


# ── the store ────────────────────────────────────────────────────────────────────

def test_a_write_replaces_the_list_and_returns_all_of_it():
    store = TodoStore()
    out = store.write("s1", _items(("read the logs", "in_progress"), ("fix the bug", "pending")))
    assert [t["content"] for t in out["todos"]] == ["read the logs", "fix the bug"]
    assert out["counts"] == {"pending": 1, "in_progress": 1, "completed": 0, "cancelled": 0, "total": 2}
    out = store.write("s1", _items(("only this", "pending")))
    assert [t["content"] for t in out["todos"]] == ["only this"]


def test_a_merge_updates_by_id_and_appends_the_rest():
    store = TodoStore()
    store.write("s1", _items(("a", "in_progress"), ("b", "pending")))
    out = store.write("s1", [{"id": "1", "status": "completed"}, {"id": "2", "status": "in_progress"},
                             {"id": "9", "content": "c"}], merge=True)
    assert [(t["id"], t["content"], t["status"]) for t in out["todos"]] == [
        ("1", "a", "completed"), ("2", "b", "in_progress"), ("9", "c", "pending")]
    out = store.write("s1", [{"id": "9", "content": "c, reworded"}], merge=True)   # only the fields sent
    assert [(t["content"], t["status"]) for t in out["todos"]][2] == ("c, reworded", "pending")


def test_an_integer_id_is_its_text_and_a_boolean_is_no_id():
    store = TodoStore()
    assert store.write("s1", [{"id": 3, "content": "a"}])["todos"][0]["id"] == "3"
    with pytest.raises(TodoError) as caught:
        store.write("s1", [{"id": True, "content": "a"}])
    assert caught.value.reason == "todo_bad_id"


def test_a_call_with_no_todos_reads_the_list():
    store = TodoStore()
    store.write("s1", _items(("a", "pending")))
    assert store.write("s1", None)["todos"] == store.read("s1")["todos"]
    assert store.read("never")["todos"] == [] and store.read("never")["counts"]["total"] == 0


@pytest.mark.parametrize("todos, merge, reason", [
    (_items(*[("x", "pending")] * (MAX_ITEMS + 1)), False, "todo_too_many"),
    ([{"id": "1", "content": "y" * (MAX_CONTENT + 1), "status": "pending"}], False, "todo_content_too_long"),
    ([{"id": "1", "content": "   ", "status": "pending"}], False, "todo_content_required"),
    ([{"id": "1", "content": "a", "status": "doing"}], False, "todo_bad_status"),
    ([{"id": "", "content": "a"}], False, "todo_bad_id"),
    ([{"id": "x" * 65, "content": "a"}], False, "todo_bad_id"),
    ([{"id": "1", "content": "a"}, {"id": "1", "content": "b"}], False, "todo_duplicate_id"),
    (_items(("a", "in_progress"), ("b", "in_progress")), False, "todo_one_in_progress"),
    ("a list", False, "todo_bad_list"),
    (["not an object"], False, "todo_bad_item"),
    ([{"id": "404", "status": "completed"}], True, "todo_content_required"),   # a new id needs content
])
def test_every_refusal_is_named(todos, merge, reason):
    store = TodoStore()
    store.write("s1", _items(("kept", "pending")))
    with pytest.raises(TodoError) as caught:
        store.write("s1", todos, merge=merge)
    assert caught.value.reason == reason
    assert [t["content"] for t in store.read("s1")["todos"]] == ["kept"]   # nothing half-applied


def test_a_merge_that_would_make_two_items_in_progress_is_refused_and_changes_nothing():
    store = TodoStore()
    store.write("s1", _items(("a", "in_progress"), ("b", "pending")))
    with pytest.raises(TodoError) as caught:
        store.write("s1", [{"id": "2", "status": "in_progress", "content": "b, edited"}], merge=True)
    assert caught.value.reason == "todo_one_in_progress"
    assert [(t["content"], t["status"]) for t in store.read("s1")["todos"]] == [
        ("a", "in_progress"), ("b", "pending")]                       # the stored items were not touched


def test_a_merge_past_the_cap_is_refused():
    store = TodoStore()
    store.write("s1", _items(*[("x", "pending")] * MAX_ITEMS))
    with pytest.raises(TodoError) as caught:
        store.write("s1", [{"id": "new", "content": "one more"}], merge=True)
    assert caught.value.reason == "todo_too_many"


def test_content_is_one_printable_line():
    store = TodoStore()
    out = store.write("s1", [{"id": "1", "content": "  line one\n\nline\t\ttwo\x00  also\u200b\u202ethree  "}])
    # every run of whitespace is one space; control and format characters (a zero-width
    # space, a bidi override) are dropped, so what the owner reads is what was written
    assert out["todos"][0]["content"] == "line one line two alsothree"


def test_sessions_are_isolated_and_the_oldest_plan_is_dropped_past_the_cap():
    store = TodoStore(max_sessions=2)
    store.write("a", _items(("for a", "pending")))
    store.write("b", _items(("for b", "pending")))
    assert store.read("a")["todos"][0]["content"] == "for a"
    store.write("c", _items(("for c", "pending")))
    assert store.read("a")["todos"] == []                 # least recently written goes
    assert store.read("b")["todos"][0]["content"] == "for b"
    assert [p["session_id"] for p in store.recent()] == ["c", "b"]
    store.write("b", _items(("for b, again", "pending")))           # a rewrite makes b the newest
    store.write("d", _items(("for d", "pending")))
    assert [p["session_id"] for p in store.recent()] == ["d", "b"]  # so c, not b, went


def test_statuses_are_hermes_four():
    assert STATUSES == ("pending", "in_progress", "completed", "cancelled")


# ── the tool ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def tool():
    server = ToolRPCServer()
    store = TodoStore()
    session = {"id": "turn-session"}
    name = register_todo_tool(server, store=store, session_id=lambda: session["id"])
    return server, store, session, name


async def _call(server, args):
    """Through the server's real entry point; the handler's own answer rides under result."""
    reply = await server.handle({"tool": "todo", "args": args})
    assert reply["ok"] is True, reply
    return reply["result"]


def test_the_tool_is_registered_ungated_with_its_schema(tool):
    server, _store, _session, name = tool
    row = next(r for r in server.tools() if r["name"] == name)
    assert name == "todo" and row["gated"] is False
    props = row["input_schema"]["properties"]
    assert set(props) == {"todos", "merge"}
    assert props["todos"]["items"]["properties"]["status"]["enum"] == list(STATUSES)


@pytest.mark.asyncio
async def test_the_tool_writes_the_turns_session_and_returns_the_whole_list(tool):
    server, store, session, _name = tool
    reply = await _call(server, {"todos": _items(("plan", "in_progress"))})
    assert reply["ok"] is True and reply["todos"][0]["content"] == "plan"
    assert reply["counts"]["in_progress"] == 1 and reply["counts"]["total"] == 1
    assert store.read("turn-session")["todos"][0]["content"] == "plan"
    session["id"] = "another"
    assert (await _call(server, {}))["todos"] == []                      # its own session only
    assert (await _call(server, {"todos": None, "merge": None}))["todos"] == []   # nulls are "not sent"
    reply = await _call(server, {"todos": _items(("replaced", "pending")), "merge": None})
    assert reply["ok"] is True and [t["content"] for t in reply["todos"]] == ["replaced"]


@pytest.mark.asyncio
async def test_a_plan_records_the_agent_and_the_posture_that_wrote_it():
    server = ToolRPCServer()
    store = TodoStore()
    register_todo_tool(server, store=store, session_id=lambda: "tg-9", posture=lambda: "inbound/guest")
    reply = await server.handle({"tool": "todo", "args": {"todos": _items(("x", "pending"))}}, actor="nerva")
    assert reply["result"]["ok"] is True
    plan = store.read("tg-9")
    assert plan["agent"] == "nerva" and plan["posture"] == "inbound/guest"


@pytest.mark.asyncio
async def test_a_session_getter_that_fails_is_a_named_refusal():
    server = ToolRPCServer()
    register_todo_tool(server, store=TodoStore(), session_id=lambda: 1 / 0)
    reply = await server.handle({"tool": "todo", "args": {"todos": _items(("x", "pending"))}})
    assert reply["result"]["reason"] == "todo_no_session"


@pytest.mark.asyncio
async def test_a_turn_with_no_session_is_refused_by_name(tool):
    server, _store, session, _name = tool
    session["id"] = ""
    reply = await _call(server, {"todos": _items(("plan", "pending"))})
    assert reply == {"ok": False, "reason": "todo_no_session",
                     "detail": "this turn has no session to keep a list for"}


@pytest.mark.asyncio
async def test_a_refusal_comes_back_named(tool):
    server, _store, _session, _name = tool
    args = {"todos": _items(("a", "in_progress"), ("b", "in_progress"))}
    reply = await _call(server, args)
    assert reply["ok"] is False and reply["reason"] == "todo_one_in_progress"
    assert "one item" in reply["detail"]
    reply = await _call(server, {"todos": _items(("a", "pending")), "merge": "yes"})
    assert reply["reason"] == "todo_bad_merge"


@pytest.mark.asyncio
async def test_a_write_leaves_a_tool_event_with_statuses_never_the_text(tool):
    server, _store, _session, _name = tool
    TOOL_EVENTS.clear()
    args = {"todos": _items(("secret plan text", "in_progress"), ("second", "pending"))}
    await _call(server, args)
    events = [e for e in TOOL_EVENTS.snapshot() if e.get("event") == "todo_updated"]
    assert len(events) == 1
    event = events[0]
    assert event["session"] == "turn-session" and "ids" not in event          # an id is free text too
    assert event["statuses"] == ["in_progress", "pending"] and event["total"] == 2
    assert event["current"] == 1 and event["merge"] is False                 # a position, not an id
    assert "secret plan text" not in json.dumps(TOOL_EVENTS.snapshot())
    await _call(server, {})
    assert len([e for e in TOOL_EVENTS.snapshot() if e.get("event") == "todo_updated"]) == 1   # a read is no update
    await _call(server, {"todos": _items(("a", "in_progress"), ("b", "in_progress"))})
    assert len([e for e in TOOL_EVENTS.snapshot() if e.get("event") == "todo_updated"]) == 1   # nor is a refusal


# ── the loop never stubs it ──────────────────────────────────────────────────────

class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(tool_calls=(ToolCall(id=f"call-{len(self.calls)}", name=name,
                                                 raw_arguments=json.dumps(args), arguments=args),),
                            finish_reason="tool_calls")
        return ToolTurn(content="done", finish_reason="stop")


@pytest.mark.asyncio
async def test_the_loop_returns_the_list_every_time_never_a_stub():
    server = ToolRPCServer()
    store = TodoStore()
    register_todo_tool(server, store=store, session_id=lambda: "loop")
    store.write("loop", _items(*[(f"step number {i} of a long plan", "pending") for i in range(20)]))

    async def big(args):
        return {"page": "x" * 700}

    server.register_tool("big", big, description="big", input_schema={"type": "object", "properties": {}})
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_iterations=lambda: 8)
    backend = _Backend([("todo", {}), ("todo", {"merge": True}), ("big", {}), ("big", {"n": 1})])
    assert await runtime.run(agent_id="nerva", backend=backend, model="m", prompt="p", system="s",
                             max_tokens=64, temperature=0.1) == "done"
    results = [json.loads(m["content"]) for m in backend.calls[-1] if m.get("role") == "tool"]
    assert "same_as" not in results[1] and len(results[1]["result"]["todos"]) == 20
    assert results[3].get("same_as") == "call-3"                          # other tools still dedupe


# ── the posture ──────────────────────────────────────────────────────────────────

def test_todo_is_offered_in_every_posture_a_guests_included():
    from agents.core.tool_profiles import POSTURES, ToolPosture, resolve_tools

    tools = [{"name": "todo", "gated": False}, {"name": "web_search", "gated": False}]
    for surface, principal in POSTURES:
        offered, _withheld = resolve_tools(tools, posture=ToolPosture(surface, principal))
        assert "todo" in [t["name"] for t in offered], (surface, principal)
    guest = resolve_tools(tools, posture=ToolPosture("inbound", "guest"))[0]
    assert [t["name"] for t in guest] == ["todo"]                         # web_search stays withheld
    gated = resolve_tools([{"name": "todo", "gated": True}], posture=ToolPosture("inbound", "guest"))[0]
    assert gated == []                                                    # never a gated tool
    unknown = resolve_tools([{"name": "todo", "gated": False}], posture=ToolPosture("martian", "owner"))[0]
    assert unknown == []                                                  # an unknown surface offers nothing


def test_an_agents_own_tool_list_still_narrows_it():
    from agents.core.tool_profiles import ToolPosture, resolve_tools

    offered, _ = resolve_tools([{"name": "todo", "gated": False}], posture=ToolPosture("operator", "owner"),
                               agent_patterns=["web_*"])
    assert offered == []


# ── the owner's view ─────────────────────────────────────────────────────────────

@pytest.fixture
def hub(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import todo_tool

    monkeypatch.setattr(web, "ADMIN_TOKEN", "todo-admin")
    monkeypatch.setattr(todo_tool, "TODOS", TodoStore())
    with TestClient(web.app) as client:
        yield client, todo_tool.TODOS


_ADMIN = {"X-Admin-Token": "todo-admin"}


def test_the_coordinator_registers_todo_on_the_live_tool_server(hub):
    import asyncio

    from agents.core.app_state import get_orch
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    _client, store = hub
    orch = get_orch()
    names = {row["name"]: row for row in orch.tool_rpc.tools()}
    assert "todo" in names and names["todo"]["gated"] is False

    async def owner_turn():
        token = bind_turn_principal(Principal(channel="web", admin=True))
        try:
            return await orch.tool_rpc.handle({"tool": "todo", "args": {"todos": _items(("live", "pending"))}})
        finally:
            reset_turn_principal(token)

    reply = asyncio.run(owner_turn())
    assert reply["result"]["ok"] is True
    plan = store.read(str(orch.session_id))                 # the live store, the turn's session
    assert [t["content"] for t in plan["todos"]] == ["live"]
    assert plan["posture"] == "operator/owner"               # the owner's HUD turn


def test_the_routes_read_one_plan_and_the_recent_ones(hub):
    client, store = hub
    store.write("web-1", _items(("look up the flight", "completed"), ("book it", "in_progress")))
    store.write("tg-9", _items(("draft the reply", "pending")))
    one = client.get("/sessions/web-1/todo", headers=_ADMIN)
    assert one.status_code == 200 and one.headers["cache-control"].startswith("no-store")
    body = one.json()
    assert body["session_id"] == "web-1" and [t["status"] for t in body["todos"]] == ["completed", "in_progress"]
    recent = client.get("/sessions/todo", headers=_ADMIN)
    assert recent.headers["cache-control"].startswith("no-store")
    assert [p["session_id"] for p in recent.json()["plans"]] == ["tg-9", "web-1"]
    assert client.get("/sessions/never/todo", headers=_ADMIN).json()["todos"] == []
    assert client.get("/sessions/bad.id/todo", headers=_ADMIN).status_code == 400
    assert client.get("/sessions/..%2Fetc/todo", headers=_ADMIN).status_code in (400, 404)


def test_the_routes_are_user_guarded(hub, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web.app, "dependency_overrides", {})     # conftest opens the user guard
    monkeypatch.setattr(web, "USER_TOKEN", "todo-user")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "todo-user")
    anonymous = TestClient(web.app)
    assert anonymous.get("/sessions/todo").status_code == 401
    assert anonymous.get("/sessions/web-1/todo").status_code == 401
    assert anonymous.get("/sessions/todo", headers={"X-User-Token": "todo-user"}).status_code == 200


def test_a_memory_purge_forgets_every_plan(monkeypatch):
    import asyncio

    from agents.core import data_purge, todo_tool

    store = TodoStore()
    monkeypatch.setattr(todo_tool, "TODOS", store)
    store.write("web-1", _items(("private plan", "pending")))
    store.write("tg-9", _items(("another", "pending")))
    # Only the plans are this test's: another test's leftovers (an ingestion cache) may be
    # cleared by the same purge, so the report is read for its plans entry alone.
    cleared, failed = asyncio.run(data_purge.clear_live_memory(object()))
    assert store.recent() == [] and cleared.count("todo_plans") == 1 and failed == []
    cleared, failed = asyncio.run(data_purge.clear_live_memory(object()))
    assert "todo_plans" not in cleared and failed == []                   # nothing to drop, nothing claimed


_PLAN = {"session_id": "web-1", "updated_at": 1790000000.0, "agent": "nerva", "posture": "operator/owner",
         "todos": [{"id": "1", "content": "book it", "status": "in_progress"},
                   {"id": "2", "content": "tell Ana", "status": "pending"},
                   {"id": "3", "content": "find flights", "status": "completed"},
                   {"id": "4", "content": "ask about the hotel", "status": "cancelled"}],
         "counts": {"pending": 1, "in_progress": 1, "completed": 1, "cancelled": 1, "total": 4}}


def test_nerva_todo_prints_the_plans():
    from tests.test_nerva_cli import _FakeHub, _run

    plans = {"plans": [_PLAN]}
    code, out, _err, hub = _run(["todo"], hub=_FakeHub({"GET /sessions/todo": plans}))
    assert code == 0 and hub.calls == [("GET", "/sessions/todo", None)]
    assert "web-1" in out and "1/4 done" in out
    assert "[>] book it" in out and "[ ] tell Ana" in out
    assert "[x] find flights" in out and "[-] ask about the hotel" in out
    code, out, _err, _hub = _run(["todo", "--json"], hub=_FakeHub({"GET /sessions/todo": plans}))
    assert code == 0 and json.loads(out) == plans


def test_nerva_todo_reads_one_session_and_says_when_there_is_none():
    from tests.test_nerva_cli import _FakeHub, _run

    code, out, _err, hub = _run(["todo", "web-1"], hub=_FakeHub({"GET /sessions/web-1/todo": _PLAN}))
    assert code == 0 and hub.calls == [("GET", "/sessions/web-1/todo", None)]
    assert "[>] book it" in out
    empty = {"session_id": "web-2", "todos": [], "counts": {"total": 0}}
    code, out, _err, _hub = _run(["todo", "web-2"], hub=_FakeHub({"GET /sessions/web-2/todo": empty}))
    assert code == 0 and "no plan" in out
    code, out, _err, _hub = _run(["todo"], hub=_FakeHub({"GET /sessions/todo": {"plans": []}}))
    assert code == 0 and "no plan" in out
    code, _out, err, hub = _run(["todo", "../etc"], hub=_FakeHub())
    assert code == 2 and hub.calls == [] and "session" in err       # refused before any request
