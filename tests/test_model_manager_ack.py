"""Strict residency receipts; no GPU or live controller required."""
import asyncio

import httpx
import pytest

from agents.core.llm.model_manager import (
    LMStudioControllerAdapter,
    ModelManager,
    OllamaControllerAdapter,
)


def manager(controller=None):
    return ModelManager(controller, enabled=True, vram_total_mb=10,
                        vram_reserve_mb=0, default_size_mb=10)


class LMS:
    def __init__(self):
        self.status = 'ok'
        self.calls = []
        self.cancel = False

    async def load_model(self, model, agent):
        self.calls.append(('load', model))
        return {'status': self.status, 'kind': 'lmstudio_control', 'action': 'load_model',
                    'model': model, 'exit_code': 0}

    async def unload_model(self, model, agent):
        self.calls.append(('unload', model))
        if self.cancel:
            raise asyncio.CancelledError
        return {'status': self.status, 'kind': 'lmstudio_control', 'action': 'unload_model',
                    'model': model, 'exit_code': 0}


@pytest.mark.parametrize('status', ['blocked', 'disabled', 'failed', 'rejected', 'ambiguous', None, True])
async def test_refused_load_never_confirms(status):
    controller = LMS()
    controller.status = status
    mgr = manager(LMStudioControllerAdapter(controller))
    await mgr.ensure_resident('a')
    assert mgr.resident_models == []
    assert mgr.used_mb() == 0


async def test_refused_unload_retains_old_and_stops_replacement():
    controller = LMS()
    mgr = manager(LMStudioControllerAdapter(controller))
    await mgr.ensure_resident('a')
    controller.status = 'blocked'
    await mgr.ensure_resident('b')
    assert mgr.resident_models == ['a']
    assert mgr.used_mb() == 10
    assert controller.calls == [('load', 'a'), ('unload', 'a')]


async def test_cancelled_unload_keeps_old_and_releases_lock():
    controller = LMS()
    mgr = manager(LMStudioControllerAdapter(controller))
    await mgr.ensure_resident('a')
    controller.cancel = True
    with pytest.raises(asyncio.CancelledError):
        await mgr.ensure_resident('b')
    assert mgr.resident_models == ['a']
    assert not mgr._lock.locked()


async def test_no_controller_and_nested_using_do_not_invent_residency():
    mgr = manager()
    await mgr.ensure_resident('a')
    async with mgr.using('a'):
        async with mgr.using('a'):
            assert mgr.resident_models == []
        assert mgr.resident_models == []
    assert mgr.resident_models == []


@pytest.mark.parametrize('patch', [{'model': 'canonical', 'resolved_from': 'a'}, {'action': 'unload_model'},
                                  {'kind': 'other'}, {'exit_code': 1}, {'exit_code': False}])
async def test_malformed_lms_receipt_is_not_residency(patch):
    class Invalid(LMS):
        async def load_model(self, model, agent):
            return {**await super().load_model(model, agent), **patch}
    mgr = manager(LMStudioControllerAdapter(Invalid()))
    await mgr.ensure_resident('a')
    assert not mgr.is_resident('a')


@pytest.mark.parametrize('status,body', [(500, {}), (200, {'error': 'failure'}), (200, []),
    (200, {'model': 'a', 'done': False, 'response': ''}),
    (200, {'model': 'a', 'done': 1, 'response': ''}),
    (200, {'model': 'other', 'done': True, 'response': ''}),
    (200, {'model': 'a', 'done': True, 'response': '', 'done_reason': 'unload'})])
async def test_ollama_negative_response_never_confirms(status, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body)), base_url='http://test') as client:
        mgr = manager(OllamaControllerAdapter(client))
        await mgr.ensure_resident('a')
        assert mgr.resident_models == []


async def test_ollama_unload_requires_unload_reason():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={'model': 'a', 'done': True, 'response': ''})), base_url='http://test') as client:
        mgr = manager(OllamaControllerAdapter(client))
        await mgr.ensure_resident('a')
        assert mgr.is_resident('a')
        await mgr.ensure_resident('b')
        assert mgr.resident_models == ['a']


@pytest.mark.parametrize('value', [None, True, {}, {'status': 'ok'}])
async def test_raw_controller_results_are_not_semantic_receipts(value):
    class Raw:
        async def load(self, model):
            return value
    mgr = manager(Raw())
    await mgr.ensure_resident('a')
    assert not mgr.is_resident('a')


async def test_cancelled_load_does_not_confirm_and_next_request_can_enter():
    class Cancel(LMS):
        async def load_model(self, model, agent):
            raise asyncio.CancelledError
    mgr = manager(LMStudioControllerAdapter(Cancel()))
    with pytest.raises(asyncio.CancelledError):
        await mgr.ensure_resident('a')
    assert mgr.resident_models == []
    async with asyncio.timeout(1):
        async with mgr.using('a'):
            assert mgr._active_refs == {'a': 1}
    assert mgr._active_refs == {}


async def test_concurrent_unknown_references_transfer_to_confirmed_load():
    controller = LMS()
    mgr = manager(LMStudioControllerAdapter(controller))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def generation():
        async with mgr.using('a'):
            entered.set()
            await release.wait()
    task = asyncio.create_task(generation())
    await entered.wait()
    try:
        async with mgr.using('a'):
            assert mgr._active_refs == {'a': 2}
            assert mgr.resident_models == []
            await mgr.ensure_resident('a')
            assert mgr._residents['a'].refs == 2
            # Existing best-effort overcommit remains, but the active model is not evicted.
            await mgr.ensure_resident('b')
            assert ('unload', 'a') not in controller.calls
        assert mgr._residents['a'].refs == 1
    finally:
        release.set()
        await task
    assert mgr._active_refs == {}
    assert mgr._residents['a'].refs == 0


async def test_cancelled_unknown_generation_releases_protection():
    mgr = manager()
    entered = asyncio.Event()

    async def generation():
        async with mgr.using('a'):
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(generation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr._active_refs == {}
    assert mgr.resident_models == []


async def test_simultaneous_ensures_acknowledge_single_load():
    controller = LMS()
    mgr = manager(LMStudioControllerAdapter(controller))
    await asyncio.gather(*(mgr.ensure_resident('a') for _ in range(5)))
    assert controller.calls == [('load', 'a')]
    assert mgr.resident_models == ['a']


@pytest.mark.parametrize('malformed', [None, [], 'ok', {'status': 'ok'}])
async def test_lms_malformed_container_is_not_confirmed(malformed):
    class Invalid(LMS):
        async def load_model(self, model, agent):
            return malformed
    mgr = manager(LMStudioControllerAdapter(Invalid()))
    await mgr.ensure_resident('a')
    assert mgr.resident_models == []


async def test_ollama_invalid_json_is_not_confirmed():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'not-json')), base_url='http://test') as client:
        mgr = manager(OllamaControllerAdapter(client))
        await mgr.ensure_resident('a')
        assert mgr.resident_models == []


@pytest.mark.parametrize('enabled', [False, True])
async def test_real_lms_disabled_or_denied_never_executes_or_confirms(enabled):
    from agents.core.llm.lmstudio_control import LMStudioController

    class Deny:
        def check_call(self, tool, agent):
            assert (tool, agent) == ('system-control', 'jarvis')
            return False

    async def forbidden(*args):
        raise AssertionError('controller must not execute')

    controller = LMStudioController(enabled=enabled, permission_gate=Deny(), exec_fn=forbidden)
    mgr = manager(LMStudioControllerAdapter(controller))
    await mgr.ensure_resident('a')
    assert mgr.resident_models == []
