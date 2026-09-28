"""Local embedding dispatch and source-bound caches, entirely offline."""
import httpx
import pytest

from agents.core.ingestion.embedder import EMBEDDING_DIM, Embedder, clear_process_cache


@pytest.fixture(autouse=True)
def clean_cache():
    clear_process_cache()
    yield
    clear_process_cache()


def client(handler, endpoint='http://127.0.0.1:1234'):
    return httpx.Client(base_url=endpoint, transport=httpx.MockTransport(handler))


def test_offloopback_destination_falls_back_without_any_model_io(tmp_path):
    sent = []
    with client(lambda request: sent.append(request) or httpx.Response(200, json={'data': [{'embedding': [0.5] * EMBEDDING_DIM}]}),
                'https://remote.invalid') as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path,
                       max_retries=3, backoff_base=0)
        assert emb.embed('private synthetic text') == emb._embed_hash('private synthetic text')
        assert sent == []


def test_fallback_does_not_poison_semantic_cache_after_recovery(tmp_path):
    sent = []
    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={'data': [{'embedding': [0.5] * EMBEDDING_DIM}]})
    with client(handler) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path,
                       max_retries=0)
        assert emb.embed('recover same text') == emb._embed_hash('recover same text')
        assert emb.embed('recover same text') == [0.5] * EMBEDDING_DIM
        assert len(sent) == 2


def test_endpoint_identity_does_not_reuse_other_semantic_vectors(tmp_path):
    with client(lambda request: httpx.Response(200, json={'data': [{'embedding': [0.1] * EMBEDDING_DIM}]})) as first:
        Embedder(backend='lmstudio', model='synthetic', http_client=first, cache_dir=tmp_path).embed('same text')
    with client(lambda request: httpx.Response(200, json={'data': [{'embedding': [0.9] * EMBEDDING_DIM}]}),
                'http://127.0.0.1:5678') as second:
        assert Embedder(backend='lmstudio', model='synthetic', http_client=second,
                        cache_dir=tmp_path).embed('same text') == [0.9] * EMBEDDING_DIM


def test_safe_local_transport_works_without_scope_key_and_does_not_cache(tmp_path, monkeypatch):
    from agents.core.ingestion import embedder
    from agents.core.llm import data_handling as dh
    def unavailable():
        raise RuntimeError('scope secret unavailable')
    monkeypatch.setattr(dh, '_scope_key', unavailable)
    sent = []
    with client(lambda request: sent.append(request) or httpx.Response(200, json={'data': [{'embedding': [0.5] * EMBEDDING_DIM}]})) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        assert emb.embed('uncached local') == emb.embed('uncached local') == [0.5] * EMBEDDING_DIM
        assert len(sent) == 2 and emb.cache_stats['writes'] == 0
        assert not embedder._PROC_CACHE and list(tmp_path.rglob('*.json')) == []


def test_legacy_mixed_namespace_ignored_and_fallback_never_semantically_cached(tmp_path):
    from agents.core.ingestion.embedder import EmbeddingCache
    EmbeddingCache(tmp_path, 'lmstudio:synthetic').put('legacy text', [0.2] * EMBEDDING_DIM)
    sent = []
    with client(lambda request: sent.append(request) or httpx.Response(500)) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path, max_retries=0)
        assert emb.embed('legacy text') == emb._embed_hash('legacy text')
        assert len(sent) == 1 and emb.cache.get('legacy text') is None
        assert emb.cache_stats['writes'] == 0


@pytest.mark.parametrize('change', ['endpoint', 'authorization', 'cookie', 'redirect', 'request_auth', 'request_delete'])
def test_fresh_physical_wire_mutation_falls_back_without_retry(tmp_path, monkeypatch, change):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={'data': [{'embedding': [0.5] * EMBEDDING_DIM}]})
    with client(handler) as actual:
        from agents.core.ingestion import embedder as module
        def no_sleep(seconds):
            pytest.fail('policy refusal retried')
        monkeypatch.setattr(module.time, 'sleep', no_sleep)
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path, max_retries=3)
        def mutate(request):
            if change == 'endpoint':
                actual.base_url = 'http://127.0.0.1:9999'
            elif change == 'authorization':
                actual.headers['Authorization'] = 'Bearer changed'
            elif change == 'cookie':
                request.headers['Cookie'] = 'session=other'
            elif change == 'redirect':
                actual.follow_redirects = True
            elif change == 'request_auth':
                request.headers['Authorization'] = 'Bearer wrong'
            else:
                request.method = 'DELETE'
        actual.event_hooks['request'].insert(0, mutate)
        assert emb.embed('mutated') == emb._embed_hash('mutated')
        assert sent == [] and emb.cache_stats['writes'] == 0


@pytest.mark.parametrize('same_url', [False, True])
def test_per_call_redirect_hop_refused(tmp_path, same_url):
    sent = []
    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(307, headers={'Location': str(request.url) if same_url else 'https://remote.invalid/capture'})
        return httpx.Response(200, json={'data': [{'embedding': [0.5] * EMBEDDING_DIM}]})
    with client(handler) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        original = actual.post
        actual.post = lambda *a, **kw: original(*a, **kw, follow_redirects=True)
        assert emb.embed('redirect') == emb._embed_hash('redirect')
        assert len(sent) == 1 and emb.cache_stats['writes'] == 0


@pytest.mark.parametrize('host,allowed', [('http://127.0.0.1:11435', True), ('https://remote.invalid', False)])
def test_owned_ollama_uses_actual_sdk_host_key_timeout_and_dispatch(monkeypatch, tmp_path, host, allowed):
    import ollama
    sent = []
    real_client = ollama.Client
    def owned(*args, **kwargs):
        return real_client(*args, **kwargs, transport=httpx.MockTransport(lambda request:
                           sent.append(request) or httpx.Response(200, json={'embedding': [0.4] * EMBEDDING_DIM})))
    monkeypatch.setattr(ollama, 'Client', owned)
    monkeypatch.setenv('OLLAMA_HOST', host)
    monkeypatch.setenv('OLLAMA_API_KEY', 'sdk-key')
    monkeypatch.setenv('EMBED_BACKEND', 'ollama')
    monkeypatch.setenv('EMBED_BASE_URL', 'http://localhost:1234')
    emb = Embedder.from_env(cache_dir=tmp_path)
    try:
        actual = emb._client._client
        assert str(actual.base_url).rstrip('/') == host and actual.timeout.read == 30
        assert actual.headers['Authorization'] == 'Bearer sdk-key' and not actual.follow_redirects
        out = emb.embed('sdk private')
        assert out == ([0.4] * EMBEDDING_DIM if allowed else emb._embed_hash('sdk private'))
        assert len(sent) == int(allowed)
        if allowed:
            assert sent[0].url.path == '/api/embeddings'
    finally:
        emb._client.close()


def test_batch_worker_scopes_and_per_result_fallback_provenance(tmp_path):
    import json
    sent = []
    def handler(request):
        text = json.loads(request.content)['input']
        sent.append(text)
        return httpx.Response(500) if text == 'fails' else httpx.Response(200, json={'data': [{'embedding': [0.8] * EMBEDDING_DIM}]})
    with client(handler) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path,
                       max_workers=4, max_retries=0)
        results = emb.embed_batch(['works', 'fails', 'works', ''])
        assert results == [[0.8] * EMBEDDING_DIM, emb._embed_hash('fails'), [0.8] * EMBEDDING_DIM, [0.0] * EMBEDDING_DIM]
        assert emb.cache.get('works') == [0.8] * EMBEDDING_DIM and emb.cache.get('fails') is None
        assert emb.cache_stats['writes'] == 1 and sorted(sent) == ['fails', 'works']


def test_namespace_rotation_between_cache_lookups_does_not_mislabel_vector(tmp_path, monkeypatch):
    from agents.core.ingestion import embedder as module
    def handler(request):
        value = 0.1 if request.headers.get('Authorization') == 'Bearer a' else 0.9
        return httpx.Response(200, json={'data': [{'embedding': [value] * EMBEDDING_DIM}]})
    with client(handler) as actual:
        actual.headers['Authorization'] = 'Bearer a'
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        assert emb.embed('rotate lookup') == [0.1] * EMBEDDING_DIM
        namespace_a = emb._cache_identity()
        actual.headers['Authorization'] = 'Bearer b'
        assert emb.embed('rotate lookup') == [0.9] * EMBEDDING_DIM
        namespace_b = emb._cache_identity()
        clear_process_cache()
        actual.headers['Authorization'] = 'Bearer a'
        original = emb._cache_identity
        def rotate():
            captured = original()
            actual.headers['Authorization'] = 'Bearer b'
            return captured
        monkeypatch.setattr(emb, '_cache_identity', rotate)
        assert emb.embed('rotate lookup') == [0.1] * EMBEDDING_DIM
        assert module._proc_cache_get((namespace_a, 'rotate lookup')) == [0.1] * EMBEDDING_DIM
        assert module._proc_cache_get((namespace_b, 'rotate lookup')) is None
        assert emb.cache.get('rotate lookup') == [0.9] * EMBEDDING_DIM


@pytest.mark.parametrize('change', ['model', 'client'])
def test_dispatch_freezes_actual_model_and_client_together(tmp_path, change):
    import json
    sent, foreign = [], []
    with client(lambda r: sent.append(r) or httpx.Response(200, json={'data': [{'embedding': [0.2] * EMBEDDING_DIM}]})) as actual, client(
            lambda r: foreign.append(r) or httpx.Response(200), 'https://remote.invalid') as replacement:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        initial_namespace = emb._cache_identity()
        original = emb._embed_primary
        def mutate(text, **kwargs):
            if change == 'model':
                emb.model = 'new-model'
            else:
                emb._http_client = replacement
            return original(text, **kwargs)
        emb._embed_primary = mutate
        assert emb.embed('stable dispatch') == [0.2] * EMBEDDING_DIM
        assert len(sent) == 1 and foreign == []
        assert json.loads(sent[0].content)['model'] == 'synthetic'
        assert emb._cache_for(initial_namespace).get('stable dispatch') == [0.2] * EMBEDDING_DIM


@pytest.mark.parametrize('change', ['credential', 'endpoint', 'policy'])
def test_change_between_retries_refuses_new_attempt_and_semantic_cache(tmp_path, monkeypatch, change):
    from dataclasses import replace

    from agents.core.ingestion import embedding_policy
    sent = []
    with client(lambda request: httpx.Response(500)) as actual:
        def handler(request):
            sent.append(request)
            if change == 'credential':
                actual.headers['Authorization'] = 'Bearer new-account'
            elif change == 'endpoint':
                actual.base_url = 'https://remote.invalid'
            else:
                original = embedding_policy.get_profile
                monkeypatch.setattr(embedding_policy, 'get_profile', lambda provider:
                                    replace(original(provider), data_policy='trains-on-inputs'))
            return httpx.Response(500)
        actual._transport = httpx.MockTransport(handler)
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path,
                       max_retries=3, backoff_base=0)
        assert emb.embed('changed retry') == emb._embed_hash('changed retry')
        assert len(sent) == 1 and emb.cache_stats['writes'] == 0


def test_actual_payload_model_mutation_is_refused_before_io(tmp_path):
    import json
    sent = []
    with client(lambda request: sent.append(request) or httpx.Response(200)) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        def mutate(request):
            body = json.loads(request.content)
            body['model'] = 'unexpected-model'
            request._content = json.dumps(body).encode()
            request.stream = httpx.ByteStream(request._content)
        actual.event_hooks['request'].insert(0, mutate)
        assert emb.embed('wrong model') == emb._embed_hash('wrong model')
        assert sent == [] and emb.cache_stats['writes'] == 0


def test_owner_context_and_primary_judge_grants_cannot_enable_remote_embedding(tmp_path, monkeypatch):
    from agents.core.commands import Principal
    from agents.core.llm import data_handling as dh
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    sent = []
    monkeypatch.setattr(dh, '_read_ack', lambda: ({'lm-studio': 'a' * 64}, True))
    monkeypatch.setattr(dh, '_read_role_ack', lambda: ({'approval_judge': 'b' * 64}, True))
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        with client(lambda request: sent.append(request) or httpx.Response(200), 'https://remote.invalid') as actual:
            emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
            assert emb.embed('owner private') == emb._embed_hash('owner private')
            assert sent == []
    finally:
        reset_turn_principal(principal)


def test_unverifiable_injected_client_falls_back_without_call():
    class Unknown:
        def post(self, *args, **kwargs):
            pytest.fail('unknown client dispatched')
    emb = Embedder(backend='lmstudio', http_client=Unknown(), max_retries=0)
    assert emb.embed('unknown client') == emb._embed_hash('unknown client')


@pytest.mark.parametrize('backend', ['lmstudio', 'ollama'])
def test_malformed_target_construction_preserves_hash_fallback(monkeypatch, tmp_path, backend, caplog):
    monkeypatch.setenv('OLLAMA_HOST', 'http://user:private-secret@localhost:invalid-port')
    emb = Embedder(backend=backend, base_url='http://user:private-secret@localhost:invalid-port', cache_dir=tmp_path)
    assert emb.embed('malformed target') == emb._embed_hash('malformed target')
    assert 'private-secret' not in caplog.text and 'invalid-port' not in caplog.text


def test_sync_guard_closed_copy_cannot_dispatch():
    import contextvars

    from agents.core.llm import data_handling as dh
    with dh.physical_request_scope(lambda: None):
        copied = contextvars.copy_context()
    with pytest.raises(dh.DataHandlingRefused, match='scope is closed'):
        copied.run(dh.check_physical_request_sync, httpx.Request('POST', 'http://localhost/a'))


def test_sync_guard_cannot_silently_authorize_async_callback():
    from agents.core.llm import data_handling as dh
    async def asynchronous():
        return True
    from contextlib import suppress

    with pytest.raises(dh.DataHandlingRefused, match='asynchronous policy check'), dh.physical_request_scope(asynchronous), suppress(dh.DataHandlingRefused):
        dh.check_physical_request_sync(httpx.Request('POST', 'http://localhost/a'))


def test_embedding_scopes_explicit_internal_and_hook_install_is_bounded(tmp_path, monkeypatch):
    from agents.core.commands import Principal
    from agents.core.llm import data_handling as dh
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    checked = []
    original = dh.authorize
    def record(*args, **kwargs):
        checked.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(dh, 'authorize', record)
    token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        with client(lambda r: httpx.Response(200, json={'data': [{'embedding': [0.3] * EMBEDDING_DIM}]})) as actual:
            first = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
            count = len(actual.event_hooks['request'])
            second = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
            assert len(actual.event_hooks['request']) == count
            assert first.embed('one') == second.embed('two') == [0.3] * EMBEDDING_DIM
            assert checked and all(k['principal'].channel == 'internal' and not k['principal'].admin
                                   and k['origin'] == 'generated' and k['actual_use'] is False for k in checked)
    finally:
        reset_turn_principal(token)


@pytest.mark.parametrize('backend', ['lmstudio', 'ollama'])
def test_owned_clients_ignore_environment_proxy_offline(monkeypatch, backend):
    import httpcore
    sent = []
    for name in ('NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.setenv(name, 'http://remote-proxy.invalid:8888')
    monkeypatch.setenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
    def transport_send(transport, request):
        sent.append(type(transport._pool))
        return httpx.Response(200, json={'data': [{'embedding': [0.6] * EMBEDDING_DIM}],
                                        'embedding': [0.6] * EMBEDDING_DIM})
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', transport_send)
    emb = Embedder(backend=backend, model='synthetic', max_retries=0)
    actual = emb._http_client if backend == 'lmstudio' else emb._client._client
    try:
        assert emb.embed('proxy-sensitive local data') == [0.6] * EMBEDDING_DIM
        assert sent == [httpcore.ConnectionPool]
        assert actual.timeout.read == 30
    finally:
        actual.close()


@pytest.mark.parametrize('kind', ['proxy', 'mount', 'opaque'])
def test_injected_proxy_or_unverifiable_transport_is_refused(monkeypatch, kind):
    sent = []
    def send(transport, request):
        sent.append(request)
        return httpx.Response(200, json={'data': [{'embedding': [0.6] * EMBEDDING_DIM}]})
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', send)
    class Opaque(httpx.BaseTransport):
        def handle_request(self, request):
            return send(self, request)
    kwargs = {'trust_env': False}
    if kind == 'proxy':
        kwargs['proxy'] = 'http://remote-proxy.invalid:8888'
    elif kind == 'mount':
        kwargs['mounts'] = {'http://': httpx.HTTPTransport(proxy='http://remote-proxy.invalid:8888')}
    else:
        kwargs['transport'] = Opaque()
    with httpx.Client(base_url='http://127.0.0.1:1234', **kwargs) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, max_retries=0)
        assert emb.embed('injected transport') == emb._embed_hash('injected transport')
        assert sent == []


def test_transport_mutation_before_physical_dispatch_is_refused(monkeypatch):
    import json
    sent = []
    with client(lambda request: sent.append(request) or httpx.Response(200, json={'data': [{'embedding': [0.6] * EMBEDDING_DIM}]})) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, max_retries=0)
        def mutate(request):
            actual._mounts = {httpx._utils.URLPattern('http://'): httpx.HTTPTransport(proxy='http://remote-proxy.invalid:8888')}
        actual.event_hooks['request'].insert(0, mutate)
        monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda transport, request:
                            sent.append(request) or httpx.Response(200, content=json.dumps({'data': []})))
        assert emb.embed('mutation') == emb._embed_hash('mutation')
        assert sent == []



def test_cache_dir_diagnostic_tracks_current_safe_namespace(tmp_path, monkeypatch):
    from agents.core.llm import data_handling
    with client(lambda request: httpx.Response(200, json={'data': []})) as actual:
        emb = Embedder(backend='lmstudio', model='synthetic', http_client=actual, cache_dir=tmp_path)
        assert emb.cache.dir == tmp_path
        with pytest.raises(AttributeError):
            emb.cache.dir = tmp_path / 'replacement'
        actual.base_url = 'https://remote.invalid'
        assert emb.cache.dir is None
        actual.base_url = 'http://127.0.0.1:1234'
        assert emb.cache.dir == tmp_path
        def missing_key():
            raise RuntimeError('scope secret unavailable')
        monkeypatch.setattr(data_handling, '_scope_key', missing_key)
        assert emb.cache.dir is None
