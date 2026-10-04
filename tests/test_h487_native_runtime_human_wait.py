"""Real registered native owner waits must survive execution-only deadlines."""

import asyncio

import pytest

from tests.test_h487_consent_runtime_integration import consent_runtime  # noqa: F401
from tests.test_h487_telegram_consent_integration import _tap, _telegram


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', ['tool', 'wall'])
async def test_delivered_owner_wait_does_not_consume_real_model_execution_budget(
    consent_runtime, monkeypatch, budget,
):
    # Real intake and post-decision proof checks measured ~0.124s of execution.
    # Leave that work a budget; the human delay still exceeds it by a factor of2.
    options = {'tool_timeout_seconds': 0.25 if budget == 'tool' else 1.0,
               'max_wall_seconds': 0.25 if budget == 'wall' else 1.0}
    h = await _telegram(consent_runtime, monkeypatch, via_model=True, model_options=options)
    try:
        await h.channel._deliver_turn(-500, 42, 'Synthetic delayed owner request')
        await asyncio.wait_for(h.ready.wait(), 2)
        await asyncio.sleep(0.5)
        assert not h.finished.is_set(), 'execution budget must exclude the delivered native human wait'
        task = consent_runtime.q.list()[0]
        assert task.status == 'blocked' and task.human_decision is None
        await h.channel._handle_update(_tap(h.cards[-1], 'session', message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        assert h.model_answers == ['Synthetic tool turn complete.']
        assert len(h.replies) == 1 and h.replies[0]['ok'] is True
        assert len(h.effects) == 1
        assert consent_runtime.q.verify_consent_terminal_result(task.id)
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', ['tool', 'wall'])
async def test_guardian_denied_owner_once_wait_preserves_real_model_budget(
    consent_runtime, monkeypatch, budget,
):
    from tests.test_h277_smart_terminal_integration import bind_judge, drain

    _env, requests = bind_judge(consent_runtime.worker, 'DENY')
    options = {'tool_timeout_seconds': 0.25 if budget == 'tool' else 1.0,
               'max_wall_seconds': 0.25 if budget == 'wall' else 1.0}
    h = await _telegram(consent_runtime, monkeypatch, via_model=True, model_options=options)
    try:
        await h.channel._deliver_turn(-500, 42, 'Synthetic denied tool request')
        await asyncio.wait_for(h.ready.wait(), 2)
        await asyncio.sleep(0.5)
        assert not h.finished.is_set(), 'actual delivered owner-once prompt earns human wait credit'
        buttons = [b for row in h.cards[-1]['reply_markup']['inline_keyboard'] for b in row]
        assert all(b['callback_data'].startswith('aut1:') for b in buttons)
        data = next(b['callback_data'] for b in buttons if b['callback_data'].endswith(':r'))
        await h.channel._handle_update({'callback_query': {
            'id': 'synthetic-timed-owner-refusal', 'data': data, 'from': {'id': 42},
            'message': {'message_id': len(h.cards) + 16, 'chat': {'id': -500}},
        }})
        await asyncio.wait_for(h.finished.wait(), 2)
        assert len(requests) == 1 and not h.effects
        assert consent_runtime.q.list()[0].status == 'rejected'
        assert h.model_answers and 'safety deadline' not in h.model_answers[0]
        assert not any(event.get('reason') == 'tool_timeout' for event in h.model_events)
        assert consent_runtime.q._conn.execute('SELECT COUNT(*) FROM h487_consent_decisions').fetchone()[0] == 0
    finally:
        await h.channel.stop()
        await drain(consent_runtime.worker.approval_judge)
