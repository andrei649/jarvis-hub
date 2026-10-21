"""Real local script capture through the scheduled-job completion path.

The governed runner uses a test authorization shim for a known task ID; these
tests do not assert the separate signed worker-approval protocol.
"""

from __future__ import annotations

import hashlib

import pytest

from agents.core.environments.execution import GovernedTargetRunner
from tests.test_job_scripts import make_runtime, scripts  # noqa: F401
from tests.test_local_transport import _FakeSandbox, _grant, _local_registry


async def _run_local_attempt(runner, job, tasks):
    pending = await runner.fire(job.id)
    assert pending.status == "pending"
    task = tasks[max(tasks)]
    terminal = GovernedTargetRunner(
        _local_registry(), _FakeSandbox(), authorizer=_grant,
        approval_check=lambda task_id: task_id == task.id,
    )
    result = await terminal.run(agent="jarvis", approved_task_id=task.id,
                                **task.payload["args"])
    assert result["ok"] is True and result["exit_code"] == 0
    task.status = "done"
    task.result = {"status": "ok", "tool": "terminal_run", "result": result}
    await runner.reconcile_scripts()
    return result


def _local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_HOST", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))


@pytest.mark.asyncio
async def test_actual_complete_stdout_over_2000_delivers_whole_and_chains(tmp_path, scripts, monkeypatch):
    _local_env(tmp_path, monkeypatch)
    (scripts / "watch.py").write_text("print(' ' * 2100 + 'substantive tail')\n")
    store, runner, producer, tasks, deliveries, prompts = make_runtime(tmp_path, scripts)
    try:
        result = await _run_local_attempt(runner, producer, tasks)
        stdout = " " * 2100 + "substantive tail\n"
        assert result["stdout"] == stdout and result["truncated"] is False
        assert result["stdout_capture"] == {
            "version": 1, "sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "byte_count": len(stdout.encode()), "complete": True,
            "utf8_valid": True, "snapshot_complete": True,
        }
        assert deliveries == [stdout] and prompts == []
        published = store.outputs.get(producer.id)
        assert published is not None and published["content"] == stdout
        assert published["bounded"] == 0
        assert store.runs(producer.id)[0].status == "ok"

        analyst = runner.create(
            name="analysis", schedule_text="0 9 * * *",
            action={"type": "ask", "prompt": "Analyze the prior job", "deliver": False},
            options={"context_from": [producer.id], "continuity": False, "deliver": []},
        )
        assert (await runner.fire(analyst.id)).status == "ok"
        assert len(prompts) == 1
        assert f"Output from job '{producer.id}'" in prompts[0]
        assert "substantive tail" in prompts[0]
        assert "scheduled-job-context" in prompts[0]
        assert "Your previous run's output" not in prompts[0]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_actual_complete_stdout_after_whitespace_runs_context_model(tmp_path, scripts, monkeypatch):
    _local_env(tmp_path, monkeypatch)
    (scripts / "watch.py").write_text("print(' ' * 2100 + 'substantive tail')\n")
    store, runner, job, tasks, deliveries, prompts = make_runtime(tmp_path, scripts, no_agent=False)
    try:
        result = await _run_local_attempt(runner, job, tasks)
        assert result["stdout_capture"]["snapshot_complete"] is True
        assert len(prompts) == 1 and "Scheduled script output (untrusted data):" in prompts[0]
        assert "[Host notice: this script context is truncated; complete stdout was longer.]" in prompts[0]
        assert deliveries == ["agent answer"]
        assert store.runs(job.id)[0].status == "ok"
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("no_agent", [False, True])
async def test_actual_last_line_wake_false_beyond_2000_suppresses_output(
    tmp_path, scripts, monkeypatch, no_agent,
):
    _local_env(tmp_path, monkeypatch)
    (scripts / "watch.py").write_text("print(' ' * 2100 + '\\n{\"wakeAgent\": false}')\n")
    store, runner, job, tasks, deliveries, prompts = make_runtime(tmp_path, scripts, no_agent=no_agent)
    try:
        result = await _run_local_attempt(runner, job, tasks)
        assert result["stdout_capture"]["snapshot_complete"] is True
        assert result["stdout"].rstrip().endswith('{"wakeAgent": false}')
        assert prompts == [] and deliveries == []
        assert store.outputs.get(job.id) is None
        assert store.runs(job.id)[0].status == "ok"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_actual_transport_incomplete_over_16000_never_delivers_or_publishes(
    tmp_path, scripts, monkeypatch,
):
    _local_env(tmp_path, monkeypatch)
    (scripts / "watch.py").write_text("print('X' * 17000)\n")
    store, runner, job, tasks, deliveries, prompts = make_runtime(tmp_path, scripts)
    try:
        result = await _run_local_attempt(runner, job, tasks)
        capture = result["stdout_capture"]
        assert capture["byte_count"] == 17001
        assert capture["complete"] is True and capture["utf8_valid"] is True
        assert capture["snapshot_complete"] is False
        assert result["truncated"] is True
        assert store.runs(job.id)[0].status == "failed"
        assert deliveries == [] and prompts == [] and store.outputs.get(job.id) is None
    finally:
        store.close()
