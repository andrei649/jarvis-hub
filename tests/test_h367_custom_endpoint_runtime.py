"""Custom physical dispatch remains bound to one owner choice and wire host."""
import asyncio
import multiprocessing as mp
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.llm import custom_endpoints as metadata
from agents.core.llm.providers.packages import ProviderPackageError
from agents.core.observability.egress_monitor import EGRESS_MONITOR
from tests.test_h361_provider_install_service import owner
from tests.test_h367_custom_endpoint_service import service as service_fixture


def _other_process_generic_writer(db_path, pipe):
    from pathlib import Path

    from agents.core import settings_db as other_settings
    from agents.core.llm.providers.selection_gates import SelectionBusy

    other_settings.DB_PATH = Path(db_path)
    try:
        other_settings.put_category('llm', {'compatible_model': 'other'})
        pipe.send('written')
    except SelectionBusy:
        pipe.send('busy')
    except Exception as exc:
        pipe.send(type(exc).__name__)
    finally:
        pipe.close()


@pytest.fixture
def active(service_fixture):
    svc, _, _ = service_fixture
    created = svc.create("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local",
                         actor=owner())
    svc.activate("one", expected_revision=created["revision"],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    return svc


def test_active_proof_survives_restart_but_raw_replay_fails(active):
    from agents.core.llm.custom_endpoint_service import CustomEndpointService

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    assert runtime.check().identity == "custom:one"
    resumed = CustomEndpointService(root=active.root, home=active.home,
                                    kernel=active.kernel, audit=active.audit)
    assert resumed.current_runtime().check().identity == "custom:one"
    old = metadata.read_choice()
    metadata.clear_endpoint_choice(expected_choice_epoch=old.epoch)
    metadata.activate_endpoint("one", expected_revision=metadata.read_endpoint("one").revision,
                               expected_choice_epoch=metadata.read_choice().epoch,
                               proof=old.consent_proof)
    with pytest.raises(ProviderPackageError):
        resumed.current_runtime()


@pytest.mark.asyncio
async def test_custom_wire_uses_pinned_loopback_and_no_ambient_key(active):
    from agents.core.llm.providers.custom_runtime import custom_client

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    observed = []

    async def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"},
                                                      "finish_reason": "stop"}]})

    client = custom_client(runtime, inner=httpx.MockTransport(handler))
    async with client:
        response = await client.post("/chat/completions", json={"model": "m", "messages": []})
        assert response.status_code == 200
    assert len(observed) == 1
    assert observed[0].url.host == "127.0.0.1"
    assert observed[0].headers["host"] == "127.0.0.1:1234"
    assert "authorization" not in observed[0].headers


@pytest.mark.asyncio
async def test_custom_status_tps_includes_synthetic_response_header_delay(active, monkeypatch):
    from agents.core import turn_usage
    from agents.core.llm.providers.custom_runtime import custom_client
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.turn_usage import model_usage_scope, record_usage, turn_usage_scope

    clock = [1.0]
    monkeypatch.setattr(turn_usage, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    async def delayed_headers(_request):
        clock[0] = 3.0
        return httpx.Response(200, json={'ok': True})

    async with custom_client(runtime, inner=httpx.MockTransport(delayed_headers)) as client:
        with turn_usage_scope() as usage, model_usage_scope(model='m', route='cloud'):
            assert (await client.post('/chat/completions', json={'model': 'm', 'messages': []})).status_code == 200
            clock[0] = 4.0
            record_usage(TokenUsage(input_tokens=10, output_tokens=60, counts_complete=True))
            assert usage.snapshot()['api_calls'] == 1
            assert usage.status_snapshot()['tps'] == 20.0


@pytest.mark.asyncio
async def test_ipv6_loopback_wire_keeps_bracketed_logical_host(service_fixture):
    from agents.core.llm.providers.custom_runtime import custom_client

    svc, _, _ = service_fixture
    created = svc.create('six', 'Six', 'http://[::1]:1234/v1', 'm',
                         'none', 'local', actor=owner())
    svc.activate('six', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, actor=owner())
    runtime = svc.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    seen = []
    async with custom_client(runtime, inner=httpx.MockTransport(
            lambda request: (seen.append(request), httpx.Response(200, content=b'{}'))[1])) as client:
        assert (await client.post('/chat/completions',
                                  json={'model': 'm', 'messages': []})).status_code == 200
    assert seen[0].url.host == '::1'
    assert seen[0].headers['host'] == '[::1]:1234'
    assert seen[0].extensions['sni_hostname'] == '::1'


@pytest.mark.asyncio
async def test_generic_writer_refused_while_custom_body_is_open(active):
    from agents.core.llm.providers.custom_runtime import custom_client
    from agents.core.llm.providers.selection_gates import SelectionBusy

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    client = custom_client(runtime, inner=httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok")))
    async with client, client.stream("POST", "/chat/completions",
                             json={"model": "m", "messages": []}) as response:
        assert response.status_code == 200
        assert active.current_runtime().check().identity == 'custom:one'
        with pytest.raises(SelectionBusy):
            settings_db.put_category("llm", {"compatible_provider": "openrouter"})


@pytest.mark.asyncio
async def test_other_process_cannot_mutate_choice_while_custom_body_is_open(active):
    from agents.core.llm.providers.custom_runtime import custom_client

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    client = custom_client(runtime, inner=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'ok')))
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_other_process_generic_writer,
                              args=(str(settings_db.DB_PATH), send))
    try:
        async with client, client.stream('POST', '/chat/completions',
                                 json={'model': 'm', 'messages': []}) as response:
            assert response.status_code == 200
            process.start()
            send.close()
            assert await asyncio.to_thread(receive.poll, 10)
            assert receive.recv() == 'busy'
            assert metadata.read_choice().active_key == 'one'
        process.join(5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receive.close()
        send.close()


@pytest.mark.asyncio
async def test_revocation_refused_during_paused_inner_transport(active):
    from agents.core.llm.providers.custom_runtime import custom_client
    from agents.core.llm.providers.selection_gates import SelectionBusy

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, content=b'{}')
    async with custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        sending = asyncio.create_task(client.post('/chat/completions',
                                                 json={'model': 'm', 'messages': []}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(SelectionBusy):
                metadata.clear_endpoint_choice(expected_choice_epoch=metadata.read_choice().epoch)
            assert metadata.read_choice().active_key == 'one'
        finally:
            release.set()
        assert (await asyncio.wait_for(sending, 3)).status_code == 200


@pytest.mark.asyncio
async def test_ambiguous_inner_timeout_records_possible_send_not_denial(active):
    from agents.core.llm.providers.custom_runtime import custom_client

    runtime = active.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    writes = []
    async def handler(request):
        writes.append(request.content)
        raise httpx.ReadTimeout('synthetic after write')
    EGRESS_MONITOR.reset()
    async with custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.post('/chat/completions', json={'model': 'm', 'messages': []})
    assert len(writes) == 1
    row = EGRESS_MONITOR.snapshot(plugin='llm:custom:one')['recent'][0]
    assert row['allowed'] is True
    assert 'possibly sent' in row['reason']


@pytest.mark.asyncio
async def test_router_refresh_selects_keyless_custom_and_restores_generic(active):
    from agents.core.llm.hybrid_router import HybridRouter

    router = HybridRouter()
    baseline = SimpleNamespace(aclose=lambda: None)
    router._compatible_backend = baseline
    router._compatible_model = "generic-model"
    router._compatible_provider_id = "openrouter"
    router._cloud_available = True
    await router.refresh_custom(active)
    runtime = router._custom_endpoint_runtime
    assert runtime is not None
    assert router._compatible_provider_id == "custom:one"
    assert router._compatible_backend.api_key == ""
    assert router._compatible_backend._custom_endpoint_runtime is runtime
    metadata.clear_endpoint_choice(expected_choice_epoch=metadata.read_choice().epoch)
    await router.refresh_custom(active)
    assert router._compatible_backend is baseline


@pytest.mark.asyncio
async def test_router_failed_health_check_retires_previous_without_leaking_detail(active, monkeypatch, caplog):
    from agents.core.llm.hybrid_router import HybridRouter

    router = HybridRouter()
    router._compatible_backend = SimpleNamespace(aclose=lambda: None)
    router._compatible_model = 'generic-model'
    router._compatible_provider_id = 'openrouter'
    router._cloud_available = True
    await router.refresh_custom(active)
    previous = router._custom_endpoint_runtime
    old_backend = router._compatible_backend

    def broken_check():
        raise RuntimeError('private endpoint detail')

    monkeypatch.setattr(previous, 'check', broken_check)
    await router.refresh_custom(active)
    assert previous.active is False
    assert router._custom_endpoint_runtime is not previous
    assert router._compatible_backend is not old_backend
    assert router._compatible_provider_id == 'custom:one'
    assert 'owner custom endpoint health check unavailable' in caplog.text
    assert 'private endpoint detail' not in caplog.text


@pytest.mark.asyncio
async def test_explicit_owner_validation_uses_bounded_guarded_models_request(active):
    seen = []

    async def handler(request):
        seen.append((request.method, str(request.url), request.headers.get('host')))
        return httpx.Response(200, json={'data': [{'id': 'm'}]})

    result = await active.validate('one', actor=owner(), inner=httpx.MockTransport(handler))
    assert result == {'ok': True, 'models': 1, 'identity': 'custom:one'}
    assert seen == [('GET', 'http://127.0.0.1:1234/v1/models', '127.0.0.1:1234')]


@pytest.mark.asyncio
async def test_public_pins_actual_ip_host_sni_and_records_dialed_ip(service_fixture, monkeypatch):
    from agents.core.llm.providers import custom_runtime

    svc, _, _ = service_fixture
    created = svc.create('hosted', 'Hosted', 'https://endpoint.invalid/v1', 'm',
                         'none', 'unknown', grant_destination=True, actor=owner())
    svc.activate('hosted', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, acknowledge_data_policy=True,
                 grant_destination=True, actor=owner())
    runtime = svc.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    monkeypatch.setattr(custom_runtime, 'resolve_and_validate',
                        lambda host, *, mode='public': (['8.8.8.8'], None)
                        if host == 'endpoint.invalid' else ([host], None))
    observed = []
    async def handler(request):
        observed.append(request)
        return httpx.Response(200, content=b'{}')
    EGRESS_MONITOR.reset()
    async with custom_runtime.custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        response = await client.post('/chat/completions', json={'model': 'm', 'messages': []})
        assert response.status_code == 200
    assert len(observed) == 1
    assert observed[0].url.host == '8.8.8.8'
    assert observed[0].headers['host'] == 'endpoint.invalid'
    assert observed[0].extensions['sni_hostname'] == 'endpoint.invalid'
    assert EGRESS_MONITOR.snapshot(plugin='llm:custom:hosted')['recent'][0]['host'] == '8.8.8.8'


@pytest.mark.asyncio
async def test_granted_lan_name_pins_all_private_answers_and_preserves_host(service_fixture, monkeypatch):
    from agents.core.llm.providers import custom_runtime

    svc, _, _ = service_fixture
    created = svc.create('lan', 'LAN', 'http://modelbox.lan:8080/api/v1', 'm',
                         'none', 'unknown', grant_destination=True, actor=owner())
    svc.activate('lan', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, acknowledge_data_policy=True,
                 grant_destination=True, actor=owner())
    runtime = svc.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    monkeypatch.setattr(custom_runtime, 'resolve_and_validate',
                        lambda host, *, mode='public':
                        (['192.168.1.5', '192.168.1.6'], None) if host == 'modelbox.lan'
                        else ([host], None))
    seen = []
    async def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b'{}')
    async with custom_runtime.custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        response = await client.post('/chat/completions', json={'model': 'm', 'messages': []})
        assert response.status_code == 200
    assert seen[0].url.host == '192.168.1.5'
    assert seen[0].headers['host'] == 'modelbox.lan:8080'
    assert seen[0].url.path == '/api/v1/chat/completions'


@pytest.mark.asyncio
async def test_mixed_public_answers_and_redirect_escape_refused(service_fixture, monkeypatch):
    from agents.core.llm.providers import custom_runtime

    svc, _, _ = service_fixture
    created = svc.create('hosted', 'Hosted', 'https://endpoint.invalid/v1', 'm',
                         'none', 'unknown', grant_destination=True, actor=owner())
    svc.activate('hosted', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, acknowledge_data_policy=True,
                 grant_destination=True, actor=owner())
    runtime = svc.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    monkeypatch.setattr(custom_runtime, 'resolve_and_validate',
                        lambda host, *, mode='public': (['8.8.8.8', '127.0.0.1'], None))
    sends = []
    async def handler(request):
        sends.append(request)
        return httpx.Response(302, headers={'location': 'https://other.invalid/steal'})
    async with custom_runtime.custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderPackageError):
            await client.post('/chat/completions', json={'model': 'm', 'messages': []})
    assert sends == []
    monkeypatch.setattr(custom_runtime, 'resolve_and_validate',
                        lambda host, *, mode='public': (['8.8.8.8'], None)
                        if host == 'endpoint.invalid' else ([host], None))
    async with custom_runtime.custom_client(runtime, inner=httpx.MockTransport(handler)) as client:
        response = await client.post('/chat/completions', json={'model': 'm', 'messages': []})
        assert response.status_code == 302
    assert len(sends) == 1


@pytest.mark.asyncio
async def test_actual_compatible_adapter_uses_custom_guarded_client(active):
    from agents.core.llm.hybrid_router import HybridRouter

    router = HybridRouter()
    router._compatible_backend = None
    router._compatible_model = ''
    router._compatible_provider_id = ''
    router._cloud_available = False
    await router.refresh_custom(active)
    backend = router._compatible_backend
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'synthetic answer'},
                                                      'finish_reason': 'stop'}]})

    backend.client._transport.inner = httpx.MockTransport(handler)
    answer = await backend.generate('m', 'synthetic prompt')
    assert answer == 'synthetic answer'
    assert len(seen) == 1
    assert seen[0].url.path == '/v1/chat/completions'
    assert backend.api_key == ''
    await router.aclose()


@pytest.mark.asyncio
async def test_wire_only_secret_and_rotation_waits_for_body(service_fixture):
    from agents.core.llm.providers.custom_runtime import custom_client
    from agents.core.llm.providers.selection_gates import SelectionBusy

    svc, _, _ = service_fixture
    created = svc.create('keyed', 'Keyed', 'http://127.0.0.1:1234/v1', 'm',
                         'bearer', 'unknown', actor=owner())
    assert svc.credential_mutation('keyed', value='synthetic-secret', actor=owner())['generation'] == 1
    svc.activate('keyed', expected_revision=created['revision'],
                 expected_choice_epoch=metadata.read_choice().epoch,
                 acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    runtime = svc.current_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
    runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
    seen = []

    async def handler(request):
        seen.append(request)
        assert request.headers['authorization'] == 'Bearer synthetic-secret'
        return httpx.Response(200, content=b'{}')

    async with custom_client(runtime, inner=httpx.MockTransport(handler)) as client, \
            client.stream('POST', '/chat/completions',
                          json={'model': 'm', 'messages': []}) as response:
        assert response.status_code == 200
        with pytest.raises(SelectionBusy):
            svc.credential_mutation('keyed', value='synthetic-rotated', actor=owner())
        assert svc.credential_status('keyed', actor=owner())['generation'] == 1
    assert 'authorization' not in seen[0].headers
    rotated = svc.credential_mutation('keyed', value='synthetic-rotated', actor=owner())
    assert rotated['generation'] == 2
    with pytest.raises(ProviderPackageError):
        runtime.check()
    assert metadata.read_choice().active_key is None
