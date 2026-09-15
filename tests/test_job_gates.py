"""Zero-model wake gates preserve approval, failure and direct-output semantics."""
import pytest

from tests.test_job_scripts import complete, make_runtime, scripts  # noqa: F401


@pytest.mark.parametrize('stdout,expected', [
    ('{"wakeAgent": false}', True), ('data\n {"wakeAgent": false}\n\n', True),
    ('{"wakeAgent": true}', False), ('{"wakeAgent": 0}', False),
    ('{"wakeAgent": "false"}', False), ('{"wakeAgent": null}', False),
    ('false', False), ('[]', False), ('{}', False), ('broken', False),
    ('{"wakeAgent": false}\nreal final line', False), ('', False),
])
def test_wake_gate_strict_last_nonempty_json(stdout, expected):
    from agents.core.autonomy.jobs_gates import wake_agent_suppressed
    assert wake_agent_suppressed(stdout) is expected
    assert not wake_agent_suppressed(stdout, truncated=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('no_agent', [True, False])
async def test_wake_gate_suppresses_both_modes_after_approval(tmp_path, scripts, no_agent):
    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts, no_agent=no_agent)
    try:
        await runner.fire(job.id)
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == 'pending'
        complete(tasks[1], stdout='data' * 2000 + '\n{"wakeAgent": false}\n\n')
        await runner.reconcile_scripts()
        await runner.reconcile_scripts()
        run = store.runs(job.id)[0]
        assert run.status == 'ok' and run.summary == 'Suppressed: wake_gate'
        assert not outputs and not prompts
        assert store.get(job.id).attempts == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_truncated_gate_fails_open_and_failed_script_stays_failed(tmp_path, scripts):
    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        complete(tasks[1], stdout='{"wakeAgent": false}')
        tasks[1].result['result']['truncated'] = True
        await runner.reconcile_scripts()
        assert outputs == ['{"wakeAgent": false}']
        await runner.fire(job.id)
        complete(tasks[2], stdout='{"wakeAgent": false}', ok=False)
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == 'failed'
        assert len(outputs) == 1
    finally:
        store.close()


@pytest.mark.parametrize('reply,expected', [
    ('[SILENT]', True), (' \n[silent]\n ', True), ('[SILENT]\nexplanation', True),
    ('explanation\n[SILENT]', True), ('SILENT', True), ('no_reply', True), ('NO REPLY', True),
    ('A report about [SILENT]', False), ('first\n[SILENT]\nlast', False),
    ('SILENT report', False), ('NO_REPLY\nreport', False), ('', False),
])
def test_silence_boundaries(reply, expected):
    from agents.core.autonomy.jobs_gates import is_silent_response
    assert is_silent_response(reply) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('with_script', [True, False])
async def test_model_silence_before_caps_persists_without_delivery(tmp_path, scripts, monkeypatch, with_script):
    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts, no_agent=False)
    if not with_script:
        store.update(job.id, options={'deliver': ['ntfy']})

    async def quiet_reply(*args, **kwargs):
        return 'report' * 3000 + '\n[SILENT]'

    monkeypatch.setattr(runner._orch, 'process', quiet_reply)
    monkeypatch.setattr(runner, '_spend_interrupt', lambda *a: pytest.fail('silent run spent interrupt budget'))
    try:
        await runner.fire(job.id)
        if with_script:
            complete(tasks[1])
            await runner.reconcile_scripts()
        run = store.runs(job.id)[0]
        assert run.status == 'ok' and run.summary == 'Suppressed: model_silent'
        assert not outputs
    finally:
        store.close()


@pytest.mark.asyncio
async def test_no_agent_silent_token_is_literal_output(tmp_path, scripts):
    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        complete(tasks[1], stdout='[SILENT]')
        await runner.reconcile_scripts()
        assert outputs == ['[SILENT]']
    finally:
        store.close()


def test_json_parser_depth_refusal_fails_open(monkeypatch):
    from agents.core.autonomy import jobs_gates

    def refuse_depth(_):
        raise RecursionError('JSON nesting exceeds parser budget')

    monkeypatch.setattr(jobs_gates.json, 'loads', refuse_depth)
    assert not jobs_gates.wake_agent_suppressed('nested payload')
