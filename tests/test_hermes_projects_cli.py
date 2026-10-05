"""The authenticated project command uses the real scoped Hermes store."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.kanban.cli_upstream import projects_commands as commands
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.projects_cli import execute_command
from agents.core.kanban.runtime import delegate_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import projects_db as pdb

OWNER = SimpleNamespace(channel="web", admin=True)


def _orch(enabled=True):
    return SimpleNamespace(get_setting=lambda key, default=None: enabled if key == "llm.kanban" else default)


@pytest.mark.asyncio
async def test_full_project_lifecycle_is_durable(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    first, second = repos / "first", repos / "second"
    first.mkdir(parents=True)
    second.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    home = tmp_path / "home"
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        async def run(*args):
            answer = await execute_command(_orch(), list(args), OWNER)
            assert answer["ok"], answer
            return answer["output"]

        assert "Created project" in await run("create", "My App", str(first), "--description", "Work", "--icon", "M", "--color", "blue", "--use")
        assert "my-app" in await run("ls")
        assert str(first) in await run("show", "my-app")
        assert str(second) in await run("add-folder", "my-app", str(second), "--label", "Second", "--primary")
        assert str(second) in await run("set-primary", "my-app", str(second))
        assert "Renamed" in await run("rename", "my-app", "New Name")
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "my-app")
            assert project.name == "New Name" and project.primary_path == str(second)
            assert (project.description, project.icon, project.color) == ("Work", "M", "blue")
            assert pdb.get_active_id(conn) == project.id
        assert "Removed" in await run("remove-folder", "my-app", str(first))
        assert "Archived" in await run("archive", "my-app")
        assert "my-app" not in await run("list")
        assert "(archived)" in await run("list", "--all")
        assert "Restored" in await run("restore", "my-app")
        assert "Cleared" in await run("use")
        with pdb.connect_closing() as conn:
            assert pdb.get_active_id(conn) is None
            assert [f.path for f in pdb.get_project(conn, "my-app").folders] == [str(second)]


@pytest.mark.asyncio
async def test_bind_board_validates_before_project_mutation(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    valid = repos / "valid"
    valid.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    home = tmp_path / "home"
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        created = await execute_command(_orch(), ["create", "Bound", str(valid)], OWNER)
        assert created["ok"], created
        rejected = await execute_command(_orch(), ["bind-board", "bound", "absent"], OWNER)
        assert not rejected["ok"]
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "bound").board_slug is None
        kb.create_board("real")
        linked = await execute_command(_orch(), ["bind-board", "bound", "real"], OWNER)
        assert linked["ok"], linked
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "bound")
            assert project.board_slug == "real"
        metadata = kb.read_board_metadata("real")
        assert metadata["project_id"] == project.id and metadata["default_workdir"] == str(valid)
        other = await execute_command(_orch(), ["create", "Other", "--board", "real"], OWNER)
        assert not other["ok"]
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "other") is None
        valid.rmdir()
        valid.symlink_to(outside, target_is_directory=True)
        refused = await execute_command(_orch(), ["bind-board", "bound", "default"], OWNER)
        assert not refused["ok"]
        assert kb.read_board_metadata("default")["project_id"] is None


@pytest.mark.asyncio
async def test_owner_scope_and_home_isolation(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    repos.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    orch = _orch()
    home_a, home_b = tmp_path / "a", tmp_path / "b"
    with kanban_scope(KanbanContext(home_a, "owner", can_mutate=True)):
        assert (await execute_command(orch, ["create", "A"], OWNER))["ok"]
        with delegate_scope():
            assert (await execute_command(orch, ["list"], OWNER))["reason"] == "delegated_scope"
    with kanban_scope(KanbanContext(home_b, "owner", can_mutate=True)):
        listed = await execute_command(orch, ["list"], OWNER)
        assert listed["ok"] and "No projects yet" in listed["output"]
    assert (home_a / "projects.db").exists() and (home_b / "projects.db").exists()
    for context in (
        KanbanContext(home_a, "owner", task_id="t1", can_mutate=True),
        KanbanContext(home_a, "owner", run_id=1, can_mutate=True),
        KanbanContext(home_a, "owner", can_mutate=False),
        KanbanContext(home_a, "worker", can_mutate=True),
    ):
        with kanban_scope(context):
            result = await execute_command(orch, ["rename", "a", "No"], OWNER)
            assert not result["ok"]
    with kanban_scope(KanbanContext(home_a, "owner", can_mutate=True)), pdb.connect_closing() as conn:
        assert pdb.get_project(conn, "a").name == "A"
    assert (await execute_command(_orch(False), ["list"], OWNER))["reason"] == "board_disabled"
    assert (await execute_command(orch, ["list"], SimpleNamespace(channel="web", admin=False)))["reason"] == "owner_required"


@pytest.mark.asyncio
async def test_bad_paths_unknown_archived_and_concurrent_output(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    repos.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repos / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    orch = _orch()

    async def one(home, name):
        with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
            for path in (str(outside), str(repos / "escape")):
                rejected = await execute_command(orch, ["create", "Bad", path], OWNER)
                assert not rejected["ok"]
            made = await execute_command(orch, ["create", name], OWNER)
            assert made["ok"]
            assert not (await execute_command(orch, ["show", "absent"], OWNER))["ok"]
            assert (await execute_command(orch, ["archive", name.lower()], OWNER))["ok"]
            assert not (await execute_command(orch, ["use", name.lower()], OWNER))["ok"]
            return await execute_command(orch, ["list", "--all"], OWNER)

    first, second = await asyncio.gather(one(tmp_path / "a", "Alpha"), one(tmp_path / "b", "Beta"))
    assert "alpha" in first["output"] and "beta" not in first["output"]
    assert "beta" in second["output"] and "alpha" not in second["output"]


@pytest.mark.asyncio
async def test_board_metadata_symlink_cannot_redirect_binding(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    repos.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    home = tmp_path / "home"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "board.json").write_text("{}")
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        made = await execute_command(_orch(), ["create", "Safe"], OWNER)
        assert made["ok"], made
        boards = home / "kanban" / "boards"
        boards.mkdir(parents=True)
        (boards / "foreign").symlink_to(foreign, target_is_directory=True)
        refused = await execute_command(_orch(), ["bind-board", "safe", "foreign"], OWNER)
        assert not refused["ok"]
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "safe").board_slug is None
    assert (foreign / "board.json").read_text() == "{}"


@pytest.mark.asyncio
async def test_archive_unbinds_board_and_restore_needs_explicit_rebind(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("work")

        async def run(*argv):
            result = await execute_command(_orch(), list(argv), OWNER)
            assert result["ok"], result
            return result["output"]

        await run("create", "Bound", str(repo), "--board", "work")
        with pdb.connect_closing() as conn:
            project_id = pdb.get_project(conn, "bound").id
        assert kb.read_board_metadata("work")["project_id"] == project_id
        assert "Unbound board work" in await run("archive", "bound")
        assert "Archived" in await run("archive", "bound")
        assert kb.read_board_metadata("work")["project_id"] is None
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "bound")
            assert project.archived and project.board_slug is None
        with kb.connect(board="work") as conn:
            task_id = kb.create_task(conn, title="Ordinary", board="work")
            task = kb.get_task(conn, task_id)
            assert task.project_id is None and task.workspace_kind == "scratch"
        assert "remains unbound" in await run("restore", "bound")
        assert "already active" in await run("restore", "bound")
        assert kb.read_board_metadata("work")["project_id"] is None
        await run("bind-board", "bound", "work")
        assert kb.read_board_metadata("work")["project_id"] == project_id


@pytest.mark.asyncio
async def test_archived_project_metadata_is_editable(tmp_path, monkeypatch):
    repos = tmp_path / "repos"
    first, second = repos / "first", repos / "second"
    first.mkdir(parents=True)
    second.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repos))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        async def run(*argv):
            result = await execute_command(_orch(), list(argv), OWNER)
            assert result["ok"], result

        await run("create", "Archived", str(first))
        await run("archive", "archived")
        await run("rename", "archived", "Renamed")
        await run("add-folder", "archived", str(second), "--primary")
        await run("remove-folder", "archived", str(first))
        await run("set-primary", "archived", str(second))
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "archived")
            assert project.archived and project.name == "Renamed"
            assert project.primary_path == str(second)
            assert [folder.path for folder in project.folders] == [str(second)]


@pytest.mark.asyncio
async def test_binding_failure_rolls_back_board_and_project_links(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("old")
        kb.create_board("new")
        assert (await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "old"], OWNER))["ok"]
        with pdb.connect_closing() as conn:
            project_id = pdb.get_project(conn, "bound").id
        original_update = commands.pdb.update_project

        def fail_update(conn, ident, **fields):
            if fields.get("board_slug") == "new":
                raise OSError("injected project write failure")
            return original_update(conn, ident, **fields)

        monkeypatch.setattr(commands.pdb, "update_project", fail_update)
        result = await execute_command(_orch(), ["bind-board", "bound", "new"], OWNER)
        assert not result["ok"]
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "bound").board_slug == "old"
        assert kb.read_board_metadata("old")["project_id"] == project_id
        assert kb.read_board_metadata("new")["project_id"] is None


@pytest.mark.asyncio
async def test_archive_failure_preserves_bound_board_and_user_workdir(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    override = tmp_path / "repos" / "override"
    repo.mkdir(parents=True)
    override.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("work")
        assert (await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "work"], OWNER))["ok"]
        with pdb.connect_closing() as conn:
            project_id = pdb.get_project(conn, "bound").id
        kb.write_board_metadata("work", default_workdir=str(override))
        original_archive = commands.pdb.archive_project

        def fail_archive(conn, ident):
            raise OSError("injected archive failure")

        monkeypatch.setattr(commands.pdb, "archive_project", fail_archive)
        result = await execute_command(_orch(), ["archive", "bound"], OWNER)
        assert not result["ok"]
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "bound")
            assert not project.archived and project.board_slug == "work"
        meta = kb.read_board_metadata("work")
        assert meta["project_id"] == project_id
        assert meta["default_workdir"] == str(override)
        monkeypatch.setattr(commands.pdb, "archive_project", original_archive)
        assert (await execute_command(_orch(), ["archive", "bound"], OWNER))["ok"]
        meta = kb.read_board_metadata("work")
        assert meta["project_id"] is None
        assert meta["default_workdir"] == str(override)


@pytest.mark.asyncio
async def test_board_write_failure_compensates_created_project(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("work")
        original_write = commands.kb.write_board_metadata

        def fail_after_write(board, **fields):
            result = original_write(board, **fields)
            if board == "work" and fields.get("project_id"):
                raise OSError("injected metadata failure")
            return result

        monkeypatch.setattr(commands.kb, "write_board_metadata", fail_after_write)
        result = await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "work"], OWNER)
        assert not result["ok"]
        assert kb.read_board_metadata("work")["project_id"] is None
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "bound") is None


@pytest.mark.asyncio
async def test_failed_rebind_preserves_newer_foreign_board_change(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("old")
        kb.create_board("new")
        assert (await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "old"], OWNER))["ok"]
        original_write = commands.kb.write_board_metadata

        def foreign_change_then_fail(board, **fields):
            result = original_write(board, **fields)
            if board == "new" and fields.get("project_id"):
                original_write(board, project_id="p_foreign")
                raise OSError("injected concurrent change")
            return result

        monkeypatch.setattr(commands.kb, "write_board_metadata", foreign_change_then_fail)
        result = await execute_command(_orch(), ["bind-board", "bound", "new"], OWNER)
        assert not result["ok"] and "inspect and repair" in result["output"]
        with pdb.connect_closing() as conn:
            assert pdb.get_project(conn, "bound").board_slug == "old"
        assert kb.read_board_metadata("new")["project_id"] == "p_foreign"


@pytest.mark.asyncio
async def test_archive_commit_failure_restores_project_and_board(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    repo.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("work")
        assert (await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "work"], OWNER))["ok"]
        original_archive = commands.pdb.archive_project

        def fail_after_archive(conn, ident):
            original_archive(conn, ident)
            raise OSError("injected post-commit failure")

        monkeypatch.setattr(commands.pdb, "archive_project", fail_after_archive)
        result = await execute_command(_orch(), ["archive", "bound"], OWNER)
        assert not result["ok"]
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "bound")
            assert not project.archived and project.board_slug == "work"
        assert kb.read_board_metadata("work")["project_id"] == project.id


@pytest.mark.asyncio
async def test_restore_active_project_keeps_existing_board_binding(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "repo"
    workdir = tmp_path / "repos" / "manual"
    repo.mkdir(parents=True)
    workdir.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo.parent))
    with kanban_scope(KanbanContext(tmp_path / "home", "owner", can_mutate=True)):
        kb.create_board("work")
        assert (await execute_command(_orch(), ["create", "Bound", str(repo), "--board", "work"], OWNER))["ok"]
        with pdb.connect_closing() as conn:
            project_id = pdb.get_project(conn, "bound").id
        kb.write_board_metadata("work", default_workdir=str(workdir))
        result = await execute_command(_orch(), ["restore", "bound"], OWNER)
        assert result["ok"] and "already active" in result["output"]
        with pdb.connect_closing() as conn:
            project = pdb.get_project(conn, "bound")
            assert not project.archived and project.board_slug == "work"
        meta = kb.read_board_metadata("work")
        assert meta["project_id"] == project_id
        assert meta["default_workdir"] == str(workdir)
