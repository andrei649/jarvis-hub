"""URL monitor integration retains durable attempts and per-hop approval."""
import httpx
import pytest

from tests.test_job_scripts import make_runtime, scripts  # noqa: F401
from tests.test_job_url_executor import rig  # noqa: F401


@pytest.mark.asyncio
async def test_url_authoring_requires_live_screening(tmp_path, scripts):
    store, runner, job, *_ = make_runtime(tmp_path, scripts, no_agent=False)
    try:
        with pytest.raises(ValueError, match='URL'):
            runner.edit(job.id, options={'monitor_url':'https://example.com/watch'})
    finally:
        store.close()


def bind(tmp_path, scripts, rig):
    from agents.core.autonomy.jobs_url import url_payload_current
    store, runner, job, _, outputs, prompts=make_runtime(tmp_path, scripts, no_agent=False)
    rig.adapter.current=lambda payload: url_payload_current(store, payload)
    runner.bind_scripts(submit=lambda *a: pytest.fail('URL reached script intake'),
        get=rig.queue.get, find=lambda origin: rig.queue.list(origin=origin, limit=2))
    runner.bind_url_monitor(rig.adapter)
    job=runner.edit(job.id, options={'monitor_url':'https://example.com/watch', 'deliver':['ntfy']})
    return store, runner, job, outputs, prompts


@pytest.mark.asyncio
async def test_final_observation_baseline_and_unchanged_skip(tmp_path, scripts, rig):
    store, runner, job, outputs, prompts=bind(tmp_path, scripts, rig)
    try:
        for _ in range(2):
            await runner.fire(job.id)
            task=rig.queue.list()[0]
            await runner.reconcile_scripts()
            assert len(rig.requests)==len(outputs)
            await rig.worker.apply_decision(task.id, 'accept', decided_by='test owner')
            await rig.worker.tick()
            await runner.reconcile_scripts()
        assert len(rig.requests)==2 and len(outputs)==len(prompts)==1
        assert store.runs(job.id)[0].summary=='Suppressed: no_change'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_redirect_waits_for_fresh_approval_then_finalizes(tmp_path, scripts, rig):
    store, runner, job, outputs, prompts=bind(tmp_path, scripts, rig)
    rig.state.response=lambda: httpx.Response(302, headers={'location':'/next', 'set-cookie':'session=secret-value'}, stream=httpx.ByteStream(b''))
    try:
        await runner.fire(job.id)
        first=rig.queue.list()[0]
        await rig.worker.apply_decision(first.id, 'accept', decided_by='test owner')
        await rig.worker.tick()
        await runner.reconcile_scripts()
        second=rig.queue.list()[0]
        assert second.id != first.id and second.status=='blocked'
        assert second.payload['url']=='https://example.com/next'
        assert not outputs and not prompts and len(rig.requests)==1
        await runner.reconcile_scripts()
        assert len(rig.queue.list())==2
        rig.state.response=lambda: httpx.Response(200, stream=httpx.ByteStream(b'final'))
        await rig.worker.apply_decision(second.id, 'accept', decided_by='test owner')
        await rig.worker.tick()
        await runner.reconcile_scripts()
        assert len(outputs)==len(prompts)==1 and store.runs(job.id)[0].status=='ok'
        assert 'cookie' not in rig.requests[-1].headers
    finally:
        store.close()


@pytest.mark.asyncio
async def test_restart_completes_persisted_capture_without_new_fetch(tmp_path, scripts, rig):
    from agents.core.autonomy.jobs import JobRunner, JobStore
    from agents.core.autonomy.jobs_url import url_payload_current
    store, runner, job, outputs, prompts=bind(tmp_path, scripts, rig)
    await runner.fire(job.id)
    task=rig.queue.list()[0]
    await rig.worker.apply_decision(task.id, 'accept', decided_by='test owner')
    await rig.worker.tick()
    store.close()
    reopened=JobStore(tmp_path/'jobs.db')
    runner=JobRunner(reopened, orch=runner._orch, scheduler=lambda:None, quiet=lambda:False)
    rig.adapter.current=lambda p: url_payload_current(reopened, p)
    runner.bind_scripts(submit=lambda *a: pytest.fail('replayed script'), get=rig.queue.get,
                        find=lambda origin: rig.queue.list(origin=origin, limit=2))
    runner.bind_url_monitor(rig.adapter)
    try:
        await runner.reconcile_scripts()
        await runner.reconcile_scripts()
        assert len(rig.requests)==len(prompts)==len(outputs)==1
        assert reopened.runs(job.id)[0].status=='ok'
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_configuration_edit_prevents_old_fetch(tmp_path, scripts, rig):
    store, runner, job, outputs, prompts=bind(tmp_path, scripts, rig)
    try:
        await runner.fire(job.id)
        task=rig.queue.list()[0]
        runner.edit(job.id, name='new generation')
        await rig.worker.apply_decision(task.id, 'accept', decided_by='test owner')
        await rig.worker.tick()
        await runner.reconcile_scripts()
        assert not rig.requests and not outputs and not prompts
    finally:
        store.close()


def test_production_coordinator_binds_narrow_executor(tmp_path, scripts, rig):
    from types import SimpleNamespace

    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    store, runner, job, outputs, prompts=bind(tmp_path, scripts, rig)
    try:
        coordinator=AutonomyCoordinator(SimpleNamespace(autonomy=rig.worker, jobs=runner,
            secret_broker=SimpleNamespace(redact=rig.adapter.redact)))
        executor=TaskExecutor(execution_guard=rig.worker.execution_allowed)
        coordinator._wire_url_monitor(executor)
        assert executor.resolve('plugin.egress').__self__ is runner._script_runtime.url_adapter
        assert callable(store.url_screen)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_ambiguous_enqueue_logs_safely_and_recovers_once(tmp_path, scripts, rig, monkeypatch, caplog):
    store, runner, job, outputs, prompts = bind(tmp_path, scripts, rig)
    submit = rig.adapter.submit

    def lost_response(payload, origin):
        submit(payload, origin)
        raise RuntimeError('credential=never-log-this')

    monkeypatch.setattr(rig.adapter, 'submit', lost_response)
    try:
        await runner.fire(job.id)
        assert 'URL monitor proposal outcome unknown' in caplog.text
        assert 'never-log-this' not in caplog.text
        await runner.reconcile_scripts()
        await runner.reconcile_scripts()
        assert len(rig.queue.list()) == 1
        task = rig.queue.list()[0]
        await rig.worker.apply_decision(task.id, 'accept', decided_by='test owner')
        await rig.worker.tick()
        await runner.reconcile_scripts()
        assert len(rig.requests) == len(outputs) == len(prompts) == 1
        assert store.runs(job.id)[0].status == 'ok'
    finally:
        store.close()
