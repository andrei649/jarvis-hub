import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from agents.core.hermes_runtime.client import HermesRPCClient, RuntimeUnavailable
from agents.core.hermes_runtime.policy import RuntimeDenied


@pytest.mark.asyncio
async def test_transport_correlates_requests_events_and_once_only_replies():
    received = []

    async def handler(ws):
        request = json.loads(await ws.recv())
        await ws.send(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': {'pong': True}}))
        await ws.send(json.dumps({'jsonrpc': '2.0', 'id': 'ask1', 'method': 'clarify', 'params': {}}))
        received.append(json.loads(await ws.recv()))
        await ws.wait_closed()

    async with serve(handler, '127.0.0.1', 0) as server:
        client = HermesRPCClient(f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}', 'private', 'g1')
        try:
            assert await client.rpc('ping', {}) == {'pong': True}
            events = client.events()
            request = await asyncio.wait_for(anext(events), 2)
            assert request['generation'] == 'g1'
            with pytest.raises(RuntimeUnavailable):
                await client.reply({'id': 'ask1', 'result': {}, 'generation': 'old'})
            assert await client.reply({'jsonrpc': '2.0', 'id': 'ask1', 'result': {'answer': 'yes'}, 'generation': 'g1'}) == {'ok': True}
            with pytest.raises(RuntimeUnavailable):
                await client.reply({'id': 'ask1', 'result': {}, 'generation': 'g1'})
            await events.aclose()
        finally:
            await client.close()
    assert received == [{'jsonrpc': '2.0', 'id': 'ask1', 'result': {'answer': 'yes'}}]


@pytest.mark.asyncio
async def test_accepted_operation_is_not_replayed_after_disconnect():
    accepted = []

    async def handler(ws):
        accepted.append(json.loads(await ws.recv()))
        await ws.close()

    async with serve(handler, '127.0.0.1', 0) as server:
        client = HermesRPCClient(f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}', 'private', 'g1')
        try:
            with pytest.raises(RuntimeUnavailable, match='outcome is unknown'):
                await client.rpc('session.create', {})
            assert len(accepted) == 1
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_upstream_kernel_queue_remains_pending_not_success():
    async def handler(ws):
        request = json.loads(await ws.recv())
        await ws.send(json.dumps({'jsonrpc': '2.0', 'id': request['id'],
            'error': {'code': 4030, 'message': 'approval required', 'data': {'jarvis_verdict': 'queue'}}}))
        await ws.wait_closed()

    async with serve(handler, '127.0.0.1', 0) as server:
        client = HermesRPCClient(f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}', 'private', 'g1')
        try:
            with pytest.raises(RuntimeDenied) as caught:
                await client.rpc('shell.exec', {})
            assert caught.value.verdict == 'queue'
        finally:
            await client.close()
