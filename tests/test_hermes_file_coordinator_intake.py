"""Registered coordinator producer must queue exact signed file approvals."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kanban.context import KanbanContext, kanban_scope
from tests.test_hermes_kanban_dispatcher import fixture_runtime


def wire(tmp_path, monkeypatch):
    controller, orch, _, _, calls = fixture_runtime(tmp_path, monkeypatch)
    orch.agents = {key: SimpleNamespace() for key in orch.agents}
    original_kernel = orch.autonomy._mediation_kernel
    orch.autonomy.bind_mediation(lambda action, **_kwargs: original_kernel(action),
                                 orch.autonomy._mediation_signer)
    root = tmp_path / "owner-files"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    coordinator = AutonomyCoordinator(orch)
    coordinator._kanban_dispatcher = controller
    coordinator._wire_agent_tool_runtime(action_kernel=orch.autonomy.kernel_gate)
    return coordinator, orch, root, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [
    ("file_write", {"path": "SOUL.md", "content": "synthetic instructions"}),
    ("file_delete", {"path": "SOUL.md"}),
])
async def test_registered_file_intake_is_signed_typed_and_classified(tmp_path, monkeypatch, tool, args):
    _, orch, root, calls = wire(tmp_path, monkeypatch)
    (root / "SOUL.md").write_text("before")
    result = await orch.tool_rpc.handle({"tool": tool, "args": args}, actor="jarvis")
    assert result["reason"] == "approval_required", result
    queued = orch.autonomy_queue.get(result["task_id"])
    assert queued.status == "blocked", queued
    assert queued.kind == "toolrpc." + tool
    assert queued.mediation_enqueue_id
    assert queued.payload["class"] == "agent_instructions"
    assert queued.payload["steers_future_runs"] is True
    assert "this file steers future runs" in queued.title
    assert queued.payload["args"] == args
    assert [action.kind for action in calls] == ["toolrpc." + tool]
    assert (root / "SOUL.md").read_text() == "before"


@pytest.mark.asyncio
async def test_registered_typed_code_intake_retains_warning_in_card_and_answer(tmp_path, monkeypatch):
    _, orch, root, _ = wire(tmp_path, monkeypatch)
    result = await orch.tool_rpc.handle({"tool": "file_write", "args": {
        "path": "job.py", "content": "eval(x)\n",
    }})
    assert result["reason"] == "approval_required", result
    queued = orch.autonomy_queue.get(result["task_id"])
    assert queued.status == "blocked", queued
    assert queued.payload["code_warnings"] == result["code_warnings"] == "py-eval@1"
    assert not (root / "job.py").exists()


@pytest.mark.asyncio
async def test_unbound_worker_cannot_queue_ambient_owner_file_effect(tmp_path, monkeypatch):
    _, orch, root, _ = wire(tmp_path, monkeypatch)
    context = KanbanContext(tmp_path / "board", "jarvis", task_id="unbound", run_id=1, can_mutate=True)
    with kanban_scope(context):
        result = await orch.tool_rpc.handle({"tool": "file_write", "args": {
            "path": "owner.txt", "content": "should never be written",
        }})
    assert not result["ok"] and "task_id" not in result, result
    assert not orch.autonomy_queue.list()
    assert not (root / "owner.txt").exists()


@pytest.mark.asyncio
async def test_typed_owner_file_approval_executes_via_actual_worker(tmp_path, monkeypatch):
    coordinator, orch, root, _ = wire(tmp_path, monkeypatch)
    result = await orch.tool_rpc.handle({"tool": "file_write", "args": {
        "path": "note.txt", "content": "approved owner write",
    }})
    orch.autonomy.executor.__self__.register("toolrpc.file_write", coordinator._approved_desktop_tool_rpc_execute)
    await orch.autonomy.apply_decision(result["task_id"], "accept", "owner")
    summary = await orch.autonomy.tick()
    assert summary["done"] == 1
    assert (root / "note.txt").read_text() == "approved owner write"


@pytest.mark.asyncio
async def test_signed_owner_file_row_without_consumed_worker_permit_cannot_execute(tmp_path, monkeypatch):
    coordinator, orch, root, _ = wire(tmp_path, monkeypatch)
    result = await orch.tool_rpc.handle({"tool": "file_write", "args": {
        "path": "note.txt", "content": "unconsumed operation",
    }})
    await orch.autonomy.apply_decision(result["task_id"], "accept", "owner")
    claimed = orch.autonomy_queue.claim_mediated(result["task_id"], execution_id=str(uuid4()))
    assert claimed is not None and claimed.status == "running"
    outcome = await coordinator._approved_desktop_tool_rpc_execute(claimed)
    assert outcome["status"] != "ok", outcome
    assert not (root / "note.txt").exists()
