"""Native dialog supervision keeps frame evidence separate from page text."""
from __future__ import annotations

import asyncio
import contextvars
import threading
from types import SimpleNamespace

import pytest

from agents.core.autonomy.queue import TaskStatus
from agents.core.browser_dialogs import (
    DialogEpisode,
    DialogFrameObserver,
    DialogPromptStore,
    run_with_dialog_supervisor,
)
from agents.core.browser_kernel import (
    approved_dialog_scope,
    authorize_dialog_response,
    physical_browser_dialog_allowed,
)
from agents.core.browser_playwright import PlaywrightBrowserDriver
from agents.core.browser_runtime import BrowserRuntime
from agents.core.kernel import Decision, Verdict


def test_same_url_child_dialog_is_not_admitted_as_main_frame():
    page = object()
    observer = DialogFrameObserver(page=page)
    observer.arm(root_frame_id='main-1', loader_id='load-1',
                 frame_url='http://fixture.browser.test/page', document_epoch=3)
    observer.on_cdp_open({'frameId': 'child-2', 'url': 'http://fixture.browser.test/page',
                          'type': 'alert', 'message': 'same message'})
    observer.on_playwright_dialog(SimpleNamespace(page=page, type='alert',
                                                   message='same message', default_value=''))
    assert observer.pending() is None
    assert observer.refused_reason == 'dialog_frame_unknown'


def test_navigation_without_modal_disarms_without_false_dialog_failure():
    observer = DialogFrameObserver(page=object())
    observer.arm(root_frame_id='root', loader_id='loader',
                 frame_url='http://fixture.browser.test/old', document_epoch=1)
    observer.invalidate()
    assert observer.pending() is None and observer.refused_reason == ''
    assert not observer.ready.is_set()


def test_main_frame_alert_pairs_with_exact_playwright_object():
    page = object()
    dialog = SimpleNamespace(page=page, type='alert', message='hello', default_value='')
    observer = DialogFrameObserver(page=page)
    observer.arm(root_frame_id='main-1', loader_id='load-1',
                 frame_url='http://fixture.browser.test/page', document_epoch=3)
    observer.on_cdp_open({'frameId': 'main-1', 'url': 'http://fixture.browser.test/page',
                          'type': 'alert', 'message': 'hello'})
    observer.on_playwright_dialog(dialog)
    pending = observer.pending()
    assert pending is not None
    assert pending.dialog is dialog
    assert pending.frame_id == 'main-1'
    assert pending.loader_id == 'load-1'
    assert pending.document_epoch == 3


def test_dialog_pair_outside_short_native_event_window_refuses():
    page = object()
    observer = DialogFrameObserver(page=page)
    observer.arm(root_frame_id='root', loader_id='loader',
                 frame_url='http://fixture.browser.test/page', document_epoch=1)
    observer.on_cdp_open({'frameId': 'root', 'url': 'http://fixture.browser.test/page',
                          'type': 'alert', 'message': 'same'})
    observer._cdp_at -= 2
    observer.on_playwright_dialog(SimpleNamespace(page=page, type='alert',
                                                   message='same', default_value=''))
    assert observer.pending() is None and observer.refused_reason


@pytest.mark.asyncio
async def test_cancelled_settlement_retains_one_durable_unknown_outcome():
    started, release = threading.Event(), threading.Event()
    calls = []

    def transition(*args, **kwargs):
        started.set()
        assert release.wait(5)
        calls.append((args, kwargs))

    runtime = object.__new__(BrowserRuntime)
    runtime.queue = SimpleNamespace(transition=transition,
                                    execution_fingerprint=lambda _task: 'fp')
    runtime._dialog_settlements = set()
    runtime._dialog_settlement_failed = False
    episode = SimpleNamespace(claimed_task=SimpleNamespace(id=27))
    settling = asyncio.create_task(runtime._settle_dialog(episode, success=False))
    assert await asyncio.to_thread(started.wait, 2)
    settling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await settling
    assert len(runtime._dialog_settlements) == 1
    release.set()
    await asyncio.wait_for(episode.settlement_task, 5)
    await asyncio.sleep(0)
    assert not runtime._dialog_settlements
    assert not runtime._dialog_settlement_failed
    assert calls == [((27, TaskStatus.FAILED), {
        'result': {'reason': 'dialog_outcome_unknown', 'possibly_applied': True},
        'expected_status': TaskStatus.RUNNING,
        'expected_execution_sha256': 'fp'})]


@pytest.mark.asyncio
async def test_driver_installs_internal_cdp_and_playwright_observers_before_operation():
    class Events:
        def __init__(self):
            self.handlers = {}

        def on(self, event, handler):
            self.handlers[event] = handler

        def remove_listener(self, event, _handler):
            self.handlers.pop(event, None)

        def emit(self, event, value):
            self.handlers[event](value)

    class Cdp(Events):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.detached = False

        async def send(self, command):
            self.calls.append(command)
            if command == 'Page.getFrameTree':
                return {'frameTree': {'frame': {'id': 'main-1', 'loaderId': 'load-1',
                                                'url': 'http://fixture.browser.test/page'}}}
            return {}

        async def detach(self):
            self.detached = True

    class Context:
        def __init__(self, cdp):
            self.cdp = cdp

        async def new_cdp_session(self, _page):
            return self.cdp

    page, cdp = Events(), Cdp()
    driver = PlaywrightBrowserDriver(host_enabled=True)
    driver._page = page
    driver._context = Context(cdp)
    observer = await driver.start_dialog_observer()
    assert cdp.calls == ['Page.enable', 'Page.getFrameTree']
    await driver.arm_dialog_observer(document_epoch=0)
    dialog = SimpleNamespace(page=page, type='alert', message='hello', default_value='')
    cdp.emit('Page.javascriptDialogOpening', {
        'frameId': 'main-1', 'url': 'http://fixture.browser.test/page',
        'type': 'alert', 'message': 'hello',
    })
    page.emit('dialog', dialog)
    assert observer.pending().dialog is dialog
    await driver.stop_dialog_observer()
    assert cdp.detached is True
    assert 'dialog' not in page.handlers


@pytest.mark.asyncio
async def test_opening_stays_in_parent_task_and_empty_context_child_unblocks_it():
    step_permit = contextvars.ContextVar('step_permit', default=None)
    token = step_permit.set('parent-only')
    parent = asyncio.current_task()
    opening_started = asyncio.Event()
    release = asyncio.Event()
    page = object()
    observer = DialogFrameObserver(page=page)
    observer.arm(root_frame_id='main', loader_id='load',
                 frame_url='http://fixture.browser.test/page', document_epoch=0)

    async def opening():
        assert asyncio.current_task() is parent
        assert step_permit.get() == 'parent-only'
        opening_started.set()
        await release.wait()
        return 'opened'

    async def respond(pending):
        assert asyncio.current_task() is not parent
        assert step_permit.get() is None
        assert pending.kind == 'alert'
        release.set()

    try:
        call = asyncio.create_task(run_with_dialog_supervisor(opening, observer, respond),
                                   context=contextvars.copy_context())
        # The created call is the true opener task; never hand its receipt to a child.
        parent = call
        await asyncio.wait_for(opening_started.wait(), 1)
        dialog = SimpleNamespace(page=page, type='alert', message='hi', default_value='')
        observer.on_cdp_open({'frameId': 'main', 'url': 'http://fixture.browser.test/page',
                              'type': 'alert', 'message': 'hi'})
        observer.on_playwright_dialog(dialog)
        assert await asyncio.wait_for(call, 1) == 'opened'
    finally:
        step_permit.reset(token)


def test_prompt_store_binds_exact_sanitized_task_and_consumes_once():
    tasks = {}
    store = DialogPromptStore(task_lookup=tasks.get,
                              task_fingerprint=lambda task: task.fingerprint)
    lease = store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'a' * 32,
                                   'choice': 'accept', 'prompt_text': 'private-marker'})
    safe = lease.args
    assert 'private-marker' not in repr(safe)
    assert safe['prompt_length'] == len('private-marker')
    assert len(safe['prompt_digest']) == 64
    ref = safe['prompt_ref']
    tasks[23] = SimpleNamespace(kind='toolrpc.browser_dialog', agent='agent-a',
                                status='proposed', fingerprint='fingerprint-a',
                                payload={'tool': 'browser_dialog', 'target': 'browser_dialog',
                                         'args': safe})
    lease.bind(23)
    lease.release()
    assert store.peek(ref, task_id=23, fingerprint='fingerprint-a', agent='agent-b') is None
    assert store.peek(ref, task_id=23, fingerprint='fingerprint-a', agent='agent-a') == 'private-marker'
    assert store.consume(ref, task_id=23, fingerprint='fingerprint-a', agent='agent-a') == 'private-marker'
    assert store.consume(ref, task_id=23, fingerprint='fingerprint-a', agent='agent-a') is None


def test_prompt_store_wipes_failed_unbound_proposal_and_rejects_changed_row():
    tasks = {}
    store = DialogPromptStore(task_lookup=tasks.get,
                              task_fingerprint=lambda task: task.fingerprint)
    lease = store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'b' * 32,
                                   'choice': 'accept', 'prompt_text': 'private-marker'})
    ref = lease.args['prompt_ref']
    tasks[23] = SimpleNamespace(kind='toolrpc.browser_dialog', agent='agent-a',
                                status='proposed', fingerprint='fingerprint-a',
                                payload={'tool': 'browser_dialog', 'args': {
                                    **lease.args, 'choice': 'dismiss'}})
    with pytest.raises(ValueError, match='dialog_task_changed'):
        lease.bind(23)
    lease.release()
    assert store.peek(ref, task_id=23, fingerprint='fingerprint-a', agent='agent-a') is None


def test_prompt_store_binds_server_fields_and_notifies_exact_row():
    tasks = {}
    notified = []
    store = DialogPromptStore(task_lookup=tasks.get,
                              task_fingerprint=lambda task: task.fingerprint,
                              on_bind=lambda args, task_id: notified.append((args, task_id)))
    lease = store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'a' * 32,
                                   'choice': 'accept', 'prompt_text': 'private-marker'},
                       binding={'opener_fingerprint': 'f' * 64, 'session_id': 's' * 32})
    safe = lease.args
    tasks[23] = SimpleNamespace(kind='toolrpc.browser_dialog', agent='agent-a',
                                status='proposed', fingerprint='fingerprint-a',
                                payload={'tool': 'browser_dialog', 'target': 'browser_dialog',
                                         'args': safe})
    lease.bind(23)
    assert notified == [(safe, 23)]
    assert store.consume(safe['prompt_ref'], task_id=23, fingerprint='fingerprint-a',
                         agent='agent-a') == 'private-marker'


def test_owner_staged_prompt_ref_can_be_proposed_once_without_raw_model_text():
    tasks = {}
    store = DialogPromptStore(task_lookup=tasks.get,
                              task_fingerprint=lambda task: task.fingerprint)
    ref = store.stage_owner_text('agent-a', 11, 'a' * 32, 'owner-only-marker')
    lease = store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'a' * 32,
                                   'choice': 'accept', 'prompt_ref': ref})
    safe = lease.args
    assert 'owner-only-marker' not in repr(safe)
    tasks[24] = SimpleNamespace(kind='toolrpc.browser_dialog', agent='agent-a',
                                status='proposed', fingerprint='f' * 64,
                                payload={'tool': 'browser_dialog', 'target': 'browser_dialog',
                                         'args': safe})
    lease.bind(24)
    assert store.consume(ref, task_id=24, fingerprint='f' * 64,
                         agent='agent-a') == 'owner-only-marker'
    with pytest.raises(ValueError):
        store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'a' * 32,
                               'choice': 'accept', 'prompt_ref': ref})


def test_dialog_close_wipes_unconsumed_private_values_only_for_that_episode():
    tasks = {}
    store = DialogPromptStore(task_lookup=tasks.get,
                              task_fingerprint=lambda task: task.fingerprint)
    first = store.stage_owner_text('agent-a', 11, 'a' * 32, 'private-a')
    second = store.stage_owner_text('agent-a', 12, 'b' * 32, 'private-b')
    store.wipe_dialog(11, 'a' * 32)
    with pytest.raises(ValueError, match='invalid_dialog_prompt'):
        store.seal('agent-a', {'opener_task_id': 11, 'dialog_id': 'a' * 32,
                               'choice': 'accept', 'prompt_ref': first})
    assert store.seal('agent-a', {'opener_task_id': 12, 'dialog_id': 'b' * 32,
                                  'choice': 'accept', 'prompt_ref': second}).args['prompt_ref'] == second


@pytest.mark.asyncio
async def test_dialog_needs_distinct_exact_kernel_receipt_in_child_task():
    dialog = object()
    response = SimpleNamespace(id=23, kind='toolrpc.browser_dialog', agent='agent-a',
                               origin='generated', payload={'args': {
                                   'opener_task_id': 11, 'opener_fingerprint': 'f' * 64,
                                   'dialog_id': 'd' * 32, 'choice': 'dismiss'}})
    opener = SimpleNamespace(id=11)
    seen = []
    def current():
        return True

    def kernel(action, *, approval_check):
        seen.append(action)
        assert approval_check(action) is True
        assert 'private-marker' not in repr(action)
        return Decision(Verdict.GRANT, 'sealed_browser_dialog_approval', tier=3)

    assert not physical_browser_dialog_allowed(dialog, 'dismiss')
    with approved_dialog_scope(response, opener, dialog, session_id='s' * 32,
                               generation=1, plan_sha256='p' * 64, step_index=2,
                               current=current):
        assert not physical_browser_dialog_allowed(dialog, 'dismiss')
        assert await authorize_dialog_response(kernel) is True
        assert len(seen) == 1 and seen[0].kind == 'browser.dialog'
        assert physical_browser_dialog_allowed(dialog, 'dismiss')
        assert not physical_browser_dialog_allowed(object(), 'dismiss')
        assert not physical_browser_dialog_allowed(dialog, 'accept')
        assert await asyncio.create_task(authorize_dialog_response(kernel)) is False
    assert not physical_browser_dialog_allowed(dialog, 'dismiss')


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', [Verdict.QUEUE, Verdict.DENY])
async def test_dialog_kernel_queue_or_denial_never_enables_physical_response(verdict):
    dialog = object()
    response = SimpleNamespace(id=23, kind='toolrpc.browser_dialog', agent='agent-a',
                               origin='generated', payload={'args': {
                                   'opener_task_id': 11, 'opener_fingerprint': 'f' * 64,
                                   'dialog_id': 'd' * 32, 'choice': 'dismiss'}})
    with approved_dialog_scope(response, SimpleNamespace(id=11), dialog,
                               session_id='s' * 32, generation=1,
                               plan_sha256='p' * 64, step_index=2,
                               current=lambda: True):
        assert await authorize_dialog_response(
            lambda _action, *, approval_check: Decision(verdict, tier=3)) is False
        assert not physical_browser_dialog_allowed(dialog, 'dismiss')


@pytest.mark.asyncio
async def test_driver_native_dialog_method_requires_exact_scope_and_is_one_use():
    class NativeDialog:
        def __init__(self):
            self.calls = []

        async def dismiss(self):
            self.calls.append(('dismiss',))

        async def accept(self, **kwargs):
            self.calls.append(('accept', kwargs))

    native = NativeDialog()
    response = SimpleNamespace(id=23, agent='agent-a', origin='generated',
                               payload={'args': {'opener_task_id': 11,
                                                 'dialog_id': 'd' * 32,
                                                 'choice': 'dismiss'}})
    driver = PlaywrightBrowserDriver(host_enabled=True)
    observed = SimpleNamespace(dialog=native, kind='alert')
    driver._dialog_observer = SimpleNamespace(pending=lambda: observed)
    assert await driver.respond_dialog(observed, 'dismiss') is False
    with approved_dialog_scope(response, SimpleNamespace(id=11), native,
                               session_id='s' * 32, generation=1,
                               plan_sha256='p' * 64, step_index=2,
                               current=lambda: True):
        assert await authorize_dialog_response(
            lambda _action, *, approval_check: Decision(Verdict.GRANT, tier=3))
        assert await driver.respond_dialog(observed, 'dismiss') is True
        assert await driver.respond_dialog(observed, 'dismiss') is False
    assert native.calls == [('dismiss',)]


def test_dialog_episode_exposes_only_bounded_pending_observation_and_expires():
    page = object()
    observer = DialogFrameObserver(page=page)
    observer.arm(root_frame_id='root', loader_id='loader',
                 frame_url='http://fixture.browser.test/page', document_epoch=1)
    episode = DialogEpisode(opener_task_id=11, opener_fingerprint='f' * 64,
                            agent='agent-a', owner='owner-a', session_id='s' * 32,
                            generation=2, plan_sha256='p' * 64, step_index=0,
                            observer=observer, expires_at=100.0)
    assert episode.pending(now=1) is None
    native = SimpleNamespace(page=page, type='prompt', message='a' * 1100,
                             default_value='default')
    observer.on_cdp_open({'frameId': 'root', 'url': 'http://fixture.browser.test/page',
                          'type': 'prompt', 'message': 'a' * 1100,
                          'defaultPrompt': 'default'})
    observer.on_playwright_dialog(native)
    assert episode.capture(now=2) is False
    assert episode.pending(now=2) is None
