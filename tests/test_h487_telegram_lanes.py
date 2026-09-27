"""H487 reason replies wait behind their prompt while other H677 chats proceed."""
import asyncio
import json
from types import SimpleNamespace

import httpx

from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.batching import Coalescer
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.telegram import TelegramChannel


async def test_early_reason_reply_waits_for_prompt_registration_without_stalling_other_chat(tmp_path):
    """Inline capture loses early replies; global lane settling blocks other chats."""
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    worker = AutonomyWorker(queue)
    channel = TelegramChannel(token='fake-token', allowed_user_ids=[99])
    channel._lanes = ChatLanes(name='telegram-reason-test')
    channel._batch = Coalescer(window=0)
    prompt_visible, prompt_response, other_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    model_turns = []

    async def telegram_api(request):
        body = json.loads(request.content)
        if body.get('reply_markup', {}).get('force_reply') is True:
            # Telegram has published the prompt, but its HTTP response is still in flight.
            prompt_visible.set()
            await prompt_response.wait()
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 77}})
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 88}})

    async def model_turn(chat_id, user_id, text, *, spoken=False):
        model_turns.append((chat_id, text))
        if chat_id == 43:
            other_finished.set()

    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(telegram_api))
    channel._run_turn = model_turn
    orchestrator = SimpleNamespace(
        autonomy=worker, autonomy_queue=queue, channels={'telegram': channel},
        get_setting=lambda key, default='': '42' if key == 'autonomy.owner_chat_id' else default,
    )
    coordinator = AutonomyCoordinator(orchestrator)
    channel.on_callback = coordinator._on_callback
    channel.on_decision_reason = coordinator._on_reason_reply
    try:
        task = await worker.submit('jarvis', 'delete_file', 'Delete test file', attention_mode='none')
        await channel._handle_update({'callback_query': {
            'id': 'reject-button', 'from': {'id': 99}, 'data': f'aut:{task.id}:reject',
            'message': {'chat': {'id': 42}},
        }})
        await asyncio.wait_for(prompt_visible.wait(), 1)
        assert queue.get(task.id).status == 'rejected'
        # Poll handling must return promptly, allowing it to read another chat's update.
        await asyncio.wait_for(channel._handle_update({'message': {
            'from': {'id': 99}, 'chat': {'id': 42, 'type': 'private'},
            'text': 'Use staging', 'reply_to_message': {'message_id': 77},
        }}), 0.2)
        await channel._handle_update({'message': {
            'from': {'id': 99}, 'chat': {'id': 43, 'type': 'private'}, 'text': 'Status please',
        }})
        await asyncio.wait_for(other_finished.wait(), 1)
        assert not prompt_response.is_set()
        assert model_turns == [(43, 'Status please')]
        assert queue.get(task.id).human_decision['reason'] is None
        prompt_response.set()
        await asyncio.wait_for(channel._lanes.settle(), 1)
        assert queue.get(task.id).human_decision['reason'] == 'Use staging'
        assert model_turns == [(43, 'Status please')]
        assert queue.get(task.id).status == 'rejected'
    finally:
        prompt_response.set()
        await channel._lanes.drain(1)
        await channel.client.aclose()
        queue.close()


async def test_unknown_reply_falls_back_once_before_later_chat_turn(tmp_path):
    """Re-queuing an uncaptured reply inside its lane would overtake later turns."""
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    worker = AutonomyWorker(queue)
    channel = TelegramChannel(token='fake-token', allowed_user_ids=[99])
    channel._lanes = ChatLanes(name='telegram-fallback-test')
    channel._batch = Coalescer(window=0)
    prompt_visible, prompt_response, other_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    model_turns = []

    async def telegram_api(request):
        body = json.loads(request.content)
        if body.get('reply_markup', {}).get('force_reply') is True:
            prompt_visible.set()
            await prompt_response.wait()
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 77}})
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 88}})

    async def model_turn(chat_id, user_id, text, *, spoken=False):
        model_turns.append((chat_id, text))
        if chat_id == 43:
            other_finished.set()

    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(telegram_api))
    channel._run_turn = model_turn
    orchestrator = SimpleNamespace(
        autonomy=worker, autonomy_queue=queue, channels={'telegram': channel},
        get_setting=lambda key, default='': '42' if key == 'autonomy.owner_chat_id' else default,
    )
    coordinator = AutonomyCoordinator(orchestrator)
    channel.on_callback = coordinator._on_callback
    channel.on_decision_reason = coordinator._on_reason_reply
    try:
        task = await worker.submit('jarvis', 'delete_file', 'Delete test file', attention_mode='none')
        await channel._handle_update({'callback_query': {
            'id': 'reject-button', 'from': {'id': 99}, 'data': f'aut:{task.id}:reject',
            'message': {'chat': {'id': 42}},
        }})
        await asyncio.wait_for(prompt_visible.wait(), 1)
        await asyncio.wait_for(channel._handle_update({'message': {
            'from': {'id': 99}, 'chat': {'id': 42, 'type': 'private'},
            'text': 'Unknown reply', 'reply_to_message': {'message_id': 78},
        }}), 0.2)
        await channel._handle_update({'message': {
            'from': {'id': 99}, 'chat': {'id': 42, 'type': 'private'}, 'text': 'Later turn',
        }})
        await channel._handle_update({'message': {
            'from': {'id': 99}, 'chat': {'id': 43, 'type': 'private'}, 'text': 'Independent turn',
        }})
        await asyncio.wait_for(other_finished.wait(), 1)
        assert model_turns == [(43, 'Independent turn')]
        assert not prompt_response.is_set()
        prompt_response.set()
        await asyncio.wait_for(channel._lanes.settle(), 1)
        assert model_turns == [(43, 'Independent turn'), (42, 'Unknown reply'), (42, 'Later turn')]
        assert queue.get(task.id).human_decision['reason'] is None
        assert queue.get(task.id).status == 'rejected'
    finally:
        prompt_response.set()
        await channel._lanes.drain(1)
        await channel.client.aclose()
        queue.close()
