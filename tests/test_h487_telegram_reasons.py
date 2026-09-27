import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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


@pytest.mark.parametrize('received_at,saved', [
    (219.5, True),                  # arrived in time; handled after the deadline (a busy lane)
    (220, False),                   # arrived at the deadline
    (None, False),                  # an older caller: judged when handled
    (True, False), ('100', False), (float('nan'), False), (float('-inf'), False),   # no instant: judged when handled
])
async def test_a_reply_is_judged_by_when_it_arrived_not_when_it_is_handled(rig, received_at, saved):
    """H117 round 3: Telegram hands the lane the instant the poll loop claimed the reply; the
    window's deadline is checked against it. Anything that is not a finite instant falls back
    to now, as for a caller that passes none."""
    queue, _, channel, coordinator = rig
    coordinator._reason_clock = lambda: 100
    task_id = await reject(rig)                               # the window closes at t=220
    coordinator._reason_clock = lambda: 250                   # the reply is handled at t=250
    kwargs = {} if received_at is None else {'received_at': received_at}
    assert await coordinator._on_reason_reply('Use staging', chat_id=42, user_id=99,
                                              reply_to_message_id=77, **kwargs)
    assert queue.get(task_id).human_decision['reason'] == ('Use staging' if saved else None)
    assert channel.send.await_args_list[-1].args[0] == (
        'Reason saved.' if saved else 'The reason window expired; the rejection is unchanged.')
    assert not coordinator._reason_windows


async def test_expired_windows_are_pruned_only_to_make_room_and_before_a_live_one(rig):
    """Below the cap an expired window stays (a reply that arrived in time may still be queued
    in the chat's lane behind the rejection that opens the next window); at the cap the
    expired ones go first, and only then the oldest live one."""
    queue, _, _, coordinator = rig
    task = queue.get(await reject(rig))                       # rejected on Telegram, no reason yet
    coordinator._reason_windows.clear()
    coordinator._reason_clock = lambda: 100
    await coordinator._offer_reason(task, 42, 0)
    await coordinator._offer_reason(task, 42, 1)              # both close at 220
    coordinator._reason_clock = lambda: 150
    await coordinator._offer_reason(task, 42, 0)              # closes at 270; still the oldest entry
    coordinator._reason_clock = lambda: 230
    for user in range(2, 32):
        await coordinator._offer_reason(task, 42, user)       # close at 350
    assert len(coordinator._reason_windows) == 32
    assert ('42', '1') in coordinator._reason_windows         # expired, but kept below the cap
    await coordinator._offer_reason(task, 42, 32)             # full: the expired one goes, not the oldest
    assert len(coordinator._reason_windows) == 32
    assert ('42', '1') not in coordinator._reason_windows and ('42', '0') in coordinator._reason_windows
    await coordinator._offer_reason(task, 42, 33)             # full, none expired: the oldest goes
    assert len(coordinator._reason_windows) == 32
    assert ('42', '0') not in coordinator._reason_windows and ('42', '33') in coordinator._reason_windows


async def test_the_reason_clock_is_the_windows_own_clock_read_live(rig):
    _, _, _, coordinator = rig
    coordinator._reason_clock = lambda: 321.5
    assert coordinator.reason_clock() == 321.5


async def test_failed_prompt_never_opens_capture(rig):
    queue, _, channel, coordinator = rig
    channel.request_decision_reason.side_effect = RuntimeError('offline')
    task_id = await reject(rig)
    assert queue.get(task_id).status == 'rejected'
    assert not await coordinator._on_reason_reply('Not a reply', chat_id=42, user_id=99, reply_to_message_id=77)


async def test_matching_reason_reply_bypasses_chat_but_edits_forwards_and_commands_do_not():
    channel = TelegramChannel(token='fake-token', allowed_user_ids=[99])
    # H117 round 2: the channel claims a reply with the inbox's side-effect-free predicate
    # (wired next to the hook by AutonomyCoordinator.wire) and runs the hook in the lane.
    channel.decision_reason_pending = Mock(return_value=True)
    channel.on_decision_reason = AsyncMock(return_value=True)
    channel._queue_turn = AsyncMock()
    message = {'from': {'id': 99}, 'chat': {'id': 42, 'type': 'private'}, 'text': 'Use staging',
               'reply_to_message': {'message_id': 77}}
    try:
        await channel._handle_update({'message': message})
        channel.decision_reason_pending.assert_called_once_with(chat_id=42, user_id=99, reply_to_message_id=77)
        channel.on_decision_reason.assert_awaited_once_with('Use staging', chat_id=42, user_id=99, reply_to_message_id=77)
        channel._queue_turn.assert_not_awaited()
        channel.decision_reason_pending.reset_mock()
        channel.on_decision_reason.reset_mock()
        await channel._handle_update({'edited_message': message})
        await channel._handle_update({'message': {**message, 'forward_origin': {'type': 'user'}}})
        await channel._handle_update({'message': {**message, 'text': '/help'}})
        channel.decision_reason_pending.assert_not_called()
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


# ── H117 round 2: the side-effect-free predicate the poll loop decides with ─────

def _snapshot(queue, channel, coordinator, task_ids):
    return (copy.deepcopy(coordinator._reason_windows), dict(coordinator._reason_prompts),
            [queue.get(task_id).human_decision for task_id in task_ids], channel.send.await_count,
            channel.request_decision_reason.await_count)


@pytest.mark.parametrize('case,expected', [
    ('live', True), ('superseded', True), ('expired', True), ('answered', True),
    ('other_chat', False), ('other_member', False), ('unknown_prompt', False),
    ('no_reply_id', False), ('bool_reply_id', False), ('revoked_owner', False),
])
async def test_would_consume_is_exactly_what_on_reason_reply_consumes_and_writes_nothing(rig, case, expected):
    queue, _, channel, coordinator = rig
    coordinator._reason_clock = lambda: 100
    task_ids = [await reject(rig)]
    chat, user, reply = 42, 99, 77
    if case == 'superseded':
        channel.request_decision_reason.return_value = 78
        task_ids.append(await reject(rig))
    elif case == 'expired':
        coordinator._reason_clock = lambda: 221
    elif case == 'answered':
        assert await coordinator._on_reason_reply('First', chat_id=42, user_id=99, reply_to_message_id=77)
    elif case == 'other_chat':
        chat = 43
    elif case == 'other_member':
        user = 100
    elif case == 'unknown_prompt':
        reply = 78
    elif case == 'no_reply_id':
        reply = None
    elif case == 'bool_reply_id':
        reply = True
    elif case == 'revoked_owner':
        channel.allowed_users = [100]
    before = _snapshot(queue, channel, coordinator, task_ids)
    claimed = coordinator.would_consume_reason_reply(chat_id=chat, user_id=user, reply_to_message_id=reply)
    assert claimed is expected
    assert coordinator.would_consume_reason_reply(chat, user, reply) is expected
    assert _snapshot(queue, channel, coordinator, task_ids) == before
    consumed = await coordinator._on_reason_reply('A reason', chat_id=chat, user_id=user, reply_to_message_id=reply)
    assert consumed is claimed


async def test_every_reason_acknowledgement_is_a_service_line_that_is_never_spoken(rig):
    queue, _, channel, coordinator = rig
    coordinator._reason_clock = lambda: 100
    task_id = await reject(rig)
    await coordinator._on_reason_reply('x' * 281, chat_id=42, user_id=99, reply_to_message_id=77)   # invalid
    await coordinator._on_reason_reply('Use staging', chat_id=42, user_id=99, reply_to_message_id=77)
    await coordinator._on_reason_reply('Again', chat_id=42, user_id=99, reply_to_message_id=77)     # stale
    channel.request_decision_reason.return_value = 78
    await reject(rig)
    coordinator._reason_clock = lambda: 400
    await coordinator._on_reason_reply('Late', chat_id=42, user_id=99, reply_to_message_id=78)      # expired
    assert queue.get(task_id).human_decision['reason'] == 'Use staging'
    texts = [call.args[0] for call in channel.send.await_args_list]
    assert texts == ['Use a nonempty reason of at most 280 characters.', 'Reason saved.',
                     'That reason prompt is no longer active; no decision changed.',
                     'The reason window expired; the rejection is unchanged.']
    assert all(call.kwargs == {'chat_id': 42, 'voice': False} for call in channel.send.await_args_list)
