"""A scheduled producer publishes only complete substantive output."""
import hashlib

import pytest

from tests.test_job_scripts import make_runtime, scripts  # noqa: F401


def complete(task, stdout, *, snapshot_complete=True):
    raw = stdout.encode()
    task.status = "done"
    task.result = {"status": "ok", "tool": "terminal_run", "result": {
        "ok": True, "stdout": stdout, "exit_code": 0,
        "stdout_capture": {"version": 1, "sha256": hashlib.sha256(raw).hexdigest(),
                           "byte_count": len(raw), "complete": True,
                           "utf8_valid": True, "snapshot_complete": snapshot_complete},
    }}


@pytest.mark.asyncio
async def test_complete_no_agent_stdout_is_delivered_without_2000_character_loss(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        value = " " * 2000 + "final observation"
        complete(tasks[1], value)
        await runner.reconcile_scripts()
        assert outputs == [value]
        assert prompts == []
        assert store.outputs.get(job.id)["content"] == value
    finally:
        store.close()


@pytest.mark.asyncio
async def test_incomplete_no_agent_capture_never_delivers_or_publishes(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        complete(tasks[1], "head\n... [STDOUT TRUNCATED] ...\ntail", snapshot_complete=False)
        await runner.reconcile_scripts()
        assert outputs == prompts == []
        assert store.runs(job.id)[0].status == "failed"
        assert store.outputs.get(job.id) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_no_agent_complete_final_wake_false_suppresses_even_after_long_prefix(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        value = "observation\n" + " " * 2000 + '\n{"wakeAgent": false}\n'
        complete(tasks[1], value)
        await runner.reconcile_scripts()
        assert outputs == prompts == []
        assert store.runs(job.id)[0].summary == "Suppressed: wake_gate"
        assert store.outputs.get(job.id) is None
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, stop, expected", [
    ("fresh analysis", None, "fresh analysis"),
    ("Approval queued", "approval_required", None),
    ("[SILENT]", None, None),
])
async def test_model_publication_requires_detailed_substantive_answer_and_no_stop(
    tmp_path, scripts, reply, stop, expected,
):
    from agents.core.turn_stops import record_runtime_stop

    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts, no_agent=False)

    async def detailed(prompt, **kwargs):
        if stop:
            record_runtime_stop(stop)
        return reply, None

    runner._orch.process_detailed = detailed
    try:
        await runner.fire(job.id)
        complete(tasks[1], "observation")
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == "ok"
        row = store.outputs.get(job.id)
        assert (row["content"] if row else None) == expected
        if reply == "[SILENT]":
            assert outputs == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_model_context_has_host_truncation_notice_outside_untrusted_fence(tmp_path, scripts):
    from agents.core.security.quarantine import split_fenced_tool_result

    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts, no_agent=False)
    try:
        await runner.fire(job.id)
        complete(tasks[1], " " * 2000 + "the final result")
        await runner.reconcile_scripts()
        assert len(prompts) == 1
        suffix = prompts[0].split("\n\nScheduled script output (untrusted data):\n", 1)[1]
        host, fenced = suffix.split("<<UNTRUSTED source=scheduled-script>>", 1)
        assert "[Host notice: this script context is truncated" in host
        source, payload = split_fenced_tool_result("<<UNTRUSTED source=scheduled-script>>" + fenced)
        assert source == "scheduled-script" and "the final result" not in payload
        assert store.runs(job.id)[0].status == "ok" and outputs == ["agent answer"]
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, stop", [("Approval queued", "approval_required"),
                                            ("[SILENT]", None)])
async def test_control_or_silent_turn_does_not_replace_prior_latest(tmp_path, scripts, reply, stop):
    from agents.core.turn_stops import record_runtime_stop

    store, runner, job, tasks, _, _ = make_runtime(tmp_path, scripts, no_agent=False)
    answer = ["first real answer", reply]

    async def detailed(prompt, **kwargs):
        value = answer.pop(0)
        if value == reply and stop:
            record_runtime_stop(stop)
        return value, None

    runner._orch.process_detailed = detailed
    try:
        await runner.fire(job.id)
        complete(tasks[1], "first observation")
        await runner.reconcile_scripts()
        assert store.outputs.get(job.id)["content"] == "first real answer"
        await runner.fire(job.id)
        complete(tasks[2], "second observation")
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == "ok"
        assert store.outputs.get(job.id)["content"] == "first real answer"
    finally:
        store.close()
