"""Script-only workdirs stay within existing local terminal authority."""

import asyncio
from pathlib import Path

import pytest

from agents.core.autonomy.jobs import validate_options
from tests.test_job_scripts import make_runtime, scripts  # noqa: F401


def options(path):
    return {"script": "watch.py", "no_agent": True, "workdir": str(path)}


def test_existing_workdir_is_canonical_and_edit_can_clear(tmp_path, scripts, monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    work = tmp_path / "project"
    work.mkdir()
    assert validate_options(options(work / "."))["workdir"] == str(work.resolve())
    store, runner, job, *_ = make_runtime(tmp_path, scripts)
    try:
        updated = runner.edit(job.id, options=options(work))
        assert updated.options["workdir"] == str(work.resolve())
        cleared = runner.edit(job.id, options={"script": "watch.py", "no_agent": True})
        assert "workdir" not in cleared.options
    finally:
        store.close()


@pytest.mark.parametrize(
    "value", ["", "relative", "https://host/path", None, True, "/" + "a" * 1024]
)
def test_invalid_workdir_values_refused(scripts, value):
    with pytest.raises(ValueError, match="workdir"):
        validate_options({**options("/tmp"), "workdir": value})


@pytest.mark.parametrize(
    "mode",
    [
        {},
        {"script": "watch.py"},
        {"monitor_script": "watch.py"},
        {"script": "watch.py", "no_agent": False},
    ],
)
def test_workdir_cannot_claim_model_workspace(scripts, mode):
    with pytest.raises(ValueError, match="workdir"):
        validate_options({**mode, "workdir": str(scripts)})


@pytest.mark.parametrize("kind", ["missing", "file", "outside", "symlink"])
def test_unavailable_or_escaping_directory_refused(tmp_path, scripts, monkeypatch, kind):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(root))
    path = root / "missing"
    if kind == "file":
        path.write_text("not a directory")
    elif kind == "outside":
        path = scripts
    elif kind == "symlink":
        path.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="workdir"):
        validate_options(options(path))


@pytest.mark.asyncio
async def test_approved_concurrent_jobs_use_distinct_cwd_without_parent_chdir(
    tmp_path, scripts, monkeypatch
):
    from agents.core.environments.execution import GovernedTargetRunner
    from tests.test_local_transport import _FakeSandbox, _grant, _local_registry

    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    (scripts / "watch.py").write_text(
        "from pathlib import Path\nprint(str(Path.cwd()) + ':' + Path('data.txt').read_text())"
    )
    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts)
    parent = Path.cwd()
    try:
        dirs = [tmp_path / "a", tmp_path / "b"]
        for index, directory in enumerate(dirs):
            directory.mkdir()
            (directory / "data.txt").write_text(str(index))
        first = runner.edit(job.id, options={**options(dirs[0]), "deliver": []})
        second = runner.create(
            name="second",
            schedule_text="0 9 * * *",
            action=job.action,
            options={**options(dirs[1]), "deliver": []},
        )
        await asyncio.gather(runner.fire(first.id), runner.fire(second.id))
        terminal = GovernedTargetRunner(
            _local_registry(),
            _FakeSandbox(),
            authorizer=_grant,
            approval_check=lambda task_id: task_id in tasks,
        )
        results = await asyncio.gather(
            *(
                terminal.run(agent="jarvis", approved_task_id=t.id, **t.payload["args"])
                for t in tasks.values()
            )
        )
        assert all(result["ok"] for result in results)
        assert {r["stdout"].strip() for r in results} == {
            f"{d.resolve()}:{i}" for i, d in enumerate(dirs)
        }
        assert Path.cwd() == parent
    finally:
        store.close()


def test_doctor_reports_deleted_workdir_without_reading_contents(tmp_path, scripts, monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    directory = tmp_path / "work"
    directory.mkdir()
    store, runner, job, *_ = make_runtime(tmp_path, scripts)
    try:
        runner.edit(job.id, options=options(directory))
        directory.rmdir()
        monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("doctor read contents"))
        report = runner.doctor()
        assert any(p["code"] == "workdir_unavailable" for p in report["problems"])
        assert "workdir" in report["supported_options"]
        assert "workdir" not in report["unsupported_options"]
        assert "no shell or project cwd" not in report["script_contract"]
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deny", "missing", "outside_symlink", "edit"])
async def test_pending_approval_keeps_frozen_cwd_and_rechecks_execution(
    tmp_path, scripts, monkeypatch, change
):
    from agents.core.environments.execution import GovernedTargetRunner
    from tests.test_local_transport import _FakeSandbox, _grant, _local_registry

    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(root))
    work = root / "a"
    work.mkdir()
    (scripts / "watch.py").write_text("from pathlib import Path\nprint(Path.cwd())")
    store, runner, job, tasks, *_ = make_runtime(tmp_path, scripts)
    try:
        runner.edit(job.id, options=options(work))
        await runner.fire(job.id)
        args = tasks[1].payload["args"]
        assert args["cwd"] == str(work.resolve())
        if change == "missing":
            work.rmdir()
        elif change == "outside_symlink":
            work.rmdir()
            work.symlink_to(scripts, target_is_directory=True)
        elif change == "edit":
            other = root / "b"
            other.mkdir()
            runner.edit(job.id, options=options(other))
        terminal = GovernedTargetRunner(
            _local_registry(),
            _FakeSandbox(),
            authorizer=_grant,
            approval_check=lambda task_id: change != "deny",
        )
        result = await terminal.run(agent="jarvis", approved_task_id=1, **args)
        assert result["ok"] is (change == "edit")
        if change == "edit":
            assert result["stdout"].strip() == str(work)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_estop_and_disappeared_workdir_prevent_proposal(tmp_path, scripts, monkeypatch):
    from agents.core import estop

    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    work = tmp_path / "work"
    work.mkdir()
    store, runner, job, tasks, *_ = make_runtime(tmp_path, scripts)
    try:
        runner.edit(job.id, options=options(work))
        monkeypatch.setattr(estop, "check_paused", lambda *args: True)
        assert (await runner.fire(job.id)).status == "skipped"
        assert not tasks
        monkeypatch.setattr(estop, "check_paused", lambda *args: False)
        work.rmdir()
        assert (await runner.fire(job.id)).status == "failed"
        assert not tasks
    finally:
        store.close()
