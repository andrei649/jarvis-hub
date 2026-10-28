"""Real signed-package/worker/native wire chain; Docker and HTTP are simulated."""
import asyncio
import json
import os

import httpx
import pytest

from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.kernel import Decision, Verdict
from agents.core.llm.backend_factory import construct_backend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.admitted_registry import AdmittedProviderRegistry
from agents.core.llm.providers.candidates import discover_candidates
from agents.core.llm.providers.hook_runtime import ProviderHookRuntime, ProviderHookRuntimeError
from agents.core.llm.providers.packages import ProviderPackageError, ProviderPackageStore
from tests.test_h361_provider_hook_runtime import IMAGE, SimulatedSealedRunner


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    root = tmp_path / 'candidates'
    source = root / 'signed-addon'
    source.mkdir(parents=True)
    (source / 'provider.json').write_text(json.dumps(
        {'schema_version': 1, 'id': 'signed-addon', 'aliases': ['signed-alias']}))
    hooks = ('prepare_messages', 'build_extra_body', 'build_api_kwargs_extras', 'get_max_tokens')
    (source / 'helper.py').write_text("def marker():\n    return 'signed-worker'\n")
    registration = {'id': 'signed-addon', 'hooks': list(hooks)}
    (source / 'main.py').write_text(
        'from helper import marker\n'
        'def register_provider():\n'
        f'    return {registration!r}\n'
        'def prepare_messages(messages):\n    return messages\n'
        'def build_extra_body(**context):\n    return {"plugin_marker": marker()}\n'
        'def build_api_kwargs_extras(**context):\n    return {}, {}\n'
        'def get_max_tokens(model):\n    return 11\n')
    sandbox = AcquisitionSandboxProfile(image=IMAGE, uid=os.getuid(), gid=os.getgid())
    signing = ManagedSigningKeyStore(tmp_path / 'signing')
    signing.provision(key_id='synthetic-integration', version=1, key=b'x' * 32)
    actions, owner_calls = [], []

    def kernel(action):
        actions.append(action)
        return Decision(Verdict.GRANT, tier=3)

    def authenticated_test_owner(proposal, record, actor):
        owner_calls.append((proposal, record.package_hash, actor))
        return actor == 'owner' and record.provider_id == 'signed-addon'

    packages = ProviderPackageStore(tmp_path / 'packages', signing=signing,
                                    authorizer=kernel, enabled=lambda: True,
                                    owner_authorizer=authenticated_test_owner)
    host_profile = ProviderProfile('signed-addon', 'Synthetic addon', 'openai-compatible',
                                   aliases=('signed-alias',), is_user_defined=True, auth_type='bearer',
                                   capabilities=frozenset({'cloud', 'chat'}),
                                   default_base_url='https://synthetic.invalid/v1')
    record = packages.stage(source, profile=host_profile, hooks=hooks, source='user',
                            home='synthetic-home', sandbox_profile=sandbox)
    proposal = packages.propose(record.artifact_id)
    packages.decide(proposal, approved=True, actor='owner', permanent=True)
    packages.promote(proposal)
    runner = SimulatedSealedRunner()
    runtime = ProviderHookRuntime(packages, sandbox, tmp_path / 'runtime', runner,
                                  enabled=lambda: True)
    candidates = discover_candidates(user_root=root, home='synthetic-home')
    registry = AdmittedProviderRegistry((), candidates, packages=packages, runtime=runtime,
                                       home='synthetic-home', bindings={'signed-addon': record.package_hash})
    backend = construct_backend('signed-alias', registry=registry, api_key='synthetic-host-key')
    return backend, packages, runner, actions, owner_calls, source


@pytest.mark.asyncio
async def test_signed_snapshot_runs_through_real_worker_and_native_adapter(tmp_path, monkeypatch):
    backend, packages, runner, actions, owners, source = setup(tmp_path, monkeypatch)
    assert owners and not runner.commands
    # The active grant owns copied signed bytes, not future directory edits.
    (source / 'helper.py').write_text("def marker():\n    return 'unsigned-replacement'\n")
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})

    await backend.client.aclose()
    backend.client = llm_async_client('signed-addon', transport=httpx.MockTransport(response),
                                      base_url='https://synthetic.invalid/v1')
    try:
        assert await backend.generate('synthetic-model', 'hello') == 'answer'
        assert len(runner.commands) == 1
        sent = json.loads(seen[0].content)
        assert sent['plugin_marker'] == 'signed-worker' and sent['max_tokens'] == 11
        assert 'synthetic-host-key' not in json.dumps(runner.input)
        assert {'main.py', 'helper.py', 'provider.json'} <= set(runner.sources)
        assert all(action.kind == 'plugin.load' for action in actions)
        packages.revoke('signed-addon')
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate('synthetic-model', 'again')
        assert len(seen) == 1 and len(runner.commands) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_revoke_during_worker_discards_result_before_provider_http(tmp_path, monkeypatch):
    backend, packages, runner, *_ = setup(tmp_path, monkeypatch)
    runner.before_return = lambda: packages.revoke('signed-addon')
    seen = []
    await backend.client.aclose()
    backend.client = llm_async_client('signed-addon',
                                      transport=httpx.MockTransport(lambda r: seen.append(r)),
                                      base_url='https://synthetic.invalid/v1')
    try:
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate('synthetic-model', 'hello')
        assert len(runner.commands) == 1 and seen == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_revoke_in_request_hook_refuses_before_physical_transport(tmp_path, monkeypatch):
    backend, packages, runner, *_ = setup(tmp_path, monkeypatch)
    seen = []

    async def revoke_before_egress(_request):
        packages.revoke('signed-addon')

    await backend.client.aclose()
    backend.client = llm_async_client(
        'signed-addon', base_url='https://synthetic.invalid/v1',
        event_hooks={'request': [revoke_before_egress]},
        transport=httpx.MockTransport(lambda request: (
            seen.append(request), httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
        )[1]),
    )
    try:
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate('synthetic-model', 'hello')
        assert len(runner.commands) == 1 and seen == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_each_native_dispatch_rechecks_live_admission(tmp_path, monkeypatch):
    backend, packages, _runner, *_ = setup(tmp_path, monkeypatch)
    seen = []
    await backend.client.aclose()
    backend.client = llm_async_client(
        'signed-addon', base_url='https://synthetic.invalid/v1',
        transport=httpx.MockTransport(lambda request: (
            seen.append(request), httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
        )[1]),
    )
    try:
        assert await backend.generate('synthetic-model', 'first') == 'answer'
        packages.revoke('signed-addon')
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.client.post('/chat/completions', json={'model': 'synthetic-model'})
        assert len(seen) == 1
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('prompt', ['x' * 40_000, '🦉' * 40_000, 'y' * 300_000],
                         ids=['ascii', 'unicode', 'within-512k-input'])
async def test_default_signed_worker_accepts_long_and_unicode_prompts(tmp_path, monkeypatch, prompt):
    backend, _packages, runner, *_ = setup(tmp_path, monkeypatch)
    seen = []
    await backend.client.aclose()
    backend.client = llm_async_client(
        'signed-addon', base_url='https://synthetic.invalid/v1',
        transport=httpx.MockTransport(lambda request: (
            seen.append(json.loads(request.content)),
            httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
        )[1]),
    )
    try:
        assert await backend.generate('synthetic-model', prompt) == 'answer'
        assert len(runner.commands) == 1 and seen[0]['messages'][1]['content'] == prompt
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_revoke_while_transport_waits_prevents_later_physical_send(tmp_path, monkeypatch):
    backend, packages, _runner, *_ = setup(tmp_path, monkeypatch)
    revoker = ProviderPackageStore(
        packages.root, signing=packages.signing, authorizer=packages.authorizer,
        enabled=packages.enabled, owner_authorizer=packages.owner_authorizer)
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    class PausedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            entered.set()
            await release.wait()
            seen.append(request)
            return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})

    await backend.client.aclose()
    backend.client = llm_async_client('signed-addon',
                                      base_url='https://synthetic.invalid/v1',
                                      transport=PausedTransport())
    task = asyncio.create_task(backend.generate('synthetic-model', 'hello'))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with pytest.raises(ProviderPackageError, match='revoke_async'):
            revoker.revoke('signed-addon')
        await asyncio.wait_for(revoker.revoke_async('signed-addon'), timeout=5)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seen == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('revoke', [False, True], ids=['healthy', 'revoked-before-send'])
async def test_admission_egress_accounting_matches_transport(tmp_path, monkeypatch, revoke):
    from agents.core import turn_usage
    from agents.core.llm import egress

    backend, packages, _runner, *_ = setup(tmp_path, monkeypatch)
    events, dispatches, seen = [], [], []
    monkeypatch.setattr(egress, '_record', lambda _backend, _request, *, allowed, reason='':
                        events.append((allowed, reason)))
    monkeypatch.setattr(turn_usage, 'record_dispatch', lambda *args: dispatches.append(args))

    async def maybe_revoke(_request):
        if revoke:
            packages.revoke('signed-addon')

    await backend.client.aclose()
    backend.client = llm_async_client(
        'signed-addon', base_url='https://synthetic.invalid/v1',
        event_hooks={'request': [maybe_revoke]},
        transport=httpx.MockTransport(lambda request: (
            seen.append(request), httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
        )[1]),
    )
    try:
        if revoke:
            with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
                await backend.generate('synthetic-model', 'hello')
            assert seen == [] and not any(allowed for allowed, _ in events) and dispatches == []
        else:
            assert await backend.generate('synthetic-model', 'hello') == 'answer'
            assert len(seen) == 1 and sum(allowed for allowed, _ in events) == 1
            assert len(dispatches) == 1
    finally:
        await backend.client.aclose()
