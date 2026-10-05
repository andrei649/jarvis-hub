"""Actual parent worker and independently approved file effects share no permit."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.autonomy.queue import TaskStatus
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_hermes_file_coordinator_intake import wire
from tests.test_hermes_kanban_dispatcher import OWNER, create, read


async def propose_child(tmp_path, monkeypatch, tool="file_write", *, content="worker after", source_lane="ready"):
    coordinator, orch, root, _ = wire(tmp_path, monkeypatch)
    if tool == "terminal_run":
        from agents.core.kernel.binding import make_action_kernel

        monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "1")
        monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
        orch.kill_switch = SimpleNamespace(is_halted=lambda _scope: False)
        orch.autonomy.bind_mediation(make_action_kernel(orch), orch.autonomy._mediation_signer)
        coordinator._wire_agent_tool_runtime(action_kernel=orch.autonomy.kernel_gate)
        orch.tool_rpc._tools["terminal_run"]["gated_review"] = None
    controller = coordinator.kanban_dispatcher()
    cwd = root / "worker"
    cwd.mkdir()
    (root / "note.txt").write_text("owner")
    (cwd / "note.txt").write_text("worker before")
    tid = create(controller, workspace_kind="dir", workspace_path=str(cwd))
    if source_lane == "review":
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), kb.connect_closing() as conn:
            assert kb.request_review(conn, tid, summary="synthetic review evidence", reviewer="jarvis")
    answers = []

    async def runner(_orch, **_kwargs):
        args = {"path": "note.txt"}
        if tool == "file_write":
            args["content"] = content
        if tool == "terminal_run":
            args = {"target": "local-host", "command": "/bin/pwd"}
        answers.append(await orch.tool_rpc.handle({"tool": tool, "args": args}, actor="jarvis"))
        return "waiting for child approval"

    controller.runner = runner
    executor = orch.autonomy.executor.__self__
    executor.register("toolrpc.file_write", coordinator._approved_desktop_tool_rpc_execute)
    executor.register("toolrpc.file_delete", coordinator._approved_desktop_tool_rpc_execute)
    executor.register("toolrpc.terminal_run", coordinator._approved_desktop_tool_rpc_execute)
    parent = (await controller.request(OWNER))["queued"][0]
    orch.autonomy_queue.transition(parent["queue_id"], TaskStatus.APPROVED,
                                   decided_by="owner", decision="approve")
    summary = await orch.autonomy.tick()
    answer = answers[0]
    assert answer["reason"] == "approval_required", answer
    assert summary["done"] == 1, orch.autonomy_queue.get(parent["queue_id"]).result
    child = orch.autonomy_queue.get(answer["task_id"])
    assert child.status == "blocked" and child.id != parent["queue_id"]
    assert child.payload["kanban_child"]["cwd"] == str(cwd.resolve())
    assert read(controller, tid).status == "blocked"
    assert read(controller, tid).block_kind == "needs_input"
    assert (root / "note.txt").read_text() == "owner"
    assert (cwd / "note.txt").read_text() == "worker before"
    return coordinator, orch, root, cwd, tid, child


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["file_write", "file_delete"])
async def test_wait_then_approved_child_mutates_only_its_persisted_workspace(tmp_path, monkeypatch, tool):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch, tool)
    assert (await orch.autonomy.tick())["ran"] == 0
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    result = await orch.autonomy.tick()
    completed = orch.autonomy_queue.get(child.id)
    assert result["done"] == 1 and completed.result["status"] == "ok", completed.result
    assert completed.result["result"]["ok"] is True
    if tool == "file_write":
        assert (cwd / "note.txt").read_text() == "worker after"
    else:
        assert not (cwd / "note.txt").exists()
    assert (root / "note.txt").read_text() == "owner"
    assert cwd.is_dir()
    # A parked parent awaits a separately governed resume; child success never
    # manufactures permission for another model run.
    assert read(coordinator.kanban_dispatcher(), tid).status == "blocked"
    assert (await orch.autonomy.tick())["ran"] == 0
    assert (await coordinator._approved_desktop_tool_rpc_execute(completed))["status"] == "refused"


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["roots", "board", "new-run", "cwd-replaced"])
async def test_waiting_child_rechecks_authority_before_physical_file_write(tmp_path, monkeypatch, drift):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch)
    controller = coordinator.kanban_dispatcher()
    if drift == "roots":
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(other))
    elif drift == "board":
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
            kb.write_board_metadata("default", default_workdir=str(root))
    elif drift == "new-run":
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), kb.connect_closing() as conn:
            assert kb.unblock_task(conn, tid)
    else:
        cwd.rename(root / "old-worker")
        cwd.mkdir()
        (cwd / "note.txt").write_text("replacement")
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    await orch.autonomy.tick()
    outcome = orch.autonomy_queue.get(child.id).result
    assert outcome["status"] != "ok", outcome
    assert (root / "note.txt").read_text() == "owner"
    assert (cwd / "note.txt").read_text() == ("replacement" if drift == "cwd-replaced" else "worker before")


@pytest.mark.asyncio
async def test_rejected_child_keeps_parent_and_workspace_without_file_effect(tmp_path, monkeypatch):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch)
    await orch.autonomy.apply_decision(child.id, "reject", "owner")
    assert (await orch.autonomy.tick())["ran"] == 0
    assert read(coordinator.kanban_dispatcher(), tid).status == "blocked"
    assert (cwd / "note.txt").read_text() == "worker before"
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
async def test_independently_approved_terminal_child_runs_real_local_process_at_signed_cwd(tmp_path, monkeypatch):
    _, orch, root, cwd, _, child = await propose_child(tmp_path, monkeypatch, "terminal_run")
    assert child.payload["args"]["cwd"] == str(cwd.resolve())
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    await orch.autonomy.tick()
    outcome = orch.autonomy_queue.get(child.id).result
    assert outcome["status"] == "ok", outcome
    assert outcome["result"]["ok"] is True
    assert outcome["result"]["stdout"].strip() == str(cwd.resolve())
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
async def test_terminal_child_checks_workspace_again_at_process_spawn(tmp_path, monkeypatch):
    from agents.core.environments.local_transport import LocalHostTransport

    _, orch, root, _, _, child = await propose_child(tmp_path, monkeypatch, "terminal_run")
    original = LocalHostTransport.run
    reached = []

    async def revoke_then_spawn(self, *args, **kwargs):
        reached.append(True)
        other = tmp_path / "revoked-roots"
        other.mkdir()
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(other))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(LocalHostTransport, "run", revoke_then_spawn)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    await orch.autonomy.tick()
    outcome = orch.autonomy_queue.get(child.id).result
    assert reached and outcome["status"] != "ok", outcome
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["file_write", "file_delete"])
async def test_child_revocation_during_checkpoint_persistence_prevents_physical_effect(tmp_path, monkeypatch, tool):
    from agents.core.file_checkpoint_history import FileCheckpointHistory

    _, orch, root, cwd, _, child = await propose_child(tmp_path, monkeypatch, tool)
    original = FileCheckpointHistory._take_checkpoint
    reached = []

    def persist_then_revoke(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        other = tmp_path / "changed-roots"
        other.mkdir()
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(other))
        reached.append(True)
        return result

    monkeypatch.setattr(FileCheckpointHistory, "_take_checkpoint", persist_then_revoke)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    await orch.autonomy.tick()
    outcome = orch.autonomy_queue.get(child.id).result
    assert reached and outcome["status"] != "ok", outcome
    assert (cwd / "note.txt").read_text() == "worker before"
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
async def test_signed_child_writes_complete_multiline_content_near_queue_string_bound(tmp_path, monkeypatch):
    content = "synthetic\n" * 1600
    _, orch, _, cwd, _, child = await propose_child(tmp_path, monkeypatch, content=content)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    await orch.autonomy.tick()
    outcome = orch.autonomy_queue.get(child.id).result
    assert outcome["status"] == "ok", outcome
    assert (cwd / "note.txt").read_text() == content
