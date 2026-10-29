"""Native dialog supervision keeps frame evidence separate from page text."""
from __future__ import annotations

import asyncio
import contextvars
from types import SimpleNamespace

import pytest

from agents.core.browser_dialogs import (
    DialogFrameObserver,
    DialogPromptStore,
    run_with_dialog_supervisor,
)
from agents.core.browser_playwright import PlaywrightBrowserDriver


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
                                payload={'tool': 'browser_dialog', 'args': safe})
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
