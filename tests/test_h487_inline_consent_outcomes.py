"""Committed owner choices must reach the exact native tool which is waiting."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.routers import _deps
from agents.core.routers import autonomy as routes
from agents.core.routers._deps import admin_guard
from tests.test_h487_consent_runtime_integration import consent_runtime  # noqa: F401
from tests.test_h487_telegram_consent_integration import _tap, _telegram


def _admin_app(runtime, monkeypatch, *, current=lambda: True):
    monkeypatch.setattr(routes, 'get_orch', lambda: runtime.orch)
    web = SimpleNamespace(
        _admin_credential_ok=lambda token: current() and token == 'synthetic-inline-owner',
        _admin_configured=lambda: True,
        _real_client_host=lambda request: '127.0.0.1', _LOCALHOSTS={'127.0.0.1'},
    )
    monkeypatch.setattr(_deps, '_web', lambda: web)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    return app


async def _delivered(h, runtime):
    await h.channel._deliver_turn(-500, 42, 'Synthetic native inline request')
    await asyncio.wait_for(h.ready.wait(), 2)
    for _ in range(100):
        if any(p.message_id is not None for p in runtime.worker._consent_prompts._pending.values()):
            return runtime.q.list()[0]
        await asyncio.sleep(0.01)
    raise AssertionError('the actual native receipt was not registered')


async def _post(app, task_id, *, revision, choice, reason=None):
    body = {'revision': revision, 'choice': choice}
    if reason is not None:
        body['reason'] = reason
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic') as client:
        return await client.post(f'/autonomy/tasks/{task_id}/consent', json=body,
                                 headers={'x-admin-token': 'synthetic-inline-owner'})


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always', 'deny'])
async def test_actual_http_choice_wakes_native_inline_tool(consent_runtime, monkeypatch, choice):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch, via_model=True, model_options={
        'tool_timeout_seconds': 2, 'max_wall_seconds': 3,
    })
    app = _admin_app(runtime, monkeypatch)
    try:
        task = await _delivered(h, runtime)
        offer = runtime.q.pending_consent_offer(task.id)
        response = await _post(app, task.id, revision=offer.revision, choice=choice)
        assert response.status_code == 200 and response.json()['ok'] is True
        assert runtime.q.get(task.id).human_decision['action'] == choice
        await asyncio.sleep(0.75)
        assert h.finished.is_set(), 'committed cross-surface choice must wake its exact native tool'
        assert len(h.replies) == 1
        assert runtime.q.get(task.id).decided_by == 'admin'
        if choice == 'deny':
            assert h.replies[0]['reason'] == 'owner_denied' and not h.replies[0]['ok']
            assert runtime.q.get(task.id).status == 'rejected' and h.effects == []
        else:
            assert h.replies[0]['ok'] is True and len(h.effects) == 1
            assert runtime.q.verify_consent_terminal_result(task.id)
            await runtime.worker.tick()
            assert len(h.effects) == 1
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['silence', 'withdrawal', 'owner_revoked'])
async def test_native_inline_timeout_and_withdrawal_are_distinct_from_denial(consent_runtime, monkeypatch, ending):
    from agents.core.autonomy import consent_prompts

    runtime = consent_runtime
    monkeypatch.setattr(consent_prompts, '_REPLY_SECONDS', 0.1 if ending == 'silence' else 3)
    h = await _telegram(runtime, monkeypatch, via_model=True, model_options={
        'tool_timeout_seconds': 2, 'max_wall_seconds': 3,
    })
    try:
        task = await _delivered(h, runtime)
        if ending == 'withdrawal':
            runtime.worker._consent_prompts.stop(h.channel._owner_once_generation)
        elif ending == 'owner_revoked':
            h.settings['autonomy.owner_user_ids'] = [99]
        await asyncio.sleep(0.3)
        assert h.finished.is_set(), 'lost or expired native request must settle promptly'
        reply = h.replies[0]
        expected = 'timeout' if ending == 'silence' else 'withdrawn'
        assert reply['ok'] is False
        assert reply['reason'] == ('approval_timed_out' if ending == 'silence' else 'approval_withdrawn')
        assert reply['approval_outcome'] == expected
        assert 'denial_reason' not in reply, 'silence or withdrawal must not fabricate human denial'
        assert h.effects == [] and runtime.q.get(task.id).human_decision is None
        assert not runtime.worker._consent_prompts._pending
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_actual_http_denial_reason_reaches_waiting_tool_verbatim(consent_runtime, monkeypatch):
    from agents.core.autonomy.decision_reasons import normalize_reason

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    app = _admin_app(runtime, monkeypatch)
    reason = '  Refuz: nu executa.\nMotiv: 🧪  '
    try:
        task = await _delivered(h, runtime)
        offer = runtime.q.pending_consent_offer(task.id)
        response = await _post(app, task.id, revision=offer.revision, choice='deny', reason=reason)
        assert response.status_code == 200
        await asyncio.wait_for(h.finished.wait(), 2)
        assert h.replies[0]['reason'] == 'owner_denied' and not h.replies[0]['ok']
        assert h.replies[0].get('denial_reason') == reason
        assert h.replies[0]['approval_outcome'] == 'denied'
        assert runtime.q.get(task.id).human_decision['reason'] == normalize_reason(reason)
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('forgery', ['uncommitted', 'wrong_revision', 'different_birth', 'different_members'])
async def test_native_notification_cannot_substitute_a_committed_exact_snapshot(consent_runtime, monkeypatch, forgery):
    from dataclasses import replace

    from agents.core.autonomy.consent_types import ConsentDecisionResult, OwnerConsentActor

    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        task = await _delivered(h, runtime)
        prompts = runtime.worker._consent_prompts
        prompt = next(iter(prompts._pending.values()))
        offer = runtime.q.pending_consent_offer(task.id)
        # Exercise each binding against otherwise genuine committed state;
        # only the uncommitted case uses a fabricated public snapshot.
        fake = replace(task, status='approved', human_decision={'id': 'forged', 'action': 'always'})
        if forgery != 'uncommitted':
            committed = runtime.q.decide_reusable_consent(
                task.id, offer.revision, choice='session',
                actor=OwnerConsentActor('admin', 'admin', lambda: True),
            )
            assert committed is not None
            fake = committed.tasks[0]
        revision = offer.revision
        if forgery == 'wrong_revision':
            revision = '0' * 64
        elif forgery == 'different_birth':
            fake = replace(fake, created_at='2000-01-01T00:00:00+00:00')
        result = ConsentDecisionResult(
            (fake, replace(fake, id=task.id + 100)) if forgery == 'different_members' else (fake,),
        )
        prompts.decision_committed(task.id, revision, result)
        assert not prompt.future.done(), 'public state must not forge an inline human response'
        assert h.effects == []
        if forgery == 'uncommitted':
            assert runtime.q.get(task.id).status == 'blocked'
            await h.channel._handle_update(_tap(h.cards[-1], 'deny', message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        if forgery == 'uncommitted':
            assert h.replies[0]['reason'] == 'owner_denied' and h.effects == []
        else:
            # The bogus notification stayed ineffective; the independent exact
            # durable owner choice is still real and must survive a lost wake.
            assert h.replies[0]['ok'] is True and len(h.effects) == 1
            assert runtime.q.verify_consent_terminal_result(task.id)
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['', '  ', '🧪' * 280])
async def test_native_denial_reason_empty_and_unicode_boundary(consent_runtime, monkeypatch, reason):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    app = _admin_app(runtime, monkeypatch)
    try:
        task = await _delivered(h, runtime)
        offer = runtime.q.pending_consent_offer(task.id)
        response = await _post(app, task.id, revision=offer.revision, choice='deny', reason=reason)
        assert response.status_code == 200
        await asyncio.wait_for(h.finished.wait(), 2)
        reply = h.replies[0]
        assert reply['approval_outcome'] == 'denied'
        assert (reply.get('denial_reason') == reason if reason.strip() else 'denial_reason' not in reply)
        assert runtime.q.get(task.id).human_decision['action'] == 'deny'
        assert h.effects == []
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'deny'])
@pytest.mark.parametrize('notification', ['deferred_wake', 'suppressed'])
async def test_committed_choice_is_not_misreported_while_native_wake_is_delayed(
    consent_runtime, monkeypatch, choice, notification,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    app = _admin_app(runtime, monkeypatch)
    loop = asyncio.get_running_loop()
    original_schedule = loop.call_soon_threadsafe
    queued = []
    try:
        task = await _delivered(h, runtime)
        prompts = runtime.worker._consent_prompts
        offer = runtime.q.pending_consent_offer(task.id)
        if notification == 'deferred_wake':
            # Delay only the wake callback, reproducing the window where another
            # loop committed and deactivated the prompt before its owner loop ran.
            def schedule(fn, *args, **kwargs):
                if getattr(fn, '__name__', None) == 'wake':
                    queued.append((fn, args))
                    return None
                return original_schedule(fn, *args, **kwargs)

            monkeypatch.setattr(loop, 'call_soon_threadsafe', schedule)
        else:
            monkeypatch.setattr(prompts, 'decision_committed', lambda *args: None)
        response = await _post(app, task.id, revision=offer.revision, choice=choice)
        assert response.status_code == 200
        await asyncio.sleep(0.4)
        assert h.finished.is_set(), 'a committed exact choice cannot be lost behind a delayed wake'
        assert h.replies[0]['ok'] is (choice != 'deny')
        if choice == 'deny':
            assert h.replies[0]['reason'] == 'owner_denied' and h.effects == []
        else:
            assert len(h.effects) == 1 and runtime.q.verify_consent_terminal_result(task.id)
    finally:
        monkeypatch.setattr(loop, 'call_soon_threadsafe', original_schedule)
        for fn, args in queued:
            fn(*args)
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'deny'])
async def test_choice_after_native_wait_ended_is_reported_without_reviving_execution(consent_runtime, monkeypatch, choice):
    from agents.core.autonomy import consent_prompts

    runtime = consent_runtime
    monkeypatch.setattr(consent_prompts, '_REPLY_SECONDS', 0.1)
    h = await _telegram(runtime, monkeypatch)
    app = _admin_app(runtime, monkeypatch)
    prompts = runtime.worker._consent_prompts
    original_request = prompts.request
    ended, release = asyncio.Event(), asyncio.Event()

    async def delayed_return(*args, **kwargs):
        outcome = await original_request(*args, **kwargs)
        ended.set()
        await release.wait()
        return outcome

    monkeypatch.setattr(prompts, 'request', delayed_return)
    try:
        task = await _delivered(h, runtime)
        offer = runtime.q.pending_consent_offer(task.id)
        await asyncio.wait_for(ended.wait(), 2)
        response = await _post(app, task.id, revision=offer.revision, choice=choice, reason='Late human choice')
        assert response.status_code == 200
        release.set()
        await asyncio.wait_for(h.finished.wait(), 2)
        reply = h.replies[0]
        assert reply['ok'] is False and h.effects == []
        if choice == 'deny':
            assert reply['reason'] == 'owner_denied' and reply['denial_reason'] == 'Late human choice'
        else:
            assert reply['reason'] == 'terminal_execution_held' and reply['approval_outcome'] == 'approved'
            assert runtime.q.get(task.id).status == 'approved' and runtime.q.get(task.id).attempts == 0
    finally:
        release.set()
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('refusal', ['stale_revision', 'revoked_admin'])
async def test_refused_http_choice_does_not_wake_or_consume_native_offer(consent_runtime, monkeypatch, refusal):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    app = _admin_app(runtime, monkeypatch, current=lambda: refusal != 'revoked_admin')
    try:
        task = await _delivered(h, runtime)
        offer = runtime.q.pending_consent_offer(task.id)
        revision = '0' * 64 if refusal == 'stale_revision' else offer.revision
        response = await _post(app, task.id, revision=revision, choice='always')
        assert response.status_code == 409
        await asyncio.sleep(0.05)
        assert not h.finished.is_set() and h.effects == []
        assert runtime.q.get(task.id).human_decision is None
        assert runtime.q.pending_consent_offer(task.id) == offer
        await h.channel._handle_update(_tap(h.cards[-1], 'deny', message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        assert h.replies[0]['reason'] == 'owner_denied'
        assert h.effects == []
    finally:
        await h.channel.stop()
