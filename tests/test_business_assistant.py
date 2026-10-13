from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core.business import assistant


async def test_local_only_refuses_cloud_before_generation(monkeypatch):
    backend=SimpleNamespace(generate=AsyncMock(return_value='answer'))
    router=SimpleNamespace(select_backend=lambda *a:(backend,'model','cloud-compatible'),
        check_data_handling=lambda *a:None)
    monkeypatch.setattr(assistant,'get_orch',lambda:SimpleNamespace(llm_router=router))
    with pytest.raises(ValueError,match='local'):
        await assistant.answer_question('Sales?', {'reports':[]},True)
    backend.generate.assert_not_awaited()


async def test_assistant_uses_existing_policy_and_no_tools(monkeypatch):
    backend=SimpleNamespace(generate=AsyncMock(return_value='42 RON'))
    checked=[]
    router=SimpleNamespace(select_backend=lambda *a:(backend,'model','local'),
        check_data_handling=lambda *a:(checked.append(a) or {'policy':'local'}))
    monkeypatch.setattr(assistant,'get_orch',lambda:SimpleNamespace(llm_router=router))
    result=await assistant.answer_question('Sales?', {'reports':[{'total':'42 RON'}]},True)
    assert result['answer']=='42 RON'
    assert checked
    kwargs=backend.generate.call_args.kwargs
    assert '42 RON' in kwargs['prompt']
    assert 'tools' not in kwargs


async def test_missing_model_has_honest_error(monkeypatch):
    monkeypatch.setattr(assistant,'get_orch',lambda:None)
    with pytest.raises(ValueError):
        await assistant.answer_question('Sales?',{},True)


async def test_internal_router_error_is_sanitized(monkeypatch):
    def select(*args):
        raise ValueError('provider-secret-not-for-users')
    monkeypatch.setattr(assistant, 'get_orch', lambda: SimpleNamespace(
        llm_router=SimpleNamespace(select_backend=select)))
    with pytest.raises(assistant.BusinessAIError) as exc:
        await assistant.answer_question('Sales?', {}, False)
    assert 'provider-secret' not in str(exc.value)


async def test_local_label_does_not_override_physical_cloud_policy(monkeypatch):
    backend = SimpleNamespace(generate=AsyncMock(return_value='answer'))
    router = SimpleNamespace(select_backend=lambda *a: (backend, 'model', 'local'),
        check_data_handling=lambda *a: {'policy': 'unknown'})
    monkeypatch.setattr(assistant, 'get_orch', lambda: SimpleNamespace(llm_router=router))
    with pytest.raises(assistant.BusinessAIError, match='loopback'):
        await assistant.answer_question('Sales?', {}, True)
    backend.generate.assert_not_awaited()


async def test_three_requests_run_and_fourth_is_refused(monkeypatch):
    import asyncio
    started = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def generate(**kwargs):
        nonlocal count
        count += 1
        if count == 3:
            started.set()
        await release.wait()
        return 'answer'

    backend = SimpleNamespace(generate=generate)
    router = SimpleNamespace(select_backend=lambda *a: (backend, 'model', 'local'),
        check_data_handling=lambda *a: {'policy': 'local'})
    monkeypatch.setattr(assistant, 'get_orch', lambda: SimpleNamespace(llm_router=router))
    pending = [asyncio.create_task(assistant.answer_question('Sales?', {}, True)) for _ in range(3)]
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(assistant.BusinessAIError, match='ocupate'):
            await assistant.answer_question('Sales?', {}, True)
    finally:
        release.set()
        await asyncio.gather(*pending)
    assert count == 3
    assert (await assistant.answer_question('Sales?', {}, True))['answer'] == 'answer'
