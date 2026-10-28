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

from agents.core.turn_usage import record_dispatch

from ..egress import _record, _recorder, llm_async_client, mark_admitted_request
from .admitted_profiles import AdmittedProviderProfile, current_signed_preparation
from .hook_runtime import ProviderHookRuntimeError

_AUTH_NAMES = frozenset({'authorization', 'x-api-key', 'x-goog-api-key', 'api-key'})
_PROTOCOL_BACKEND = {
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
    ticket = _Attempt(asyncio.current_task(), profile, profile._package_hash, model,
                      request.method, str(request.url), hashlib.sha256(request.content).hexdigest())
    token = _NATIVE_ATTEMPT.set(ticket)
    try:
        yield
    finally:
        _NATIVE_ATTEMPT.reset(token)


def _consume_attempt(request, profile, model):
    ticket = _NATIVE_ATTEMPT.get()
    if (type(ticket) is not _Attempt or ticket.used or ticket.task is not asyncio.current_task()
            or ticket.profile is not profile or ticket.package_hash != profile._package_hash
            or ticket.model != model or ticket.method != request.method
            or ticket.url != str(request.url)
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

    def __init__(self, profile, credential: str, model: str, inner):
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
                or request.headers.get('host') != base.host
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
            suffix = {'anthropic': '/messages', 'deepinfra-chat': '/chat/completions',
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
        from agents.core.kernel import Decision, Verdict

        profile = self.profile
        entered = False
        accounted = False
        try:
            self._check(request)
            async with profile._hook_runtime.dispatch_lease(
                    profile.id, package_hash=profile._package_hash, home=profile._home):
                # No worker or DNS await occurs while this non-reentrant lease is held.
                self._check(request)
                _consume_attempt(request, profile, self.model)
                packages = profile._hook_runtime.packages
                gate = getattr(packages, 'authorize_native_egress', None)
                if not callable(gate):
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                decision = gate(request, self)
                if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                        or decision.tier != 3):
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                entered = True
                response = await self.inner.handle_async_request(request)
                try:
                    self._streams.add(packages.track_native_response(profile.id, response))
                except BaseException:
                    await response.aclose()
                    raise
                accounted = True
                if 300 <= response.status_code < 400:
                    await response.aclose()
                    _record(profile.id, request, allowed=True,
                            reason='admitted redirect response refused; request possibly sent')
                    record_dispatch(profile.id, request)
                    raise ProviderHookRuntimeError('native_egress_unavailable')
                _record(profile.id, request, allowed=True)
                record_dispatch(profile.id, request)
                return response
        except BaseException as exc:
            if not accounted:
                if entered:
                    _record(profile.id, request, allowed=True,
                            reason=f'admitted transport entered; request possibly sent; {type(exc).__name__}')
                    record_dispatch(profile.id, request)
                else:
                    _record(profile.id, request, allowed=False,
                            reason='admitted physical request refused before transport')
            raise
        finally:
            # HTTPX may retain the request on responses and exceptions. The key
            # is needed only during the inner transport call.
            for name in _AUTH_NAMES:
                request.headers.pop(name, None)

    async def aclose(self):
        for stream in tuple(self._streams):
            await stream.aclose()
        await self.inner.aclose()


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
    """Construct the only admitted native client shape; MockTransport is test-only."""
    from agents.core.tls_trust import verify_for

    if inner is None:
        inner = httpx.AsyncHTTPTransport(verify=verify_for(profile.id, profile.default_base_url),
                                         trust_env=False)
    guard = AdmittedNativeTransport(profile, credential, model, inner)
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
