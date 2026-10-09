"""Completed child effects propose a fresh permit instead of restarting a worker."""

import pytest

from agents.core.kanban import child_store
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.workspace_context import current_workspace
from tests.test_hermes_kanban_child_effects import propose_child
from tests.test_hermes_kanban_dispatcher import read


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["file_write", "file_delete", "terminal_run"])
async def test_successful_child_proposes_one_independently_approved_parent_resume(tmp_path, monkeypatch, tool):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch, tool)
    original_run = child.payload["kanban_child"]["run_id"]
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    completed = orch.autonomy_queue.get(child.id)
    assert completed.result["status"] == "ok" and completed.result["result"]["ok"] is True
    controller = coordinator.kanban_dispatcher()
    proposal = await controller.tick()
    assert len(proposal["queued"]) == 1, proposal
    resume_id = proposal["queued"][0]["queue_id"]
    resume = orch.autonomy_queue.get(resume_id)
    assert resume.kind == "kanban.worker" and resume_id != child.id
    assert resume.payload["resume"]["child_id"] == child.payload["kanban_child"]["child_id"]
    assert resume.payload["resume"]["source_run_id"] == original_run
    assert resume.status in {"proposed", "blocked"}
    assert read(controller, tid).status == "blocked"
    assert (await orch.autonomy.tick())["ran"] == 0

    # Reopening the controller must recover the same durable proposal. A
    # proposal is not permission to run another model turn or replay its child.
    reopened = KanbanDispatcher(orch, home=controller.home)
    again = await reopened.tick()
    assert [item["queue_id"] for item in again["queued"]] == [resume_id]
    assert len(orch.autonomy_queue.active_kind_tasks("kanban.worker")) == 1
    turns = []

    async def finish(_orch, *, prompt, agent_id, session_id):
        context = current_context()
        assert context.task_id == tid and context.run_id != original_run
        assert context.profile == agent_id == "jarvis"
        assert current_workspace().cwd == cwd.resolve()
        assert session_id != child.payload["kanban_child"]["session_id"]
        assert "already completed" in prompt
        with kb.connect_closing() as conn:
            assert kb.complete_task(conn, tid, result="continued after the approved child",
                                    expected_run_id=context.run_id)
        turns.append(context.run_id)
        return "continued after the approved child"

    controller.runner = finish
    await orch.autonomy.apply_decision(resume_id, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    assert len(turns) == 1 and read(controller, tid).status == "done"
    assert (root / "note.txt").read_text() == "owner"
    assert (await controller.tick())["queued"] == []
    assert (await orch.autonomy.tick())["ran"] == 0
    assert len(turns) == 1


@pytest.mark.asyncio
async def test_dispatcher_reconciles_rejected_child_without_resume_or_effect(tmp_path, monkeypatch):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch)
    controller = coordinator.kanban_dispatcher()
    await orch.autonomy.apply_decision(child.id, "reject", "owner")
    assert (await controller.tick())["queued"] == []
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        record = child_store.get(conn, child.payload["kanban_child"]["child_id"])
        assert record["state"] == "failed"
        assert not child_store.active(conn, tid)
    assert read(controller, tid).status == "blocked"
    assert (cwd / "note.txt").read_text() == "worker before"
    assert (root / "note.txt").read_text() == "owner"
    assert (await controller.tick())["queued"] == []
    assert (await orch.autonomy.tick())["ran"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["board", "cwd-replaced", "assignee", "dependency"])
async def test_waiting_resume_cannot_claim_changed_authority(tmp_path, monkeypatch, drift):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    controller = coordinator.kanban_dispatcher()
    proposal = await controller.tick()
    resume_id = proposal["queued"][0]["queue_id"]
    original_run = child.payload["kanban_child"]["run_id"]
    if drift == "cwd-replaced":
        cwd.rename(root / "old-worker")
        cwd.mkdir()
        (cwd / "note.txt").write_text("replacement")
    else:
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), kb.connect_closing() as conn:
            if drift == "board":
                kb.write_board_metadata("default", default_workdir=str(root))
            elif drift == "assignee":
                with kb.write_txn(conn):
                    conn.execute("UPDATE tasks SET assignee='reviewer' WHERE id=?", (tid,))
            else:
                dependency = kb.create_task(conn, title="new prerequisite", assignee="reviewer")
                kb.link_tasks(conn, dependency, tid)
    turns = []

    async def forbidden_turn(*_args, **_kwargs):
        turns.append(True)
        raise AssertionError("changed resume must not reach the worker")

    controller.runner = forbidden_turn
    await orch.autonomy.apply_decision(resume_id, "accept", "owner")
    outcome = await orch.autonomy.tick()
    assert outcome["failed"] == 1 and turns == []
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        task = kb.get_task(conn, tid)
        assert task.current_run_id is None and kb.latest_run(conn, tid).id == original_run
    assert (root / "note.txt").read_text() == "owner"
    assert (cwd / "note.txt").read_text() == ("replacement" if drift == "cwd-replaced" else "worker after")
