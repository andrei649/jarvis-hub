"""Actual local embedding identity, independent of owner turns/provider consent."""
import hashlib
import hmac
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

import httpcore
import httpx

from agents.core.action_origin import DEFAULT_ACTION_ORIGIN
from agents.core.commands import Principal
from agents.core.llm import data_handling
from agents.core.llm.model_roles import _is_loopback_base
from agents.core.llm.providers import get_profile


@dataclass(frozen=True)
class EmbeddingTarget:
    provider: str
    model: str
    binding: tuple = field(repr=False)
    namespace: str | None = None


def _require_direct_transport(client, url):
    """Verify the selected HTTPX route; opaque injected transports opt out."""
    try:
        if type(client)._transport_for_url is not httpx.Client._transport_for_url:
            raise ValueError('unsupported transport selector')
        transport = client._transport_for_url(url)
        # Exact types avoid custom subclasses silently supplying proxy behavior.
        direct = (type(transport) is httpx.MockTransport
                  or (type(transport) is httpx.HTTPTransport
                      and type(transport._pool) is httpcore.ConnectionPool))
    except Exception as exc:
        raise data_handling.DataHandlingRefused('embedding transport identity is unavailable') from exc
    if not direct:
        raise data_handling.DataHandlingRefused('embedding transport is not proven direct local')


def describe(client, provider, model):
    if not isinstance(client, httpx.Client):
        raise data_handling.DataHandlingRefused('embedding client wire identity is unavailable')
    endpoint = client.base_url
    profile = get_profile(provider)
    policy, _ = profile.data_policy_for(model)
    if (endpoint.scheme not in {'http', 'https'} or not _is_loopback_base(str(endpoint))
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or policy not in {'local', 'no-training'} or client.auth is not None
            or client.follow_redirects or client.headers.get('Cookie') or client.cookies):
        raise data_handling.DataHandlingRefused('embedding target is not proven safe local')
    path = '/v1/embeddings' if provider == 'lm-studio' else '/api/embeddings'
    _require_direct_transport(client, client.build_request('POST', path).url)
    authorization = client.headers.get('Authorization', '')
    binding = (provider, model, str(endpoint), authorization, policy,
               profile.data_policy, tuple(profile.data_policy_models))
    try:
        namespace = 'embedding:v2:' + hmac.new(data_handling._scope_key(),
                    b'H513:embedding-cache:v2\0' + json.dumps(binding).encode(), hashlib.sha256).hexdigest()
    except Exception:
        namespace = None
    return EmbeddingTarget(provider, model, binding, namespace)


def install_hook(client, provider):
    if not isinstance(client, httpx.Client):
        return
    from agents.core.llm.egress import llm_sync_request_hook

    hooks = client.event_hooks['request']
    if not any(getattr(hook, '_nerva_sync_provider', None) == provider for hook in hooks):
        hooks.append(llm_sync_request_hook(provider))


@contextmanager
def request_scope(client, provider, model, *, expected=None):
    target = describe(client, provider, model)
    if expected is not None and target.binding != expected.binding:
        raise data_handling.DataHandlingRefused('embedding target changed between retries')
    path = '/v1/embeddings' if provider == 'lm-studio' else '/api/embeddings'
    base = httpx.URL(target.binding[2])
    expected = base.copy_with(raw_path=base.raw_path + path.encode().lstrip(b'/'))
    if client.build_request('POST', path).url != expected:
        raise data_handling.DataHandlingRefused('embedding request URL is unsupported')
    marker = object()

    def check():
        current = describe(client, provider, model)
        if current.binding != target.binding:
            raise data_handling.DataHandlingRefused('embedding wire identity changed')
        adapter = SimpleNamespace(profile=get_profile(provider), base_url=target.binding[2], api_key=target.binding[3])
        return data_handling.authorize(None, adapter, model, route='embedding',
                                      principal=Principal(channel='internal', admin=False),
                                      origin=DEFAULT_ACTION_ORIGIN, actual_use=False)

    def request_check(request):
        _require_direct_transport(client, request.url)
        try:
            request_model = json.loads(request.content).get('model')
        except Exception as exc:
            raise data_handling.DataHandlingRefused('embedding request model is unavailable') from exc
        if (request_model != model or request.method != 'POST' or request.url != expected
                or request.headers.get('Authorization', '') != target.binding[3]
                or request.headers.get('Cookie')
                or request.extensions.get('nerva_embedding_request') is marker):
            raise data_handling.DataHandlingRefused('embedding physical request identity changed')
        request.extensions['nerva_embedding_request'] = marker

    check()
    with data_handling.physical_request_scope(check, request_check=request_check):
        yield target
        check()
