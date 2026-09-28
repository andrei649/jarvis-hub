"""Native judge transports: no proxies, network, or borrowed-client mutation."""
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy import approval_judge as aj
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.egress import llm_async_client

SNAPSHOT = {'id': 'direct-route', 'agent': 'pepper', 'tool': 'write_file', 'args': {'path':'synthetic'}}
VERDICT = '{"risk":4,"why":"Review the destination"}'


@pytest.fixture
def dh(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import data_handling
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'direct-judge-test-key')
    for name in ('JARVIS_STRICT_LOCAL','JARVIS_SAFE_MODE',
                 'JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER','JARVIS_ROLE_APPROVAL_JUDGE_MODEL',
                 'JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL','JARVIS_ROLE_APPROVAL_JUDGE_KEY',
                 'JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE',
                 'http_proxy','https_proxy','all_proxy','no_proxy',
                 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'):
        monkeypatch.delenv(name, raising=False)
    return data_handling


def configure(monkeypatch, provider='lm-studio', *, model='judge-model', remote=False):
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', model)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER', provider)
    endpoint = 'https://judge.invalid/v1' if remote else 'http://localhost:1234'
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL', endpoint)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_KEY', 'synthetic-private-key')
    if remote:
        monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE','1')
    return endpoint


def grant(dh, router=None):
    target = aj.describe_data_target(router)
    if target.policy in {'unknown','trains-on-inputs'}:
        dh.acknowledge(router, target.provider, True, dh.role_target_scope(target),
                       SimpleNamespace(log=lambda event: None), target='role:approval_judge')


def response(request):
    body = {'response': VERDICT} if request.url.path.endswith('/api/generate') else {
        'choices':[{'message':{'content':VERDICT}}]}
    return httpx.Response(200, json=body)


def instrument_native_proxies(monkeypatch):
    """Real AsyncClient selection and real proxy pool; replace only its I/O."""
    direct, proxied = [], []
    def root(_client, **kwargs):
        return kwargs.get('transport') or httpx.MockTransport(
            lambda request: direct.append(request) or response(request))
    def proxy(_client, proxy, **kwargs):
        transport = httpx.AsyncHTTPTransport(proxy=proxy, trust_env=False)
        async def offline(request):
            proxied.append(request)
            return response(request)
        transport.handle_async_request = offline
        return transport
    monkeypatch.setattr(httpx.AsyncClient, '_init_transport', root)
    monkeypatch.setattr(httpx.AsyncClient, '_init_proxy_transport', proxy)
    return direct, proxied


@pytest.mark.parametrize('provider', ['lm-studio','ollama','openai-compatible'])
async def test_owned_clients_disable_ambient_proxy_at_construction(dh, monkeypatch, provider):
    configure(monkeypatch, provider, remote=provider == 'openai-compatible')
    monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:8080')
    monkeypatch.setenv('HTTPS_PROXY','http://proxy.invalid:8080')
    monkeypatch.setenv('ALL_PROXY','http://proxy.invalid:8080')
    monkeypatch.setenv('NO_PROXY','')
    direct, proxied = instrument_native_proxies(monkeypatch)
    built = []
    original = aj._backend_for
    def factory(status, **kwargs):
        backend = original(status, **kwargs)
        built.append(backend)
        return backend
    monkeypatch.setattr(aj, '_backend_for', factory)
    grant(dh)
    judge = aj.ApprovalJudge()
    assert (await judge.score(SNAPSHOT, judge.status()))['score'] == 4
    assert built[0].client.trust_env is False and built[0].client.is_closed
    assert len(direct) == 1 and proxied == []
    assert direct[0].headers['Authorization'] == 'Bearer synthetic-private-key'


@pytest.mark.parametrize('kind', ['ambient','explicit'])
async def test_active_proxy_route_refuses_without_mutating_or_closing_client(dh, monkeypatch, kind):
    configure(monkeypatch, model='active')
    if kind == 'ambient':
        monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:8080')
        monkeypatch.setenv('NO_PROXY','')
    direct, proxied = instrument_native_proxies(monkeypatch)
    backend = LMStudioBackend('http://localhost:1234')
    if kind == 'explicit':
        await backend.client.aclose()
        backend.client = llm_async_client('lm-studio', base_url=backend.base_url,
                                          proxy='http://proxy.invalid:8080')
    router = SimpleNamespace(local_backend=backend, local_backend_name='lm-studio', active_model='loaded-model')
    client = backend.client
    mounts = dict(client._mounts)
    judge = aj.ApprovalJudge(router=router)
    try:
        with pytest.raises(dh.DataHandlingRefused):
            await judge.score(SNAPSHOT, judge.status())
        assert client is backend.client and not client.is_closed
        assert client._mounts == mounts and direct == proxied == []
    finally:
        await backend.aclose()


async def test_active_effective_no_proxy_bypass_preserves_shared_defaults(dh, monkeypatch):
    configure(monkeypatch, model='active')
    monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:8080')
    monkeypatch.setenv('NO_PROXY','localhost')
    direct, proxied = instrument_native_proxies(monkeypatch)
    backend = LMStudioBackend('http://localhost:1234')
    client = backend.client
    router = SimpleNamespace(local_backend=backend, local_backend_name='lm-studio', active_model='loaded-model')
    try:
        judge = aj.ApprovalJudge(router=router)
        assert (await judge.score(SNAPSHOT, judge.status()))['score'] == 4
        assert client.trust_env is True and not client.is_closed and backend.client is client
        assert len(direct) == 1 and proxied == []
    finally:
        await backend.aclose()


async def native_judge(monkeypatch, *, client_kwargs=None, handler=response):
    configure(monkeypatch)
    backend = LMStudioBackend('http://localhost:1234')
    await backend.client.aclose()
    backend.client = llm_async_client('lm-studio', base_url=backend.base_url, trust_env=False,
                                      transport=httpx.MockTransport(handler), **(client_kwargs or {}))
    backend.client.headers['Authorization'] = 'Bearer synthetic-private-key'
    return aj.ApprovalJudge(backend_factory=lambda status: backend), backend


async def test_selected_safe_direct_mount_is_supported(dh, monkeypatch):
    sent = []
    mounted = httpx.MockTransport(lambda request: sent.append(request) or response(request))
    judge, backend = await native_judge(monkeypatch, client_kwargs={'mounts':{'http://localhost:1234':mounted}})
    assert (await judge.score(SNAPSHOT, judge.status()))['score'] == 4
    assert len(sent) == 1 and backend.client.is_closed


@pytest.mark.parametrize('override', ['instance','class'])
async def test_overridden_native_selector_fails_closed(dh, monkeypatch, override):
    sent = []
    judge, backend = await native_judge(monkeypatch, handler=lambda request: sent.append(request) or response(request))
    original = backend.client._transport_for_url
    if override == 'instance':
        backend.client._transport_for_url = lambda url: original(url)
    else:
        monkeypatch.setattr(httpx.AsyncClient, '_transport_for_url', lambda self, url: original(url))
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == [] and backend.client.is_closed


async def test_proxy_mount_added_by_earlier_request_hook_is_refused(dh, monkeypatch):
    from httpx._utils import URLPattern
    sent, proxied = [], []
    judge, backend = await native_judge(monkeypatch, handler=lambda request: sent.append(request) or response(request))
    proxy = httpx.AsyncHTTPTransport(proxy='http://proxy.invalid:8080', trust_env=False)
    async def offline(request):
        proxied.append(request)
        return response(request)
    proxy.handle_async_request = offline
    async def reroute(request):
        backend.client._mounts[URLPattern('http://localhost:1234')] = proxy
    backend.client.event_hooks['request'].insert(0, reroute)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == proxied == [] and backend.client.is_closed


async def test_native_retry_revalidates_changed_proxy_route(dh, monkeypatch):
    from httpx._utils import URLPattern
    sent, proxied = [], []
    proxy = httpx.AsyncHTTPTransport(proxy='http://proxy.invalid:8080', trust_env=False)
    async def offline(request):
        proxied.append(request)
        return response(request)
    proxy.handle_async_request = offline
    def first(request):
        sent.append(request)
        backend.client._mounts[URLPattern('http://localhost:1234')] = proxy
        return httpx.Response(400,json={'error':'model unloaded'})
    judge, backend = await native_judge(monkeypatch, handler=first)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1 and proxied == [] and backend.client.is_closed


async def test_generic_local_constructor_defaults_and_positional_arguments_are_preserved(dh):
    lm = LMStudioBackend('http://localhost:1234')
    ol = OllamaBackend('http://localhost:11434', 4096)
    try:
        assert lm.client.trust_env is True and ol.client.trust_env is True and ol.num_ctx == 4096
    finally:
        await lm.aclose()
        await ol.aclose()


@pytest.mark.parametrize('remote', [False, True])
async def test_explicit_root_proxy_cannot_be_authorized_by_consent(dh, monkeypatch, remote):
    provider = 'openai-compatible' if remote else 'lm-studio'
    endpoint = configure(monkeypatch, provider, remote=remote)
    adapter = aj._backend_for(aj.approval_judge_status())
    await adapter.client.aclose()
    proxied = []
    proxy = httpx.AsyncHTTPTransport(proxy='http://proxy.invalid:8080', trust_env=False)
    async def offline(request):
        proxied.append(request)
        return response(request)
    proxy.handle_async_request = offline
    adapter.client = llm_async_client(provider, base_url=endpoint, transport=proxy, trust_env=False)
    adapter.client.headers['Authorization'] = 'Bearer synthetic-private-key'
    grant(dh)
    judge = aj.ApprovalJudge(backend_factory=lambda status: adapter)
    with pytest.raises(dh.DataHandlingRefused, match='not proven direct'):
        await judge.score(SNAPSHOT, judge.status())
    assert proxied == [] and adapter.client.is_closed


async def test_direct_remote_route_does_not_replace_role_consent(dh, monkeypatch):
    endpoint = configure(monkeypatch, 'openai-compatible', remote=True)
    adapter = aj._backend_for(aj.approval_judge_status())
    await adapter.client.aclose()
    sent = []
    adapter.client = llm_async_client('openai-compatible', base_url=endpoint, trust_env=False,
                                      transport=httpx.MockTransport(lambda request: sent.append(request) or response(request)))
    judge = aj.ApprovalJudge(backend_factory=lambda status: adapter)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == [] and adapter.client.is_closed
