"""The ported Hermes tools execute through real Nerva ToolRPC and live scopes."""
import importlib.util
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.commands import Principal
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.tool_profiles import ToolPosture, resolve_tools
from agents.core.tool_rpc import ToolRPCServer


def registration():
    assert importlib.util.find_spec("agents.core.kanban.runtime") is not None, "Kanban has no real ToolRPC adapter"
    from agents.core.kanban.runtime import register_kanban_tools
    return register_kanban_tools


def server_for(tmp_path, *, owner=True, enabled=True):
    server = ToolRPCServer()
    registration()(server, home=lambda: tmp_path, enabled=lambda: enabled,
                   principal=lambda: Principal(channel="web", admin=owner),
                   session_id=lambda: "s-owner", profiles=lambda: ("jarvis", "reviewer"))
    return server


async def call(server, tool, args=None, *, actor="jarvis"):
    answer = await server.handle({"tool": tool, "args": args or {}}, actor=actor)
    return answer.get("result", answer)


def test_all_fourteen_pinned_schemas_are_registered(tmp_path):
    server = server_for(tmp_path)
    assert len(server.tools()) == 14
    assert {row["name"] for row in server.tools()} == {
        "kanban_show", "kanban_list", "kanban_complete", "kanban_block",
        "kanban_request_review", "kanban_request_changes", "kanban_heartbeat",
        "kanban_comment", "kanban_attach", "kanban_attach_url", "kanban_attachments",
        "kanban_create", "kanban_unblock", "kanban_link",
    }


@pytest.mark.asyncio
async def test_real_rpc_durable_create_comment_attach_show_complete(tmp_path):
    server = server_for(tmp_path)
    created = await call(server, "kanban_create", {"title": "deliver", "assignee": "jarvis"})
    assert created["ok"] is True
    tid = created["task_id"]
    assert (await call(server, "kanban_comment", {"task_id": tid, "body": "handoff"}))["ok"]
    assert (await call(server, "kanban_attach", {"task_id": tid, "filename": "note.txt", "content_base64": "bm90ZQ=="}))["ok"]
    shown = await call(server, "kanban_show", {"task_id": tid})
    assert shown["task"]["created_by"] == "jarvis"
    assert shown["comments"][-1]["author"] == "jarvis"
    assert shown["comments"][-1]["body"] == "handoff"
    assert (await call(server, "kanban_complete", {"task_id": tid, "summary": "delivered"}))["ok"]
    assert (await call(server, "kanban_show", {"task_id": tid}))["task"]["status"] == "done"
    assert current_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,enabled", [(False, True), (True, False)])
async def test_non_owner_or_disabled_calls_do_not_create_state(tmp_path, owner, enabled):
    answer = await call(server_for(tmp_path, owner=owner, enabled=enabled), "kanban_create",
                        {"title": "forbidden", "assignee": "jarvis"})
    assert answer["ok"] is False
    assert not (tmp_path / "kanban.db").exists()


@pytest.mark.asyncio
async def test_worker_cannot_borrow_other_task_board_or_actor(tmp_path):
    server = server_for(tmp_path, owner=False)
    with kanban_scope(KanbanContext(tmp_path, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        own = kb.create_task(conn, title="own", assignee="jarvis")
        other = kb.create_task(conn, title="other", assignee="jarvis")
        run = kb.claim_task(conn, own)
    with kanban_scope(KanbanContext(tmp_path, "jarvis", task_id=own, run_id=run.current_run_id, can_mutate=True)):
        for name, args, actor in (
            ("kanban_complete", {"task_id": other, "summary": "forged"}, "jarvis"),
            ("kanban_show", {"task_id": other}, "jarvis"),
            ("kanban_show", {"board": "other"}, "jarvis"),
            ("kanban_complete", {"summary": "forged"}, "ultron"),
            ("kanban_list", {}, "jarvis"),
            ("kanban_link", {"parent_id": own, "child_id": other}, "jarvis"),
        ):
            assert (await call(server, name, args, actor=actor))["ok"] is False
        assert (await call(server, "kanban_complete", {"summary": "owned result"}))["ok"]
    with kanban_scope(KanbanContext(tmp_path, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.get_task(conn, own).status == "done"
        assert kb.get_task(conn, other).status == "ready"


@pytest.mark.asyncio
async def test_stale_worker_and_unknown_args_are_rejected_without_success(tmp_path):
    server = server_for(tmp_path)
    tid = (await call(server, "kanban_create", {"title": "owned", "assignee": "jarvis"}))["task_id"]
    with kanban_scope(KanbanContext(tmp_path, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        claimed = kb.claim_task(conn, tid)
    with kanban_scope(KanbanContext(tmp_path, "jarvis", task_id=tid, run_id=claimed.current_run_id + 1, can_mutate=True)):
        assert (await call(server, "kanban_complete", {"summary": "wrong"}))["ok"] is False
        assert (await call(server, "kanban_comment", {"body": "bad", "identity": "admin"}))["ok"] is False


@pytest.mark.asyncio
async def test_rpc_review_block_dependency_and_heartbeat(tmp_path):
    server = server_for(tmp_path)
    parent = (await call(server, "kanban_create", {"title": "parent", "assignee": "jarvis"}))["task_id"]
    child = (await call(server, "kanban_create", {"title": "child", "assignee": "jarvis"}))["task_id"]
    assert (await call(server, "kanban_link", {"parent_id": parent, "child_id": child}))["ok"]
    assert (await call(server, "kanban_request_review", {"task_id": parent, "summary": "review", "reviewer": "reviewer"}))["ok"]
    with kanban_scope(KanbanContext(tmp_path, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        review_run = kb.claim_review_task(conn, parent)
    with kanban_scope(KanbanContext(tmp_path, "reviewer", task_id=parent, run_id=review_run.current_run_id, can_mutate=True)):
        assert (await call(server, "kanban_request_changes", {"reason": "revise"}, actor="reviewer"))["ok"]
    assert (await call(server, "kanban_block", {"task_id": parent, "reason": "need input", "kind": "needs_input"}))["ok"]
    assert (await call(server, "kanban_unblock", {"task_id": parent}))["ok"]
    with kanban_scope(KanbanContext(tmp_path, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        working = kb.claim_task(conn, parent)
    with kanban_scope(KanbanContext(tmp_path, "jarvis", task_id=parent, run_id=working.current_run_id, can_mutate=True)):
        assert (await call(server, "kanban_heartbeat", {"note": "working"}))["ok"]
        assert (await call(server, "kanban_complete", {"summary": "ready"}))["ok"]
    listed = await call(server, "kanban_list")
    assert next(t for t in listed["tasks"] if t["id"] == child)["status"] == "ready"


@pytest.mark.asyncio
async def test_unbound_goal_network_and_workspace_never_report_success(tmp_path):
    server = server_for(tmp_path)
    made = await call(server, "kanban_create", {"title": "goal", "assignee": "jarvis", "goal_mode": True})
    assert made["ok"]
    tid = made["task_id"]
    for name, args in (
        ("kanban_complete", {"task_id": tid, "summary": "unsupported judge"}),
        ("kanban_attach_url", {"task_id": tid, "url": "http://127.0.0.1/"}),
        ("kanban_create", {"title": "escape", "assignee": "jarvis", "workspace_path": "/etc"}),
    ):
        assert (await call(server, name, args))["ok"] is False
    assert (await call(server, "kanban_show", {"task_id": tid}))["task"]["status"] == "ready"


def test_profiles_withhold_board_from_guests_jobs_and_disabled_owner():
    tools = [{"name": name, "gated": False} for name in ("kanban_show", "kanban_create", "kanban_list")]
    def settings(key, default):
        return True if key == "llm.kanban" else default
    for posture in (ToolPosture("operator", "guest"), ToolPosture("inbound", "owner"), ToolPosture("internal", "system")):
        assert resolve_tools(tools, posture=posture, settings=settings)[0] == []
    assert resolve_tools(tools, posture=ToolPosture("operator", "owner"))[0] == []
    assert len(resolve_tools(tools, posture=ToolPosture("operator", "owner"), settings=settings)[0]) == 3


@pytest.mark.asyncio
async def test_same_agent_delegate_cannot_inherit_parent_board_authority(tmp_path):
    from agents.core.autonomy_coordinator import make_subagent_runner
    observed = []
    async def process(task, **kwargs):
        observed.append(current_context())
        return "findings", None
    runner = make_subagent_runner(SimpleNamespace(agents={"jarvis": object()}, process_detailed=process))
    with kanban_scope(KanbanContext(tmp_path, "jarvis", task_id="t_parent", run_id=3, can_mutate=True)):
        await runner("inspect", "s-child", "jarvis")
        assert current_context().task_id == "t_parent"
    assert observed == [None]


@pytest.mark.asyncio
async def test_delegate_and_closed_worker_cannot_fall_back_to_ambient_owner(tmp_path):
    from agents.core.autonomy_coordinator import make_subagent_runner
    server = server_for(tmp_path)
    async def process(task, **kwargs):
        refused = await call(server, "kanban_create", {"title": "borrowed", "assignee": "jarvis"})
        assert refused["ok"] is False
        return "findings", None
    runner = make_subagent_runner(SimpleNamespace(agents={"jarvis": object()}, process_detailed=process))
    with kanban_scope(KanbanContext(tmp_path, "jarvis", task_id="t_parent", run_id=3, can_mutate=True)):
        inherited = copy_context()
        await runner("inspect", "s-child", "jarvis")
    # An inherited task may continue after its worker scope has ended.
    import asyncio
    late = inherited.run(asyncio.create_task, call(server, "kanban_create", {"title": "late", "assignee": "jarvis"}))
    assert (await late)["ok"] is False
    assert not (tmp_path / "kanban.db").exists()


def test_coordinator_registers_the_real_board_tools_without_enabling_them(tmp_path):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    orch = SimpleNamespace(agents={}, get_setting=lambda key, default=None: default)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    rows = orch.tool_rpc.tools()
    assert len([row for row in rows if row["name"].startswith("kanban_")]) == 14
    offered, _ = resolve_tools(rows, posture=ToolPosture("operator", "owner"))
    assert not any(row["name"].startswith("kanban_") for row in offered)


@pytest.mark.asyncio
async def test_enabled_coordinator_writes_scoped_data_with_authenticated_owner(tmp_path, monkeypatch):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch = SimpleNamespace(agents={"jarvis": SimpleNamespace()}, session_id="s-owner",
                           get_setting=lambda key, default=None: True if key == "llm.kanban" else default)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    token = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        result = await call(orch.tool_rpc, "kanban_create", {"title": "real coordinator", "assignee": "jarvis"})
        assert result["ok"]
        assert (await call(orch.tool_rpc, "kanban_show", {"task_id": result["task_id"]}))["task"]["created_by"] == "jarvis"
    finally:
        reset_turn_principal(token)
    assert current_context() is None


@pytest.mark.asyncio
async def test_assigned_task_guidance_reaches_real_request_only_with_matching_worker(tmp_path):
    from agents.core.agent_runtime import AgentToolRuntime
    from tests.test_h388_guidance_runtime import Backend, run
    server = server_for(tmp_path)
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    runtime._guidance_context = lambda aid: {}
    for profile, expected in (("jarvis", True), ("ultron", False)):
        backend = Backend()
        with kanban_scope(KanbanContext(tmp_path, profile, task_id="t_owned", run_id=2, can_mutate=True)):
            await run(runtime, backend)
        system = backend.requests[0]["messages"][0]["content"]
        assert ("You have been assigned task t_owned" in system) is expected
