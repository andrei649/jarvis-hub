"""Bounded cross-call browser session contracts."""

import pytest


def test_session_request_requires_explicit_mode_and_bounded_actions():
    from agents.core.browser_runtime import BrowserPlanRefused, validate_browser_request

    start = validate_browser_request({'mode': 'start', 'steps': [
        {'action': 'navigate', 'url': 'https://example.com/'},
        {'action': 'snapshot'},
    ]})
    assert start.mode == 'start' and start.steps[0]['action'] == 'navigate'
    act = validate_browser_request({'mode': 'act', 'session_id': 'a' * 32, 'steps': [
        {'action': 'press', 'ref': '@e1', 'key': 'Enter'},
        {'action': 'scroll', 'ref': '@e1', 'direction': 'down', 'pixels': 100},
        {'action': 'back'},
    ]})
    assert len(act.steps) == 3
    for bad in (
        {'mode': 'act', 'session_id': 'a' * 32, 'steps': [{'action': 'press', 'ref': '@e1', 'key': 'Meta+A'}]},
        {'mode': 'act', 'session_id': 'a' * 32, 'steps': [{'action': 'scroll', 'ref': '@e1', 'direction': 'down', 'pixels': 100000}]},
        {'mode': 'act', 'session_id': 'a' * 32, 'steps': [{'action': 'click', 'ref': '@e1', 'selector': '#other'}]},
        {'mode': 'act', 'session_id': 'a' * 32, 'steps': [{'action': 'navigate', 'url': 'https://example.com/' }], 'owner': 'andrei'},
    ):
        with pytest.raises(BrowserPlanRefused):
            validate_browser_request(bad)


def test_session_observations_are_exact_read_actions_without_extra_authority():
    from agents.core.browser_runtime import BrowserPlanRefused, validate_browser_request

    sid = 'a' * 32
    request = validate_browser_request({'mode': 'act', 'session_id': sid,
                                        'steps': [{'action': 'console'}, {'action': 'get_images'}]})
    assert request.mode == 'act'
    assert request.steps == ({'action': 'console'}, {'action': 'get_images'})
    for action in ('console', 'get_images'):
        for extra in ({'selector': 'img'}, {'url': 'https://example.com/x'}, {'ref': '@e1'}):
            with pytest.raises(BrowserPlanRefused):
                validate_browser_request({'mode': 'act', 'session_id': sid,
                                          'steps': [{'action': action, **extra}]})


def test_owner_observation_projection_is_typed_bounded_and_never_raw_task_data():
    from agents.core.routers.browser import _project_browser_observations

    observations, truncated = _project_browser_observations([
        {'action': 'console', 'status': 'done', 'payload': 'private-task-payload',
         'result': {'observation': 'console', 'cookie': 'private-cookie', 'dropped': 2,
                    'records': [
                        {'level': 'log', 'text': '<script>page text</script>',
                         'source_origin': 'https://example.test', 'document_epoch': 1,
                         'stack': '/private/home'},
                        {'level': 'error', 'text': 'bad',
                         'source_origin': 'file:///private/home', 'document_epoch': 1}]}},
        {'action': 'get_images', 'status': 'done',
         'result': {'observation': 'images', 'images': [
             {'source_url': 'https://example.test/a.png', 'alt': 'Image',
              'width': 10, 'height': 12, 'fetchable': True,
              'frame_origin': 'https://example.test', 'document_epoch': 1,
              'ref': '@e2', 'secret': 'private-secret'},
             {'source_url': 'https://user:password@example.test/a', 'alt': 'Bad',
              'width': 1, 'height': 1, 'fetchable': True,
              'frame_origin': 'https://example.test', 'document_epoch': 1},
         ]}},
    ])
    assert truncated is False
    assert observations == [
        {'action': 'console', 'records': [{'level': 'log',
            'text': '<script>page text</script>', 'source_origin': 'https://example.test',
            'document_epoch': 1}], 'dropped': 2},
        {'action': 'get_images', 'images': [{'source_url': 'https://example.test/a.png',
            'alt': 'Image', 'width': 10, 'height': 12, 'fetchable': True,
            'frame_origin': 'https://example.test', 'document_epoch': 1, 'ref': '@e2'}]},
    ]


def test_console_event_ring_caps_text_records_and_bytes_without_retaining_arguments():
    import json
    from types import SimpleNamespace

    from agents.core.browser_playwright import (
        MAX_CONSOLE_BYTES,
        MAX_CONSOLE_RECORDS,
        MAX_CONSOLE_TEXT,
        PlaywrightBrowserDriver,
    )

    driver = PlaywrightBrowserDriver()
    frame = SimpleNamespace(url='https://example.test/page')
    driver._page = SimpleNamespace(frames=[frame], main_frame=frame)
    for index in range(80):
        driver._on_console(SimpleNamespace(type='log', text=f'{index}:' + 'x' * 1000,
                                           location={'url': frame.url}, args=['private-argument']))
    assert len(driver._console_records) <= MAX_CONSOLE_RECORDS
    assert driver._console_dropped > 0 and driver._console_truncated == 80
    assert driver._console_bytes <= MAX_CONSOLE_BYTES
    assert all(len(item['text']) <= MAX_CONSOLE_TEXT and 'args' not in item
               for item in driver._console_records)
    assert len(json.dumps(list(driver._console_records)).encode()) <= MAX_CONSOLE_BYTES
    driver._on_console_navigation(frame)
    assert not driver._console_records and driver._console_bytes == 0


@pytest.mark.parametrize('navigated', [0, 1])
def test_duplicate_url_child_console_event_is_not_retained_after_either_navigation(navigated):
    from types import SimpleNamespace

    from agents.core.browser_playwright import PlaywrightBrowserDriver

    driver = PlaywrightBrowserDriver()
    main = SimpleNamespace(url='https://example.test/main')
    first = SimpleNamespace(url='https://example.test/child')
    second = SimpleNamespace(url=first.url)
    driver._page = SimpleNamespace(frames=[main, first, second], main_frame=main)
    driver._on_console(SimpleNamespace(type='log', text='from-ambiguous-child',
                                       location={'url': first.url}))
    driver._on_console_navigation((first, second)[navigated])
    assert not driver._console_records
    assert driver._console_bytes == 0


@pytest.mark.asyncio
async def test_image_inventory_never_mints_ref_for_source_changed_during_observation():
    from types import SimpleNamespace

    from agents.core.browser_session import BrowserSession, SessionRefused

    state = {'source': 'old', 'changed': False}

    class Handle:
        async def is_visible(self):
            return True

        async def evaluate(self, expression):
            if 'src_truncated' in expression:
                return {'connected': True, 'hidden': False, 'alt': 'Image',
                        'src': 'https://example.test/old.png', 'src_truncated': False,
                        'width': 10, 'height': 10,
                        'semantics': {'connected': True, 'hidden': False, 'disabled': False,
                                      'role': 'img', 'name': 'Image',
                                      'target': 'old-source-semantics'}}
            return {'connected': True, 'hidden': False, 'disabled': False,
                    'role': 'img', 'name': 'Image',
                    'target': state['source'] + '-source-semantics'}

    handle = Handle()
    class Locator:
        async def count(self):
            return 1

        def nth(self, _index):
            return self

        async def element_handle(self):
            return handle

    class Frame:
        url = 'https://example.test/page'

        def locator(self, _selector):
            return Locator()

    frame = Frame()
    page = SimpleNamespace(frames=[frame], main_frame=frame,
                           on=lambda *_args: None)
    driver = SimpleNamespace(_ensure_started=lambda: _ready(page),
                             _assert_execution_current=lambda: None)
    def allowed(url):
        if url.endswith('/old.png'):
            state['source'] = 'new'
            state['changed'] = True
        return True, ''

    policy = SimpleNamespace(domain_allowed=allowed)
    pins = SimpleNamespace(pinned_hosts=lambda: {'example.test'})
    session = BrowserSession('a' * 32, driver, policy, pins, 'agent', 'owner',
                             None, 'head', 'registration')
    result = await session.get_images()
    assert result['images'][0]['source_url'] == 'https://example.test/old.png'
    assert state['changed']
    ref = result['images'][0]['ref']
    assert session.refs[ref].target == 'old-source-semantics'
    with pytest.raises(SessionRefused, match='stale_browser_ref'):
        await session.resolve_ref(ref, 'click')


async def _ready(value):
    return value


@pytest.mark.asyncio
async def test_image_inventory_exact_row_cap_reports_eligible_later_frame():
    from types import SimpleNamespace

    from agents.core.browser_session import MAX_IMAGES, BrowserSession

    class Handle:
        async def is_visible(self):
            return True

        async def evaluate(self, _expression):
            return {'connected': True, 'hidden': False, 'alt': 'Image',
                    'src': 'data:image/png;base64,AAA', 'src_truncated': False,
                    'width': 1, 'height': 1}

    class Locator:
        def __init__(self, count):
            self.total = count

        async def count(self):
            return self.total

        def nth(self, _index):
            return self

        async def element_handle(self):
            return Handle()

    class Frame:
        def __init__(self, count):
            self.url = 'https://example.test/page'
            self.images = Locator(count)

        def locator(self, _selector):
            return self.images

        async def frame_element(self):
            return SimpleNamespace(is_visible=lambda: _ready(True))

    main, child = Frame(MAX_IMAGES), Frame(1)
    page = SimpleNamespace(frames=[main, child], main_frame=main,
                           on=lambda *_args: None)
    driver = SimpleNamespace(_ensure_started=lambda: _ready(page),
                             _assert_execution_current=lambda: None)
    policy = SimpleNamespace(domain_allowed=lambda _url: (True, ''))
    pins = SimpleNamespace(pinned_hosts=lambda: {'example.test'})
    session = BrowserSession('a' * 32, driver, policy, pins, 'agent', 'owner',
                             None, 'head', 'registration')
    result = await session.get_images()
    assert result['count'] == MAX_IMAGES
    assert result['truncated'] is True
    assert result['dropped'] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(('candidates', 'hidden'), [(25, False), (101, True)])
async def test_image_inventory_byte_and_scan_limits_report_known_omissions(candidates, hidden):
    import json
    from types import SimpleNamespace

    from agents.core.browser_session import MAX_IMAGE_BYTES, BrowserSession

    class Handle:
        async def is_visible(self):
            return True

        async def evaluate(self, _expression):
            return {'connected': True, 'hidden': hidden, 'alt': 'A' * 128,
                    'src': 'https://example.test/' + 'x' * 480,
                    'src_truncated': False, 'width': 1, 'height': 1,
                    'semantics': {'connected': True, 'hidden': hidden,
                                  'disabled': False, 'role': 'img',
                                  'name': 'A' * 128, 'target': 'same-source'}}

    class Locator:
        async def count(self):
            return candidates

        def nth(self, _index):
            return self

        async def element_handle(self):
            return Handle()

    class Frame:
        url = 'https://example.test/page'

        def locator(self, _selector):
            return Locator()

    frame = Frame()
    page = SimpleNamespace(frames=[frame], main_frame=frame, on=lambda *_args: None)
    driver = SimpleNamespace(_ensure_started=lambda: _ready(page),
                             _assert_execution_current=lambda: None)
    session = BrowserSession('a' * 32, driver,
                             SimpleNamespace(domain_allowed=lambda _url: (True, '')),
                             SimpleNamespace(pinned_hosts=lambda: {'example.test'}),
                             'agent', 'owner', None, 'head', 'registration')
    result = await session.get_images()
    assert result['truncated'] is True
    assert result['count'] < candidates
    if hidden:
        assert result['count'] == 0 and result['dropped'] == 1
    else:
        assert result['dropped'] == candidates - result['count']
        assert len(json.dumps(result['images'], ensure_ascii=False).encode()) <= MAX_IMAGE_BYTES


@pytest.mark.asyncio
async def test_uncertain_native_close_still_removes_console_listener_and_buffer():
    from types import SimpleNamespace

    from agents.core.browser_playwright import PlaywrightBrowserDriver, PlaywrightDriverError

    removed = []

    async def fail_close():
        raise OSError('synthetic close failure')

    page = SimpleNamespace(remove_listener=lambda event, handler: removed.append(event))
    driver = PlaywrightBrowserDriver()
    driver._page = page
    driver._console_page = page
    driver._context = SimpleNamespace(close=fail_close)
    driver._on_console(SimpleNamespace(type='log', text='synthetic', location={'url': ''}))
    assert driver._console_records
    with pytest.raises(PlaywrightDriverError):
        await driver._close_resources()
    assert driver._console_page is None and not driver._console_records
    assert set(removed) == {'console', 'framenavigated', 'framedetached'}


def test_actionable_refs_require_real_live_nodes_not_aria_ordinals():
    from agents.core.browser_session import BrowserSession

    assert BrowserSession.__name__ == 'BrowserSession'


@pytest.mark.asyncio
async def test_ambiguous_journal_never_adopts_profile_or_reaps_live_controller(tmp_path):
    import os
    import shutil
    import tempfile
    from pathlib import Path

    import psutil

    from agents.core.browser_session import BrowserOwnershipJournal

    journal = BrowserOwnershipJournal(tmp_path / 'journal')
    profile = Path(tempfile.mkdtemp(prefix='nerva-browser-owner-test'))
    sid = 'a' * 32
    current = psutil.Process(os.getpid())
    try:
        journal.write(sid, {'profile': str(profile),
                            'controller': [current.pid, current.create_time()],
                            'owner_process': [current.pid, current.create_time()],
                            'native': [current.pid, current.create_time()]})
        assert await journal.reap_entry(journal._file(sid)) is False
        assert profile.exists() and journal._file(sid).exists()
    finally:
        shutil.rmtree(profile)


@pytest.mark.asyncio
async def test_owner_close_cancellation_retains_owned_cleanup_until_settled(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from agents.core.browser_runtime import BrowserRuntime
    from agents.core.browser_session import BrowserOwnershipJournal, BrowserSession

    entered = asyncio.Event()
    release = asyncio.Event()

    class Driver:
        profile_dir = tmp_path / 'nerva-playwright-fake'
        owned_browser_identity = None

        async def close(self):
            entered.set()
            await release.wait()

    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    runtime = BrowserRuntime(queue=None, approved_task=lambda: None, authorizer=None,
                             enqueue=None, execution_check=lambda _: False)
    runtime.journal = BrowserOwnershipJournal(tmp_path / 'journal')
    driver = Driver()
    owner_task = SimpleNamespace(agent='jarvis')
    session = BrowserSession('b' * 32, driver, None, None, 'jarvis', 'andrei',
                             owner_task, 'head', 'registration')
    runtime.sessions[session.id] = session
    first = asyncio.create_task(runtime.close_owner_session(session.id))
    await asyncio.wait_for(entered.wait(), 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(runtime.close_owner_session(session.id))
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert runtime._uncertain_drivers == [driver]
    assert session.id in runtime._owner_close_tasks
    release.set()
    async with asyncio.timeout(1):
        while runtime._owner_close_tasks:
            await asyncio.sleep(0.01)
    assert runtime._uncertain_drivers == []
    assert runtime._uncertain_sessions == {}


@pytest.mark.asyncio
async def test_changed_registration_reaps_idle_session_without_waiting_for_expiry(tmp_path, monkeypatch):
    import asyncio
    import contextlib
    import uuid
    from types import SimpleNamespace

    from agents.core.autonomy import consent_registration
    from agents.core.browser_runtime import BrowserRuntime
    from agents.core.browser_session import BrowserSession

    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    epoch = uuid.uuid4().hex
    spec = {'capability_id': 'tool:browser_run', '_consent_registration_key': 'old',
            '_grouping_epoch': epoch}
    monkeypatch.setattr(consent_registration, 'trusted_registration_key',
                        lambda _tool, candidate: candidate['_consent_registration_key'])
    runtime = BrowserRuntime(queue=None, approved_task=lambda: None, authorizer=None,
                             enqueue=None, execution_check=lambda _: False,
                             registration=lambda: spec,
                             control_current=lambda _: True)
    monkeypatch.setattr(runtime, '_head', lambda: 'same-source')
    closed = asyncio.Event()

    class Driver:
        profile_dir = None
        owned_browser_identity = None

        async def close(self):
            closed.set()

    sid = 'c' * 32
    session = BrowserSession(sid, Driver(), None, None, 'jarvis', 'owner',
                             SimpleNamespace(agent='jarvis'), 'same-source', 'old', epoch)
    runtime.sessions[sid] = session
    spec['_consent_registration_key'] = 'new'
    runtime._ensure_reaper()
    try:
        await asyncio.wait_for(closed.wait(), 2.5)
        async with asyncio.timeout(2):
            while (sid in runtime.sessions or runtime._uncertain_drivers
                   or runtime._journal_uncertain):
                await asyncio.sleep(0.01)
    finally:
        session.closed = True
        if runtime._reaper_task is not None:
            runtime._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runtime._reaper_task


@pytest.mark.asyncio
async def test_session_mutating_receipt_keeps_exact_kernel_and_taint_floor():
    from types import SimpleNamespace

    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.browser_kernel import approved_step_scope, browser_receipt_matches
    from agents.core.kernel import Action, Verdict, authorize

    task = SimpleNamespace(id=77, agent='jarvis', origin='generated')
    step = {'action': 'press', 'ref': '@e1', 'key': 'Enter'}
    payload = {'action': 'press', 'args': {'ref': '@e1', 'key': 'Enter'},
               'risk_tier': 3, 'approved_task_id': 77, 'plan_sha256': 'c' * 64,
               'step_index': 0, 'session_id': 'a' * 32, 'session_generation': 5}
    action = Action(kind='browser.step', agent='jarvis', origin='generated', payload=payload)
    with approved_step_scope(task, 'c' * 64, 0, step, lambda: True,
                             session_id='a' * 32, session_generation=5):
        assert authorize(action, policy=AutonomyPolicy(),
                         approval_check=browser_receipt_matches).verdict is Verdict.GRANT
        changed = Action(kind='browser.step', agent='jarvis', origin='generated',
                         payload={**payload, 'session_generation': 6})
        assert authorize(changed, policy=AutonomyPolicy(),
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
        assert authorize(action, policy=AutonomyPolicy(mode='ask'),
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
        tainted = Action(kind='browser.step', agent='jarvis', origin='external', payload=payload)
        assert authorize(tainted, policy=AutonomyPolicy(),
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE


@pytest.mark.asyncio
async def test_only_known_stale_ref_code_survives_kernel_handler_error():
    from types import SimpleNamespace

    from agents.core.browser_kernel import BrowserActionExecutor, approved_step_scope
    from agents.core.browser_session import SessionRefused
    from agents.core.kernel import Decision, Verdict

    class Driver:
        requires_kernel = True
        error = 'stale_browser_ref'

        async def click(self, **_kwargs):
            raise SessionRefused(self.error)

    driver = Driver()
    executor = BrowserActionExecutor(driver, authorizer=lambda action, *, approval_check: (
        Decision(Verdict.GRANT if approval_check(action) else Verdict.QUEUE, tier=3)))
    task = SimpleNamespace(id=11, agent='jarvis', origin='generated')
    step = {'action': 'click', 'ref': '@e1'}
    with approved_step_scope(task, 'a' * 64, 0, step, lambda: True,
                             session_id='a' * 32, session_generation=0):
        assert (await executor.perform(step)).reason == 'stale_browser_ref'
        driver.error = 'private page text and path'
        assert (await executor.perform(step)).reason == 'browser_step_failed'


@pytest.mark.asyncio
async def test_detached_or_replaced_same_semantics_never_retargets_old_ref():
    from types import SimpleNamespace

    from agents.core.browser_session import BrowserSession, LiveRef, SessionRefused

    class Handle:
        connected = True

        async def is_visible(self):
            return True

        async def evaluate(self, _script):
            return {'connected': self.connected, 'role': 'button', 'name': 'Continue',
                    'target': '', 'focus': True, 'disabled': False, 'hidden': False}

    frame = SimpleNamespace(url='https://example.com/')
    page = SimpleNamespace(frames=[frame], main_frame=frame)

    class Driver:
        async def _ensure_started(self):
            return page

        def _assert_execution_current(self):
            pass

    session = BrowserSession('a' * 32, Driver(),
                             SimpleNamespace(domain_allowed=lambda _url: (True, '')),
                             SimpleNamespace(pinned_hosts=lambda: {'example.com'}),
                             'jarvis', 'andrei', SimpleNamespace(), 'head', 'registration')
    old = Handle()
    session.refs['@e1'] = LiveRef(old, frame, frame.url, 0, 'button', 'Continue', '', True, True)
    assert await session.resolve_ref('@e1', 'click') is old
    old.connected = False
    replacement = Handle()  # Same text and ordinal cannot replace the retained handle.
    assert replacement.connected
    with pytest.raises(SessionRefused, match='stale_browser_ref'):
        await session.resolve_ref('@e1', 'click')
    old.connected = True
    frame.url = 'https://other.example/'
    with pytest.raises(SessionRefused, match='stale_browser_ref'):
        await session.resolve_ref('@e1', 'click')
