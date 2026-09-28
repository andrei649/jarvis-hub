"""Exact asynchronous HTTPX route proof, entirely offline."""
import httpx
import pytest

from agents.core.llm.data_handling import DataHandlingRefused
from agents.core.llm.direct_transport import require_direct_async_transport

URL = httpx.URL('http://127.0.0.1:1234/v1/chat/completions')


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['native', 'mock', 'native_mount', 'mock_mount'])
async def test_direct_selected_transport_passes_without_io(route):
    options = {'trust_env': False}
    if route == 'mock':
        options['transport'] = httpx.MockTransport(lambda r: pytest.fail('validator performed I/O'))
    elif route.endswith('mount'):
        mount = (httpx.AsyncHTTPTransport() if route == 'native_mount' else
                 httpx.MockTransport(lambda r: pytest.fail('validator performed I/O')))
        options.update(proxy='http://remote-proxy.invalid:8888', mounts={'http://127.0.0.1': mount})
    async with httpx.AsyncClient(**options) as client:
        assert require_direct_async_transport(client, URL) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['proxy', 'proxy_mount', 'opaque', 'class_selector', 'instance_selector', 'dispatch_subclass', 'native_class_selector', 'asgi'])
async def test_proxy_or_unverified_selected_route_refused(route, monkeypatch):
    options = {'trust_env': False}
    client_type = httpx.AsyncClient
    if route == 'proxy':
        options['proxy'] = 'http://remote-proxy.invalid:8888'
    elif route == 'proxy_mount':
        options['mounts'] = {'http://': httpx.AsyncHTTPTransport(proxy='http://remote-proxy.invalid:8888')}
    elif route == 'opaque':
        class Opaque(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                pytest.fail('opaque transport invoked')
        options['transport'] = Opaque()
    elif route == 'asgi':
        options['transport'] = httpx.ASGITransport(app=None)
    elif route == 'dispatch_subclass':
        class CustomDispatch(httpx.AsyncClient):
            async def _send_single_request(self, request):
                pytest.fail('custom dispatch invoked')
        client_type = CustomDispatch
    elif route == 'class_selector':
        class CustomSelector(httpx.AsyncClient):
            def _transport_for_url(self, url):
                return self._transport
        client_type = CustomSelector
    async with client_type(**options) as client:
        if route == 'native_class_selector':
            native = httpx.AsyncClient._transport_for_url
            monkeypatch.setattr(httpx.AsyncClient, '_transport_for_url', lambda self, url: native(self, url))
        if route == 'instance_selector':
            client._transport_for_url = lambda url: client._transport
        with pytest.raises(DataHandlingRefused):
            require_direct_async_transport(client, URL)


def test_wrong_client_and_unreadable_route_fail_closed():
    with pytest.raises(DataHandlingRefused):
        require_direct_async_transport(object(), URL)
    with httpx.Client(trust_env=False) as client, pytest.raises(DataHandlingRefused):
        require_direct_async_transport(client, URL)
