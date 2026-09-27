"""Approval judge policy binds configured targets to the actual outgoing adapter."""
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy import approval_judge as aj
from agents.core.llm.providers import get_profile


def env(**changes):
    return {'JARVIS_ROLE_APPROVAL_JUDGE_MODEL': 'synthetic-judge', **changes}


def backend(provider='lm-studio', endpoint='http://localhost:1234', authorization=''):
    return SimpleNamespace(profile=get_profile(provider), base_url=endpoint,
                           client=SimpleNamespace(base_url=httpx.URL(endpoint + '/'),
                                                  headers=httpx.Headers({'Authorization': authorization})))


def test_descriptor_is_pure_even_when_remote_judge_disabled(monkeypatch):
    monkeypatch.setattr(aj, '_backend_for', lambda *a, **k: pytest.fail('client constructed'))
    target = aj.describe_data_target(env=env(JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER='openai-compatible',
                                          JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL='https://judge.invalid/v1',
                                          JARVIS_ROLE_APPROVAL_JUDGE_KEY='private-test-key'))
    assert target.target_id == 'role:approval_judge' and target.mode == 'dedicated'
    assert target.policy == 'unknown' and target.model == 'synthetic-judge'
    assert 'private-test-key' not in repr(target) and 'judge.invalid' not in repr(target)
    assert target.binding[4:6] == ('https://judge.invalid/v1/', 'Bearer private-test-key')


def test_descriptor_injected_key_is_same_as_construction_key(monkeypatch):
    monkeypatch.setenv(aj.ENV_KEY, 'ambient-wrong-key')
    configured = env(JARVIS_ROLE_APPROVAL_JUDGE_KEY='injected-key')
    target = aj.describe_data_target(env=configured)
    status = aj.approval_judge_status(configured)
    assert aj._judge_key(status, env=configured) == 'injected-key'
    assert target.binding[5] == 'Bearer injected-key'


@pytest.mark.parametrize('change', ['provider', 'model', 'endpoint', 'credential'])
def test_descriptor_changes_for_actual_target_changes(change):
    initial = env(JARVIS_ROLE_APPROVAL_JUDGE_KEY='key-a')
    changed = dict(initial)
    field, value = {'provider': ('PROVIDER', 'ollama'), 'model': ('MODEL', 'other'),
                    'endpoint': ('BASE_URL', 'http://127.0.0.1:1234'),
                    'credential': ('KEY', 'key-b')}[change]
    changed['JARVIS_ROLE_APPROVAL_JUDGE_' + field] = value
    assert aj.describe_data_target(env=initial).binding != aj.describe_data_target(env=changed).binding


def test_active_uses_actual_local_backend_and_client_header():
    actual = backend(endpoint='https://local-gateway.invalid', authorization='Bearer active-key')
    router = SimpleNamespace(local_backend=actual, local_backend_name='lm-studio', active_model='live-model')
    target = aj.describe_data_target(router, env=env(JARVIS_ROLE_APPROVAL_JUDGE_MODEL='active'))
    assert target.mode == 'active' and target.model == 'live-model' and target.policy == 'unknown'
    assert target.binding[4:6] == ('https://local-gateway.invalid/', 'Bearer active-key')
    actual.client.headers['Authorization'] = 'Bearer changed'
    assert aj.describe_data_target(router, env=env(JARVIS_ROLE_APPROVAL_JUDGE_MODEL='active')) != target


def test_unresolvable_or_unknown_wire_adapter_has_no_target():
    assert aj.describe_data_target(env={}) is None
    assert aj.describe_data_target(env=env(JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER='made-up')) is None
    router = SimpleNamespace(local_backend=SimpleNamespace(base_url='http://localhost:1234'),
                             local_backend_name='lm-studio', active_model='live-model')
    assert aj.describe_data_target(router, env=env(JARVIS_ROLE_APPROVAL_JUDGE_MODEL='active')) is None


@pytest.fixture
def dh(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import data_handling

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'judge-policy-test-key')
    for name in ('PROVIDER', 'MODEL', 'BASE_URL', 'KEY', 'ALLOW_REMOTE'):
        monkeypatch.delenv('JARVIS_ROLE_APPROVAL_JUDGE_' + name, raising=False)
    monkeypatch.delenv('JARVIS_STRICT_LOCAL', raising=False)
    monkeypatch.delenv('JARVIS_SAFE_MODE', raising=False)
    return data_handling


class Audit:
    def log(self, event):
        pass


SNAPSHOT = {'id': 'policy-item', 'agent': 'pepper', 'tool': 'write_file', 'args': {'path': 'a'}}


def grant(dh, router=None, *, acknowledged=True):
    target = aj.describe_data_target(router)
    return dh.acknowledge(router, target.provider, acknowledged, dh.role_target_scope(target),
                          Audit(), target='role:approval_judge')


def request_path(adapter):
    from agents.core.llm.base import LMStudioBackend, OllamaBackend

    if isinstance(adapter, LMStudioBackend):
        return "/v1/chat/completions"
    if isinstance(adapter, OllamaBackend):
        return "/api/generate"
    return "/chat/completions"


async def wire_judge(monkeypatch, *, provider='openai-compatible', endpoint='https://judge.invalid/v1',
                     handler=None, generate=None):
    from agents.core.llm.egress import llm_async_client

    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', 'synthetic-judge')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER', provider)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL', endpoint)
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE', '1')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_KEY', 'test-wire-key')
    adapter = aj._backend_for(aj.approval_judge_status())
    await adapter.client.aclose()
    adapter.client = llm_async_client(provider, base_url=endpoint,
                                     transport=httpx.MockTransport(handler or (
                                         lambda request: httpx.Response(200, json={'choices': [{'message': {
                                             'content': '{"risk": 4, "why": "Review the file"}'}}]}))))
    adapter.client.headers['Authorization'] = 'Bearer test-wire-key'
    if generate is not None:
        adapter.generate = lambda **kw: generate(adapter, **kw)
    judge = aj.ApprovalJudge(backend_factory=lambda status: adapter)
    return judge, adapter


async def test_unknown_policy_without_role_consent_never_sends(dh, monkeypatch):
    sent = []
    judge, adapter = await wire_judge(monkeypatch, handler=lambda request: sent.append(request))
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == [] and adapter.client.is_closed


async def test_loopback_native_client_succeeds_without_consent(dh, monkeypatch):
    judge, adapter = await wire_judge(monkeypatch, provider='lm-studio', endpoint='http://127.0.0.1:1234')
    opinion = await judge.score(SNAPSHOT, judge.status())
    assert opinion['score'] == 4 and opinion['advisory'] is True
    assert adapter.client.is_closed


@pytest.mark.parametrize('change', ['revoke', 'config_key', 'config_endpoint', 'model',
                                     'adapter_endpoint', 'client_endpoint', 'actual_key', 'remote_off'])
async def test_changes_after_first_physical_request_block_retry(dh, monkeypatch, change):
    sent = []
    async def generate(adapter, **kwargs):
        await adapter.client.post(request_path(adapter))
        if change == 'revoke':
            grant(dh, acknowledged=False)
        elif change == 'adapter_endpoint':
            adapter.base_url = 'https://other.invalid/v1'
        elif change == 'client_endpoint':
            adapter.client.base_url = 'https://other.invalid/v1'
        elif change == 'actual_key':
            adapter._key = 'mutated-key'
        else:
            field, value = {'config_key': ('KEY', 'new-key'), 'config_endpoint': ('BASE_URL', 'https://other.invalid'),
                            'model': ('MODEL', 'different-model'), 'remote_off': ('ALLOW_REMOTE', '0')}[change]
            monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_' + field, value)
        await adapter.client.post(request_path(adapter))
        return '{"risk": 4, "why": "Review"}'

    judge, adapter = await wire_judge(monkeypatch, generate=generate, handler=lambda request:
                                     sent.append(request) or httpx.Response(200))
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1 and sent[0].headers['Authorization'] == 'Bearer test-wire-key'
    assert adapter.client.is_closed


async def test_local_header_mutation_blocks_retry(dh, monkeypatch):
    sent = []
    async def generate(adapter, **kwargs):
        await adapter.client.post(request_path(adapter))
        adapter.client.headers['Authorization'] = 'Bearer replacement'
        await adapter.client.post(request_path(adapter))
    judge, adapter = await wire_judge(monkeypatch, provider='lm-studio', endpoint='http://127.0.0.1:1234',
                                     generate=generate, handler=lambda request: sent.append(request) or httpx.Response(200))
    with pytest.raises(dh.DataHandlingRefused, match='wire identity changed'):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1


async def test_swallowed_physical_denial_cannot_become_opinion(dh, monkeypatch):
    sent = []
    async def generate(adapter, **kwargs):
        await adapter.client.post(request_path(adapter))
        grant(dh, acknowledged=False)
        try:
            await adapter.client.post(request_path(adapter))
        except dh.DataHandlingRefused:
            return '{"risk": 0, "why": "Adapter swallowed refusal"}'
    judge, _ = await wire_judge(monkeypatch, generate=generate,
                               handler=lambda request: sent.append(request) or httpx.Response(200))
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1


async def test_untruthful_factory_metadata_is_refused_before_generate(dh, monkeypatch):
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', 'synthetic-judge')
    called = []
    class Unknown:
        async def generate(self, **kwargs):
            called.append(kwargs)
    judge = aj.ApprovalJudge(backend_factory=lambda status: Unknown())
    with pytest.raises(dh.DataHandlingRefused, match='wire identity is unavailable'):
        await judge.score(SNAPSHOT, judge.status())
    assert called == []


def test_endpoint_binding_preserves_repeated_trailing_path_slashes():
    plain = aj.describe_data_target(env=env(JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL='http://localhost:1234/v1'))
    single = aj.describe_data_target(env=env(JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL='http://localhost:1234/v1/'))
    repeated = aj.describe_data_target(env=env(JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL='http://localhost:1234/v1//'))
    assert plain == single and repeated != single
    assert repeated.binding[4] == 'http://localhost:1234/v1//'


async def test_server_cookie_cannot_change_account_on_retry(dh, monkeypatch):
    sent = []
    async def generate(adapter, **kwargs):
        await adapter.client.post(request_path(adapter))
        await adapter.client.post(request_path(adapter))
    judge, _ = await wire_judge(monkeypatch, generate=generate, handler=lambda request:
                               sent.append(request) or httpx.Response(200, headers={'Set-Cookie': 'session=other; Path=/'}))
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused, match='wire identity is unavailable'):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1


@pytest.mark.parametrize('change', ['decided', 'tainted', 'judge_detached'])
async def test_queue_change_during_generation_prevents_first_physical_request(dh, monkeypatch, tmp_path, change):
    import asyncio

    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    started, proceed = asyncio.Event(), asyncio.Event()
    sent = []
    async def generate(adapter, **kwargs):
        started.set()
        await proceed.wait()
        await adapter.client.post(request_path(adapter))
        return '{"risk": 1, "why": "Review"}'
    judge, _ = await wire_judge(monkeypatch, generate=generate,
                               handler=lambda request: sent.append(request) or httpx.Response(200))
    grant(dh)
    q = ActionApprovalQueue(tmp_path / 'actions.json')
    q.attach_judge(judge, loop=asyncio.get_running_loop())
    item = q.request(SNAPSHOT)
    await started.wait()
    if change == 'decided':
        q.decide(item['id'], True)
    elif change == 'tainted':
        q._items[item['id']]['tainted'] = True
        q._save()
    else:
        q.attach_judge(None)
    proceed.set()
    await asyncio.gather(*q._judge_tasks)
    assert sent == [] and 'judge' not in q.get(item['id'])


async def test_task_edit_during_generation_prevents_request_and_old_opinion(dh, monkeypatch, tmp_path):
    import asyncio

    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.task_approval_judge import TaskApprovalJudge

    started, proceed = asyncio.Event(), asyncio.Event()
    sent = []
    async def generate(adapter, **kwargs):
        started.set()
        await proceed.wait()
        await adapter.client.post(request_path(adapter))
        return '{"risk": 1, "why": "Review"}'
    judge, _ = await wire_judge(monkeypatch, generate=generate,
                               handler=lambda request: sent.append(request) or httpx.Response(200))
    grant(dh)
    q = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    try:
        task_id = q.enqueue('pepper', 'write_file', 'write', {'path': 'a'})
        q.transition(task_id, TaskStatus.BLOCKED)
        adapter = TaskApprovalJudge(q)
        adapter.attach_judge(judge, loop=asyncio.get_running_loop())
        adapter.schedule(task_id)
        await started.wait()
        q.update_payload_policy(task_id, {'path': 'edited'}, risk_tier=3, autonomy_level='ask')
        proceed.set()
        await asyncio.gather(*adapter._judge_tasks)
        assert sent == [] and 'judge' not in adapter.project(q.get(task_id))
        assert q.get(task_id).status == TaskStatus.BLOCKED.value
    finally:
        q.close()


async def test_revoke_while_waiting_for_slot_prevents_later_dispatch(dh, monkeypatch, tmp_path):
    import asyncio

    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    first_two, release = asyncio.Event(), asyncio.Event()
    sent = []
    async def handler(request):
        sent.append(request)
        if len(sent) == 2:
            first_two.set()
        await release.wait()
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"risk": 4, "why": "Review"}'}}]})
    # Each owned native client gets its own transport; queue permits two calls.
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', 'synthetic-judge')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER', 'openai-compatible')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL', 'https://judge.invalid/v1')
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE', '1')
    from agents.core.llm.egress import llm_async_client
    def factory(status):
        obj = aj._CompatibleJudgeBackend.__new__(aj._CompatibleJudgeBackend)
        obj.base_url, obj._key = status.base_url, ''
        obj.client = llm_async_client('openai-compatible', base_url=status.base_url,
                                     transport=httpx.MockTransport(handler))
        return obj
    judge = aj.ApprovalJudge(backend_factory=factory)
    grant(dh)
    q = ActionApprovalQueue(tmp_path / 'actions.json')
    q.attach_judge(judge, loop=asyncio.get_running_loop())
    items = [q.request({**SNAPSHOT, 'summary': str(n)}) for n in range(3)]
    await first_two.wait()
    grant(dh, acknowledged=False)
    release.set()
    await asyncio.gather(*q._judge_tasks)
    assert len(sent) == 2
    assert all(q.get(i['id'])['status'] == 'pending' and 'judge' not in q.get(i['id']) for i in items)


async def test_active_shared_client_closed_scope_blocks_copied_child(dh, monkeypatch):
    import asyncio

    from agents.core.llm.router import LLMRouter

    release = asyncio.Event()
    sent, children = [], []
    async def generate(adapter, **kwargs):
        async def later():
            await release.wait()
            await adapter.client.post(request_path(adapter))
        children.append(asyncio.create_task(later()))
        await adapter.client.post(request_path(adapter))
        return '{"risk": 4, "why": "Review"}'
    _, adapter = await wire_judge(monkeypatch, provider='lm-studio', endpoint='http://127.0.0.1:1234',
                                 generate=generate, handler=lambda request: sent.append(request) or httpx.Response(200))
    router = LLMRouter()
    router._backend, router._backend_name, router._detected_model = adapter, 'lm-studio', 'live-model'
    monkeypatch.setenv('JARVIS_ROLE_APPROVAL_JUDGE_MODEL', 'active')
    judge = aj.ApprovalJudge(router=router)
    try:
        assert (await judge.score(SNAPSHOT, judge.status()))['score'] == 4
        assert not adapter.client.is_closed
        release.set()
        with pytest.raises(dh.DataHandlingRefused, match='scope is closed'):
            await children[0]
        assert len(sent) == 1
    finally:
        await adapter.aclose()


async def test_revoke_during_single_request_drops_returned_verdict(dh, monkeypatch):
    sent = []
    def handler(request):
        sent.append(request)
        grant(dh, acknowledged=False)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"risk": 0, "why": "Review"}'}}]})
    judge, _ = await wire_judge(monkeypatch, handler=handler)
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1


@pytest.mark.parametrize('field', ['adapter_endpoint', 'client_endpoint', 'authorization'])
async def test_constructed_factory_wire_mismatch_never_generates(dh, monkeypatch, field):
    sent = []
    judge, adapter = await wire_judge(monkeypatch, handler=lambda request: sent.append(request))
    grant(dh)
    if field == 'adapter_endpoint':
        adapter.base_url = 'https://other.invalid/v1'
    elif field == 'client_endpoint':
        adapter.client.base_url = 'https://other.invalid/v1'
    else:
        adapter._key = 'other-account'
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == [] and adapter.client.is_closed


async def test_revoke_during_owned_client_close_drops_returned_verdict(dh, monkeypatch):
    judge, adapter = await wire_judge(monkeypatch)
    grant(dh)
    original_close = adapter.aclose
    async def close_and_revoke():
        await original_close()
        grant(dh, acknowledged=False)
    adapter.aclose = close_and_revoke
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())


async def test_redirect_cannot_resend_judge_prompt_to_another_endpoint(dh, monkeypatch):
    sent = []
    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(307, headers={'Location': 'https://other.invalid/capture'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"risk": 0, "why": "Review"}'}}]})
    judge, adapter = await wire_judge(monkeypatch, handler=handler)
    adapter.client.follow_redirects = True
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) <= 1


@pytest.mark.parametrize('mutation', ['url', 'authorization', 'cookie', 'delete'])
async def test_actual_request_hook_mutation_is_refused_before_transport(dh, monkeypatch, mutation):
    sent = []
    judge, adapter = await wire_judge(monkeypatch, handler=lambda request: sent.append(request))
    grant(dh)
    async def change(request):
        if mutation == 'url':
            request.url = httpx.URL('https://other.invalid/capture')
        elif mutation == 'authorization':
            request.headers['Authorization'] = 'Bearer other-account'
        elif mutation == 'cookie':
            request.headers['Cookie'] = 'session=other-account'
        else:
            request.method = 'DELETE'
    adapter.client.event_hooks['request'].insert(0, change)
    with pytest.raises(dh.DataHandlingRefused, match='physical request identity changed'):
        await judge.score(SNAPSHOT, judge.status())
    assert sent == []


@pytest.mark.parametrize('same_url', [False, True])
async def test_per_call_redirect_override_cannot_replay_request(dh, monkeypatch, same_url):
    sent = []
    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            location = str(request.url) if same_url else 'https://other.invalid/capture'
            return httpx.Response(307, headers={'Location': location})
        return httpx.Response(200)
    async def generate(adapter, **kwargs):
        await adapter.client.post(request_path(adapter), follow_redirects=True)
        return '{"risk": 0, "why": "Review"}'
    judge, adapter = await wire_judge(monkeypatch, handler=handler, generate=generate)
    assert adapter.client.follow_redirects is False
    grant(dh)
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(SNAPSHOT, judge.status())
    assert len(sent) == 1


async def test_existing_delete_cleanup_skips_guard_but_request_validator_cannot_be_skipped(dh):
    checks = []
    request = httpx.Request('DELETE', 'https://cleanup.invalid/a')
    with dh.physical_request_scope(lambda: checks.append('old-check')):
        await dh.check_physical_request(request)
    assert checks == []
    with dh.physical_request_scope(lambda: checks.append('new-check'),
                                   request_check=lambda actual: checks.append(actual.method)):
        await dh.check_physical_request(request)
    assert checks == ['new-check', 'DELETE']


@pytest.mark.parametrize('provider', ['lm-studio', 'ollama'])
async def test_native_local_provider_exact_endpoint_and_rebuilt_retry(dh, monkeypatch, provider):
    sent = []
    def handler(request):
        sent.append(request)
        if provider == 'lm-studio' and len(sent) == 1:
            return httpx.Response(400, json={'error': 'model unloaded'})
        verdict = '{"risk": 4, "why": "Review"}'
        body = {'response': verdict} if provider == 'ollama' else {'choices': [{'message': {'content': verdict}}]}
        return httpx.Response(200, json=body)
    judge, _ = await wire_judge(monkeypatch, provider=provider, endpoint='http://127.0.0.1:1234', handler=handler)
    assert (await judge.score(SNAPSHOT, judge.status()))['score'] == 4
    assert len(sent) == (2 if provider == 'lm-studio' else 1)
    path = '/v1/chat/completions' if provider == 'lm-studio' else '/api/generate'
    assert all(r.url.path == path and r.method == 'POST' for r in sent)
