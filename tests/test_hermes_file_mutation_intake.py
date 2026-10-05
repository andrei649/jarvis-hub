"""Registered file mutations bind validated calls and labels before queue intake."""

import asyncio
from contextvars import copy_context

import pytest

from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.workspace_context import workspace_scope
from agents.core.tool_rpc import ToolRPCServer


def _file_server(tmp_path, intake=None):
    root = tmp_path / "owner"
    root.mkdir()
    (root / "SOUL.md").write_text("original", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    server = ToolRPCServer(enqueue=lambda *_args, **_kwargs: 99)
    register_file_tools(server, tools, enabled=True, mutation_intake=intake)
    return server, root


@pytest.mark.asyncio
async def test_registered_mutation_intake_gets_final_args_and_file_labels_without_effect(tmp_path):
    calls = []

    def intake(actor, tool, args, labels):
        calls.append((actor, tool, args, labels))
        return len(calls)

    server, root = _file_server(tmp_path, intake)
    instruction = await server.handle({
        "tool": "file_write", "gated_intake": "caller-chosen",
        "args": {"path": "SOUL.md", "content": "new", "class": "ordinary"},
    }, actor="worker")
    code = await server.handle({
        "tool": "file_write", "args": {"path": "job.py", "content": "eval(x)\n"},
    }, actor="worker")
    deleted = await server.handle({"tool": "file_delete", "args": {"path": "SOUL.md"}}, actor="worker")

    assert instruction == {"ok": False, "reason": "approval_required", "tool": "file_write", "task_id": 1}
    assert calls[0] == ("worker", "file_write", {"path": "SOUL.md", "content": "new"}, {
        "class": "agent_instructions", "notice": "this file steers future runs", "steers_future_runs": True,
    })
    assert code["task_id"] == 2
    assert code["code_warnings"] == "py-eval@1"
    assert code["code_warning_count"] == 1
    assert calls[1][0:3] == ("worker", "file_write", {"path": "job.py", "content": "eval(x)\n"})
    assert calls[1][3]["code_warnings"] == "py-eval@1"
    assert calls[1][3]["code_warning_count"] == 1
    assert deleted["task_id"] == 3
    assert calls[2][0:3] == ("worker", "file_delete", {"path": "SOUL.md"})
    assert calls[2][3]["class"] == "agent_instructions"
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "original"
    assert not (root / "job.py").exists()


@pytest.mark.asyncio
async def test_validation_and_classification_refuse_before_custom_intake(tmp_path, monkeypatch):
    calls = []
    server, root = _file_server(tmp_path, lambda *_args: calls.append(True) or 1)
    invalid = await server.handle({"tool": "file_write", "args": {"path": "../outside", "content": "x"}})
    assert invalid["reason"] == "outside_scope"

    from agents.core import file_tools

    monkeypatch.setattr(file_tools.FileTools, "classify_mutation",
                        lambda _self, _args: (_ for _ in ()).throw(RuntimeError("classification lost")))
    unclassified = await server.handle({"tool": "file_write", "args": {"path": "SOUL.md", "content": "x"}})
    assert unclassified["reason"] == "classify_failed"
    assert calls == []
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_expired_workspace_refuses_custom_intake_without_owner_fallback(tmp_path):
    calls = []
    server, root = _file_server(tmp_path, lambda *_args: calls.append(True) or 1)
    home = tmp_path / "home"
    cwd = home / "kanban" / "workspaces" / "task-a"
    cwd.mkdir(parents=True)
    (cwd / "SOUL.md").write_text("worker original", encoding="utf-8")
    context = KanbanContext(home, "worker", task_id="task-a", run_id=1, can_mutate=True)
    with kanban_scope(context), workspace_scope(cwd, still_current=lambda: True):
        inherited = copy_context()
    result = await inherited.run(asyncio.create_task, server.handle({
        "tool": "file_write", "args": {"path": "SOUL.md", "content": "new"},
    }))
    assert result["reason"] == "outside_scope"
    assert calls == []
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "original"
    assert (cwd / "SOUL.md").read_text(encoding="utf-8") == "worker original"


@pytest.mark.asyncio
async def test_workspace_expiring_during_classification_refuses_before_intake(tmp_path, monkeypatch):
    calls = []
    server, _ = _file_server(tmp_path, lambda *_args: calls.append(True) or 1)
    home = tmp_path / "home"
    cwd = home / "kanban" / "workspaces" / "task-a"
    cwd.mkdir(parents=True)
    context = KanbanContext(home, "worker", task_id="task-a", run_id=1, can_mutate=True)
    live = [True]
    original = FileTools.classify_mutation
    classifications = []

    def expire_on_intake_classification(self, args):
        classifications.append(True)
        if len(classifications) == 2:
            live[0] = False
        return original(self, args)

    monkeypatch.setattr(FileTools, "classify_mutation", expire_on_intake_classification)
    with kanban_scope(context), workspace_scope(cwd, still_current=lambda: live[0]):
        result = await server.handle({
            "tool": "file_write", "args": {"path": "SOUL.md", "content": "new"},
        })
    assert result["reason"] == "outside_scope"
    assert len(classifications) == 2 and calls == []
    assert not (cwd / "SOUL.md").exists()


@pytest.mark.asyncio
async def test_absent_mutation_intake_keeps_existing_file_queue_path(tmp_path):
    server, root = _file_server(tmp_path)
    result = await server.handle({"tool": "file_write", "args": {"path": "SOUL.md", "content": "new"}})
    assert result == {"ok": False, "reason": "approval_required", "tool": "file_write", "task_id": 99}
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "original"
