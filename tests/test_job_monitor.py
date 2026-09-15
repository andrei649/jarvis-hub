"""Approved script monitor detection commits before any model call."""
import hashlib

import pytest

from tests.test_job_scripts import complete, make_runtime, scripts  # noqa: F401


def monitor(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = make_runtime(tmp_path, scripts, no_agent=False)
    job = runner.edit(job.id, options={'monitor_script': 'watch.py', 'deliver': ['ntfy']})
    return store, runner, job, tasks, outputs, prompts


def observed(task, text, *, raw=None, **metadata):
    complete(task, stdout=text)
    raw = text.encode() if raw is None else raw
    task.result['result']['stdout_capture'] = {'version': 1, 'sha256': hashlib.sha256(raw).hexdigest(),
        'byte_count': len(raw), 'complete': True, 'utf8_valid': True, 'snapshot_complete': True, **metadata}


@pytest.mark.asyncio
@pytest.mark.parametrize('initial', ['', 'one\n'])
async def test_baseline_no_change_and_diff(tmp_path, scripts, initial):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        for value in [initial, initial, initial + 'two\n']:
            await runner.fire(job.id)
            observed(tasks[len(tasks)], value)
            await runner.reconcile_scripts()
        assert len(prompts) == len(outputs) == 2
        assert 'Monitor Baseline' in prompts[0]
        assert 'MONITOR CHANGE DETECTED' in prompts[1] and '+two' in prompts[1]
        assert store.runs(job.id)[1].summary == 'Suppressed: no_change'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_detection_survives_model_failure(tmp_path, scripts, monkeypatch):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)

    async def fail(*a, **kw):
        raise RuntimeError('model failed')

    monkeypatch.setattr(runner._orch, 'process', fail)
    try:
        await runner.fire(job.id)
        observed(tasks[1], 'same')
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == 'failed'
        await runner.fire(job.id)
        observed(tasks[2], 'same')
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].summary == 'Suppressed: no_change'
        assert not outputs
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [{'complete': False}, {'utf8_valid': False}, {'snapshot_complete': False}, {'version': 2}])
async def test_bad_capture_never_updates_baseline(tmp_path, scripts, bad):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        observed(tasks[1], 'one', **bad)
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == 'failed'
        await runner.fire(job.id)
        observed(tasks[2], 'one')
        await runner.reconcile_scripts()
        assert len(prompts) == 1 and 'Monitor Baseline' in prompts[0]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_source_edit_resets_baseline_and_pending_config_edit_is_stale(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        observed(tasks[1], 'same')
        await runner.reconcile_scripts()
        (scripts / 'watch.py').write_text("print('new implementation')")
        await runner.fire(job.id)
        observed(tasks[2], 'same')
        await runner.reconcile_scripts()
        assert len(prompts) == 2 and 'Monitor Baseline' in prompts[1]
        await runner.fire(job.id)
        runner.edit(job.id, name='replacement')
        observed(tasks[3], 'changed')
        await runner.reconcile_scripts()
        assert len(prompts) == 2
        assert store.runs(job.id)[0].summary == 'Suppressed: stale_configuration'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_monitor_literal_wake_json_and_scrubbed_snapshot(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        observed(tasks[1], '{"wakeAgent": false}')
        await runner.reconcile_scripts()
        assert len(prompts) == 1
        await runner.fire(job.id)
        observed(tasks[2], '[REDACTED]', raw=b'private value')
        await runner.reconcile_scripts()
        assert 'scrubbed' in prompts[1] and 'private value' not in prompts[1]
    finally:
        store.close()


def test_monitor_excludes_other_source_and_no_agent(tmp_path, scripts):
    store, runner, job, *_ = make_runtime(tmp_path, scripts)
    try:
        for options in [{'monitor_script': 'watch.py', 'no_agent': True},
                        {'monitor_script': 'watch.py', 'script': 'watch.py'}, {'monitor_url': 'https://example.com'}]:
            with pytest.raises(ValueError):
                runner.edit(job.id, options=options)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_monitor_restart_and_concurrent_reconciliation(tmp_path, scripts):
    import asyncio

    from agents.core.autonomy.jobs import JobRunner, JobStore
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    await runner.fire(job.id)
    observed(tasks[1], 'first')
    await runner.reconcile_scripts()
    orch = runner._orch
    store.close()
    reopened = JobStore(tmp_path / 'jobs.db')
    resumed = JobRunner(reopened, orch=orch, scheduler=lambda: None, quiet=lambda: False)
    resumed.bind_scripts(submit=runner._script_runtime.submit, get=tasks.get, find=lambda _: [])
    try:
        await resumed.fire(job.id)
        observed(tasks[2], 'first')
        await asyncio.gather(resumed.reconcile_scripts(), resumed.reconcile_scripts())
        assert reopened.runs(job.id)[0].summary == 'Suppressed: no_change'
        assert len(outputs) == len(prompts) == 1
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_config_edit_during_model_suppresses_old_delivery(tmp_path, scripts, monkeypatch):
    import asyncio
    store, runner, job, tasks, outputs, _ = monitor(tmp_path, scripts)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*a, **kw):
        entered.set()
        await release.wait()
        return 'old answer'

    monkeypatch.setattr(runner._orch, 'process', blocked)
    try:
        await runner.fire(job.id)
        observed(tasks[1], 'first')
        running = asyncio.create_task(runner.reconcile_scripts())
        await entered.wait()
        runner.edit(job.id, name='new configuration')
        release.set()
        await running
        assert not outputs
        assert store.runs(job.id)[0].summary == 'Suppressed: stale_configuration'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_monitor_real_approved_capture(tmp_path, scripts, monkeypatch):
    from agents.core.environments.execution import GovernedTargetRunner
    from tests.test_local_transport import _FakeSandbox, _grant, _local_registry
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(tmp_path))
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    terminal = GovernedTargetRunner(_local_registry(), _FakeSandbox(), authorizer=_grant,
                                    approval_check=lambda task_id: task_id == 1)
    try:
        await runner.fire(job.id)
        result = await terminal.run(agent='jarvis', approved_task_id=1, **tasks[1].payload['args'])
        assert result['stdout_capture']['sha256'] == hashlib.sha256(b'ready\n').hexdigest()
        tasks[1].status = 'done'
        tasks[1].result = {'status': 'ok', 'tool': 'terminal_run', 'result': result}
        await runner.reconcile_scripts()
        assert len(prompts) == len(outputs) == 1
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [{'byte_count': 50001}, {'byte_count': True}, {'sha256': 'forged'}, {'version': True}])
async def test_malformed_capture_is_not_a_monitor_observation(tmp_path, scripts, bad):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        await runner.fire(job.id)
        observed(tasks[1], 'value', **bad)
        await runner.reconcile_scripts()
        assert store.runs(job.id)[0].status == 'failed' and not prompts and not outputs
    finally:
        store.close()


@pytest.mark.asyncio
async def test_final_newline_change_has_explicit_unified_diff(tmp_path, scripts):
    store, runner, job, tasks, outputs, prompts = monitor(tmp_path, scripts)
    try:
        for text in ('one', 'one\n'):
            await runner.fire(job.id)
            observed(tasks[len(tasks)], text)
            await runner.reconcile_scripts()
        assert len(prompts) == 2
        assert 'No newline at end of file' in prompts[1]
    finally:
        store.close()
