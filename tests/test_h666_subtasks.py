"""H666 — the agent's task list nests subtasks under a parent.

Hermes puts one optional ``parent`` on each todo item (the id of another item) and
renders the list through one defensive tree builder: DFS order, depth capped at 4, a
dangling or self parent at depth 0, cycle members appended flat — nothing disappears.
Nerva does the same for the ``todo`` tool's items and for mission plan steps, and
renders the tree in ``nerva todo``, the Decision Inbox and the mission canvas.
"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest

from agents.core import todo_tool
from agents.core.autonomy.missions import BudgetExceeded, MissionError, MissionStatus, MissionStore
from agents.core.todo_tool import TodoError, TodoStore
from agents.core.todo_tree import MAX_DEPTH, tree


def _rows(*pairs):
    return [{"id": key, "parent": parent} for key, parent in pairs]


def _shape(rows):
    return [(item["id"], depth) for item, depth in tree(rows, lambda i: i["id"], lambda i: i["parent"])]


# ── the tree builder ─────────────────────────────────────────────────────────

def test_children_follow_their_parent_depth_first_in_list_order():
    rows = _rows(("a", None), ("b", None), ("a1", "a"), ("b1", "b"), ("a2", "a"), ("a1x", "a1"))
    assert _shape(rows) == [("a", 0), ("a1", 1), ("a1x", 2), ("a2", 1), ("b", 0), ("b1", 1)]


def test_a_child_listed_before_its_parent_still_nests_under_it():
    assert _shape(_rows(("c", "p"), ("p", None))) == [("p", 0), ("c", 1)]


def test_depth_stops_at_four_and_the_deeper_items_stay_under_their_parent():
    rows = _rows(*[(f"n{i}", f"n{i - 1}" if i else None) for i in range(7)], ("tail", None))
    assert MAX_DEPTH == 4
    assert _shape(rows) == [("n0", 0), ("n1", 1), ("n2", 2), ("n3", 3), ("n4", 4), ("n5", 4),
                            ("n6", 4), ("tail", 0)]


def test_a_dangling_parent_renders_at_depth_zero_in_its_place():
    assert _shape(_rows(("a", None), ("orphan", "gone"), ("b", None))) == [
        ("a", 0), ("orphan", 0), ("b", 0)]


def test_a_self_parent_renders_at_depth_zero_and_keeps_its_children():
    assert _shape(_rows(("me", "me"), ("kid", "me"))) == [("me", 0), ("kid", 1)]


def test_cycle_members_are_appended_flat_after_the_tree():
    rows = _rows(("x", "y"), ("root", None), ("y", "x"), ("under", "x"), ("r1", "root"))
    assert _shape(rows) == [("root", 0), ("r1", 1), ("x", 0), ("y", 0), ("under", 0)]


def test_nothing_disappears_and_nothing_repeats_on_any_shape():
    rows = _rows(("a", "b"), ("b", "c"), ("c", "a"), ("d", "d"), ("e", "zz"), ("f", None),
                 ("g", "f"), ("a", "f"), ("h", ["not", "an", "id"]), ("i", True))
    got = tree(rows, lambda i: i["id"], lambda i: i["parent"])
    assert sorted(map(id, (item for item, _ in got))) == sorted(map(id, rows))


def test_a_parent_that_is_not_an_id_is_no_parent():
    # A bool is not an index (True == 1), a list is not hashable, a dict is not an id, and
    # neither is a fractional float, as a key or as a parent. A whole float is its number
    # (JSON's 0.0 is 0 to the HUD's twin), so step 5 sits under step 0.
    rows = [{"idx": 0, "parent": None}, {"idx": 1, "parent": None}, {"idx": 2, "parent": True},
            {"idx": 3, "parent": [0]}, {"idx": 4, "parent": {"x": 0}}, {"idx": 5, "parent": 0.0},
            {"idx": 0.5, "parent": None}, {"idx": 7, "parent": 0.5}]
    got = [(s["idx"], d) for s, d in tree(rows, lambda s: s["idx"], lambda s: s["parent"])]
    assert got == [(0, 0), (5, 1), (1, 0), (2, 0), (3, 0), (4, 0), (0.5, 0), (7, 0)]


def test_two_items_sharing_an_id_the_first_holds_it():
    assert _shape(_rows(("a", None), ("a", None), ("k", "a"))) == [("a", 0), ("k", 1), ("a", 0)]


def test_a_getter_that_raises_is_no_parent():
    def bad(_item):
        raise KeyError("parent")

    assert [d for _, d in tree([{"id": "a"}, {"id": "b"}], lambda i: i["id"], bad)] == [0, 0]


def test_a_long_chain_costs_no_recursion():
    rows = _rows(*[(f"n{i}", f"n{i - 1}" if i else None) for i in range(5_000)])
    got = _shape(rows)
    assert len(got) == 5_000 and got[-1] == ("n4999", MAX_DEPTH)


# ── the todo tool keeps a parent ─────────────────────────────────────────────

def _write(store, todos, merge=False, **kw):
    return store.write("s1", todos, merge, posture="hud/owner", **kw)


def test_an_item_keeps_the_id_of_its_parent():
    store = TodoStore()
    view = _write(store, [{"id": "1", "content": "ship"}, {"id": "1a", "content": "tests", "parent": "1"}])
    assert [item.get("parent") for item in view["todos"]] == [None, "1"]
    assert todo_tool.model_items(view["todos"])[1] == {
        "id": "1a", "content": "tests", "status": "pending", "parent": "1"}
    # an item with no parent answers exactly as before: no key at all
    assert "parent" not in todo_tool.model_items(view["todos"])[0]
    assert "parent" not in view["todos"][0]


def test_a_merge_moves_an_item_under_a_parent_and_clears_it_with_an_empty_id():
    store = TodoStore()
    _write(store, [{"id": "1", "content": "ship"}, {"id": "2", "content": "tests"}])
    moved = _write(store, [{"id": "2", "parent": "1"}], merge=True)
    assert moved["todos"][1]["parent"] == "1" and moved["todos"][1]["content"] == "tests"
    kept = _write(store, [{"id": "2", "status": "completed"}], merge=True)
    assert kept["todos"][1]["parent"] == "1"                  # a merge without parent keeps it
    kept = _write(store, [{"id": "2", "parent": None}], merge=True)
    assert kept["todos"][1]["parent"] == "1"                  # null is "not sent", like content
    cleared = _write(store, [{"id": "2", "parent": ""}], merge=True)
    assert "parent" not in cleared["todos"][1]
    _write(store, [{"id": "2", "parent": "1"}], merge=True)
    spaced = _write(store, [{"id": "2", "parent": "  \t "}], merge=True)
    assert "parent" not in spaced["todos"][1]            # only whitespace clears too, as in Hermes


def test_a_parent_is_cleaned_like_an_id_and_refused_with_its_own_reason():
    store = TodoStore()
    view = _write(store, [{"id": "1", "content": "a"}, {"id": "2", "content": "b", "parent": " 1​ "}])
    assert view["todos"][1]["parent"] == "1"
    assert _write(store, [{"id": "3", "content": "c", "parent": 1}], merge=True)["todos"][2]["parent"] == "1"
    for bad in (["1"], {"id": "1"}, True, "​", "x" * (todo_tool.MAX_ID + 1), "x" * 10_000):
        with pytest.raises(TodoError) as refused:
            _write(store, [{"id": "4", "content": "d", "parent": bad}], merge=True)
        assert refused.value.reason == "todo_bad_parent", bad
    assert len(store.read("s1")["todos"]) == 3                # a refused call changes nothing


def test_a_dangling_self_or_cyclic_parent_is_stored_and_the_list_still_renders():
    store = TodoStore()
    view = _write(store, [{"id": "a", "content": "a", "parent": "b"}, {"id": "b", "content": "b", "parent": "a"},
                          {"id": "c", "content": "c", "parent": "c"}, {"id": "d", "content": "d", "parent": "gone"}])
    got = [(item["id"], depth) for item, depth in tree(view["todos"], lambda i: i["id"],
                                                        lambda i: i.get("parent"))]
    assert got == [("c", 0), ("d", 0), ("a", 0), ("b", 0)]


def test_a_parent_counts_toward_the_plan_cap_and_its_change_is_a_write():
    store = TodoStore()
    base = [{"id": f"{i:02d}" + "i" * 50, "content": "x" * 70} for i in range(40)]
    _write(store, base)
    assert todo_tool.plan_bytes(store.read("s1")["todos"]) <= todo_tool.MAX_PLAN_BYTES
    parents = [{"id": item["id"], "parent": base[0]["id"]} for item in base[1:]]
    with pytest.raises(TodoError) as refused:
        _write(store, parents, merge=True)
    assert refused.value.reason == "todo_plan_too_long"


def test_moving_an_item_moves_the_plans_labels_and_a_same_parent_does_not():
    store = TodoStore()
    first = _write(store, [{"id": "1", "content": "a"}, {"id": "2", "content": "b"}])
    moved = store.write("s1", [{"id": "2", "parent": "1"}], True, posture="hud/owner", agent="other")
    assert moved["agent"] == "other" and moved["updated_at"] >= first["updated_at"]
    again = store.write("s1", [{"id": "2", "parent": "1"}], True, posture="hud/owner", agent="third")
    assert again["agent"] == "other"


def test_an_untrusted_turn_that_moves_an_item_taints_it():
    store = TodoStore()
    _write(store, [{"id": "1", "content": "a"}, {"id": "2", "content": "b"}])
    view, foreign = store.apply("s1", [{"id": "2", "parent": "1"}], True, posture="telegram/guest",
                                tainted=True, turn="t-guest")
    assert view["todos"][1]["tainted"] is True and view["todos"][0]["tainted"] is False
    _, foreign = store.apply("s1", None, turn="t-owner")
    assert foreign is True


def test_an_untrusted_turn_resending_the_same_parent_changes_nothing():
    store = TodoStore()
    _write(store, [{"id": "1", "content": "a"}, {"id": "2", "content": "b", "parent": "1"}])
    view, foreign = store.apply("s1", [{"id": "2", "parent": "1"}], True, posture="telegram/guest",
                                tainted=True, turn="t-guest")
    assert view["todos"][1]["tainted"] is False and foreign is False
    assert view["posture"] == "hud/owner"


def test_the_schema_and_description_offer_a_parent():
    item = todo_tool.INPUT_SCHEMA["properties"]["todos"]["items"]
    assert item["properties"]["parent"] == {"type": "string", "maxLength": todo_tool.MAX_ID}
    assert item["additionalProperties"] is False and item["required"] == ["id"]
    assert "parent" in todo_tool.DESCRIPTION


def test_the_tool_answers_the_parent_to_the_model():
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()
    store = TodoStore()
    todo_tool.register_todo_tool(server, session_id=lambda: "s1", store=store,
                                 posture=lambda: "operator/owner", origin=lambda: "hud")
    reply = asyncio.run(server.handle({"tool": "todo", "args": {"todos": [
        {"id": "1", "content": "ship"}, {"id": "1a", "content": "tests", "parent": "1"}]}}, actor="jarvis"))
    assert reply["result"]["todos"][1]["parent"] == "1"
    refused = asyncio.run(server.handle({"tool": "todo", "args": {"todos": [
        {"id": "1", "content": "ship", "parent": ["1"]}]}}, actor="jarvis"))
    assert refused["result"]["reason"] == "todo_bad_parent"


# ── mission plan steps keep a parent ─────────────────────────────────────────

@pytest.fixture()
def missions(tmp_path):
    store = MissionStore(db_path=str(tmp_path / "m.db"), artifact_root=str(tmp_path / "art")).initialize()
    yield store
    store.close()


def test_a_plan_step_may_name_an_earlier_step_as_its_parent(missions):
    m = missions.create("x", plan=["phase", {"title": "sub a", "parent": 0}, {"title": "sub b", "parent": 0},
                                   {"title": "deeper", "parent": 2}, {"title": "next"}])
    assert [(s["title"], s["parent"]) for s in m.plan] == [
        ("phase", None), ("sub a", 0), ("sub b", 0), ("deeper", 2), ("next", None)]
    again = missions.get(m.id)
    assert [s["parent"] for s in again.plan] == [None, 0, 0, 2, None]
    assert [(s["idx"], d) for s, d in tree(again.plan, lambda s: s["idx"], lambda s: s["parent"])] == [
        (0, 0), (1, 1), (2, 1), (3, 2), (4, 0)]


def test_a_plain_title_plan_is_what_it_was_with_a_null_parent(missions):
    m = missions.create("x", plan=["a", "b", 7, {"text": "legacy"}])
    assert [s["title"] for s in m.plan] == ["a", "b", "7", "{'text': 'legacy'}"]
    assert all(s["parent"] is None for s in m.plan)
    assert missions.create("y", plan=[{"title": "  padded  "}]).plan[0]["title"] == "padded"


@pytest.mark.parametrize("step", [
    {"title": "self", "parent": 2},            # itself
    {"title": "later", "parent": 3},           # a later step: a cycle could follow
    {"title": "gone", "parent": 99},
    {"title": "neg", "parent": -1},
    {"title": "bool", "parent": True},
    {"title": "text", "parent": "0"},
    {"title": "float", "parent": 0.0},
    {"parent": 0},                              # no title
    {"title": "   ", "parent": 0},
    {"title": 5, "parent": 0},
    {"title": "extra", "parent": 0, "status": "done"},
])
def test_a_step_parent_must_be_an_earlier_step_and_a_step_needs_a_title(missions, step):
    with pytest.raises(MissionError) as refused:
        missions.create("x", plan=["a", "b", step, "d"])
    assert refused.value.code == "bad_plan_step"
    assert missions.list() == []


def test_a_child_step_is_charged_and_gated_like_any_step(missions):
    m = missions.create("x", plan=["phase", {"title": "sub", "parent": 0}], max_steps=2)
    missions.start(m.id)
    after = missions.finish_step(m.id, 1, "done", "ok")
    assert after.steps_used == 1 and after.plan[1]["parent"] == 0 and after.plan[1]["status"] == "done"
    assert after.plan[0]["status"] == "pending"                # a parent is not closed by its child
    with pytest.raises(BudgetExceeded):
        missions.finish_step(m.id, 0, "done")
    assert missions.get(m.id).status == MissionStatus.FAILED.value


def test_the_api_accepts_step_parents_and_refuses_a_bad_one_by_name(missions, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web

    monkeypatch.setattr(web, "orch", SimpleNamespace(missions=missions))
    client = TestClient(web.app)
    ok = client.post("/api/missions", json={"title": "m", "plan": ["phase", {"title": "sub", "parent": 0}]})
    assert ok.status_code == 200, ok.text
    assert [s["parent"] for s in ok.json()["mission"]["plan"]] == [None, 0]
    bad = client.post("/api/missions", json={"title": "m", "plan": ["a", {"title": "b", "parent": 1}]})
    assert bad.status_code == 400
    assert bad.json() == {"error": "a plan step is a title, or {title, parent} where parent is the index "
                                   "of an earlier step", "code": "bad_plan_step"}
    assert len(missions.list()) == 1


# ── nerva todo indents the tree ──────────────────────────────────────────────

def test_nerva_todo_indents_subtasks_and_keeps_every_item():
    from agents.cli.nerva import Context, main

    plan = {"session_id": "s1", "todos": [
        {"id": "b", "content": "loop b", "status": "pending", "parent": "a"},
        {"id": "a", "content": "loop a", "status": "pending", "parent": "b"},
        {"id": "1", "content": "ship", "status": "in_progress"},
        {"id": "1a", "content": "tests", "status": "completed", "parent": "1"},
        {"id": "1b", "content": "orphan", "status": "pending", "parent": "gone"},
    ]}

    class Hub:
        base_url = "http://127.0.0.1:8080"

        def get(self, path):
            assert path == "/sessions/s1/todo"
            return plan

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: Hub())
    assert main(["todo", "s1"], context=ctx) == 0, err.getvalue()
    lines = out.getvalue().splitlines()[1:]
    assert lines == ["  [>] ship", "    [x] tests", "  [ ] orphan", "  [ ] loop b", "  [ ] loop a"]


def test_the_twin_draws_every_shared_case_the_same():
    """The HUD's twin (frontend/src/todo-tree.ts) is pinned to the same file of cases."""
    import json
    from pathlib import Path

    shared = json.loads((Path(__file__).resolve().parent.parent / "frontend/src/test/todo-tree-cases.json")
                        .read_text(encoding="utf-8"))
    assert len(shared["cases"]) >= 40
    for case in shared["cases"]:
        items = case["items"]
        got = tree(items, lambda r: r["id"], lambda r: r["parent"])
        where = {id(item): pos for pos, item in enumerate(items)}
        assert [[where[id(item)], depth] for item, depth in got] == case["expected"], case["name"]


def test_tree_of_something_that_is_not_a_list_is_empty():
    assert tree(None, lambda r: r, lambda r: r) == []
    assert tree(5, lambda r: r, lambda r: r) == []
    assert tree("abc", lambda r: r, lambda r: r) == []
