"""H367 physical send for one durable owner-approved compatible endpoint."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import weakref
from contextlib import contextmanager
from contextvars import ContextVar

import httpcore
import httpx

from agents.core import settings_db
from agents.core.security.ssrf import resolve_and_validate
from agents.core.turn_usage import record_dispatch

from .. import custom_endpoint_consent as consent
from .. import custom_endpoints as metadata
from ..egress import _record, is_custom_request, llm_async_client, mark_custom_request
from . import selection_gates
from .packages import ProviderPackageError

_VALIDATION_SCOPE: ContextVar[object | None] = ContextVar('custom_validation_scope', default=None)


@contextmanager
def validation_scope(ticket):
    token = _VALIDATION_SCOPE.set(ticket)
    try:
        yield
    finally:
        _VALIDATION_SCOPE.reset(token)


class CustomEndpointRuntime:
    """No credential bytes or socket are retained on this runtime or backend."""

    def __init__(self, service, endpoint, choice):
        from ..custom_endpoint_service import profile_for

        self.service = service
        self.endpoint = endpoint
        self.choice = choice
        self.profile = profile_for(endpoint)
        self.active = True
        self.backend = None
        self.router = None
        self.check()

    @classmethod
    def from_current(cls, service):
        choice = metadata.read_choice()
        if choice.active_key is None:
            return None
        endpoint = metadata.read_active_endpoint()
        return cls(service, endpoint, choice)

    def check_locked(self):
        from ..provider_selection import _row as signed_row

        if not self.active or self.service.enabled() is not True:
            raise ProviderPackageError('custom endpoint retired')
        conn = settings_db.get_conn()
        try:
            choice = metadata._choice(conn)
            signed_revision, signed = signed_row(conn)
            if signed is not None or type(signed_revision) is not int:
                raise ProviderPackageError('effective provider choice changed')
            endpoint = self.service._current(conn, self.endpoint.key)
        finally:
            conn.close()
        if (choice != self.choice
                or endpoint.key != self.endpoint.key
                or endpoint.base_url != self.endpoint.base_url
                or endpoint.model != self.endpoint.model
                or endpoint.auth_type != self.endpoint.auth_type
                or endpoint.data_policy != self.endpoint.data_policy
                or endpoint.config_revision != self.endpoint.config_revision
                or not consent.verify(self.service.root, self.service.home,
                                      endpoint, choice)):
            raise ProviderPackageError('custom endpoint consent or scope changed')
        status = self.service._credential_status(endpoint)
        if (status['generation'] != choice.credential_generation
                or endpoint.auth_type != 'none' and not status['configured']):
            raise ProviderPackageError('custom endpoint credential changed')
        return endpoint

    def check(self):
        with selection_gates.shared(settings_db.DB_PATH):
            return self.check_locked()

    def proven_consent(self):
        try:
            self.check()
            return True
        except Exception:
            return False

    def bind_backend(self, backend, router):
        if (self.backend is not None or backend is None or router is None
                or getattr(backend, '_custom_endpoint_runtime', None) is not self):
            raise ProviderPackageError('custom backend binding refused')
        self.backend, self.router = backend, router

    def retire(self):
        self.active = False

    def scope_material(self):
        e, c = self.endpoint, self.choice
        return ['custom-endpoint-owner-v1', self.service.home, e.key, e.base_url,
                e.model, e.auth_type, e.data_policy, e.config_revision,
                c.epoch, c.credential_generation, c.unknown_price_ack,
                c.data_policy_ack]

    async def resolve_address(self):
        endpoint = self.endpoint
        host = httpx.URL(endpoint.base_url).host
        kind = endpoint.destination_class
        addresses, error = await asyncio.to_thread(
            resolve_and_validate, host, mode='public' if kind == 'public' else 'lan')
        if error or not addresses:
            raise ProviderPackageError('custom endpoint DNS refused')
        for address in addresses:
            literal = ipaddress.ip_address(address)
            if (kind == 'loopback' and not literal.is_loopback
                    or kind == 'lan' and not (
                        isinstance(literal, ipaddress.IPv4Address)
                        and literal.is_private and not literal.is_loopback
                        and not literal.is_link_local and not literal.is_reserved)
                    or kind == 'public' and not literal.is_global):
                raise ProviderPackageError('custom endpoint DNS refused')
            checked, refusal = resolve_and_validate(
                address, mode='public' if kind == 'public' else 'lan')
            if refusal or checked != [address]:
                raise ProviderPackageError('custom endpoint DNS refused')
        return addresses[0]

    def wire_request(self, request, address, key, *, validation=False):
        endpoint = httpx.URL(self.endpoint.base_url)
        logical = request.url
        if (logical.scheme != endpoint.scheme or logical.host != endpoint.host
                or logical.port != endpoint.port or logical.userinfo or logical.fragment
                or logical.query or 'cookie' in request.headers
                or 'proxy-authorization' in request.headers):
            raise ProviderPackageError('custom request destination changed')
        allowed = (request.method == 'POST' and
                   logical.path == endpoint.path.rstrip('/') + '/chat/completions')
        if validation:
            allowed = (request.method == 'GET' and
                       logical.path == endpoint.path.rstrip('/') + '/models')
        if not allowed:
            raise ProviderPackageError('custom request path refused')
        if not validation:
            try:
                body = json.loads(request.content)
                if type(body) is not dict or body.get('model') != self.endpoint.model:
                    raise ValueError
            except (ValueError, TypeError, httpx.RequestNotRead) as exc:
                raise ProviderPackageError('custom request model refused') from exc
        headers = httpx.Headers(request.headers)
        if any(name in headers for name in ('authorization', 'x-api-key', 'cookie')):
            raise ProviderPackageError('custom request carried ambient credential')
        if self.endpoint.auth_type == 'none':
            if key not in (None, ''):
                raise ProviderPackageError('custom credential unexpected')
        elif type(key) is not str or not key:
            raise ProviderPackageError('custom credential unavailable')
        elif self.endpoint.auth_type == 'bearer':
            headers['Authorization'] = 'Bearer ' + key
        else:
            headers['x-api-key'] = key
        authority = logical.host
        if logical.port not in (None, 80 if logical.scheme == 'http' else 443):
            authority += ':' + str(logical.port)
        headers['Host'] = authority
        extensions = {k: v for k, v in request.extensions.items()
                      if k not in {'nerva.custom', 'nerva.admitted'}}
        extensions['sni_hostname'] = logical.host
        return httpx.Request(request.method, logical.copy_with(host=address),
                             headers=headers, content=request.content,
                             extensions=extensions)


class _CustomBody(httpx.AsyncByteStream):
    def __init__(self, inner, pool, lease):
        self.inner, self.pool, self.lease = inner, pool, lease
        self.closed = False
        self._closing = None

    async def __aiter__(self):
        try:
            async for chunk in self.inner:
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._finish())
        await asyncio.shield(self._closing)

    async def _finish(self):
        try:
            await self.inner.aclose()
            if self.pool is not None:
                await self.pool.aclose()
        except BaseException:
            # An uncertain socket cannot release a lease and claim mutation safe.
            _UNCERTAIN.append((self.pool, self.lease))
            raise
        self.lease.close()
        self.closed = True


_UNCERTAIN = []


class CustomEndpointTransport(httpx.AsyncBaseTransport):
    def __init__(self, runtime, inner=None):
        self.runtime = runtime
        if inner is not None and type(inner) is not httpx.MockTransport:
            raise ProviderPackageError('custom transport inner unavailable')
        self.inner = inner
        self.client = None
        self._hooks = ()
        self._streams = weakref.WeakSet()

    def bind(self, client):
        self.client = client
        self._hooks = tuple(client.event_hooks['request'])
        return client

    def _check_client(self, request):
        from ..direct_transport import _NATIVE_ROUTE_SELECTOR

        client = self.client
        selector = client._transport_for_url
        if (type(client) is not httpx.AsyncClient or client._transport is not self
                or client._mounts or client._trust_env or client.follow_redirects
                or getattr(selector, '__func__', None) is not _NATIVE_ROUTE_SELECTOR
                or getattr(selector, '__self__', None) is not client
                or selector(request.url) is not self
                or tuple(client.event_hooks['request']) != self._hooks
                or not is_custom_request(request)
                or set(request.extensions) - {'timeout', 'nerva.custom'}):
            raise ProviderPackageError('custom physical route unavailable')

    async def handle_async_request(self, request):
        from agents.core.tls_trust import verify_for

        from ..data_handling import authorize, check_physical_request

        runtime = self.runtime
        lease = pool = wire = response = None
        entered = accounted = handed = False
        try:
            self._check_client(request)
            if runtime.backend is None or runtime.router is None:
                raise ProviderPackageError('custom routed backend unavailable')
            address = await runtime.resolve_address()
            await asyncio.to_thread(runtime.check)
            await check_physical_request(request)
            authorize(runtime.router, runtime.backend, runtime.endpoint.model,
                      route='cloud-compatible')
            lease = await selection_gates.acquire_shared_async(settings_db.DB_PATH)
            runtime.check_locked()
            self._check_client(request)
            # The route and durable consent are rechecked after the last await.
            key = ('' if runtime.endpoint.auth_type == 'none' else
                   await asyncio.to_thread(runtime.service._credentials().read,
                                           runtime.service._binding(runtime.endpoint),
                                           runtime.choice.credential_generation))
            runtime.check_locked()
            self._check_client(request)
            await check_physical_request(request)
            runtime.check_locked()
            validation = request.method == 'GET'
            if validation and not consent.consume_validation(_VALIDATION_SCOPE.get(), runtime):
                raise ProviderPackageError('custom validation receipt unavailable')
            wire = runtime.wire_request(request, address, key, validation=validation)
            if self.inner is not None:
                pool = self.inner
            else:
                trust = verify_for(runtime.profile.id, runtime.endpoint.base_url)
                if trust is False:
                    raise ProviderPackageError('custom TLS trust unavailable')
                pool = httpx.AsyncHTTPTransport(verify=trust, trust_env=False)
                if type(pool._pool) is not httpcore.AsyncConnectionPool:
                    raise ProviderPackageError('custom direct transport unavailable')
            entered = True
            try:
                response = await pool.handle_async_request(wire)
            finally:
                for name in ('authorization', 'x-api-key'):
                    wire.headers.pop(name, None)
            if response.status_code >= 300:
                status = response.status_code
                await response.aclose()
                _record(runtime.profile.id, wire, allowed=True,
                        reason='custom endpoint refused status; request possibly sent')
                record_dispatch(runtime.profile.id, wire)
                accounted = True
                return httpx.Response(status, content=b'{"error":"custom_request_failed"}',
                                      headers={'content-type': 'application/json'}, request=request)
            response.stream = _CustomBody(response.stream, pool if pool is not self.inner else None, lease)
            self._streams.add(response.stream)
            _record(runtime.profile.id, wire, allowed=True)
            record_dispatch(runtime.profile.id, wire)
            handed = accounted = True
            return response
        except BaseException as exc:
            if not accounted:
                _record(runtime.profile.id, wire or request, allowed=entered,
                        reason=('custom transport entered; request possibly sent' if entered else
                                'custom physical request refused before transport'))
                if entered:
                    record_dispatch(runtime.profile.id, wire or request)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, httpx.TimeoutException):
                raise type(exc)('custom endpoint timeout', request=request) from exc
            if isinstance(exc, httpx.TransportError):
                raise httpx.ConnectError('custom endpoint transport failed', request=request) from exc
            raise ProviderPackageError('custom physical request refused') from exc
        finally:
            if not handed:
                try:
                    if response is not None:
                        await response.aclose()
                    if pool is not None and pool is not self.inner:
                        await pool.aclose()
                except BaseException:
                    if lease is not None:
                        _UNCERTAIN.append((pool, lease))
                else:
                    if lease is not None:
                        lease.close()

    async def aclose(self):
        for stream in tuple(self._streams):
            await stream.aclose()
        if self.inner is not None:
            await self.inner.aclose()


def custom_client(runtime: CustomEndpointRuntime, *, inner=None):
    if type(runtime) is not CustomEndpointRuntime:
        raise ProviderPackageError('current custom runtime required')
    runtime.check()
    transport = CustomEndpointTransport(runtime, inner)

    async def mark(request):
        mark_custom_request(request)

    client = llm_async_client(runtime.profile.id, base_url=runtime.endpoint.base_url,
                              timeout=120.0, transport=transport, follow_redirects=False,
                              trust_env=False, event_hooks={'request': [mark]})
    return transport.bind(client)


def require_custom_client(client, runtime):
    if (type(client) is not httpx.AsyncClient
            or type(client._transport) is not CustomEndpointTransport
            or client._transport.runtime is not runtime
            or client._transport.client is not client):
        raise ProviderPackageError('custom client changed')
    return client
