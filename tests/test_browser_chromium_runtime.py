"""Actual signed owner ToolRPC plan against one local Chromium loopback fixture."""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.browser_runtime import _chrome_binary
from agents.core.kernel.binding import make_action_kernel
from agents.core.security.capability import KillSwitch
from tests.test_task_mediation_evidence import _head_anchor, _signer

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def local_page():
    state = {'clicked': 0, 'hosts': []}

    async def respond(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            head = request.decode('latin1')
            first = head.splitlines()[0].split()
            path = first[1] if len(first) >= 2 else '/'
            state['hosts'].extend(line[6:] for line in head.splitlines()
                                  if line.lower().startswith('host: '))
            if path == '/clicked':
                state['clicked'] += 1
                body = b'ok'
                status = '200 OK'
            elif path == '/escape':
                body = (f'<!doctype html><title>Escape probe</title>'
                        f'<img src="http://127.0.0.1:{port}/clicked">').encode()
                status = '200 OK'
            elif path == '/redirect':
                body = b''
                status = '302 Found'
            elif path == '/':
                body = (b'<!doctype html><title>Synthetic browser</title>'
                        b'<h1 id="heading">Local fixture</h1>'
                        b'<button id="click" onclick="fetch(\'/clicked\').then(() => '
                        b'document.body.insertAdjacentHTML(\'beforeend\', '
                        b'\'<span id=done>done</span>\'))">Click</button>')
                status = '200 OK'
            else:
                body = b'not found'
                status = '404 Not Found'
            extra = f'Location: http://127.0.0.1:{port}/clicked\r\n' if path == '/redirect' else ''
            writer.write(f'HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n{extra}'
                         'Content-Type: text/html\r\nConnection: close\r\n\r\n'.encode() + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield SimpleNamespace(origin=f'http://fixture.browser.test:{port}', port=port, state=state)
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def browser_rig(tmp_path, monkeypatch, local_page):
    from agents import web
    if importlib.util.find_spec('playwright') is None or not _chrome_binary():
        pytest.skip('isolated Python Playwright and installed Chrome required')
    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setenv('JARVIS_UNIFIED_ACTION_API', '1')
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_HOST', '1')
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'chromium')
    path = tmp_path / 'queue.db'
    queue = TaskQueue(str(path), mediation_mode='enforce', mediation_signer=_signer(),
                      mediation_head_anchor=_head_anchor(path), mediation_scope='global').initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    kill = KillSwitch(tmp_path / 'kill.json')
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=kill, capabilities=None, budget_ledger=None,
                           loop_detector=None, permission_gate=None)
    kernel = make_action_kernel(orch)
    worker.bind_mediation(kernel, _signer())
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate,
                                          _browser_fixture_origin=local_page.origin)
    monkeypatch.setattr(web, 'orch', orch)
    monkeypatch.setattr(web, 'USER_TOKEN', 'browser-user')
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register('toolrpc.browser_run', coordinator._approved_desktop_tool_rpc_execute)
    worker.executor = executor.execute
    runtime = orch.tool_rpc._tools['browser_run']['handler'].__self__
    try:
        yield SimpleNamespace(queue=queue, worker=worker, orch=orch, runtime=runtime, kill=kill,
                              web=web,
                              page=local_page, coordinator=coordinator)
    finally:
        queue.close()


async def test_signed_owner_approval_runs_chromium_once_and_cleans_profile(browser_rig):
    rig = browser_rig
    assert rig.orch.tool_rpc.allows('browser_run')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                 base_url='http://testserver',
                                 headers={'X-User-Token': 'browser-user'}) as client:
        status = await client.get('/api/browser/status')
        assert status.status_code == 200 and status.json() == {'available': True}
        response = await client.post('/api/toolrpc/call', json={'tool': 'browser_run', 'args': {'steps': [
            {'action': 'navigate', 'url': rig.page.origin + '/'},
            {'action': 'snapshot'},
            {'action': 'extract', 'selector': '#heading'},
            {'action': 'click', 'selector': '#click'},
            {'action': 'wait', 'selector': '#done', 'timeout_ms': 3000},
        ]}})
    assert response.status_code == 422
    proposal = response.json()
    assert proposal['reason'] == 'approval_required', proposal
    task = rig.queue.get(proposal['task_id'])
    assert task.status == 'blocked' and task.mediation_receipt is not None
    assert rig.page.state['clicked'] == 0
    early = await rig.coordinator._approved_desktop_tool_rpc_execute(task)
    assert early['reason'] == 'trusted_execution_required'
    await rig.worker.apply_decision(task.id, 'accept', decided_by='andrei')
    await rig.worker.tick()
    done = rig.queue.get(task.id)
    assert done.result['status'] == 'ok', done.result
    result = done.result['result']
    assert result['ok'] is True and len(result['trace']) == 5
    assert result['trace'][2]['result']['text'] == 'Local fixture'
    assert rig.page.state['clicked'] == 1
    assert rig.page.state['hosts'] and set(rig.page.state['hosts']) == {f'fixture.browser.test:{rig.page.port}'}
    assert isinstance(rig.runtime.last_profile, Path)
    assert rig.runtime.last_profile.parent == Path(tempfile.gettempdir())
    assert rig.runtime.last_profile.name.startswith('nerva-browser-')
    assert not rig.runtime.last_profile.exists()


async def test_kernel_kill_after_owner_acceptance_prevents_chromium_start(browser_rig):
    rig = browser_rig
    proposal = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'},
        {'action': 'click', 'selector': '#click'},
    ]}})
    assert proposal['reason'] == 'approval_required', proposal
    await rig.worker.apply_decision(proposal['task_id'], 'accept', decided_by='andrei')
    rig.kill.engage(reason='test halt')
    await rig.worker.tick()
    done = rig.queue.get(proposal['task_id'])
    assert done.result['status'] != 'ok'
    assert rig.page.state['clicked'] == 0
    assert rig.runtime.last_profile is None


async def test_live_kernel_read_denial_prevents_chromium_start(browser_rig):
    from agents.core.kernel import Decision, Verdict

    rig = browser_rig
    proposed = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'},
        {'action': 'snapshot'},
    ]}})
    assert proposed['reason'] == 'approval_required', proposed
    await rig.worker.apply_decision(proposed['task_id'], 'accept', decided_by='andrei')
    rig.runtime.revalidator = lambda *_args, **_kwargs: Decision(Verdict.DENY, reason='test_denial')
    await rig.worker.tick()
    assert rig.queue.get(proposed['task_id']).result['status'] != 'ok'
    assert rig.runtime.last_profile is None
    assert rig.page.state['hosts'] == []


async def test_browser_timeout_cleans_fresh_profile_without_click(browser_rig):
    rig = browser_rig
    proposal = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'},
        {'action': 'wait', 'selector': '#never', 'timeout_ms': 100},
        {'action': 'click', 'selector': '#click'},
    ]}})
    assert proposal['reason'] == 'approval_required', proposal
    await rig.worker.apply_decision(proposal['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    done = rig.queue.get(proposal['task_id'])
    assert done.result['status'] != 'ok'
    assert rig.page.state['clicked'] == 0
    assert rig.runtime.last_profile is not None and not rig.runtime.last_profile.exists()


async def test_cancelling_active_browser_step_drains_chromium_cleanup(browser_rig, monkeypatch):
    from agents.core.browser_playwright import PlaywrightBrowserDriver

    rig = browser_rig
    entered = asyncio.Event()

    async def paused_click(self, *, selector):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(PlaywrightBrowserDriver, 'click', paused_click)
    proposal = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'},
        {'action': 'click', 'selector': '#click'},
    ]}})
    assert proposal['reason'] == 'approval_required', proposal
    await rig.worker.apply_decision(proposal['task_id'], 'accept', decided_by='andrei')
    running = asyncio.create_task(rig.worker.tick())
    await asyncio.wait_for(entered.wait(), 20)
    running.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(running, 20)
    assert rig.page.state['clicked'] == 0
    assert rig.runtime.last_profile is not None and not rig.runtime.last_profile.exists()


async def test_rejected_owner_and_changed_server_binding_never_start_browser(browser_rig, monkeypatch):
    rig = browser_rig
    def proposal():
        return rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
            {'action': 'navigate', 'url': rig.page.origin + '/'},
            {'action': 'click', 'selector': '#click'},
        ]}})

    rejected = await proposal()
    await rig.worker.apply_decision(rejected['task_id'], 'reject', decided_by='andrei')
    await rig.worker.tick()
    assert rig.page.state['clicked'] == 0 and rig.runtime.last_profile is None

    changed = await proposal()
    await rig.worker.apply_decision(changed['task_id'], 'accept', decided_by='andrei')
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'firefox')
    await rig.worker.tick()
    assert rig.queue.get(changed['task_id']).result['status'] != 'ok'
    assert rig.page.state['clicked'] == 0 and rig.runtime.last_profile is None


async def test_real_chromium_blocks_unpinned_subresource_and_redirect(browser_rig):
    rig = browser_rig
    first = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/escape'},
        {'action': 'wait', 'timeout_ms': 300},
    ]}})
    assert first['reason'] == 'approval_required', first
    await rig.worker.apply_decision(first['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    assert rig.queue.get(first['task_id']).result['status'] == 'ok'
    assert rig.page.state['clicked'] == 0

    second = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/redirect'},
    ]}})
    assert second['reason'] == 'approval_required', second
    await rig.worker.apply_decision(second['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    assert rig.queue.get(second['task_id']).result['status'] != 'ok'
    assert rig.page.state['clicked'] == 0
    assert rig.runtime.last_profile is not None and not rig.runtime.last_profile.exists()


async def test_changed_tool_registration_after_acceptance_refuses_before_launch(browser_rig):
    rig = browser_rig
    proposed = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'},
        {'action': 'click', 'selector': '#click'},
    ]}})
    assert proposed['reason'] == 'approval_required', proposed
    await rig.worker.apply_decision(proposed['task_id'], 'accept', decided_by='andrei')
    rig.orch.tool_rpc._tools['browser_run']['_grouping_epoch'] = '0' * 32
    await rig.worker.tick()
    assert rig.queue.get(proposed['task_id']).result['status'] != 'ok'
    assert rig.page.state['clicked'] == 0 and rig.runtime.last_profile is None
