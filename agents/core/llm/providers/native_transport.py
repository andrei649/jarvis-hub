"""One signed physical-send boundary for explicitly constructed native adapters.

The adapter's request hooks prepare and validate the logical request. This transport
checks the final HTTPX request and keeps the package grant through the actual send.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import weakref
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpcore
import httpx

from agents.core.turn_usage import physical_transport_entry, record_dispatch

from ..egress import _record, _recorder, llm_async_client, mark_admitted_request
from .admitted_profiles import AdmittedProviderProfile, current_signed_preparation
from .hook_runtime import ProviderHookRuntimeError

_AUTH_NAMES = frozenset({'authorization', 'x-api-key', 'x-goog-api-key', 'api-key'})
_PROTOCOL_BACKEND = {
    'openai-compatible': 'openai-compatible',
    'anthropic': 'anthropic', 'gemini': 'gemini', 'deepinfra-chat': 'openai-compatible',
    'openai-responses': 'openai-responses', 'xai-responses': 'xai',
}
_NATIVE_ATTEMPT: ContextVar[object | None] = ContextVar('native_signed_attempt', default=None)


@dataclass
class _Attempt:
    task: object
    profile: AdmittedProviderProfile
    package_hash: str
    model: str
    method: str
    url: str
    digest: str
    selected: object | None = None
    revision: int | None = None
    credential_generation: int | None = None
    used: bool = False


@contextmanager
def _attempt_scope(profile, prepared, client, method, url, *, headers=None, json_body=None,
                   content=None):
    if not isinstance(profile, AdmittedProviderProfile):
        yield
        return
    model = prepared._model
    if not current_signed_preparation(profile, prepared, model):
        raise ProviderHookRuntimeError('native_preparation_unavailable')
    kwargs = {'headers': headers}
    if json_body is not None:
        kwargs['json'] = json_body
    else:
        kwargs['content'] = content
    request = client.build_request(method, url, **kwargs)
    selected = getattr(client._transport, 'selected', None)
    ticket = _Attempt(asyncio.current_task(), profile, profile._package_hash, model,
                      request.method, str(request.url), hashlib.sha256(request.content).hexdigest(),
                      selected, selected.selection.revision if selected is not None else None,
                      selected.binding.credential_generation if selected is not None else None)
    token = _NATIVE_ATTEMPT.set(ticket)
    try:
        yield
    finally:
        _NATIVE_ATTEMPT.reset(token)


def _consume_attempt(request, profile, model, transport):
    ticket = _NATIVE_ATTEMPT.get()
    if (type(ticket) is not _Attempt or ticket.used or ticket.task is not asyncio.current_task()
            or ticket.profile is not profile or ticket.package_hash != profile._package_hash
            or ticket.model != model or ticket.method != request.method
            or ticket.url != str(request.url)
            or ticket.selected is not transport.selected
            or (ticket.selected is not None
                and (ticket.revision != ticket.selected.selection.revision
                     or ticket.credential_generation != ticket.selected.binding.credential_generation))
            or ticket.digest != hashlib.sha256(request.content).hexdigest()):
        raise ProviderHookRuntimeError('native_preparation_unavailable')
    ticket.used = True


async def native_post(profile, prepared, client, url, *, headers, json):
    with _attempt_scope(profile, prepared, client, 'POST', url, headers=headers, json_body=json):
        return await client.post(url, headers=headers, json=json)


@asynccontextmanager
async def native_stream(profile, prepared, client, method, url, *, headers, json=None, content=None):
    with _attempt_scope(profile, prepared, client, method, url, headers=headers,
                        json_body=json, content=content):
        async with client.stream(method, url, headers=headers, json=json, content=content) as response:
            yield response


def native_protocol_backend(profile):
    return _PROTOCOL_BACKEND.get(profile.backend_kind, profile.id)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate native request field')
        value[key] = item
    return value


class AdmittedNativeTransport(httpx.AsyncBaseTransport):
    """Exact request, direct route and signed dispatch lease for every attempt."""

    def __init__(self, profile, credential: str, model: str, inner, *, selected=None):
        if type(profile) is not AdmittedProviderProfile:
            raise ProviderHookRuntimeError('native_egress_unavailable')
        if (type(inner) is not httpx.MockTransport
                and not (type(inner) is httpx.AsyncHTTPTransport
                         and type(inner._pool) is httpcore.AsyncConnectionPool)):
            raise ProviderHookRuntimeError('native_egress_unavailable')
        self.profile = profile
        self.credential = credential
        self.model = model
        self.inner = inner
        self.selected = selected
        self.client = None
        self._request_hooks = ()
        self._response_hooks = ()
        self._streams = weakref.WeakSet()

    def bind(self, client):
        self.client = client
        return client

    def seal_hooks(self):
        self._request_hooks = tuple(self.client.event_hooks.get('request', ()))
        self._response_hooks = tuple(self.client.event_hooks.get('response', ()))

    def hooks_intact(self):
        client = self.client
        return (len(self._request_hooks) >= 3
                and len(self._response_hooks) >= 1
                and len(client.event_hooks.get('request', ())) == len(self._request_hooks)
                and all(a is b for a, b in zip(
                    client.event_hooks['request'], self._request_hooks, strict=True))
                and len(client.event_hooks.get('response', ())) == len(self._response_hooks)
                and all(a is b for a, b in zip(
                    client.event_hooks['response'], self._response_hooks, strict=True)))

    def _check(self, request):
        from ..direct_transport import _NATIVE_ROUTE_SELECTOR
        from ..egress import is_admitted_request

        client = self.client
        selector = client._transport_for_url
        if (type(client) is not httpx.AsyncClient or client._transport is not self
                or getattr(selector, '__func__', None) is not _NATIVE_ROUTE_SELECTOR
                or getattr(selector, '__self__', None) is not client
                or selector(request.url) is not self
                or client.follow_redirects or client._trust_env
                or client._mounts
                or (type(self.inner) is not httpx.MockTransport
                    and not (type(self.inner) is httpx.AsyncHTTPTransport
                             and type(self.inner._pool) is httpcore.AsyncConnectionPool))
                or not is_admitted_request(request)):
            raise ProviderHookRuntimeError('native_egress_unavailable')
        hooks = client.event_hooks.get('request', ())
        if (not self.hooks_intact()
                or sum(bool(getattr(hook, '_nerva_egress_recorder', False)) for hook in hooks) != 1):
            raise ProviderHookRuntimeError('native_egress_unavailable')
        profile = self.profile
        base = httpx.URL(str(profile.default_base_url).rstrip('/'))
        url = request.url
        if (url.scheme != 'https' or url.host != base.host or url.port != base.port
                or url.userinfo or url.fragment or 'cookie' in request.headers
                or 'proxy-authorization' in request.headers
                or request.headers.get('host') != (base.host if base.port in (None, 443) else
                                                   f'{base.host}:{base.port}')
                or set(request.extensions) - {'timeout', 'nerva.admitted'}):
            raise ProviderHookRuntimeError('native_egress_unavailable')
        kind = profile.backend_kind
        path = base.path.rstrip('/')
        if kind == 'gemini':
            stem = f'{path}/models/{self.model}'
            allowed = (
                request.method == 'POST'
                and (url == base.copy_with(path=stem + ':generateContent')
                     or url == base.copy_with(path=stem + ':streamGenerateContent', query=b'alt=sse'))
            )
        else:
            suffix = {'openai-compatible': '/chat/completions',
                      'anthropic': '/messages', 'deepinfra-chat': '/chat/completions',
                      'openai-responses': '/responses', 'xai-responses': '/responses'}.get(kind)
            allowed = (suffix is not None and request.method == 'POST'
                       and url == base.copy_with(path=path + suffix))
        if not allowed:
            raise ProviderHookRuntimeError('native_egress_unavailable')
        auth = {'anthropic': 'x-api-key', 'gemini': 'x-goog-api-key'}.get(kind, 'authorization')
        present = _AUTH_NAMES.intersection(request.headers)
        if profile.auth_type == 'none':
            if present:
                raise ProviderHookRuntimeError('native_egress_unavailable')
        else:
            expected = self.credential if auth != 'authorization' else 'Bearer ' + self.credential
            if present != {auth} or request.headers.get(auth) != expected:
                raise ProviderHookRuntimeError('native_egress_unavailable')
        try:
            body = json.loads(request.content, object_pairs_hook=_unique_object)
            if type(body) is not dict:
                raise ValueError
            if kind != 'gemini' and body.get('model') != self.model:
                raise ValueError
            if kind == 'gemini' and body.get('model', self.model) != self.model:
                raise ValueError
        except (ValueError, TypeError, httpx.RequestNotRead) as exc:
            raise ProviderHookRuntimeError('native_egress_unavailable') from exc

    async def handle_async_request(self, request):
        if self.selected is not None:
            return await self._selected_request(request)
        raise ProviderHookRuntimeError('native_egress_unavailable')

    async def _selected_request(self, request):
        """One selected physical attempt, with the logical Action and pinned wire copy."""
        from agents.core import settings_db
        from agents.core.kernel import Decision, Verdict
        from agents.core.llm import provider_selection
        from agents.core.llm.data_handling import _physical_guard, authorize, check_physical_request
        from agents.core.tls_trust import verify_for

        from . import lifecycle_gates, selection_gates
        from .credentials import credential_binding
        from .packages import _SIGNED_EGRESS_LEASE

        runtime = self.selected
        profile = self.profile
        selection_lease = lifecycle_lease = None
        attempt_inner = wire = response = entry = None
        entered = accounted = handed = False
        failure = None
        sanitized_response = None
        try:
            scope = _physical_guard.get()
            if (scope is None or not scope.active or runtime.backend is None
                    or runtime.router is None):
                raise ProviderHookRuntimeError('native_egress_unavailable')
            self._check(request)
            address = await runtime.resolve_public()
            await asyncio.to_thread(runtime.check)
            await check_physical_request(request)
            authorize(runtime.router, runtime.backend, runtime.binding.model,
                      route='cloud-compatible')
            self._check(request)
            selection_lease = await selection_gates.acquire_shared_async(settings_db.DB_PATH)
            lifecycle_lease = await lifecycle_gates.acquire_shared_async(
                runtime.service.root, profile.id)
            async with profile._hook_runtime.dispatch_lease(
                    profile.id, package_hash=profile._package_hash, home=profile._home):
                package_lease = _SIGNED_EGRESS_LEASE.get()
                if (package_lease is None or package_lease[0] is not profile._hook_runtime.packages
                        or package_lease[2] is not asyncio.current_task()):
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                record = package_lease[1]
                current = await asyncio.to_thread(provider_selection._read, settings_db.DB_PATH)
                if current != (runtime.selection.revision, runtime.binding):
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                runtime.validate_locked_record(record)
                await check_physical_request(request)
                authorize(runtime.router, runtime.backend, runtime.binding.model,
                          route='cloud-compatible')
                self._check(request)
                trust = None if type(self.inner) is httpx.MockTransport else verify_for(
                    profile.id, runtime.binding.endpoint)
                if trust is False:
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                _consume_attempt(request, profile, self.model, self)
                packages = profile._hook_runtime.packages
                decision = packages.authorize_native_egress(request, self)
                if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                        or decision.tier != 3):
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                scope = credential_binding(record, runtime.service.home)
                key = ('' if scope.auth_type == 'none' else await asyncio.to_thread(
                    runtime.service._credentials().read, scope,
                    runtime.binding.credential_generation))
                # Selection/lifecycle leases and the package record remain current
                # while the vault read awaits. Repeat the final request/policy checks.
                await check_physical_request(request)
                self._check(request)
                wire = runtime.wire_request(request, address, key)
                if type(self.inner) is httpx.MockTransport:
                    attempt_inner = self.inner
                else:
                    attempt_inner = httpx.AsyncHTTPTransport(
                        verify=trust, trust_env=False)
                entered = True
                entry = physical_transport_entry(request)
                try:
                    response = await attempt_inner.handle_async_request(wire)
                finally:
                    for name in _AUTH_NAMES:
                        wire.headers.pop(name, None)
                if response.status_code >= 300:
                    # A provider can echo the key in an error or redirect body.
                    # Keep only the numeric status used by retry classification.
                    status = response.status_code
                    await response.aclose()
                    accounted = True
                    _record(profile.id, request, allowed=True,
                            reason='selected provider returned a refused status; request possibly sent')
                    record_dispatch(profile.id, request, entry=entry)
                    if status < 400:
                        raise ProviderHookRuntimeError('native_egress_unavailable')
                    sanitized_response = httpx.Response(
                        status, content=b'{"error":"provider_request_failed"}',
                        headers={'content-type': 'application/json'}, request=request)
                else:
                    packages.track_native_response(profile.id, response)
                    response.stream = _SelectedBody(
                        response.stream, attempt_inner if attempt_inner is not self.inner else None,
                        selection_lease, lifecycle_lease, runtime.service.root, profile.id)
                    lifecycle_gates.register_body(runtime.service.root, profile.id, response.stream)
                    self._streams.add(response.stream)
                    handed = True
                    accounted = True
                    _record(profile.id, request, allowed=True)
                    record_dispatch(profile.id, request, entry=entry)
                    return response
        except BaseException as exc:
            if not accounted:
                _record(profile.id, request, allowed=entered,
                        reason=('selected transport entered; request possibly sent' if entered else
                                'selected physical request refused before transport'))
                if entered:
                    record_dispatch(profile.id, request, entry=entry)
            if isinstance(exc, asyncio.CancelledError):
                failure = asyncio.CancelledError()
            elif isinstance(exc, httpx.TimeoutException):
                failure = type(exc)('selected provider timeout', request=request)
            elif isinstance(exc, httpx.TransportError):
                failure = httpx.ConnectError('selected provider transport failed',
                                             request=request)
            elif (isinstance(exc, ProviderHookRuntimeError)
                  and exc.reason in {'native_preparation_unavailable',
                                     'native_egress_unavailable', 'not_runnable'}):
                failure = ProviderHookRuntimeError(exc.reason)
            else:
                failure = ProviderHookRuntimeError('native_egress_unavailable')
        finally:
            if not handed:
                try:
                    if response is not None:
                        await response.aclose()
                    if attempt_inner is not None and attempt_inner is not self.inner:
                        await attempt_inner.aclose()
                except BaseException:
                    # An uncertain attempt pool remains fenced until process
                    # shutdown; no owner mutation may claim completion.
                    from . import lifecycle_gates
                    lifecycle_gates.retain_uncertain(
                        runtime.service.root, profile.id, selection_lease, lifecycle_lease)
                    failure = ProviderHookRuntimeError('native_egress_unavailable')
                else:
                    if lifecycle_lease is not None:
                        lifecycle_lease.close()
                    if selection_lease is not None:
                        selection_lease.close()
        if failure is not None:
            raise failure
        return sanitized_response

    async def aclose(self):
        for stream in tuple(self._streams):
            await stream.aclose()
        await self.inner.aclose()


class _SelectedBody(httpx.AsyncByteStream):
    """Hold both cross-process leases until body and attempt pool finish closing."""

    def __init__(self, inner, pool, selection_lease, lifecycle_lease, root, provider):
        self.inner, self.pool = inner, pool
        self.selection_lease, self.lifecycle_lease = selection_lease, lifecycle_lease
        self.root, self.provider = root, provider
        self.loop = asyncio.get_running_loop()
        self.closed = False
        self.close_task = None
        self._closing_readers = ()

    async def __aiter__(self):
        try:
            async for chunk in self.inner:
                yield chunk
        finally:
            await self.aclose()

    async def _finish_close(self, readers):
        from . import lifecycle_gates
        from .packages import _join_reader_tasks

        # The tracked stream closes its origin-loop body without joining readers.
        # Readers may themselves be unwinding this wrapper's iterator, so join
        # them only after their own aclose calls can return.
        await self.inner.aclose(_reader=True)
        await _join_reader_tasks(readers)
        if self.pool is not None:
            await self.pool.aclose()
        self.lifecycle_lease.close()
        self.selection_lease.close()
        self.closed = True
        lifecycle_gates.unregister_body(self.root, self.provider, self)

    async def _aclose_origin(self, caller):
        if self.close_task is None:
            self._closing_readers = tuple(self.inner.tasks)
            self.close_task = asyncio.create_task(self._finish_close(self._closing_readers))
        if any(task is caller for _loop, task in self._closing_readers):
            # The finisher waits for this reader; the underlying close has
            # already been scheduled and will stop further bytes.
            return
        await asyncio.shield(self.close_task)

    async def aclose(self):
        caller = asyncio.current_task()
        if asyncio.get_running_loop() is self.loop:
            await self._aclose_origin(caller)
        else:
            future = asyncio.run_coroutine_threadsafe(self._aclose_origin(caller), self.loop)
            await asyncio.shield(asyncio.wrap_future(future))


def require_native_client(client, profile):
    """Prove the adapter still uses its sole guarded HTTPX route before every send."""
    from ..direct_transport import _NATIVE_ROUTE_SELECTOR

    try:
        selector = client._transport_for_url
        transport = client._transport
        if (type(client) is not httpx.AsyncClient
                or getattr(selector, '__func__', None) is not _NATIVE_ROUTE_SELECTOR
                or getattr(selector, '__self__', None) is not client
                or type(transport) is not AdmittedNativeTransport
                or transport.client is not client or transport.profile is not profile
                or not transport.hooks_intact()
                or (type(transport.inner) is not httpx.MockTransport
                    and not (type(transport.inner) is httpx.AsyncHTTPTransport
                             and type(transport.inner._pool) is httpcore.AsyncConnectionPool))
                or selector(httpx.URL(profile.default_base_url)) is not transport
                or client._mounts or client._trust_env or client.follow_redirects):
            raise ValueError
    except Exception as exc:
        raise ProviderHookRuntimeError('native_egress_unavailable') from exc
    return client


class AdmittedClientMixin:
    @property
    def client(self):
        client = self._client
        if isinstance(self.profile, AdmittedProviderProfile):
            if getattr(self, 'auth_pool', None) is not None:
                raise ProviderHookRuntimeError('native_egress_unavailable')
            return require_native_client(client, self.profile)
        return client

    @client.setter
    def client(self, value):
        self._client = value


def native_admitted_client(profile, credential, model, *, timeout=120.0, inner=None):
    """Construct the only admitted native client from live selected authority."""
    from agents.core.tls_trust import verify_for

    from .selected_runtime import AUTH_MARKER, current_construction

    selected = current_construction()
    if selected is None:
        raise ProviderHookRuntimeError('native_egress_unavailable')
    expected_marker = '' if selected is not None and selected.binding.auth_type == 'none' else AUTH_MARKER
    if selected is not None and (selected.profile is not profile
                                 or credential != expected_marker or selected.binding.model != model):
        raise ProviderHookRuntimeError('native_egress_unavailable')

    if inner is None:
        trust = verify_for(profile.id, profile.default_base_url)
        if trust is False:
            raise ProviderHookRuntimeError('native_egress_unavailable')
        inner = httpx.AsyncHTTPTransport(verify=trust, trust_env=False)
    guard = AdmittedNativeTransport(profile, credential, model, inner, selected=selected)
    async def mark(request):
        mark_admitted_request(request)
    client = llm_async_client(profile.id, base_url=profile.default_base_url,
                              timeout=timeout, transport=guard,
                              follow_redirects=False, trust_env=False,
                              event_hooks={'request': [mark]})
    guard.bind(client)
    quota_hook = client.event_hooks['request'][1]
    client.event_hooks['request'][-1] = _recorder(profile.id, native_protocol_backend(profile))

    async def recorded_quota(request):
        try:
            await quota_hook(request)
        except BaseException:
            _record(profile.id, request, allowed=False,
                    reason='admitted quota or request guard refused before transport')
            raise

    client.event_hooks['request'][1] = recorded_quota
    guard.seal_hooks()
    return client
