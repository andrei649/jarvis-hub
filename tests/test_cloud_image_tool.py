"""Model image proposals reuse one signed cloud task, never a second approval."""
from types import SimpleNamespace

import pytest

from tests.test_cloud_image import cloud  # noqa: F401


@pytest.fixture
def tool(cloud):
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    orch = SimpleNamespace(agents={}, autonomy=cloud.worker, autonomy_queue=cloud.queue,
                           cloud_images=cloud.runtime, intent_log=None, secret_broker=None)
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=cloud.worker.kernel_gate)
    return SimpleNamespace(orch=orch, coordinator=coordinator, server=orch.tool_rpc)


@pytest.mark.asyncio
async def test_cloud_tool_uses_single_signed_task_and_trusted_actor(cloud, tool):
    from agents.core.media_library import gallery_page, read_catalog_blob

    response = await tool.server.handle({'tool': 'image_generate', 'args': {
        'cloud': True, 'prompt': 'blue square', 'backend': 'openai', 'quality': 'low',
    }}, actor='athena')
    assert response['reason'] == 'approval_required', response
    task_id = response['task_id']
    task = cloud.queue.get(task_id)
    assert task.kind == 'plugin.egress' and task.agent == 'athena'
    assert task.status == 'blocked' and task.autonomy_level == 'ask'
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 1
    assert not cloud.requests
    await cloud.worker.apply_decision(task_id, 'accept', decided_by='test owner')
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert task.result['status'] == 'ok', task.result
    assert len(cloud.requests) == 1
    rows = gallery_page(cloud.root, generated=True)['items']
    assert len(rows) == 1 and rows[0]['available'] and rows[0]['cloud']
    assert read_catalog_blob(rows[0]['id'], cloud.root)[1].startswith(b'\x89PNG')


@pytest.mark.asyncio
@pytest.mark.parametrize('extra', [
    {'cloud': 'true'}, {'cloud': 1}, {'cloud': None}, {'seed': 2}, {'width': 512},
    {'reference': 'a' * 32}, {'references': ['a' * 32]}, {'upscale': 2},
    {'strength': 10}, {'steps': 5}, {'backend': 'comfyui'}, {'model': 'other'},
    {'size': 'auto'}, {'quality': 'auto'}, {'actor': 'jarvis'}, {'origin': 'user'},
    {'_binding': {}}, {'endpoint': 'https://other.invalid'},
])
async def test_invalid_cloud_arguments_never_enqueue(cloud, tool, extra):
    result = await tool.server.handle({'tool': 'image_generate', 'args': {
        'cloud': True, 'prompt': 'blue square', **extra,
    }})
    assert 'task_id' not in result and result['ok'] is False
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 0
    assert not cloud.requests


@pytest.mark.asyncio
async def test_missing_runtime_is_lazy_and_never_falls_back(cloud, tool):
    tool.orch.cloud_images = None
    request = {'tool': 'image_generate', 'args': {'cloud': True, 'prompt': 'blue square'}}
    assert (await tool.server.handle(request))['reason'] == 'cloud_image_unavailable'
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 0
    tool.orch.cloud_images = cloud.runtime
    assert (await tool.server.handle(request))['reason'] == 'approval_required'
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 1


@pytest.mark.asyncio
async def test_inbound_origin_is_not_downgraded(cloud, tool):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    token = bind_action_origin('inbound')
    try:
        result = await tool.server.handle({'tool': 'image_generate', 'args': {
            'cloud': True, 'prompt': 'blue square',
        }}, actor='athena')
    finally:
        reset_action_origin(token)
    task = cloud.queue.get(result['task_id'])
    assert task.origin == 'inbound' and task.payload['tainted'] is True
    assert task.agent == 'athena' and task.status == 'blocked'
    assert not cloud.requests


@pytest.mark.asyncio
async def test_cloud_arguments_cannot_execute_as_local_tool_task(cloud, tool):
    from agents.core.autonomy_coordinator import _APPROVED_TASK
    from agents.core.tool_rpc import ToolRPCValidationError

    dispatcher = tool.server._tools['image_generate']['gated_intake'].__self__
    args = {'cloud': True, 'prompt': 'blue square'}
    token = _APPROVED_TASK.set(SimpleNamespace(kind='tool.rpc'))
    try:
        with pytest.raises(ToolRPCValidationError, match='cloud_worker_required'):
            dispatcher.preflight(args)
    finally:
        _APPROVED_TASK.reset(token)
    assert (await dispatcher.execute(args))['status'] == 'failed'
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 0
    assert not cloud.requests


@pytest.mark.asyncio
async def test_real_agent_loop_stops_after_one_cloud_proposal(cloud, tool):
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolTurn
    from tests.test_agent_runtime_v2 import _call, _run, _ScriptedBackend

    backend = _ScriptedBackend([
        ToolTurn(tool_calls=(_call('image_generate', call_id='image-1', arguments={
            'cloud': True, 'prompt': 'blue square',
        }),)),
        ToolTurn(content='must not request another turn'),
    ])
    answer = await _run(AgentToolRuntime(tool.server, enabled=lambda: True), backend,
                        agent_id='athena')
    assert 'approval' in answer.lower()
    assert len(backend.calls) == 1
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 1
    assert not cloud.requests


@pytest.mark.asyncio
async def test_cancelled_tool_proposal_execution_cannot_replay_after_restart(cloud, tool):
    import asyncio

    import httpx

    from agents.core.cloud_image_runtime import CloudImageRuntime

    ready = asyncio.Event()
    async def transport(request):
        cloud.requests.append(request)
        ready.set()
        await asyncio.Event().wait()
    cloud.runtime.transport_factory = lambda target: httpx.MockTransport(transport)
    result = await tool.server.handle({'tool': 'image_generate', 'args': {
        'cloud': True, 'prompt': 'blue square',
    }})
    await cloud.worker.apply_decision(result['task_id'], 'accept', decided_by='test owner')
    running = asyncio.create_task(cloud.worker.tick())
    await asyncio.wait_for(ready.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    restarted = CloudImageRuntime(cloud.worker, kernel=cloud.kernel,
        redact=lambda value: value, root=cloud.root, key=lambda: cloud.state.key)
    task = cloud.queue.get(result['task_id'])
    assert (await restarted.execute(task))['status'] == 'refused'
    assert len(cloud.requests) == 1
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 1


@pytest.mark.asyncio
async def test_ambiguous_enqueue_is_not_retried_or_logged_with_prompt(cloud, tool, monkeypatch, caplog):
    original = cloud.runtime.submit
    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('private prompt and credential')
    monkeypatch.setattr(cloud.runtime, 'submit', lost_ack)
    result = await tool.server.handle({'tool': 'image_generate', 'args': {
        'cloud': True, 'prompt': 'blue square',
    }})
    assert result['reason'] == 'cloud_image_proposal_refused' and 'task_id' not in result
    assert cloud.queue.verified_mediation_stats()['authorized_enqueue'] == 1
    assert 'private prompt and credential' not in caplog.text
    assert not cloud.requests


@pytest.mark.asyncio
async def test_explicit_local_selector_preserves_approved_local_binding(monkeypatch):
    from agents.core.image_tool_dispatcher import ImageToolDispatcher

    captured = []
    normalized = {'prompt': 'edit', 'reference': 'a' * 32, 'seed': 7, '_binding': {'nonce': 'n'}}
    local = SimpleNamespace(preflight=lambda args: captured.append(args) or normalized)
    dispatcher = ImageToolDispatcher(local, cloud_runtime=lambda: pytest.fail('cloud lookup'),
                                     approved_task=lambda: None)
    assert dispatcher.preflight({'cloud': False, 'prompt': 'edit', 'reference': 'a' * 32}) is normalized
    assert captured == [{'prompt': 'edit', 'reference': 'a' * 32}]
