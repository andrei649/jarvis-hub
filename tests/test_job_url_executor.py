"""Real signed queue composition; HTTP is injected and never reaches a socket."""
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel.binding import make_action_kernel
from tests.test_task_mediation_evidence import _head_anchor, _signer


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from agents.core.autonomy.jobs_url import URLMonitorExecutor
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setenv('JARVIS_SYSTEM_PROFILE', 'balanced')
    path = tmp_path / 'queue.db'
    queue = TaskQueue(str(path), mediation_mode='enforce', mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(path), mediation_scope='global').initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(autonomy=worker, kill_switch=None, capabilities=None,
        intent_log=None, budget_ledger=None, loop_detector=None)
    kernel = make_action_kernel(orch)
    worker.bind_mediation(kernel, _signer())
    requests = []
    state = SimpleNamespace(response=lambda: httpx.Response(200, stream=httpx.ByteStream(b'hello secret-value')), current=True)
    def service(req):
        requests.append(req)
        return state.response()
    adapter = URLMonitorExecutor(worker, kernel=kernel,
        redact=lambda text: text.replace('secret-value', '[redacted]'), current=lambda p: state.current,
        resolver=lambda *a, **kw: (['93.184.216.34'], None),
        transport_factory=lambda target: httpx.MockTransport(service))
    executor = TaskExecutor(execution_guard=adapter.guard)
    executor.register('plugin.egress', adapter.execute)
    worker.executor = executor.execute
    yield SimpleNamespace(queue=queue, worker=worker, adapter=adapter, executor=executor,
                          requests=requests, state=state)
    queue.close()


def payload(url='https://example.com/watch'):
    return {'plugin':'job-url-monitor', 'method':'GET', 'url':url,
            'monitor':{'job_id':'one', 'generation':0, 'attempt_id':1, 'hop':0},
            'representation':'utf-8-identity'}


async def approved(rig, value=None):
    task_id = rig.adapter.submit(value or payload(), 'job-url:one:1:0')
    assert rig.queue.get(task_id).status == 'blocked'
    assert (await rig.worker.tick())['ran'] == 0
    await rig.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    await rig.worker.tick()
    return rig.queue.get(task_id)


@pytest.mark.asyncio
async def test_approved_get_is_single_and_scrubbed(rig):
    task = await approved(rig)
    assert task.result['status'] == 'ok', task.result
    assert task.result['result']['stdout'] == 'hello [redacted]'
    assert 'secret-value' not in str(task.result)
    assert len(rig.requests) == 1
    assert rig.requests[0].headers['accept-encoding'] == 'identity'
    assert 'cookie' not in rig.requests[0].headers
    assert (await rig.executor.execute(task))['status'] == 'refused'
    assert (await rig.adapter.execute(task))['status'] == 'refused'
    await rig.worker.tick()
    assert len(rig.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers,body', [(302, {'location':'/next'}, b''),
    (302, {'location':'https://another.example/next'}, b'')])
async def test_redirect_never_sends_second_get(rig, status, headers, body):
    rig.state.response=lambda: httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))
    task=await approved(rig)
    assert task.result['status']=='redirect'
    assert len(rig.requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,body', [({'content-encoding':'gzip'}, b'not-gzip'),
    ({}, b'x'*(262144+1)), ({}, b'\xff')])
async def test_bad_representation_never_returns_observation(rig, headers, body):
    rig.state.response=lambda: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))
    task=await approved(rig)
    assert task.result['status']=='failed'
    assert 'stdout' not in task.result


@pytest.mark.parametrize('url', ['https://user:pass@example.com/', 'https://example.com/?token=abc',
    'https://example.com/secret-value', 'file:///etc/passwd', 'https://example.com/#secret'])
def test_credentials_rejected_before_enqueue(rig, url):
    with pytest.raises(ValueError):
        rig.adapter.submit(payload(url), 'job-url:one:1:0')
    assert rig.queue.list()==[] and not rig.requests


@pytest.mark.asyncio
async def test_stale_generation_and_disabled_mediation_never_send(rig):
    task_id=rig.adapter.submit(payload(), 'job-url:one:1:0')
    rig.state.current=False
    await rig.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    await rig.worker.tick()
    assert not rig.requests


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['kernel_missing', 'kernel_error', 'kernel_deny', 'estop', 'changed_payload', 'signer_missing'])
async def test_live_refusals_prevent_network(rig, monkeypatch, failure):
    from agents.core import estop
    from agents.core.kernel import Decision, Verdict
    task_id=rig.adapter.submit(payload(), 'job-url:one:1:0')
    await rig.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    if failure=='kernel_missing':
        rig.adapter.kernel=None
    elif failure=='kernel_error':
        def broken(action):
            raise RuntimeError('secret-value')
        rig.adapter.kernel=broken
    elif failure=='kernel_deny':
        rig.adapter.kernel=lambda action: Decision(Verdict.DENY, reason='test denial')
    elif failure=='estop':
        monkeypatch.setattr(estop, 'is_engaged', lambda: True)
    elif failure=='signer_missing':
        rig.worker._mediation_signer=None
    else:
        with rig.queue._lock:
            rig.queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?", ('{}', task_id))
            rig.queue._conn.commit()
    await rig.worker.tick()
    assert not rig.requests


@pytest.mark.asyncio
async def test_worker_does_not_retry_cancelled_fetch(rig):
    import asyncio
    entered=asyncio.Event()
    class Blocking(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Future()
            yield b''
    rig.state.response=lambda: httpx.Response(200, stream=Blocking())
    task_id=rig.adapter.submit(payload(), 'job-url:one:1:0')
    await rig.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    call=asyncio.create_task(rig.worker.tick())
    await entered.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await rig.worker.tick()
    assert len(rig.requests)==1
    assert rig.queue.get(task_id).status=='running'


@pytest.mark.asyncio
async def test_public_address_pinning_denies_loopback(rig):
    rig.adapter.resolver=lambda *a, **kw: (['127.0.0.1'], None)
    task=await approved(rig)
    assert task.result['status']=='failed' and not rig.requests


@pytest.mark.parametrize('mode', ['off', 'hold'])
def test_mediation_not_enforced_refuses_authoring(rig, monkeypatch, mode):
    monkeypatch.setattr(rig.queue, 'mediation_mode', mode)
    with pytest.raises(ValueError):
        rig.adapter.screen('https://example.com')


@pytest.mark.asyncio
async def test_exact_cap_is_successful_and_breaker_stops_later_hop(rig):
    rig.state.response=lambda: httpx.Response(200, stream=httpx.ByteStream(b'x'*262144))
    task=await approved(rig)
    assert task.result['status']=='ok'
    assert task.result['result']['stdout_capture']['byte_count']==262144


@pytest.mark.asyncio
async def test_overall_deadline_does_not_retry(rig, monkeypatch):
    import asyncio

    from agents.core.autonomy import jobs_url
    original_timeout=asyncio.timeout
    monkeypatch.setattr(jobs_url.asyncio, 'timeout', lambda seconds: original_timeout(.01))
    class Blocking(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Future()
            yield b''
    rig.state.response=lambda: httpx.Response(200, stream=Blocking())
    task=await approved(rig)
    assert task.result['status']=='failed'
    await rig.worker.tick()
    assert len(rig.requests)==1


@pytest.mark.asyncio
async def test_open_circuit_breaker_stops_dial(rig, monkeypatch):
    from agents.core.resilience import CircuitBreaker
    monkeypatch.setattr(CircuitBreaker, 'is_open', lambda self: True)
    task=await approved(rig)
    assert task.result['status']=='failed' and not rig.requests


@pytest.mark.asyncio
async def test_prefix_matched_sibling_cannot_dispatch(rig):
    from dataclasses import replace
    task_id=rig.adapter.submit(payload(), 'job-url:one:1:0')
    task=replace(rig.queue.get(task_id), kind='plugin.egress.unapproved')
    assert (await rig.executor.execute(task))['status']=='refused'
    assert not rig.requests


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['malformed', 'expired'])
async def test_invalid_signed_receipt_never_reaches_transport(rig, failure):
    task_id=rig.adapter.submit(payload(), 'job-url:one:1:0')
    await rig.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    task=rig.queue.get(task_id)
    if failure=='expired':
        rig.queue._mediation_clock_ms=lambda: task.mediation_receipt['expires_at_ms']+1
    else:
        with rig.queue._lock:
            rig.queue._conn.execute('UPDATE tasks SET mediation_receipt=? WHERE id=?', ('{bad', task_id))
            rig.queue._conn.commit()
    await rig.worker.tick()
    assert not rig.requests


@pytest.mark.asyncio
async def test_redirect_credentials_are_not_persisted(rig):
    rig.state.response=lambda: httpx.Response(302,
        headers={'location':'https://user:secret-value@example.com/'}, stream=httpx.ByteStream(b''))
    task=await approved(rig)
    assert task.result['status']=='failed'
    assert 'secret-value' not in str(task.result)
    assert len(rig.requests)==1
