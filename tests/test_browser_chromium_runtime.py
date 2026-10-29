"""Actual signed owner ToolRPC plan against one local Chromium loopback fixture."""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil
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


def browser_identity_alive(identity):
    pid, started = identity
    try:
        process = psutil.Process(pid)
        return (process.create_time() == started and process.is_running()
                and process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})
    except psutil.Error:
        return False


def browser_processes_for_profile(profile):
    marker = f'--user-data-dir={profile}'
    return [process.pid for process in psutil.process_iter(['pid', 'cmdline'])
            if marker in (process.info.get('cmdline') or [])]


@pytest.fixture
async def local_page():
    state = {'clicked': 0, 'hosts': [], 'paths': [], 'websocket_handshakes': 0,
             'form_submits': 0}

    async def respond(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            head = request.decode('latin1')
            if 'upgrade: websocket' in head.lower():
                state['websocket_handshakes'] += 1
            first = head.splitlines()[0].split()
            path = first[1] if len(first) >= 2 else '/'
            state['paths'].append(path)
            state['hosts'].extend(line[6:] for line in head.splitlines()
                                  if line.lower().startswith('host: '))
            if path == '/clicked':
                state['clicked'] += 1
                body = b'ok'
                status = '200 OK'
            elif path in {'/first', '/second'}:
                state['form_submits'] += 1
                body = b'form submitted'
                status = '200 OK'
            elif path == '/form':
                body = (b'<!doctype html><title>Native form</title>'
                        b'<form id="owner" action="/first" method="get" target="_self">'
                        b'<button id="submit" type="submit">Pay</button></form>')
                status = '200 OK'
            elif path == '/frame':
                body = (f'<!doctype html><title>Frames</title><h1>Main frame</h1>'
                        f'<iframe id="child" src="http://frame.other.test:{port}/inside"></iframe>').encode()
                status = '200 OK'
            elif path == '/hidden-frame':
                body = (f'<!doctype html><title>Hidden frame</title>'
                        f'<iframe style="display:none" src="http://frame.other.test:{port}/inside"></iframe>').encode()
                status = '200 OK'
            elif path == '/inside':
                body = (b'<!doctype html><title>Child frame</title>'
                        b'<button id="child-button" onclick="this.dataset.clicked = 1">'
                        b'Child click</button>')
                status = '200 OK'
            elif path == '/observation-child':
                body = (b'<!doctype html><title>Child observations</title>'
                        b'<script>console.log("child-observation")</script>'
                        b'<img id="child-image" src="/pixel-child" alt="Child image" width="12" height="12">')
                status = '200 OK'
            elif path == '/observations':
                body = (f'<!doctype html><title>Observations</title>'
                        '<script>console.log("main-observation"); console.error("bounded-error")</script>'
                        '<img id="visible-image" src="/pixel" alt="Visible image" width="10" height="10">'
                        '<img style="display:none" src="/pixel-hidden" alt="Hidden image">'
                        '<img src="data:image/png;base64,AAA" alt="Embedded image" width="10" height="10">'
                        '<img src="http://unapproved.invalid/x" alt="Unpinned image" width="10" height="10">'
                        '<img src="javascript:alert(1)" alt="Hostile image" width="10" height="10">'
                        f'<iframe src="http://frame.other.test:{port}/observation-child"></iframe>').encode()
                status = '200 OK'
            elif path == '/observation-flood':
                images = ''.join(f'<img src="data:image/png;base64,AAA" alt="Image {index}" '
                                 'width="10" height="10">' for index in range(40))
                body = ('<!doctype html><title>Bounded observations</title>'
                        '<script>for(let i=0;i<80;i++) console.log(String(i)+":"+"x".repeat(1000))</script>'
                        + images).encode()
                status = '200 OK'
            elif path in {'/pixel', '/pixel-child', '/pixel-hidden'}:
                body = b'GIF89a'  # only request counting matters; dimensions are fixed in markup
                status = '200 OK'
            elif path == '/actions':
                body = (b'<!doctype html><title>Actions</title>'
                        b'<button id="activate" onclick="this.dataset.count = '
                        b'(Number(this.dataset.count || 0) + 1); '
                        b'fetch(\'/clicked\').then(() => this.dataset.sent = 1)">Activate</button>'
                        b'<div id="scroller" role="region" tabindex="0" '
                        b'style="height:60px;overflow:auto">'
                        b'<div style="height:1200px">Tall content</div></div>')
                status = '200 OK'
            elif path == '/idle':
                body = (b'<!doctype html><title>Idle egress</title>'
                        b'<script>setTimeout(() => fetch("/clicked"), 2000)</script>'
                        b'<button id="safe">Safe</button>')
                status = '200 OK'
            elif path == '/websocket':
                body = (b'<!doctype html><title>Socket probe</title>'
                        b'<script>document.documentElement.dataset.socketProbe = "started";'
                        b'window.__socketProbe = new WebSocket("ws://fixture.browser.test:' + str(port).encode()
                        + b'/echo")</script>')
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
    assert rig.runtime.last_browser_identity is None
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
    assert rig.runtime.last_browser_identity is not None
    assert not browser_identity_alive(rig.runtime.last_browser_identity)
    assert browser_processes_for_profile(rig.runtime.last_profile) == []


async def test_session_snapshot_ref_survives_separate_owner_approved_call(browser_rig, monkeypatch):
    rig = browser_rig
    monkeypatch.setattr(rig.web, 'ADMIN_TOKEN', 'browser-admin')
    start = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'start', 'steps': [
            {'action': 'navigate', 'url': rig.page.origin + '/'},
            {'action': 'snapshot'},
        ]}})
    assert start['reason'] == 'approval_required', start
    await rig.worker.apply_decision(start['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    start_result = rig.queue.get(start['task_id']).result['result']
    assert start_result['ok'] is True, start_result
    sid = start_result['session_id']
    driver = rig.runtime.sessions[sid].driver
    journal_path = rig.runtime.journal._file(sid)
    ownership = rig.runtime.journal.read(journal_path)
    assert ownership['profile'] == str(driver.profile_dir)
    assert ownership['controller'][0] > 0
    assert ownership['owner_process'][0] == os.getpid()
    assert ownership['native'] == list(driver.owned_browser_identity)
    refs = start_result['trace'][1]['result']['refs']
    button = next(item for item in refs if item['role'] == 'button' and item['name'] == 'Click')
    assert rig.page.state['clicked'] == 0
    from agents.core.browser_playwright import PlaywrightHostDisabled
    with pytest.raises(PlaywrightHostDisabled):
        await driver.click(ref=button['ref'])
    act = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'act', 'session_id': sid, 'steps': [
            {'action': 'click', 'ref': button['ref']},
            {'action': 'wait', 'selector': '#done', 'timeout_ms': 3000},
        ]}})
    assert act['reason'] == 'approval_required', act
    await rig.worker.apply_decision(act['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    result = rig.queue.get(act['task_id']).result['result']
    assert result['ok'] is True, (result, list(driver.blocked_requests), rig.page.state)
    assert rig.page.state['clicked'] == 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                 base_url='http://testserver',
                                 headers={'X-Admin-Token': 'browser-admin'}) as client:
        shown = await client.get(f"/api/browser/tasks/{act['task_id']}")
        assert shown.status_code == 200
        assert shown.json() == {'found': True, 'status': 'done', 'ok': True, 'steps': 2}
        missing = await client.get('/api/browser/tasks/999999')
        assert missing.status_code == 404 and missing.json() == {'found': False}
    assert await rig.runtime.close_owner_session(sid)
    assert rig.runtime.last_profile is not None and not rig.runtime.last_profile.exists()
    assert not browser_identity_alive(rig.runtime.last_browser_identity)
    assert not journal_path.exists()


async def test_owner_approved_console_and_image_inventory_use_live_pinned_frames(browser_rig,
                                                                                monkeypatch):
    from agents.core.browser_playwright import PlaywrightHostDisabled

    rig = browser_rig
    child = rig.page.origin.replace('fixture.browser.test', 'frame.other.test')
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': child + '/observation-child'},
        {'action': 'navigate', 'url': rig.page.origin + '/observations'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    session = rig.runtime.sessions[sid]
    profile = session.driver.profile_dir
    identity = session.driver.owned_browser_identity
    await session.driver._page.evaluate("console.log('main-after-child')")
    with pytest.raises(PlaywrightHostDisabled):
        await session.driver.console()
    with pytest.raises(PlaywrightHostDisabled):
        await session.get_images()
    checked_hosts = []
    original_policy = session.policy.domain_allowed

    def checked_policy(url):
        checked_hosts.append(url)
        return original_policy(url)

    session.policy.domain_allowed = checked_policy
    before = list(rig.page.state['paths'])
    proposed = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'console'}, {'action': 'get_images'}]}})
    assert proposed['reason'] == 'approval_required', proposed
    await rig.worker.apply_decision(proposed['task_id'], 'accept', decided_by='andrei')
    await rig.worker.tick()
    observed = rig.queue.get(proposed['task_id']).result['result']
    assert observed['ok'] is True, observed
    console = observed['trace'][0]['result']
    images = observed['trace'][1]['result']
    assert console['observation'] == 'console' and console['untrusted'] is True
    assert {'main-after-child', 'child-observation'} <= {
        item['text'] for item in console['records']}
    assert 'main-observation' not in {item['text'] for item in console['records']}
    assert all(item['source_origin'] in {'', rig.page.origin, child}
               for item in console['records'])
    assert images['observation'] == 'images' and images['untrusted'] is True
    by_alt = {item['alt']: item for item in images['images']}
    assert {'Visible image', 'Child image', 'Embedded image'} <= set(by_alt)
    assert 'Hidden image' not in by_alt
    assert by_alt['Visible image']['fetchable'] is True
    assert by_alt['Child image']['fetchable'] is True
    assert by_alt['Embedded image']['source_url'] == ''
    assert by_alt['Embedded image']['fetchable'] is False
    assert by_alt['Unpinned image']['fetchable'] is False
    assert by_alt['Hostile image']['source_url'] == ''
    assert rig.page.state['paths'] == before
    assert not any('unapproved.invalid' in url for url in checked_hosts)
    monkeypatch.setattr(rig.web, 'ADMIN_TOKEN', 'browser-admin')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                 base_url='http://testserver',
                                 headers={'X-User-Token': 'browser-user'}) as user:
        assert (await user.get(f"/api/browser/tasks/{proposed['task_id']}")).status_code == 401
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                 base_url='http://testserver',
                                 headers={'X-Admin-Token': 'browser-admin'}) as owner:
        projected = await owner.get(f"/api/browser/tasks/{proposed['task_id']}")
        assert projected.status_code == 200
        body = projected.json()
        assert body['observations'][0]['records']
        assert {item['alt'] for item in body['observations'][1]['images']} >= {
            'Visible image', 'Child image'}
        assert 'trace' not in body and 'payload' not in body
    repeated = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'console'}, {'action': 'get_images'}]})
    assert repeated['ok'] is True, repeated
    assert repeated['trace'][0]['result']['records'] == console['records']
    assert {item['alt'] for item in repeated['trace'][1]['result']['images']} == set(by_alt)
    assert rig.page.state['paths'] == before
    ref = by_alt['Visible image']['ref']
    await session.driver._page.evaluate(
        "document.querySelector('#visible-image').src = '/pixel-child'")
    stale = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': ref}]})
    assert stale['ok'] is False and stale['reason'] == 'stale_browser_ref'
    assert sid not in rig.runtime.sessions
    assert not profile.exists() and not browser_identity_alive(identity)


async def test_console_and_image_inventory_report_honest_native_bounds(browser_rig):
    from agents.core.browser_playwright import MAX_CONSOLE_BYTES, MAX_CONSOLE_RECORDS
    from agents.core.browser_session import MAX_IMAGE_BYTES, MAX_IMAGES

    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/observation-flood'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    try:
        observed = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
            'steps': [{'action': 'console'}, {'action': 'get_images'}]})
        assert observed['ok'] is True, observed
        console = observed['trace'][0]['result']
        images = observed['trace'][1]['result']
        assert len(console['records']) <= MAX_CONSOLE_RECORDS
        assert console['dropped'] > 0 and console['truncated'] > 0
        assert len(json.dumps(console['records'], ensure_ascii=False).encode()) <= MAX_CONSOLE_BYTES
        assert images['count'] <= MAX_IMAGES and images['truncated'] is True
        assert images['dropped'] > 0
        assert len(json.dumps(images['images'], ensure_ascii=False).encode()) <= MAX_IMAGE_BYTES
        assert all(item['fetchable'] is False and item['source_url'] == ''
                   for item in images['images'])
    finally:
        assert await rig.runtime.close_owner_session(sid)


async def test_console_navigation_and_close_discard_prior_document_events(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/observations'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    await driver._page.evaluate("console.log('main-after-child')")
    first = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
                                               'steps': [{'action': 'console'}]})
    assert any(item['text'] == 'main-after-child'
               for item in first['trace'][0]['result']['records'])
    navigated = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'navigate', 'url': rig.page.origin + '/'}]})
    assert navigated['ok'] is True, navigated
    second = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
                                                'steps': [{'action': 'console'}]})
    assert second['ok'] is True
    assert not any(item['text'] in {'main-after-child', 'child-observation'}
                   for item in second['trace'][0]['result']['records'])
    assert await rig.runtime.close_owner_session(sid)
    assert not driver._console_records and driver._console_page is None


async def test_image_ref_srcset_change_is_stale_even_before_current_src_reselects(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/observations'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    inventory = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'get_images'}]})
    assert inventory['ok'] is True
    ref = next(item['ref'] for item in inventory['trace'][0]['result']['images']
               if item['alt'] == 'Visible image')
    await rig.runtime.sessions[sid].driver._page.evaluate(
        "document.querySelector('#visible-image').setAttribute('srcset','/pixel-child 2x')")
    stale = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': ref}]})
    assert stale['ok'] is False and stale['reason'] == 'stale_browser_ref'
    assert sid not in rig.runtime.sessions


async def test_live_kernel_read_denial_blocks_console_and_images_before_observation(browser_rig):
    from agents.core.kernel import Decision, Verdict

    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/observations'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    profile = driver.profile_dir
    proposed = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'console'}, {'action': 'get_images'}]}})
    assert proposed['reason'] == 'approval_required', proposed
    await rig.worker.apply_decision(proposed['task_id'], 'accept', decided_by='andrei')
    rig.runtime.revalidator = lambda *_args, **_kwargs: Decision(Verdict.DENY,
                                                                  reason='test_denial')
    await rig.worker.tick()
    done = rig.queue.get(proposed['task_id'])
    assert done.result['result']['ok'] is False
    assert done.result['result']['reason'] == 'browser_kernel_refused'
    assert sid not in rig.runtime.sessions
    assert not profile.exists() and not driver._console_records


async def test_unchanged_real_registration_survives_two_reaper_ticks_and_next_action(browser_rig,
                                                                                      monkeypatch):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    session = rig.runtime.sessions[sid]
    spec = rig.orch.tool_rpc._tools['browser_run']
    profile = session.driver.profile_dir
    identity = session.driver.owned_browser_identity
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['name'] == 'Click')
    checks = 0
    two_ticks = asyncio.Event()
    real_check = rig.runtime._session_registration_current

    def counted_check(candidate):
        nonlocal checks
        current = real_check(candidate)
        if candidate is session:
            checks += 1
            if checks >= 2:
                two_ticks.set()
        return current

    monkeypatch.setattr(rig.runtime, '_session_registration_current', counted_check)
    try:
        assert session.registration_epoch == spec['_grouping_epoch']
        assert isinstance(session.registration_epoch, str) and len(session.registration_epoch) == 32
        assert isinstance(session.registration_key, str) and session.registration_key
        assert real_check(session)
        await asyncio.wait_for(two_ticks.wait(), 5)
        assert sid in rig.runtime.sessions and not session.closed
        assert profile.exists() and browser_identity_alive(identity)
        assert rig.runtime.journal._file(sid).exists()
        acted = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
            'steps': [{'action': 'click', 'ref': ref},
                      {'action': 'wait', 'selector': '#done', 'timeout_ms': 3000}]})
        assert acted['ok'] is True, acted
        assert rig.page.state['clicked'] == 1
    finally:
        await rig.runtime.close_owner_session(sid)
    assert not profile.exists() and not browser_identity_alive(identity)
    assert not rig.runtime.journal._file(sid).exists()


async def _approved_session_call(rig, args, *, owner='andrei'):
    proposed = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': args})
    assert proposed['reason'] == 'approval_required', proposed
    await rig.worker.apply_decision(proposed['task_id'], 'accept', decided_by=owner)
    await rig.worker.tick()
    return rig.queue.get(proposed['task_id']).result['result']


async def test_session_ref_same_node_semantic_change_and_focus_refuse(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    button = next(item for item in started['trace'][1]['result']['refs']
                  if item['role'] == 'button')
    await driver._page.evaluate("document.querySelector('#click').textContent = 'Pay now'")
    changed = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
                                                  'steps': [{'action': 'click', 'ref': button['ref']}]})
    assert changed['ok'] is False and rig.page.state['clicked'] == 0
    assert changed['reason'] == 'stale_browser_ref'
    assert sid not in rig.runtime.sessions
    assert not browser_identity_alive(rig.runtime.last_browser_identity)

    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['role'] == 'button')
    other_agent = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'act', 'session_id': sid, 'steps': [{'action': 'click', 'ref': ref}]}
    }, actor='someone-else')
    assert other_agent['reason'] == 'browser_session_unavailable'
    assert rig.page.state['clicked'] == 0
    wrong_focus = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'press', 'ref': ref, 'key': 'Enter'}]})
    assert wrong_focus['ok'] is False and rig.page.state['clicked'] == 0
    assert sid not in rig.runtime.sessions

    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/actions'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['name'] == 'Activate')
    driver = rig.runtime.sessions[sid].driver
    await driver._page.evaluate("document.querySelector('#activate').setAttribute('type', 'submit')")
    changed_target = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': ref}]})
    assert changed_target['ok'] is False
    assert changed_target['reason'] == 'stale_browser_ref'
    assert sid not in rig.runtime.sessions

    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/actions'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['name'] == 'Activate')
    driver = rig.runtime.sessions[sid].driver
    focused = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': ref},
                  {'action': 'wait', 'selector': '[data-sent="1"]', 'timeout_ms': 3000}]})
    assert focused['ok'] is True
    assert rig.page.state['clicked'] == 1
    await driver._page.evaluate("document.querySelector('#scroller').focus()")
    transferred = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'press', 'ref': ref, 'key': 'Enter'}]})
    assert transferred['ok'] is False
    assert rig.page.state['clicked'] == 1


async def test_session_wrong_owner_and_forged_ref_never_mutate(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['role'] == 'button')
    wrong = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': ref}]}, owner='someone-else')
    assert wrong['ok'] is False and rig.page.state['clicked'] == 0
    assert sid in rig.runtime.sessions
    forged = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': '@e999'}]})
    assert forged['ok'] is False and rig.page.state['clicked'] == 0
    assert sid not in rig.runtime.sessions


@pytest.mark.parametrize('mutation', [
    "document.querySelector('#owner').action = '/second'",
    "document.querySelector('#owner').method = 'post'",
    "document.querySelector('#submit').formAction = '/second'",
    "document.querySelector('#submit').formTarget = '_blank'",
])
async def test_same_node_native_form_target_change_refuses_before_submit(browser_rig, mutation):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/form'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['name'] == 'Pay')
    try:
        await rig.runtime.sessions[sid].driver._page.evaluate(mutation)
        changed = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
            'steps': [{'action': 'click', 'ref': ref}]})
        assert changed == {'ok': False, 'reason': 'stale_browser_ref'}
        assert rig.page.state['form_submits'] == 0
        assert sid not in rig.runtime.sessions
        assert not browser_identity_alive(rig.runtime.last_browser_identity)
    finally:
        if sid in rig.runtime.sessions:
            await rig.runtime.close_owner_session(sid)


async def test_session_cross_origin_frame_ref_and_back_invalidation(browser_rig):
    rig = browser_rig
    child = rig.page.origin.replace('fixture.browser.test', 'frame.other.test')
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': child + '/inside'},
        {'action': 'navigate', 'url': rig.page.origin + '/frame'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    session = rig.runtime.sessions[sid]
    driver = session.driver
    refs = started['trace'][-1]['result']['refs']
    child_ref = next(item for item in refs if item['name'] == 'Child click')
    assert child_ref['frame_origin'] == child
    cdp = await driver._context.new_cdp_session(driver._page)
    targets = await cdp.send('Target.getTargets')
    assert any(item.get('type') == 'iframe' and item.get('url', '').startswith(child)
               for item in targets['targetInfos']), targets
    assert {url.split(':')[0] for url in rig.page.state['hosts']} == {
        'fixture.browser.test', 'frame.other.test'}
    clicked = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': child_ref['ref']}]})
    assert clicked['ok'] is True, clicked
    frame = next(frame for frame in driver._page.frames if frame.url.startswith(child))
    assert await frame.locator('#child-button').get_attribute('data-clicked') == '1'
    backed = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'back'}]})
    assert backed['ok'] is True, backed
    assert child_ref['ref'] not in session.refs
    stale = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': child_ref['ref']}]})
    assert stale['ok'] is False and sid not in rig.runtime.sessions
    assert not browser_identity_alive(rig.runtime.last_browser_identity)


async def test_hidden_cross_origin_frame_never_mints_action_ref(browser_rig):
    rig = browser_rig
    child = rig.page.origin.replace('fixture.browser.test', 'frame.other.test')
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': child + '/inside'},
        {'action': 'navigate', 'url': rig.page.origin + '/hidden-frame'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    assert all(item['frame_origin'] != child
               for item in started['trace'][-1]['result']['refs'])
    assert await rig.runtime.close_owner_session(started['session_id'])


async def test_idle_session_blocks_background_page_egress(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/idle'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    await asyncio.sleep(2.5)
    assert rig.page.state['clicked'] == 0
    assert any(item['reason'] == 'approved_task_revoked' for item in driver.blocked_requests)
    assert await rig.runtime.close_owner_session(sid)


@pytest.mark.parametrize('change', ['config', 'kill', 'registration', 'registration_epoch'])
async def test_session_revoked_control_reaps_native_chrome(browser_rig, monkeypatch, change):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True
    sid = started['session_id']
    assert rig.runtime._session_registration_current(rig.runtime.sessions[sid])
    identity = rig.runtime.sessions[sid].driver.owned_browser_identity
    profile = rig.runtime.sessions[sid].driver.profile_dir
    journal_path = rig.runtime.journal._file(sid)
    driver = rig.runtime.sessions[sid].driver
    if change == 'config':
        monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'firefox')
    elif change == 'kill':
        rig.kill.engage(reason='test session stop')
    elif change == 'registration_epoch':
        spec = rig.orch.tool_rpc._tools['browser_run']
        spec['_grouping_epoch'] = '0' * 32 if spec['_grouping_epoch'] != '0' * 32 else '1' * 32
    else:
        rig.orch.tool_rpc._tools['browser_run']['_consent_registration_key'] = 'changed'
    async with asyncio.timeout(10):
        while (sid in rig.runtime.sessions or profile.exists() or browser_identity_alive(identity)
               or journal_path.exists() or sid in rig.runtime._owner_close_tasks
               or driver in rig.runtime._uncertain_sessions or rig.runtime._journal_uncertain):
            await asyncio.sleep(0.05)
    assert not journal_path.exists()
    assert rig.page.state['clicked'] == 0


async def test_session_press_focus_and_scroll_are_new_kernel_mutations(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/actions'},
        {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    refs = started['trace'][1]['result']['refs']
    button = next(item['ref'] for item in refs if item['name'] == 'Activate')
    scroller = next(item['ref'] for item in refs if item['role'] == 'region')
    first = await _approved_session_call(rig, {'mode': 'act', 'session_id': sid,
        'steps': [{'action': 'click', 'ref': button},
                  {'action': 'press', 'ref': button, 'key': 'Enter'},
                  {'action': 'scroll', 'ref': scroller, 'direction': 'down', 'pixels': 120}]})
    assert first['ok'] is True, first
    assert await driver._page.locator('#activate').get_attribute('data-count') == '2'
    assert await driver._page.locator('#scroller').evaluate('(e) => e.scrollTop') > 0
    assert await rig.runtime.close_owner_session(sid)
    assert not browser_identity_alive(rig.runtime.last_browser_identity)


async def test_orphan_journal_reaps_only_exact_native_chrome_after_controller_exit(tmp_path):
    chrome = _chrome_binary()
    if not chrome:
        pytest.skip('installed local Chrome required')
    from agents.core.browser_session import BrowserOwnershipJournal

    journal = BrowserOwnershipJournal(tmp_path / 'journal')
    sid = 'f' * 32
    child_code = '''
import json, os, psutil, subprocess, sys, tempfile
from pathlib import Path
from agents.core.browser_session import BrowserOwnershipJournal
chrome, root, sid = sys.argv[1:]
profile = Path(tempfile.mkdtemp(prefix='nerva-browser-orphan-'))
journal = BrowserOwnershipJournal(Path(root))
controller = psutil.Process(os.getpid())
record = {'profile': str(profile), 'controller': [controller.pid, controller.create_time()],
    'owner_process': [controller.pid, controller.create_time()], 'native': None}
journal.write(sid, record)
proc = subprocess.Popen([chrome, '--headless=new', '--no-sandbox', '--no-first-run',
    '--no-default-browser-check', '--disable-background-networking', '--no-proxy-server',
    '--host-resolver-rules=MAP * ~NOTFOUND', '--remote-debugging-port=0',
    '--user-data-dir=' + str(profile), 'about:blank'], start_new_session=True,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
native = psutil.Process(proc.pid)
record['native'] = [native.pid, native.create_time()]
journal.write(sid, record)
print(json.dumps(record), flush=True)
os._exit(0)
'''
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(Path.cwd()), env.get('PYTHONPATH', '')])
    child = await asyncio.to_thread(subprocess.run,
        [sys.executable, '-c', child_code, chrome, str(journal.root), sid],
        capture_output=True, text=True, timeout=15, env=env, check=True)
    record = json.loads(child.stdout)
    identity = tuple(record['native'])
    try:
        assert browser_identity_alive(identity)
        assert await journal.reap_entry(journal._file(sid)) is True
        assert not browser_identity_alive(identity)
        assert not Path(record['profile']).exists()
        assert not journal._file(sid).exists()
    finally:
        if browser_identity_alive(identity):
            process = psutil.Process(identity[0])
            for item in reversed([process, *process.children(recursive=True)]):
                with contextlib.suppress(psutil.Error):
                    item.kill()
        with contextlib.suppress(OSError):
            import shutil
            shutil.rmtree(record['profile'])
        journal.remove(sid)


async def test_session_idle_reaper_closes_native_chrome(browser_rig, monkeypatch):
    from agents.core import browser_session

    rig = browser_rig
    monkeypatch.setattr(browser_session, 'IDLE_SECONDS', 0.2)
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    identity = rig.runtime.sessions[sid].driver.owned_browser_identity
    profile = rig.runtime.sessions[sid].driver.profile_dir
    async with asyncio.timeout(10):
        while (sid in rig.runtime.sessions or profile.exists()
               or browser_identity_alive(identity)):
            await asyncio.sleep(0.05)
    assert not browser_identity_alive(identity)
    assert not profile.exists()
    assert not rig.runtime.journal._file(sid).exists()


async def test_owner_close_cancels_active_session_before_ref_dispatch(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    session = rig.runtime.sessions[sid]
    identity = session.driver.owned_browser_identity
    profile = session.driver.profile_dir
    ref = next(item['ref'] for item in started['trace'][1]['result']['refs']
               if item['name'] == 'Click')
    entered = asyncio.Event()
    original = session.driver._ref_resolver

    async def paused(ref_value, action):
        entered.set()
        await asyncio.Event().wait()
        return await original(ref_value, action)

    session.driver._ref_resolver = paused
    proposal = await rig.orch.tool_rpc.handle({'tool': 'browser_run', 'args': {
        'mode': 'act', 'session_id': sid, 'steps': [{'action': 'click', 'ref': ref}]}})
    assert proposal['reason'] == 'approval_required', proposal
    await rig.worker.apply_decision(proposal['task_id'], 'accept', decided_by='andrei')
    running = asyncio.create_task(rig.worker.tick())
    await asyncio.wait_for(entered.wait(), 10)
    assert await asyncio.wait_for(rig.runtime.close_owner_session(sid), 15)
    with contextlib.suppress(asyncio.CancelledError):
        await running
    assert rig.page.state['clicked'] == 0
    assert not browser_identity_alive(identity)
    assert not profile.exists() and not rig.runtime.journal._file(sid).exists()


async def test_authenticated_owner_session_projection_and_close(browser_rig, monkeypatch):
    rig = browser_rig
    monkeypatch.setattr(rig.web, 'ADMIN_TOKEN', 'browser-admin')
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/'}, {'action': 'snapshot'},
    ]})
    sid = started['session_id']
    profile = rig.runtime.sessions[sid].driver.profile_dir
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                     base_url='http://testserver',
                                     headers={'X-User-Token': 'browser-user'}) as user:
            assert (await user.get('/api/browser/status')).status_code == 200
            assert (await user.get('/api/browser/sessions')).status_code == 401
            assert (await user.get('/api/browser/tasks/1')).status_code == 401
            assert (await user.post(f'/api/browser/sessions/{sid}/close', json={})).status_code == 401
            assert sid in rig.runtime.sessions
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                     base_url='http://testserver',
                                     headers={'X-Admin-Token': 'browser-admin'}) as owner:
            listing = await owner.get('/api/browser/sessions')
            assert listing.status_code == 200
            row = next(item for item in listing.json()['sessions'] if item['id'] == sid)
            assert row['origin'] == rig.page.origin and row['refs']
            assert 'profile' not in row and 'owner' not in row
            closed = await owner.post(f'/api/browser/sessions/{sid}/close', json={})
            assert closed.status_code == 200 and closed.json()['closed'] is True
            assert (await owner.get('/api/browser/sessions')).json()['sessions'] == []
    finally:
        if sid in rig.runtime.sessions:
            await rig.runtime.close_owner_session(sid)
    assert not profile.exists()


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
    assert rig.runtime.last_browser_identity is None


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
    assert rig.runtime.last_browser_identity is not None
    assert not browser_identity_alive(rig.runtime.last_browser_identity)
    assert browser_processes_for_profile(rig.runtime.last_profile) == []


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
    assert rig.runtime.last_browser_identity is not None
    assert not browser_identity_alive(rig.runtime.last_browser_identity)
    assert browser_processes_for_profile(rig.runtime.last_profile) == []


async def test_cleanup_uncertainty_changes_live_status_and_recovers(browser_rig):
    from agents.core.operator_router import _browser_available

    rig = browser_rig
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rig.web.app),
                                 base_url='http://testserver',
                                 headers={'X-User-Token': 'browser-user'}) as client:
        assert (await client.get('/api/browser/status')).json() == {'available': True}
        marker = object()
        rig.runtime._uncertain_drivers.append(marker)
        assert (await client.get('/api/browser/status')).json() == {'available': False}
        assert _browser_available(rig.orch) is False
        rig.runtime._uncertain_drivers.remove(marker)
        assert (await client.get('/api/browser/status')).json() == {'available': True}
        assert _browser_available(rig.orch) is True


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
    assert rig.runtime.last_browser_identity is not None
    assert not browser_identity_alive(rig.runtime.last_browser_identity)
    assert browser_processes_for_profile(rig.runtime.last_profile) == []


async def test_session_chromium_blocks_websocket_before_fixture_handshake(browser_rig):
    rig = browser_rig
    started = await _approved_session_call(rig, {'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': rig.page.origin + '/websocket'},
        {'action': 'wait', 'timeout_ms': 500},
    ]})
    assert started['ok'] is True, started
    sid = started['session_id']
    driver = rig.runtime.sessions[sid].driver
    assert await driver._page.evaluate('document.documentElement.dataset.socketProbe') == 'started'
    assert await driver._page.evaluate('window.__socketProbe instanceof WebSocket') is True
    assert rig.page.state['websocket_handshakes'] == 0
    assert await rig.runtime.close_owner_session(sid)
    assert not browser_identity_alive(rig.runtime.last_browser_identity)


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
    assert rig.runtime.last_browser_identity is None
