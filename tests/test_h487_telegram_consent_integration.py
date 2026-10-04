"""Actual owner Telegram turn, registered terminal producer and private dispatch."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel
from agents.core.commands import Principal
from tests.test_h487_consent_runtime_integration import _Process, ask, consent_runtime  # noqa: F401


async def _telegram(runtime, monkeypatch, *, via_model=False, model_options=None):
    cards, answers, effects, replies = [], [], [], []
    card_ready, finished = asyncio.Event(), asyncio.Event()
    model_answers = []
    model_events = []
    settings = {'autonomy.owner_chat_id': '-500', 'autonomy.owner_user_ids': [42]}

    def transport(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/sendMessage'):
            cards.append(body)
            card_ready.set()
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': len(cards) + 16}})
        assert request.url.path.endswith('/answerCallbackQuery')
        answers.append((body, tuple(t.status for t in runtime.q.list())))
        return httpx.Response(200, json={'ok': True})

    async def spawn(*args, **kwargs):
        effects.append((args, kwargs['cwd']))
        return _Process()

    async def handler(_text, *, channel, sender, chat_id):
        turn = open_approval_turn(
            session_id='telegram-owner-session', session_instance='telegram-instance',
            principal=Principal(channel=channel, sender=sender, chat=str(chat_id), admin=True),
            session_is_live=lambda *_: True,
        )
        token = bind_approval_turn(turn)
        try:
            args = {'target': 'local-host', 'command': 'git reset --hard'}
            if via_model:
                from agents.core.agent_runtime import AgentToolRuntime
                from agents.core.llm.tool_protocol import ToolCall, ToolTurn

                model_runtime = AgentToolRuntime(runtime.orch.tool_rpc, **(model_options or {}))
                call = ToolCall(id='owner-terminal', name='terminal_run',
                                raw_arguments=json.dumps(args), arguments=args)
                if model_options is not None:
                    class Backend:
                        supports_tools = True
                        calls = 0

                        async def generate_tool_turn(self, **kwargs):
                            self.calls += 1
                            if self.calls == 1:
                                return ToolTurn(tool_calls=(call,))
                            tool_message = next(m for m in reversed(kwargs['messages'])
                                                if m['role'] == 'tool')
                            replies.append(json.loads(tool_message['content']))
                            return ToolTurn(content='Synthetic tool turn complete.')

                    model_answers.append(await model_runtime.run(
                        agent_id='jarvis', backend=Backend(), model='synthetic-local-model',
                        prompt='Synthetic owner request', max_tokens=256,
                        event_sink=lambda event: model_events.append(event),
                    ))
                else:
                    observations = await model_runtime._execute_turn_calls(
                        (call,), agent_id='jarvis', gated_tools={'terminal_run': True}, event_sink=None,
                    )
                    replies.append(observations[0][0])
            else:
                replies.append(await runtime.orch.tool_rpc.handle(
                    {'tool': 'terminal_run', 'args': args}, actor='jarvis',
                ))
        finally:
            close_approval_turn(turn, token)
            finished.set()

    channel = TelegramChannel('synthetic-consent-bot', handler=handler, allowed_user_ids=[42])
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    channel._running = True
    channel._owner_once_generation = uuid.uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    channel._lanes = ChatLanes(name='actual-consent-turn')
    runtime.orch.channels = {'telegram': channel}
    runtime.orch.get_setting = lambda key, default=None: settings.get(key, default)
    runtime.coordinator.wire()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    return SimpleNamespace(channel=channel, cards=cards, answers=answers, effects=effects,
                           replies=replies, ready=card_ready, finished=finished, settings=settings,
                           model_answers=model_answers, model_events=model_events)


def _tap(card, choice, *, message_id=17, user_id=42, callback_id='actual-owner-tap'):
    suffix = {'session': 's', 'always': 'a', 'deny': 'd'}[choice]
    data = next(button['callback_data'] for row in card['reply_markup']['inline_keyboard']
                for button in row if button['callback_data'].endswith(':' + suffix))
    assert data.startswith('autc:')
    return {'callback_query': {'id': callback_id, 'data': data, 'from': {'id': user_id},
                               'message': {'message_id': message_id, 'chat': {'id': -500}}}}


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always', 'deny'])
async def test_actual_model_runtime_child_call_waits_for_owner_and_verifies_effect(
    consent_runtime, monkeypatch, choice,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch, via_model=True)
    try:
        await h.channel._deliver_turn(-500, 42, 'model tool request')
        await asyncio.wait_for(h.ready.wait(), 2)
        assert not h.finished.is_set(), 'model runtime must join its actual owner reply'
        task = runtime.q.list()[0]
        assert task.status == 'blocked' and task.human_decision is None
        await h.channel._handle_update(_tap(h.cards[-1], choice, message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        task = runtime.q.get(task.id)
        assert task.human_decision['action'] == choice
        if choice == 'deny':
            assert task.status == 'rejected' and h.effects == []
            assert h.replies[0]['ok'] is False and h.replies[0]['reason'] == 'owner_denied'
        else:
            assert task.status == 'done' and h.replies[0]['ok'] is True
            assert len(h.effects) == 1 and runtime.q.verify_consent_terminal_result(task.id)
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always', 'deny'])
async def test_actual_same_chat_choice_wakes_tool_wait_and_dispatches_exactly_once(
    consent_runtime, monkeypatch, choice,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, 'synthetic owner request')
        await asyncio.wait_for(h.ready.wait(), 2)
        await asyncio.sleep(0)
        assert not h.finished.is_set(), 'the real tool turn must wait for its owner'
        task = runtime.q.list()[0]
        assert task.status == 'blocked' and task.human_decision is None
        await h.channel._handle_update(_tap(h.cards[-1], choice, message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        task = runtime.q.get(task.id)
        assert task.human_decision['action'] == choice and task.decided_by == 'telegram'
        assert h.answers and h.answers[0][1] != ('blocked',), 'ack must follow durable commit'
        if choice == 'deny':
            assert task.status == 'rejected' and h.effects == []
            assert h.replies[0]['ok'] is False
        else:
            assert task.status == 'done' and task.attempts == 1
            assert h.replies[0]['ok'] is True
            assert h.effects == [(('git', 'reset', '--hard'), str(runtime.root))]
            assert runtime.q.verify_consent_terminal_result(task.id)
            await runtime.worker.tick()
            assert len(h.effects) == 1
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always'])
async def test_actual_future_same_session_reuses_without_second_card_or_human(
    consent_runtime, monkeypatch, choice,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, 'first')
        await asyncio.wait_for(h.ready.wait(), 2)
        await asyncio.sleep(0)
        await h.channel._handle_update(_tap(h.cards[-1], choice, message_id=len(h.cards) + 16))
        await asyncio.wait_for(h.finished.wait(), 2)
        h.finished.clear()
        await h.channel._deliver_turn(-500, 42, 'future matching request')
        await asyncio.wait_for(h.finished.wait(), 2)
        tasks = runtime.q.list()
        future = max(tasks, key=lambda t: t.id)
        assert future.status == 'done' and future.decided_by == 'consent'
        assert future.human_decision is None
        assert len(h.cards) == 1 and len(h.effects) == 2
        assert len(h.replies) == 2 and all(reply['ok'] for reply in h.replies)
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_actual_web_origin_inbox_card_keeps_web_grant_scope(consent_runtime, monkeypatch):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        first = await ask(runtime)
        assert await runtime.worker.notifier(first) is True
        callback = _tap(h.cards[-1], 'always', message_id=len(h.cards) + 16)
        assert h.channel.consent_pending(callback['callback_query']) is True
        await h.channel._handle_update(callback)
        for _ in range(100):
            if runtime.q.get(first.id).status != 'blocked':
                break
            await asyncio.sleep(0.01)
        first = runtime.q.get(first.id)
        assert first.status == 'approved' and first.decided_by == 'telegram', {
            'cards': len(h.cards), 'answers': h.answers,
            'pending': [(p.offer.task_id, p.message_id, p.active, p.inflight)
                        for p in runtime.worker._consent_prompts._pending.values()],
        }
        assert first.human_decision['principal_key'] == '["telegram","42","-500"]'
        decision = json.loads(runtime.q._conn.execute(
            'SELECT payload FROM h487_consent_decisions',
        ).fetchone()[0])
        assert decision['context']['principal'] == '["web-owner"]'
        assert decision['decider_principal'] == '["telegram","42","-500"]'
        assert (await ask(runtime, session='future-web', instance='future-web-instance')).decided_by == 'consent'
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_actual_revoked_owner_cannot_apply_delivered_offer(consent_runtime, monkeypatch):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        task = await ask(runtime)
        assert await runtime.worker.notifier(task) is True
        h.settings['autonomy.owner_user_ids'] = [99]
        await h.channel._handle_update(_tap(h.cards[-1], 'always', message_id=len(h.cards) + 16))
        await asyncio.sleep(0.05)
        assert runtime.q.get(task.id).status == 'blocked'
        assert runtime.q.get(task.id).human_decision is None
        assert h.effects == []
        assert runtime.q._conn.execute('SELECT COUNT(*) FROM h487_consent_decisions').fetchone()[0] == 0
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always', 'deny'])
async def test_real_web_followers_require_fresh_card_and_settle_each_receipt(
    consent_runtime, monkeypatch, choice,
):
    runtime = consent_runtime
    h = await _telegram(runtime, monkeypatch)
    try:
        first = await ask(runtime)
        assert await runtime.worker.notifier(first) is True
        old_card = h.cards[-1]
        old_message_id = len(h.cards) + 16
        second = await ask(runtime)
        offer = runtime.q.pending_consent_offer(first.id)
        assert offer.member_ids == (first.id, second.id)
        await h.channel._handle_update(_tap(old_card, choice, message_id=old_message_id))
        assert all(task.status == 'blocked' and task.human_decision is None
                   for task in runtime.q.list())
        assert h.answers[-1][0]['text'] == 'Not applied.'
        assert await runtime.worker.notifier(runtime.q.get(first.id)) is True
        assert len(h.cards) == 2
        assert 'Pending identical requests in this offer: 2' in h.cards[-1]['text']
        await h.channel._handle_update(_tap(h.cards[-1], choice, message_id=len(h.cards) + 16))
        await asyncio.gather(*tuple(h.channel._consent_fast.values()))
        tasks = [runtime.q.get(first.id), runtime.q.get(second.id)]
        assert all(task.human_decision['action'] == choice
                   and task.human_decision['principal_key'] == '["telegram","42","-500"]'
                   for task in tasks)
        assert len({task.human_decision['id'] for task in tasks}) == 2
        if choice == 'deny':
            assert all(task.status == 'rejected' for task in tasks) and h.effects == []
        else:
            assert all(task.status == 'approved' for task in tasks)
            for task in tasks:
                assert (await runtime.worker.tick(task_id=task.id))['done'] == 1
                assert runtime.q.verify_consent_terminal_result(task.id)
            assert len(h.effects) == 2
            await runtime.worker.tick()
            assert len(h.effects) == 2
    finally:
        await h.channel.stop()


@pytest.mark.asyncio
async def test_actual_smart_deny_keeps_owner_once_controls_and_never_reusable(
    consent_runtime, monkeypatch,
):
    from tests.test_h277_smart_terminal_integration import bind_judge, drain

    runtime = consent_runtime
    _env, judge_requests = bind_judge(runtime.worker, 'DENY')
    h = await _telegram(runtime, monkeypatch)
    try:
        await h.channel._deliver_turn(-500, 42, 'guardian-denied request')
        await asyncio.wait_for(h.ready.wait(), 2)
        await asyncio.sleep(0)
        buttons = [button for row in h.cards[-1]['reply_markup']['inline_keyboard'] for button in row]
        assert len(buttons) == 2 and all(b['callback_data'].startswith('aut1:') for b in buttons)
        task = runtime.q.list()[0]
        assert runtime.q.pending_consent_offer(task.id) is None
        data = next(b['callback_data'] for b in buttons if b['callback_data'].endswith(':r'))
        await h.channel._handle_update({'callback_query': {
            'id': 'owner-refuses-denied-request', 'data': data, 'from': {'id': 42},
            'message': {'message_id': len(h.cards) + 16, 'chat': {'id': -500}},
        }})
        await asyncio.wait_for(h.finished.wait(), 2)
        assert len(judge_requests) == 1 and h.effects == []
        assert h.replies[0]['ok'] is False and h.replies[0]['reason'] == 'guardian_denied'
        assert runtime.q.get(task.id).status == 'rejected'
        assert runtime.q._conn.execute('SELECT COUNT(*) FROM h487_consent_decisions').fetchone()[0] == 0
    finally:
        await h.channel.stop()
        await drain(runtime.worker.approval_judge)
