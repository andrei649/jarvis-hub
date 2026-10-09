"""Approval, recovery and transaction boundaries of real child continuations."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from agents.core.kanban import child_resume, dispatch_store
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_hermes_kanban_child_effects import propose_child
from tests.test_hermes_kanban_dispatcher import read


async def completed_child(tmp_path, monkeypatch, **kwargs):
    coordinator, orch, root, cwd, tid, child = await propose_child(tmp_path, monkeypatch, **kwargs)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    return coordinator.kanban_dispatcher(), orch, root, cwd, tid, child


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "expire"])
async def test_terminal_resume_never_creates_a_replacement_approval(tmp_path, monkeypatch, decision):
    controller, orch, root, cwd, tid, _ = await completed_child(tmp_path, monkeypatch)
    qid = (await controller.tick())["queued"][0]["queue_id"]
    if decision == "reject":
        await orch.autonomy.apply_decision(qid, "reject", "owner")
    else:
        queue = orch.autonomy_queue
        deadline = datetime.now(UTC) - timedelta(minutes=1)
        queue._conn.execute("UPDATE tasks SET approval_deadline_at=? WHERE id=?", (deadline.isoformat(), qid))
        queue._conn.commit()
        assert [task.id for task in queue.expire_pending_approvals(now=datetime.now(UTC)).tasks] == [qid]
    reopened = KanbanDispatcher(orch, home=controller.home)
    assert (await reopened.tick())["queued"] == []
    assert (await reopened.tick())["queued"] == []
    assert (await orch.autonomy.tick())["ran"] == 0
    assert orch.autonomy_queue.active_kind_tasks("kanban.worker") == []
    assert len(orch.autonomy_queue.list()) == 3
    assert read(controller, tid).status == "blocked"
    assert (cwd / "note.txt").read_text() == "worker after"
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["roots", "source-run", "result", "runtime"])
async def test_resume_rechecks_source_and_runtime_before_opening_a_run(tmp_path, monkeypatch, drift):
    controller, orch, root, cwd, tid, child = await completed_child(tmp_path, monkeypatch)
    qid = (await controller.tick())["queued"][0]["queue_id"]
    source_run = child.payload["kanban_child"]["run_id"]
    if drift == "roots":
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(elsewhere))
    elif drift == "result":
        # Exact result bytes are bound in the new signed proposal. Even a
        # privileged storage edit cannot substitute another successful outcome.
        changed = dict(orch.autonomy_queue.get(child.id).result, witness="changed after approval")
        orch.autonomy_queue._conn.execute("UPDATE tasks SET result=? WHERE id=?", (json.dumps(changed), child.id))
        orch.autonomy_queue._conn.commit()
    elif drift == "runtime":
        get_setting = orch.get_setting
        orch.get_setting = lambda key, default=None: False if key == "llm.kanban_dispatch" else get_setting(key, default)
    else:
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), kb.connect_closing() as conn:
            assert kb.unblock_task(conn, tid)
            replacement = kb.claim_task(conn, tid, claimer="owner:replacement")
            assert replacement.current_run_id != source_run
    before = read(controller, tid)
    turns = []

    async def forbidden(*_args, **_kwargs):
        turns.append(True)
        raise AssertionError("stale continuation reached the worker")

    controller.runner = forbidden
    await orch.autonomy.apply_decision(qid, "accept", "owner")
    assert (await orch.autonomy.tick())["failed"] == 1
    after = read(controller, tid)
    assert turns == [] and after.current_run_id == before.current_run_id
    assert after.status == before.status
    assert (cwd / "note.txt").read_text() == "worker after"
    assert (root / "note.txt").read_text() == "owner"


@pytest.mark.asyncio
async def test_claim_failure_rolls_back_run_and_resume_mapping_together(tmp_path, monkeypatch):
    controller, orch, _, _, tid, child = await completed_child(tmp_path, monkeypatch)
    qid = (await controller.tick())["queued"][0]["queue_id"]
    source_run = child.payload["kanban_child"]["run_id"]
    claim = child_resume.claim

    def fail_after_resume_claim(conn, submission_id):
        claim(conn, submission_id)
        raise ValueError("synthetic crash before claim transaction commits")

    monkeypatch.setattr(child_resume, "claim", fail_after_resume_claim)
    await orch.autonomy.apply_decision(qid, "accept", "owner")
    assert (await orch.autonomy.tick())["failed"] == 1
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        task = kb.get_task(conn, tid)
        assert task.status == "blocked" and task.current_run_id is None
        assert kb.latest_run(conn, tid).id == source_run
        bound = conn.execute("SELECT state FROM nerva_child_resumes WHERE child_id=?",
                             (child.payload["kanban_child"]["child_id"],)).fetchone()
        assert bound["state"] == "prepared"


@pytest.mark.asyncio
async def test_queue_birth_without_board_binding_recovers_same_resume(tmp_path, monkeypatch):
    controller, orch, _, _, tid, _ = await completed_child(tmp_path, monkeypatch)

    def fail_bind(*_args, **_kwargs):
        raise ValueError("synthetic crash after queue birth")

    with monkeypatch.context() as crash:
        crash.setattr(dispatch_store, "bind", fail_bind)
        assert (await controller.tick())["status"] == "refused"
    pending = orch.autonomy_queue.active_kind_tasks("kanban.worker")
    assert len(pending) == 1
    reopened = KanbanDispatcher(orch, home=controller.home)
    recovered = await reopened.tick()
    assert recovered["queued"] == [{"task_id": tid, "queue_id": pending[0].id, "status": "blocked"}]
    assert len(orch.autonomy_queue.list()) == 3
    assert read(controller, tid).status == "blocked"


@pytest.mark.asyncio
async def test_review_child_resume_keeps_review_completion_phase(tmp_path, monkeypatch):
    controller, orch, _, _, tid, _ = await completed_child(tmp_path, monkeypatch, source_lane="review")
    qid = (await controller.tick())["queued"][0]["queue_id"]
    assert orch.autonomy_queue.get(qid).payload["resume"]["source_lane"] == "review"
    turns = []

    async def finish_review(*_args, **_kwargs):
        context = current_context()
        with kb.connect_closing() as conn:
            assert kb._retry_status_for_run(conn, tid) == "review"
            assert kb.complete_task(conn, tid, result="review accepted", expected_run_id=context.run_id)
        turns.append(context.run_id)
        return "review accepted"

    controller.runner = finish_review
    await orch.autonomy.apply_decision(qid, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    assert len(turns) == 1 and read(controller, tid).status == "done"
