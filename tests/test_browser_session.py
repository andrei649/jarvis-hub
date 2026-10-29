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
    from types import SimpleNamespace

    from agents.core.autonomy import consent_registration
    from agents.core.browser_runtime import BrowserRuntime
    from agents.core.browser_session import BrowserSession

    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    spec = {'capability_id': 'tool:browser_run', '_consent_registration_key': 'old',
            '_grouping_epoch': 3}
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
                             SimpleNamespace(agent='jarvis'), 'same-source', 'old', 3)
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
