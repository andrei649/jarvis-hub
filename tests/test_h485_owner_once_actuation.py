"""One real Telegram turn resumes its exact ToolRPC operation after owner reply."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.channels.telegram import TelegramChannel
from agents.core.commands import Principal
from agents.core.sandbox import Sandbox
from tests.test_h277_smart_terminal_integration import (
    bind_judge,
    propose,
    runtime,  # noqa: F401
    use_real_kernel,
)


class _Process:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"hello")
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


@asynccontextmanager
async def _owner_runtime(runtime, monkeypatch, tmp_path, *, kernel_options=None):
    queue, worker, orch, _old_sandbox, _seen = runtime
    delivered, finished = asyncio.Event(), asyncio.Event()
    cards, acks, spawns, answers, turns = [], [], [], [], []
    owners = {"autonomy.owner_chat_id": "99", "autonomy.owner_user_ids": [99]}

    def response(request):
        payload = json.loads(request.content)
        if request.url.path.endswith('/sendMessage'):
            cards.append(payload)
            if 'reply_markup' in payload:
                delivered.set()
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 17}})
        acks.append(payload)
        return httpx.Response(200, json={'ok': True})

    channel = TelegramChannel('test-token')
    channel.allowed_users = {99}
    await channel.client.aclose()
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    channel._running = True
    channel._owner_once_generation = uuid4().hex
    channel._poll_task = asyncio.create_task(asyncio.sleep(100))
    orch.channels = {'telegram': channel}
    orch._telegram_owner_settings = lambda: dict(owners)
    orch.get_setting = lambda key, default=None: owners.get(key, default)
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = False
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = 'fixture:local'
    sandbox.work_dir = tmp_path
    sandbox.work_dir_managed = False
    orch.sandbox = sandbox

    async def spawn(*argv, **kwargs):
        spawns.append((argv, kwargs))
        return _Process()

    monkeypatch.setattr('agents.core.sandbox.asyncio.create_subprocess_exec', spawn)
    use_real_kernel(runtime, synchronous=True)
    if kernel_options:
        from agents.core.autonomy.executor import TaskExecutor
        from agents.core.kernel.binding import make_action_kernel

        worker.bind_mediation(make_action_kernel(orch, **kernel_options), queue._mediation_signer)
        orch._test_coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
        executor = TaskExecutor(execution_guard=worker.execution_allowed)
        executor.register('toolrpc.terminal_run', orch._test_coordinator._approved_desktop_tool_rpc_execute)
        worker.executor = executor.execute
    else:
        worker.executor.__self__.execution_guard = worker.execution_allowed
    orch._test_coordinator.wire()
    env, requests = bind_judge(worker, 'DENY')

    async def handler(_text, **_kwargs):
        turn = open_approval_turn(
            session_id='telegram-session', session_instance='birth',
            principal=Principal(channel='telegram', sender='99', chat='99', admin=True),
            session_is_live=lambda *_args: True,
        )
        turns.append({'context': turn})
        token = bind_approval_turn(turn)
        try:
            assert worker._owner_once_prompts.can_reply(), 'fixture must have a live owner reply source'
            answers.append(await propose(orch))
            turns[-1]['outcome'] = queue.chat_invocation_outcome(turn, answers[-1]['task_id'])
        finally:
            close_approval_turn(turn, token)
            finished.set()

    channel.handler = handler
    invocation = asyncio.create_task(channel._run_turn(99, 99, 'run operation'))
    try:
        yield (queue, worker, channel, sandbox, delivered, finished, cards, acks,
               spawns, answers, turns, owners, env, requests, invocation)
    finally:
        if not invocation.done():
            invocation.cancel()
        await asyncio.gather(invocation, return_exceptions=True)
        await channel.stop()


async def _wait_for_offer(delivered, finished, answers=None):
    waits = [asyncio.create_task(event.wait()) for event in (delivered, finished)]
    try:
        await asyncio.wait(waits, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        assert delivered.is_set(), ('a live owner turn must offer once/deny after native DENY', answers)
    finally:
        for wait in waits:
            wait.cancel()
        await asyncio.gather(*waits, return_exceptions=True)
    # Delivery confirmation is committed after the HTTP response returns.
    await asyncio.sleep(0)


def _callback(cards, choice='a'):
    card = next(card for card in cards if 'reply_markup' in card)
    nonce = card['reply_markup']['inline_keyboard'][0][0]['callback_data'].split(':')[1]
    return {'id': 'owner-tap', 'data': f'aut1:{nonce}:{choice}', 'from': {'id': 99},
            'message': {'message_id': 17, 'chat': {'id': 99}}}


async def test_native_deny_owner_once_resumes_same_toolrpc_with_real_kernel_and_spawn(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, _sandbox, delivered, finished, cards, acks,
         spawns, answers, turns, _owners, _env, requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        assert not finished.is_set() and spawns == []
        await worker.tick()
        assert spawns == [], 'ordinary scheduler must never consume an owner offer'
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(invocation, 2)
        await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert len(answers) == 1 and answers[0]['ok'] is True, answers
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'done' and task.decision == 'owner-once'
        assert task.result['status'] == 'ok' and task.result['result']['ok'] is True
        assert answers[0]['result']['stdout'] == 'hello'
        assert queue.verify_owner_once_terminal_result(task.id)
        assert not queue.verify_smart_terminal_result(task.id)
        assert len(spawns) == 1 and spawns[0][0][:2] == ('docker', 'run')
        assert spawns[0][0][-3:] == ('sh', '-c', 'printf hello')
        assert len(requests) == 1 and acks[0]['text'] == 'OK: once'
        observation = turns[0]['outcome']
        assert observation['guardian']['consecutive_denials'] == 1
        assert answers[0]['guardian']['consecutive_denials'] == 1
        await worker.tick()
        assert len(spawns) == 1


async def test_owner_rejection_finishes_same_invocation_without_dispatch(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, _sandbox, delivered, finished, cards, acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': _callback(cards, 'r')})
        await asyncio.wait_for(invocation, 2)
        await asyncio.gather(*tuple(channel._owner_once_fast.values()))
        assert answers[0]['ok'] is False and answers[0]['reason'] == 'owner_denied'
        assert answers[0]['approval_outcome'] == 'denied'
        assert answers[0]['guardian']['consecutive_denials'] == 1
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'rejected' and task.human_decision['action'] == 'reject'
        assert spawns == [] and acks[0]['text'] == 'OK: deny'


@pytest.mark.parametrize('revocation', ['owner', 'smart', 'kernel', 'targets', 'runtime', 'halt'])
async def test_revocation_after_owner_reply_before_physical_spawn_refuses(
    runtime, monkeypatch, tmp_path, revocation,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, owners, env, _requests, invocation) = state
        entered, release = asyncio.Event(), asyncio.Event()
        original = sandbox.execute_shell

        async def paused(command):
            entered.set()
            await release.wait()
            return await original(command)

        sandbox.execute_shell = paused
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(entered.wait(), 2)
        if revocation == 'owner':
            owners['autonomy.owner_user_ids'] = [98]
        elif revocation == 'smart':
            env['JARVIS_SMART_APPROVALS'] = '0'
        elif revocation == 'kernel':
            monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
        elif revocation == 'targets':
            monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '0')
        elif revocation == 'runtime':
            sandbox.docker_image = 'changed:local'
        else:
            from types import SimpleNamespace

            worker._kill_switch = SimpleNamespace(is_halted=lambda *_args: True)
        release.set()
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['ok'] is False and spawns == []
        task = queue.get(answers[0]['task_id'])
        assert task.status == 'failed' and task.attempts == 1
        assert not queue.verify_owner_once_terminal_result(task.id)
        await worker.tick()
        assert spawns == []


async def test_cancelled_origin_cannot_spawn_after_cancellation_resistant_pause(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, _worker, channel, sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        entered, release = asyncio.Event(), asyncio.Event()
        original = sandbox.execute_shell

        async def resistant(command):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return await original(command)

        sandbox.execute_shell = resistant
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(entered.wait(), 2)
        invocation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(invocation, 2)
        assert spawns == [] and answers == []
        task = queue.list()[0]
        assert task.status == 'failed' and task.attempts == 1
        assert not queue.verify_owner_once_terminal_result(task.id)


async def test_cancelled_review_settles_native_deny_before_prompt_registration(
    runtime, monkeypatch, tmp_path,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, _channel, _sandbox, _delivered, _finished, _cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        entered = asyncio.Event()
        original = worker.approval_judge.wait_for_review

        async def paused(*args, **kwargs):
            await original(*args, **kwargs)
            if asyncio.current_task() is invocation:
                entered.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(worker.approval_judge, 'wait_for_review', paused)
        await asyncio.wait_for(entered.wait(), 2)
        assert queue.list()[0].status == 'blocked'
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation
        assert queue.list()[0].status == 'rejected'
        assert spawns == [] and answers == []
        assert worker._owner_once_prompts._origins == {}


@pytest.mark.parametrize('forgery', ['synthetic-done', 'changed-output', 'missing-proof'])
async def test_invocation_does_not_report_success_without_exact_owner_done_proof(
    runtime, monkeypatch, tmp_path, forgery,
):
    async with _owner_runtime(runtime, monkeypatch, tmp_path) as state:
        (queue, worker, channel, _sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        original = worker._run_owner_once

        async def corrupt(claim, **kwargs):
            if forgery == 'synthetic-done':
                outcome = {'ran': 1, 'done': 1, 'failed': 0, 'held': 0}
                result = {'status': 'ok', 'result': {'ok': True, 'stdout': 'invented'}}
            else:
                outcome = await original(claim, **kwargs)
                result = queue.get(claim.task_id).result
                if forgery == 'changed-output':
                    result['result']['stdout'] = 'invented'
                else:
                    result.pop('_owner_once_execution')
            queue._conn.execute('UPDATE tasks SET status=?, result=? WHERE id=?',
                                ('done', json.dumps(result), claim.task_id))
            queue._conn.commit()
            return outcome

        monkeypatch.setattr(worker, '_run_owner_once', corrupt)
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['ok'] is False
        assert answers[0]['reason'] == 'terminal_execution_unverified'
        assert not queue.verify_owner_once_terminal_result(answers[0]['task_id'])
        assert len(spawns) == (0 if forgery == 'synthetic-done' else 1)


@pytest.mark.parametrize('floor', ['ask', 'off', 'kill', 'unreadable-kill', 'budget', 'loop'])
async def test_real_kernel_live_floor_changes_during_dispatch_pause_prevent_spawn(
    runtime, monkeypatch, tmp_path, floor,
):
    from agents.core.kernel import BudgetLedger, BudgetLimits, LoopDetector

    budget = BudgetLedger(BudgetLimits(max_tokens=1))
    loop = LoopDetector(max_repeats=100)
    async with _owner_runtime(runtime, monkeypatch, tmp_path, kernel_options={
        'budget_ledger': budget, 'loop_detector': loop,
    }) as state:
        (queue, worker, channel, sandbox, delivered, finished, cards, _acks,
         spawns, answers, _turns, _owners, _env, _requests, invocation) = state
        entered, release = asyncio.Event(), asyncio.Event()
        original = sandbox.execute_shell

        async def paused(command):
            entered.set()
            await release.wait()
            return await original(command)

        sandbox.execute_shell = paused
        await _wait_for_offer(delivered, finished, answers)
        await channel._handle_update({'callback_query': _callback(cards)})
        await asyncio.wait_for(entered.wait(), 2)
        if floor in {'ask', 'off'}:
            worker.policy.mode = floor
        elif floor == 'budget':
            budget.add_tokens(2)
        elif floor == 'loop':
            for _ in range(loop.max_repeats + 1):
                loop.record('terminal.exec')
        elif floor == 'kill':
            runtime[2].kill_switch.is_halted = lambda *_args: True
        else:
            def unreadable(*_args):
                raise OSError('private store contents')

            runtime[2].kill_switch.is_halted = unreadable
        recorded = len(loop._events)
        release.set()
        await asyncio.wait_for(invocation, 2)
        assert answers[0]['ok'] is False and spawns == []
        assert queue.get(answers[0]['task_id']).status == 'failed'
        assert len(loop._events) == recorded, 'final revalidation must not record another loop event'


async def test_enforced_owner_invocation_composes_b7_and_one_physical_dispatch(
    runtime, monkeypatch, tmp_path,
):
    from agents.core.autonomy.mediation import MonotonicHeadAnchor
    from agents.core.autonomy.queue import TaskQueue

    old_queue, worker, orch, sandbox, seen = runtime
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(
        str(tmp_path / 'enforced-actuation.db'), mediation_mode='enforce',
        mediation_signer=old_queue._mediation_signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_classifier=lambda _kind: True, mediation_scope='global',
    ).initialize()
    worker.queue = queue
    orch.autonomy_queue = queue
    try:
        async with _owner_runtime((queue, worker, orch, sandbox, seen), monkeypatch, tmp_path) as state:
            (_queue, _worker, channel, _sandbox, delivered, finished, cards, _acks,
             spawns, answers, _turns, _owners, _env, _requests, invocation) = state
            await _wait_for_offer(delivered, finished, answers)
            await worker.tick()
            assert spawns == []
            await channel._handle_update({'callback_query': _callback(cards)})
            await asyncio.wait_for(invocation, 2)
            assert answers[0]['ok'] is True, answers
            task = queue.get(answers[0]['task_id'])
            assert task.status == 'done' and task.attempts == 1
            assert queue.verify_owner_once_terminal_result(task.id)
            assert queue.verified_mediation_stats()['governed'] == 1
            assert len(spawns) == 1
    finally:
        queue.close()
        worker.queue = old_queue
        orch.autonomy_queue = old_queue
