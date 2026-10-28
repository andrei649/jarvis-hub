"""Selected signed worker to native wire: owner, Kernel, Vault and current leases.

DNS and HTTP are synthetic; no provider or Docker service is contacted.
"""
import asyncio
import json
import ssl
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agents.core.llm.providers.hook_runtime import ProviderHookRuntimeError
from tests.test_h361_admitted_native_bridge import setup_backend
from tests.test_h361_provider_install_service import owner

CASE = ('openrouter', 'openai-compatible', 'chat_completions',
        'https://synthetic.invalid/v1', 'synthetic-model')


def setup(tmp_path, monkeypatch, *, path='text'):
    backend, model, calls, wire, actions = setup_backend(
        tmp_path, monkeypatch, CASE, path, identity='signed-addon')
    service = backend._selected_test_service
    runner = backend._selected_test_runner
    source = backend._selected_test_source
    packages = backend.profile._hook_runtime.packages
    return backend, model, packages, service, runner, source, wire, actions


@pytest.mark.asyncio
async def test_selected_snapshot_uses_signed_worker_and_wire_only_vault_key(tmp_path, monkeypatch):
    backend, model, packages, service, runner, source, wire, actions = setup(tmp_path, monkeypatch)
    observed = []
    try:
        (source / 'helper.py').write_text("def marker():\n    return 'unsigned-replacement'\n")
        backend.client._transport.inner = httpx.MockTransport(
            lambda request: observed.append((request.headers.get('authorization'),
                                             request.headers.get('host'),
                                             request.extensions.get('sni_hostname')))
            or wire.append(request) or httpx.Response(
                200, json={'choices': [{'message': {'content': 'answer'}}]}))
        assert await backend.generate(model, 'hello') == 'answer'
        assert len(runner.commands) == len(wire) == len(actions) == 1
        sent = json.loads(wire[0].content)
        assert sent['plugin_marker'] == 'signed-worker'
        assert 'host-secret' not in json.dumps(runner.input)
        assert {'main.py', 'helper.py', 'provider.json'} <= set(runner.sources)
        assert observed == [('Bearer host-secret', 'synthetic.invalid', 'synthetic.invalid')]
        assert 'authorization' not in wire[0].headers
        assert actions[0].payload['url'] == 'https://synthetic.invalid/v1/chat/completions'
        assert 'host-secret' not in repr(actions[0]) + repr(backend) + repr(runner.commands)
        assert service.selection_status(actor=owner())['status'] == 'selected'
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_revoke_during_worker_discards_prepared_result_before_http(tmp_path, monkeypatch):
    backend, model, packages, service, runner, source, wire, actions = setup(tmp_path, monkeypatch)
    runner.before_return = lambda: service.revoke('signed-addon', actor=owner())
    backend.client._transport.inner = httpx.MockTransport(lambda request: wire.append(request))
    try:
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'hello')
        assert len(runner.commands) == 1 and wire == [] and actions == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_owner_revoke_cancels_pending_headers_and_blocks_next_send(tmp_path, monkeypatch):
    backend, model, packages, service, runner, source, wire, actions = setup(tmp_path, monkeypatch)
    entered = asyncio.Event()

    async def waiting(request):
        wire.append(request)
        entered.set()
        await asyncio.Future()

    backend.client._transport.inner = httpx.MockTransport(waiting)
    task = asyncio.create_task(backend.generate(model, 'hello'))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(service.revoke_async('signed-addon', actor=owner()), 2)
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProviderHookRuntimeError, match='not_runnable'):
            await backend.generate(model, 'again')
        assert len(wire) == len(actions) == 1
    finally:
        if not task.done():
            task.cancel()
        await backend.aclose()


@pytest.mark.asyncio
async def test_provider_error_echo_is_scrubbed_with_status_retained(tmp_path, monkeypatch, caplog):
    backend, model, packages, service, runner, source, wire, actions = setup(tmp_path, monkeypatch)
    backend.client._transport.inner = httpx.MockTransport(lambda request: (
        wire.append(request) or httpx.Response(401, json={
            'error': 'host-secret was echoed by the synthetic provider'})))
    try:
        assert await backend.generate(model, 'hello') == '[OpenRouter error]'
        assert len(wire) == len(actions) == 1
        assert 'host-secret' not in caplog.text
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_mixed_dns_refuses_before_egress_or_vault_read(tmp_path, monkeypatch):
    from agents.core.llm.providers import selected_runtime

    backend, model, packages, service, runner, source, wire, actions = setup(tmp_path, monkeypatch)
    def unsafe(host, mode):
        if host == 'synthetic.invalid':
            return ['93.184.216.34', '127.0.0.1'], None
        return ([], 'unsafe') if host == '127.0.0.1' else ([host], None)
    monkeypatch.setattr(selected_runtime, 'resolve_and_validate', unsafe)
    backend.client._transport.inner = httpx.MockTransport(lambda request: wire.append(request))
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
            await backend.generate(model, 'hello')
        assert len(runner.commands) == 1 and wire == [] and actions == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_selection_change_during_dns_refuses_before_physical_entry(tmp_path, monkeypatch):
    backend, model, _packages, service, runner, _source, wire, actions = setup(
        tmp_path, monkeypatch)
    from agents.core.llm.provider_selection import read_selection

    async def changing_dns():
        service.clear_selection(expected_revision=read_selection().revision, actor=owner())
        return '93.184.216.34'

    backend._selected_provider_runtime.resolve_public = changing_dns
    backend.client._transport.inner = httpx.MockTransport(lambda request: wire.append(request))
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
            await backend.generate(model, 'hello')
        assert len(runner.commands) == 1 and wire == [] and actions == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_pinned_ip_keeps_logical_host_and_verified_sni(tmp_path, monkeypatch):
    """Generated local TLS isolates Host/SNI proof from separately tested public DNS."""
    from agents.core.tls_trust import verify_for

    hostname = 'one.synthetic.invalid'
    other = 'two.synthetic.invalid'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'local-ca.pem', tmp_path / 'local-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    monkeypatch.setenv('JARVIS_CA_BUNDLE', str(cert_path))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(cert_path), str(key_path))
    names, requests = [], []
    server_context.set_servername_callback(lambda _ssl, name, _context: names.append(name))

    async def serve(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            length = 0
            for line in head.split(b'\r\n'):
                if line.lower().startswith(b'content-length:'):
                    length = int(line.split(b':', 1)[1].strip())
            if length:
                await reader.readexactly(length)
            requests.append(head)
            body = b'{"choices":[{"message":{"content":"answer"}}]}'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                         + f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()
                         + body)
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(serve, '127.0.0.1', 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    try:
        for name, accepted in ((hostname, True), (other, False)):
            folder = tmp_path / name
            folder.mkdir()
            case = ('openrouter', 'openai-compatible', 'chat_completions',
                    f'https://{name}:{port}/v1', 'synthetic-model')
            backend, model, *_ = setup_backend(
                folder, monkeypatch, case, 'text', identity='signed-addon')
            async def local_pin():
                return '127.0.0.1'
            backend._selected_provider_runtime.resolve_public = local_pin
            backend.client._transport.inner = httpx.AsyncHTTPTransport(
                verify=verify_for('signed-addon', case[3]), trust_env=False)
            try:
                if accepted:
                    assert await backend.generate(model, 'hello') == 'answer'
                else:
                    # This adapter converts a TLS transport failure into its
                    # public error text. No HTTP request reaches the wrong host.
                    assert await backend.generate(model, 'wrong hostname') != 'answer'
            finally:
                await backend.aclose()
        assert names == [hostname, other]
        assert len(requests) == 1
        assert f'host: {hostname}:{port}'.encode() in requests[0].lower()
        assert b'POST /v1/chat/completions HTTP/1.1' in requests[0]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_insecure_target_override_cannot_disable_selected_tls(tmp_path, monkeypatch):
    from agents.core.llm.backend_factory import construct_selected_backend
    from agents.core.tls_trust import verify_for

    backend, model, _packages, _service, runner, _source, wire, actions = setup(
        tmp_path, monkeypatch)
    monkeypatch.setenv('JARVIS_TLS_INSECURE_TARGETS', 'synthetic.invalid')
    assert verify_for('signed-addon', CASE[3]) is False
    with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
        construct_selected_backend(backend._selected_provider_runtime)
    backend.client._transport.inner = httpx.AsyncHTTPTransport(verify=False, trust_env=False)
    try:
        with pytest.raises(ProviderHookRuntimeError, match='native_egress_unavailable'):
            await backend.generate(model, 'hello')
        assert wire == [] and actions == [] and len(runner.commands) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_entered_exception_echo_has_no_secret_chain_and_one_attempt(tmp_path, monkeypatch):
    from agents.core.turn_usage import turn_usage_scope

    backend, model, _packages, _service, runner, _source, wire, actions = setup(
        tmp_path, monkeypatch)

    def failing(request):
        wire.append(request)
        raise RuntimeError('host-secret synthetic inner failure')

    backend.client._transport.inner = httpx.MockTransport(failing)
    try:
        with turn_usage_scope() as usage, pytest.raises(
                ProviderHookRuntimeError, match='native_egress_unavailable') as caught:
            await backend.generate(model, 'hello')
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert 'host-secret' not in repr(caught.value)
        assert len(wire) == len(actions) == 1
        assert usage.snapshot()['api_calls'] == 1
        assert 'authorization' not in wire[0].headers
    finally:
        await backend.aclose()
