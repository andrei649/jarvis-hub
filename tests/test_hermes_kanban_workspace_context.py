"""Worker-local file scopes must affect actual registered tools and expire."""

import asyncio
from contextvars import copy_context

import pytest

from agents.core.file_tools import (
    FileScope,
    FileScopeError,
    FileTools,
    SnapshotStore,
    register_file_tools,
)
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.workspace_context import current_workspace, workspace_scope
from agents.core.tool_rpc import ToolRPCServer
from tests.test_h487_consent_runtime_integration import consent_runtime  # noqa: F401


def server(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "notes.txt").write_text("parent")
    tools = FileTools(FileScope([owner]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    rpc = ToolRPCServer()
    register_file_tools(rpc, tools, enabled=True)
    return rpc, tools


def worker(tmp_path, task_id):
    home = tmp_path / "board-home"
    cwd = home / "kanban" / "workspaces" / task_id
    cwd.mkdir(parents=True)
    (cwd / "notes.txt").write_text(task_id)
    return KanbanContext(home, "jarvis", task_id=task_id, run_id=1, can_mutate=True), cwd


@pytest.mark.asyncio
async def test_registered_file_tools_are_independent_for_concurrent_workers(tmp_path):
    rpc, tools = server(tmp_path)
    original_scope, original_history = tools.scope, tools.history
    ready = asyncio.Event()
    count = 0

    async def read(task_id):
        nonlocal count
        context, cwd = worker(tmp_path, task_id)
        with kanban_scope(context), workspace_scope(cwd, still_current=lambda: True):
            count += 1
            if count == 2:
                ready.set()
            await ready.wait()
            result = await rpc.handle({"tool": "file_read", "args": {"path": "notes.txt"}})
            listed = await rpc.handle({"tool": "file_list", "args": {}})
            assert listed["ok"] and "notes.txt" in [v["name"] for v in listed["result"]["entries"]]
            return result["result"]["content"]

    assert await asyncio.gather(read("task-a"), read("task-b")) == ["task-a", "task-b"]
    assert tools.scope is original_scope and tools.history is original_history
    assert (await rpc.handle({"tool": "file_read", "args": {"path": "notes.txt"}}))["result"]["content"] == "parent"


@pytest.mark.asyncio
async def test_closed_inherited_scope_never_falls_back_to_owner_files(tmp_path):
    rpc, _ = server(tmp_path)
    context, cwd = worker(tmp_path, "task-a")
    with kanban_scope(context), workspace_scope(cwd, still_current=lambda: True):
        inherited = copy_context()
    result = await inherited.run(asyncio.create_task, rpc.handle({"tool": "file_read", "args": {"path": "notes.txt"}}))
    assert not result["ok"] and result["reason"] == "outside_scope"


def test_captured_file_scope_rechecks_revocation_and_directory_identity(tmp_path):
    context, cwd = worker(tmp_path, "task-a")
    live = [True]
    with kanban_scope(context), workspace_scope(cwd, still_current=lambda: live[0]):
        scope = current_workspace().file_scope()
        assert scope.resolve("notes.txt") == cwd / "notes.txt"
        live[0] = False
        with pytest.raises(FileScopeError):
            scope.resolve("notes.txt")
        live[0] = True
        cwd.rename(cwd.with_name("old-task-a"))
        cwd.mkdir()
        with pytest.raises(FileScopeError):
            scope.resolve("notes.txt")


def test_binding_requires_worker_identity_and_admitted_path(tmp_path, monkeypatch):
    context, cwd = worker(tmp_path, "task-a")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path / "allowed"))
    with (kanban_scope(KanbanContext(context.home, "owner", can_mutate=True)),
          pytest.raises(FileScopeError), workspace_scope(cwd, still_current=lambda: True)):
        pass
    outsider = tmp_path / "outside"
    outsider.mkdir()
    with kanban_scope(context), pytest.raises(FileScopeError), workspace_scope(outsider, still_current=lambda: True):
        pass


@pytest.mark.asyncio
async def test_workspace_does_not_grant_mutating_tool_approval(tmp_path):
    rpc, _ = server(tmp_path)
    context, cwd = worker(tmp_path, "task-a")
    with kanban_scope(context), workspace_scope(cwd, still_current=lambda: True):
        result = await rpc.handle({"tool": "file_write", "args": {"path": "notes.txt", "content": "not approved"}})
        assert not result["ok"]
    assert (cwd / "notes.txt").read_text() == "task-a"


@pytest.mark.asyncio
async def test_actual_project_context_reads_worker_conventions_not_owner_default(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agents.core import project_context as pc
    from agents.core.commands import Principal
    from agents.core.orchestrator import (
        _begin_project_context,
        bind_turn_principal,
        reset_turn_principal,
    )

    context, cwd = worker(tmp_path, "task-a")
    parent = tmp_path / "owner"
    parent.mkdir()
    (parent / "AGENTS.md").write_text("Use Vitest for owner tests.")
    (cwd / "AGENTS.md").write_text("Use pytest for workspace tests.")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(parent))
    orch = SimpleNamespace(session_id="worker-session", get_setting=lambda key, default=None:
                           str(parent) if key == "llm.project_dir" else default)
    token = pc.bind()
    principal_token = bind_turn_principal(Principal(channel="internal"))
    try:
        with kanban_scope(context), workspace_scope(cwd, still_current=lambda: True):
            await _begin_project_context(orch)
            state = pc.current()
            assert state is not None
            assert "Use pytest for workspace tests." in state.block
            assert "Use Vitest for owner tests." not in state.block
            assert state.scope.roots == (cwd,)
    finally:
        reset_turn_principal(principal_token)
        pc.reset(token)
        pc.forget("worker-session")


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_worker_terminal_cannot_enqueue_without_signed_workspace_child_binding(consent_runtime, tmp_path, expired):
    runtime = consent_runtime
    context = KanbanContext(tmp_path / "board-home", "jarvis", task_id="task-a", run_id=1, can_mutate=True)
    request = {"tool": "terminal_run", "args": {"target": "local-host", "command": "pwd"}}
    with kanban_scope(context):
        if not expired:
            answer = await runtime.orch.tool_rpc.handle(request, actor="jarvis")
        else:
            captured = copy_context()
    if expired:
        answer = await captured.run(asyncio.create_task, runtime.orch.tool_rpc.handle(request, actor="jarvis"))
    assert not answer["ok"] and answer["reason"] == "kanban_terminal_execution_unbound"
    assert "task_id" not in answer and runtime.q.list() == []


@pytest.mark.asyncio
async def test_unbound_owner_board_scope_preserves_normal_terminal_approval_intake(consent_runtime, tmp_path):
    runtime = consent_runtime
    with kanban_scope(KanbanContext(tmp_path / "board-home", "owner", can_mutate=True)):
        answer = await runtime.orch.tool_rpc.handle(
            {"tool": "terminal_run", "args": {"target": "local-host", "command": "pwd"}}, actor="jarvis")
    assert answer["reason"] == "approval_required" and answer["task_id"] > 0
    assert len(runtime.q.list()) == 1
