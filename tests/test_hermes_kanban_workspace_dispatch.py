"""Actual signed queue execution must own the exact approved workspace."""

import json
from contextvars import copy_context
from pathlib import Path

import pytest

from agents.core.autonomy.queue import TaskStatus
from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
from agents.core.kanban import dispatch_store as store
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import projects_db as pdb
from agents.core.kanban.workspace_context import current_workspace
from agents.core.tool_rpc import ToolRPCServer
from tests.test_hermes_kanban_dispatcher import OWNER, create, fixture_runtime, read


def approve(orch, queued):
    orch.autonomy_queue.transition(
        queued["queue_id"], TaskStatus.APPROVED, decided_by="owner", decision="approve"
    )


@pytest.mark.asyncio
async def test_signed_workspace_is_persisted_and_materialized_only_after_approval(tmp_path, monkeypatch):
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(controller)
    queued = (await controller.request(OWNER))["queued"][0]
    payload = orch.autonomy_queue.get(queued["queue_id"]).payload
    spec = payload["workspace_spec"]
    assert spec["task_id"] == tid
    assert spec["run_id"] is None
    cwd = Path(spec["path"])
    assert not cwd.exists()
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        record = store.get(conn, payload["submission_id"])
        assert store.digest(json.loads(record["workspace_json"])) == payload["workspace_binding_sha256"]
        assert json.loads(record["workspace_json"])["spec"] == spec

    seen = []

    async def run(_orch, **_kwargs):
        context = current_context()
        workspace = current_workspace()
        assert workspace is not None and workspace.cwd == cwd and cwd.is_dir()
        seen.append(workspace)
        with kb.connect_closing() as conn:
            assert kb.complete_task(conn, tid, result="synthetic", expected_run_id=context.run_id)
        return "synthetic"

    controller.runner = run
    approve(orch, queued)
    assert (await orch.autonomy.tick())["done"] == 1
    assert seen[0].closed
    assert current_workspace() is None and read(controller, tid).status == "done"
    assert not cwd.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["board", "roots", "project"])
async def test_workspace_anchor_drift_cannot_use_old_approval(tmp_path, monkeypatch, drift):
    controller, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    root = tmp_path / "roots"
    root.mkdir()
    first, second = root / "first", root / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    options = {}
    if drift == "project":
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), pdb.connect_closing() as conn:
            options["project_id"] = pdb.create_project(conn, name="Project", folders=[str(first), str(second)])
        options.update(workspace_kind="dir", workspace_path=str(first))
    tid = create(controller, **options)
    response = await controller.request(OWNER)
    assert response["queued"], (response, read(controller, tid), orch.autonomy_queue.list())
    queued = response["queued"][0]
    if drift == "board":
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
            kb.write_board_metadata("default", default_workdir=str(first))
    elif drift == "roots":
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(first))
    else:
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), pdb.connect_closing() as conn:
            pdb.set_primary(conn, options["project_id"], str(second))
    approve(orch, queued)
    assert (await orch.autonomy.tick())["failed"] == 1
    assert seen == [] and read(controller, tid).current_run_id is None
    assert not (controller.home / "kanban" / "workspaces" / tid).exists()


@pytest.mark.asyncio
async def test_real_registered_file_tool_is_scoped_to_approved_dir_and_expires(tmp_path, monkeypatch):
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    root = tmp_path / "repos"
    root.mkdir()
    cwd = root / "project"
    cwd.mkdir()
    (cwd / "note.txt").write_text("worker")
    (root / "note.txt").write_text("owner")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    base = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    rpc = ToolRPCServer()
    register_file_tools(rpc, base, enabled=True)
    tid = create(controller, workspace_kind="dir", workspace_path=str(cwd))
    response = await controller.request(OWNER)
    assert response["queued"], response
    inherited = []

    async def run(_orch, **_kwargs):
        context = current_context()
        answer = await rpc.handle({"tool": "file_read", "args": {"path": "note.txt"}})
        assert answer["ok"] and answer["result"]["content"] == "worker"
        inherited.append(copy_context())
        with kb.connect_closing() as conn:
            assert kb.complete_task(conn, tid, result="read worker file", expected_run_id=context.run_id)
        answer = await rpc.handle({"tool": "file_read", "args": {"path": "note.txt"}})
        assert not answer["ok"] and answer["reason"] == "outside_scope"
        return "synthetic"

    controller.runner = run
    approve(orch, response["queued"][0])
    result = await orch.autonomy.tick()
    assert result["done"] == 1, (result, vars(orch.autonomy_queue.list()[0]).get("result"),
                                read(controller, tid).last_failure_error)
    import asyncio

    expired = await inherited[0].run(asyncio.create_task, rpc.handle({"tool": "file_read", "args": {"path": "note.txt"}}))
    assert not expired["ok"] and expired["reason"] == "outside_scope"
    assert (await rpc.handle({"tool": "file_read", "args": {"path": "note.txt"}}))["result"]["content"] == "owner"
    assert cwd.is_dir()


@pytest.mark.asyncio
async def test_cleanup_waits_for_runner_exit_and_preserves_attached_artifacts(tmp_path, monkeypatch):
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(controller)
    queued = (await controller.request(OWNER))["queued"][0]
    cwd = Path(orch.autonomy_queue.get(queued["queue_id"]).payload["workspace_spec"]["path"])

    async def run(_orch, **_kwargs):
        context = current_context()
        (cwd / "result.txt").write_text("preserved result")
        with kb.connect_closing() as conn:
            conn.execute(
                "INSERT INTO task_attachments (task_id, filename, content_type, size, uploaded_by, stored_path, created_at) "
                "VALUES (?, 'result.txt', 'text/plain', 16, 'jarvis', ?, 1)",
                (tid, str(cwd / "result.txt")),
            )
            conn.commit()
            assert kb.complete_task(conn, tid, result="synthetic", expected_run_id=context.run_id)
        assert cwd.is_dir()  # The model's terminal tool call never removes its live cwd.
        return "synthetic"

    controller.runner = run
    approve(orch, queued)
    assert (await orch.autonomy.tick())["done"] == 1
    assert (cwd / "result.txt").read_text() == "preserved result"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["board", "project", "successor", "dispatch_off"])
async def test_worker_file_effect_rechecks_live_anchor_and_exact_run(tmp_path, monkeypatch, change):
    controller, orch, settings, _, _ = fixture_runtime(tmp_path, monkeypatch)
    root = tmp_path / "repos"
    root.mkdir()
    cwd = root / "project"
    cwd.mkdir()
    second = root / "second"
    second.mkdir()
    (cwd / "note.txt").write_text("worker")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Bound", folders=[str(cwd), str(second)])
    tid = create(controller, workspace_kind="dir", workspace_path=str(cwd), project_id=pid)
    queued = (await controller.request(OWNER))["queued"][0]
    rpc = ToolRPCServer()
    register_file_tools(rpc, FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots")), enabled=True)
    seen = []

    async def run(_orch, **_kwargs):
        scope = current_workspace().file_scope()
        assert scope.resolve("note.txt") == cwd / "note.txt"
        with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
            if change == "board":
                kb.write_board_metadata("default", default_workdir=str(second))
            elif change == "project":
                with pdb.connect_closing() as conn:
                    pdb.set_primary(conn, pid, str(second))
            elif change == "dispatch_off":
                settings["llm.kanban_dispatch"] = False
            else:
                with kb.connect_closing() as conn:
                    conn.execute("UPDATE tasks SET current_run_id=current_run_id+1 WHERE id=?", (tid,))
                    conn.commit()
        result = await rpc.handle({"tool": "file_read", "args": {"path": "note.txt"}})
        assert not result["ok"] and result["reason"] == "outside_scope"
        seen.append(True)
        return "cannot finish changed execution"

    controller.runner = run
    approve(orch, queued)
    assert (await orch.autonomy.tick())["failed"] == 1
    assert seen == [True] and cwd.is_dir()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["clean", "dirty", "unpushed"])
async def test_project_worktree_runs_on_deterministic_branch_and_preserves_work(tmp_path, monkeypatch, state):
    from tests.test_hermes_kanban_workspaces import _git

    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    root = tmp_path / "repos"
    root.mkdir()
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
         "commit", "--allow-empty", "-m", "base")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="My App", primary_path=str(repo))
    tid = create(controller, project_id=pid)
    board_task = read(controller, tid)
    assert board_task.workspace_kind == "worktree" and board_task.branch_name.startswith(f"my-app/{tid}")
    queued = (await controller.request(OWNER))["queued"][0]
    cwd = Path(orch.autonomy_queue.get(queued["queue_id"]).payload["workspace_spec"]["path"])
    assert not cwd.exists()

    async def run(_orch, **_kwargs):
        context = current_context()
        assert current_workspace().cwd == cwd
        assert _git(cwd, "branch", "--show-current") == board_task.branch_name
        if state == "dirty":
            (cwd / "work.txt").write_text("preserve")
        elif state == "unpushed":
            _git(cwd, "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                 "commit", "--allow-empty", "-m", "unique work")
        with kb.connect_closing() as conn:
            assert kb.complete_task(conn, tid, result="synthetic", expected_run_id=context.run_id)
        assert cwd.exists()
        return "synthetic"

    controller.runner = run
    approve(orch, queued)
    assert (await orch.autonomy.tick())["done"] == 1
    assert cwd.exists() is (state != "clean")
    assert _git(repo, "branch", "--list", board_task.branch_name)  # Custom project branches survive.
