from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.telegram import TelegramChannel


@pytest.fixture
def rig(tmp_path):
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    worker = AutonomyWorker(queue)
    channel = SimpleNamespace(name='telegram', allowed_users=[99],
                              request_decision_reason=AsyncMock(return_value=77),
                              send=AsyncMock(return_value=True))
    orch = SimpleNamespace(autonomy=worker, autonomy_queue=queue, channels={'telegram': channel},
                           get_setting=lambda key, default='': '42' if key == 'autonomy.owner_chat_id' else default)
    coordinator = AutonomyCoordinator(orch)
    yield queue, worker, channel, coordinator
    queue.close()


async def reject(rig):
    queue, worker, channel, coordinator = rig
    task = await worker.submit('jarvis', 'delete_file', 'Delete test file', attention_mode='none')
    await coordinator._on_callback(task.id, 'reject', chat_id=42, user_id=99)
    return task.id


async def test_owner_reply_fills_only_rejected_decision_metadata(rig):
    queue, _, channel, coordinator = rig
    task_id = await reject(rig)
    channel.request_decision_reason.assert_awaited_once_with(task_id, chat_id=42)
    before = queue.get(task_id)
    consumed = await coordinator._on_reason_reply('Use staging', chat_id=42, user_id=99, reply_to_message_id=77)
    after = queue.get(task_id)
    assert consumed and after.human_decision['reason'] == 'Use staging'
    assert (after.status, after.payload, after.result, after.updated_at) == (before.status, before.payload, before.result, before.updated_at)
    assert await coordinator._on_reason_reply('Replace it', chat_id=42, user_id=99, reply_to_message_id=77)
    assert queue.get(task_id).human_decision['reason'] == 'Use staging'


async def test_superseded_prompt_is_consumed_without_becoming_a_chat_turn(rig):
    queue, _, channel, coordinator = rig
    first = await reject(rig)
    channel.request_decision_reason.return_value = 78
    second = await reject(rig)
    assert await coordinator._on_reason_reply('Old reason', chat_id=42, user_id=99, reply_to_message_id=77)
    assert queue.get(first).human_decision['reason'] is None
    assert queue.get(second).human_decision['reason'] is None
    assert await coordinator._on_reason_reply('New reason', chat_id=42, user_id=99, reply_to_message_id=78)
    assert queue.get(second).human_decision['reason'] == 'New reason'


@pytest.mark.parametrize('chat,user,reply', [(43, 99, 77), (42, 100, 77), (42, 99, 78), (42, 99, None), (42, 99, True), (42, 99, [])])
async def test_reply_must_match_owner_chat_and_exact_prompt(rig, chat, user, reply):
    queue, _, _, coordinator = rig
    task_id = await reject(rig)
    assert not await coordinator._on_reason_reply('Wrong context', chat_id=chat, user_id=user, reply_to_message_id=reply)
    assert queue.get(task_id).human_decision['reason'] is None


async def test_expired_window_and_revoked_owner_cannot_write_reason(rig):
    queue, _, channel, coordinator = rig
    coordinator._reason_clock = lambda: 100
    task_id = await reject(rig)
    coordinator._reason_clock = lambda: 221
    await coordinator._on_reason_reply('Late', chat_id=42, user_id=99, reply_to_message_id=77)
    assert queue.get(task_id).human_decision['reason'] is None
    coordinator._reason_clock = lambda: 300
    second = await reject(rig)
    channel.allowed_users = [100]
    await coordinator._on_reason_reply('Revoked', chat_id=42, user_id=99, reply_to_message_id=77)
    assert queue.get(second).human_decision['reason'] is None


async def test_failed_prompt_never_opens_capture(rig):
    queue, _, channel, coordinator = rig
    channel.request_decision_reason.side_effect = RuntimeError('offline')
    task_id = await reject(rig)
    assert queue.get(task_id).status == 'rejected'
    assert not await coordinator._on_reason_reply('Not a reply', chat_id=42, user_id=99, reply_to_message_id=77)


async def test_matching_reason_reply_bypasses_chat_but_edits_forwards_and_commands_do_not():
    channel = TelegramChannel(token='fake-token', allowed_user_ids=[99])
    channel.on_decision_reason = AsyncMock(return_value=True)
    channel._queue_turn = AsyncMock()
    message = {'from': {'id': 99}, 'chat': {'id': 42, 'type': 'private'}, 'text': 'Use staging',
               'reply_to_message': {'message_id': 77}}
    try:
        await channel._handle_update({'message': message})
        channel.on_decision_reason.assert_awaited_once_with('Use staging', chat_id=42, user_id=99, reply_to_message_id=77)
        channel._queue_turn.assert_not_awaited()
        channel.on_decision_reason.reset_mock()
        await channel._handle_update({'edited_message': message})
        await channel._handle_update({'message': {**message, 'forward_origin': {'type': 'user'}}})
        await channel._handle_update({'message': {**message, 'text': '/help'}})
        channel.on_decision_reason.assert_not_awaited()
    finally:
        await channel.client.aclose()


async def test_wired_telegram_card_describes_group_without_changing_approval_target(rig, monkeypatch):
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext
    queue, worker, channel, coordinator = rig
    monkeypatch.delenv('AUTONOMY_OWNER_CHAT_ID', raising=False)
    channel.send_card = AsyncMock(return_value=True)
    coordinator.wire()
    body = {'agent': 'jarvis', 'kind': 'delete_file', 'title': 'Delete one file',
            'payload': {'path': 'old'}, 'origin': 'generated'}
    context = OwnerTaskRegistrationContext.from_request(body)
    first = await worker.submit(**body, attention_mode='none', grouping_context=context)
    second = await worker.submit(**body, attention_mode='none', grouping_context=context)
    assert queue.pending_group(first.id)['count'] == 2
    await worker.notifier(queue.get(first.id))
    chat, card = channel.send_card.call_args.args
    assert chat == 42 and '2 cereri identice' in card['text']
    callbacks = [button['callback_data'] for row in card['reply_markup']['inline_keyboard'] for button in row]
    assert callbacks and all(value.startswith(f'aut:{first.id}:') for value in callbacks)
    assert queue.get(first.id).payload == queue.get(second.id).payload == {'path': 'old'}
