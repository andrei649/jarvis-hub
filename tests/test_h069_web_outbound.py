"""The real HTTP/SSE boundary never emits a raw credential or silence sentinel."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.channels import outbound_safety
from agents.core.channels.outbound_stream import OutboundStream
from agents.core.code_interruptions import MARKER
from agents.core.secrets import SecretStore
from agents.core.security.secret_broker import SecretBroker
from tests.test_chat_http import _mock_orch, _mock_orch_with_stream, _parse_sse


@pytest.fixture(autouse=True)
def clean_gate():
    outbound_safety.install_known_secret_redactor(None)
    yield
    outbound_safety.install_known_secret_redactor(None)


def test_sse_redacts_secret_split_between_tokens_and_final_reply(monkeypatch):
    secret = 'private-value-with spaces-987654321'
    monkeypatch.setenv('ACME_API_KEY', secret)
    text = 'Before ' + secret + ' after the credential.'
    tokens = list(text)
    mock = _mock_orch_with_stream(tokens, full=text)
    monkeypatch.setattr(web, 'orch', mock)
    events = _parse_sse(TestClient(web.app).post('/chat/stream', json={'message': 'hi'}).text)
    shown = ''.join(e['text'] for e in events if e['type'] == 'token')
    assert secret not in shown and 'private-value' not in shown
    assert '[REDACTED:ACME_API_KEY]' in events[-1]['text']
    assert shown == events[-1]['text']


@pytest.mark.parametrize('route', ['/chat', '/chat/stream'])
def test_web_suppresses_literal_agent_silence(monkeypatch, route):
    mock = _mock_orch_with_stream(['[SI', 'LENT]'], full='[SILENT]') if route.endswith('stream') else _mock_orch()
    if route == '/chat':
        mock.handle_input = AsyncMock(return_value='[SILENT]')
    monkeypatch.setattr(web, 'orch', mock)
    response = TestClient(web.app).post(route, json={'message': 'hi'})
    if route.endswith('stream'):
        events = _parse_sse(response.text)
        assert not [event for event in events if event['type'] == 'token']
        assert events[-1]['text'] == ''
    else:
        assert response.json()['reply'] == ''


def test_http_reply_and_notices_are_sanitized_without_losing_approval_ids(monkeypatch):
    monkeypatch.setenv('ACME_API_KEY', 'private-credential-123456789')
    response = web.ChatResponse(reply='private-credential-123456789\x00', pending_approvals=[7],
                                notices=[{'code': 'test', 'text': 'private-credential-123456789'}])
    assert 'private-credential' not in response.model_dump_json()
    assert response.pending_approvals == [7] and '\x00' not in response.reply


def _stream_events(monkeypatch, raw):
    mock = _mock_orch_with_stream(list(raw), full=raw)
    monkeypatch.setattr(web, 'orch', mock)
    return _parse_sse(TestClient(web.app).post('/chat/stream', json={'message': 'hi'}).text)


def test_provider_error_body_never_leaks_before_final_mapping(monkeypatch):
    raw = ('[OpenAI API error: Error code: 401 - {"message": '
           '"private provider policy text request identifier abcdef1234567"}]')
    events = _stream_events(monkeypatch, raw)
    draft = ''.join(event['text'] for event in events if event['type'] == 'token')
    assert 'private provider policy' not in draft
    assert 'request identifier' not in draft
    assert events[-1]['text'].startswith('The model provider OpenAI refused')


def test_cancellation_marker_prefix_never_leaks_in_tokens(monkeypatch):
    events = _stream_events(monkeypatch, 'hello\n' + MARKER + '\nworld')
    draft = ''.join(event['text'] for event in events if event['type'] == 'token')
    assert '[execution' not in draft and MARKER not in draft
    assert events[-1]['text'] == 'hello\nworld'


def test_opaque_known_redactor_multiword_secret_never_leaks_a_prefix(monkeypatch):
    secret = 'private broker credential with spaces 987654321'
    outbound_safety.install_known_secret_redactor(lambda text: text.replace(secret, '[REDACTED:broker]'))
    stream = OutboundStream()
    assert all(not stream.push(part) for part in 'before ' + secret + ' after')
    events = _stream_events(monkeypatch, 'before ' + secret + ' after')
    draft = ''.join(event['text'] for event in events if event['type'] == 'token')
    assert 'private broker' not in draft
    assert secret not in draft
    assert '[REDACTED:broker]' in events[-1]['text']


def test_empty_real_broker_streams_normal_text(monkeypatch, tmp_path):
    broker = SecretBroker(store=SecretStore(tmp_path / 'secrets.enc', key='synthetic passphrase'))
    broker.put('temporary', 'fixture-only value')
    assert broker.delete('temporary')
    outbound_safety.install_known_secret_redactor(
        broker.redact, empty_inventory=broker.empty_stream_inventory)
    raw = ('A normal answer unfolds one word at a time across many distinct frames. '
           'The answer then continues with another long ordinary sentence.')
    events = _stream_events(monkeypatch, raw)
    tokens = [event['text'] for event in events if event['type'] == 'token']
    assert len([part for part in tokens if part]) > 3
    assert ''.join(tokens) == events[-1]['text']

    # An attestation belongs to that broker redactor, not any later opaque
    # redactor installed by another caller in the same process.
    monkeypatch.setattr(outbound_safety, '_known_redactor', lambda text: text)
    opaque = OutboundStream()
    assert all(not opaque.push(part) for part in raw)


def test_populated_real_broker_masks_split_secret_at_finish(monkeypatch, tmp_path):
    secret = 'private broker credential with spaces 987654321'
    broker = SecretBroker(store=SecretStore(tmp_path / 'secrets.enc', key='synthetic passphrase'))
    broker.put('synthetic', secret)
    outbound_safety.install_known_secret_redactor(
        broker.redact, empty_inventory=broker.empty_stream_inventory)
    raw = 'Before ' + secret + ' after the credential.'
    stream = OutboundStream()
    assert all(not stream.push(part) for part in raw)
    events = _stream_events(monkeypatch, raw)
    assert secret not in events[-1]['text']
    assert '[REDACTED:synthetic]' in events[-1]['text']


def test_fallback_broker_without_encrypted_store_is_final_only():
    broker = SecretBroker()
    outbound_safety.install_known_secret_redactor(
        broker.redact, empty_inventory=broker.empty_stream_inventory)
    stream = OutboundStream()
    assert all(not stream.push(part) for part in 'A normal answer with many separate words.')


def test_external_source_history_keeps_real_broker_final_only(monkeypatch, tmp_path):
    secret = 'external history value with spaces 123456789'

    class Sources:
        def redaction_values(self):
            return [('external', secret)]

    broker = SecretBroker(store=SecretStore(tmp_path / 'secrets.enc', key='synthetic passphrase'),
                          sources=Sources())
    outbound_safety.install_known_secret_redactor(
        broker.redact, empty_inventory=broker.empty_stream_inventory)
    raw = ('An ordinary introduction contains enough words to stream safely. '
           'Then ' + secret + ' appears before a long closing passage '
           'that continues across many model token events.')
    stream = OutboundStream()
    assert all(not stream.push(part) for part in raw)
    events = _stream_events(monkeypatch, raw)
    draft = ''.join(event['text'] for event in events if event['type'] == 'token')
    assert draft == events[-1]['text']
    assert secret not in draft and 'external history' not in draft
    assert '[REDACTED:external]' in draft


def test_unavailable_empty_inventory_withholds_draft():
    def failed_inventory():
        raise RuntimeError('synthetic inventory failure')

    outbound_safety.install_known_secret_redactor(
        lambda text: text, empty_inventory=failed_inventory)
    raw = 'A normal reply with many separate words and events.'
    stream = OutboundStream()
    assert all(not stream.push(part) for part in raw)
    assert stream.finish(raw) == (raw, raw)


def test_malformed_encrypted_inventory_withholds_draft(tmp_path):
    store = SecretStore(tmp_path / 'secrets.enc', key='synthetic passphrase')
    store.path.write_text('{malformed', encoding='utf-8')
    broker = SecretBroker(store=store)
    outbound_safety.install_known_secret_redactor(
        broker.redact, empty_inventory=broker.empty_stream_inventory)
    stream = OutboundStream()
    assert all(not stream.push(part) for part in 'A long ordinary answer with many words.')


def test_selected_status_title_is_sanitized_on_http_and_sse(monkeypatch):
    secret = 'private-title-credential-123456789'
    monkeypatch.setenv('ACME_API_KEY', secret)
    mock = _mock_orch_with_stream(['Done'], full='Done')
    from agents.core.turn_outcome import record_turn_latency

    async def answered(*_args, **_kwargs):
        record_turn_latency(0)
        return 'Done'

    async def streamed(_message, channel, on_token, **_kwargs):
        record_turn_latency(0)
        await on_token('Done')
        return 'Done'

    mock.handle_input = answered
    mock.handle_input_stream = streamed
    mock.get_setting.side_effect = lambda key, default=None: (
        ['title'] if key == 'display.status_bar_fields' else True if key == 'memory.session_titles' else default)
    mock.checkpoints.session_title = lambda _session: {'title': 'Topic ' + secret}
    monkeypatch.setattr(web, 'orch', mock)
    client = TestClient(web.app)
    for route in ('/chat', '/chat/stream'):
        response = client.post(route, json={'message': 'hi'})
        assert response.status_code == 200, response.text
        payload = response.json() if route == '/chat' else _parse_sse(response.text)[-1]
        assert payload.get('outcome') is not None, payload
        title = payload['outcome']['title']
        assert secret not in title and '[REDACTED:ACME_API_KEY]' in title


def test_failed_known_redactor_withholds_web_reply(monkeypatch):
    def failed(_text):
        raise RuntimeError('synthetic broker failure')

    outbound_safety.install_known_secret_redactor(failed)
    events = _stream_events(monkeypatch, 'private broker-only value 987654321')
    notice = 'A reply could not be checked before sending, so it was withheld.'
    shown = ''.join(event['text'] for event in events if event['type'] == 'token')
    assert shown in ('', notice)
    assert events[-1]['text'] == notice


@pytest.mark.asyncio
async def test_sse_clarify_masks_display_labels_and_numeric_answer_resolves_original(tmp_path, monkeypatch):
    from tests.test_pending_input_web import event, stream_host

    secret = 'private-clarify-credential-123456789'
    monkeypatch.setenv('ACME_API_KEY', secret)
    orch, cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=[secret, 'Local'])
    original = cap['server'].handle

    async def private_question(request, *args, **kwargs):
        if request.get('tool') == 'clarify':
            request = {**request, 'args': {**request['args'], 'question': 'Choose ' + secret}}
        return await original(request, *args, **kwargs)

    monkeypatch.setattr(cap['server'], 'handle', private_question)
    try:
        assert (await event(stream))['type'] == 'start'
        question = await event(stream)
        assert question['type'] == 'clarify'
        assert secret not in question['question'] and secret not in question['choices'][0]
        assert '[REDACTED:ACME_API_KEY]' in question['choices'][0]
        following = asyncio.create_task(event(stream))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://localhost') as client:
            async with asyncio.timeout(5):
                while not orch._pending_input_service()._delivered:
                    await asyncio.sleep(0.01)
            reply = await client.post(f"/chat/pending/{question['id']}/answer", json={'answer': '1'})
            assert reply.status_code == 200, reply.text
        assert (await following)['type'] == 'token'
        assert answers[0]['user_response'] == secret
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_http_pending_masks_labels_but_index_resolves_original(tmp_path, monkeypatch):
    from tests.test_pending_input_web import stream_host

    secret = 'private-pending-credential-123456789'
    monkeypatch.setenv('ACME_API_KEY', secret)
    orch, cap, answers, unused_stream = await stream_host(tmp_path, monkeypatch,
                                                           choices=[secret, 'Local'])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://localhost') as client:
            turn = asyncio.create_task(client.post('/chat/stream', json={'message': 'ask'},
                                                   headers={'X-Nerva-Pending': 'poll'}))
            async with asyncio.timeout(5):
                listed = []
                while not listed:
                    listed = (await client.get('/chat/pending')).json()['questions']
                    await asyncio.sleep(0.01)
            question = listed[0]
            assert secret not in question['choices'][0]
            assert '[REDACTED:ACME_API_KEY]' in question['choices'][0]
            answered = await client.post(f"/chat/pending/{question['id']}/answer", json={'answer': '1'})
            assert answered.status_code == 200, answered.text
            await asyncio.wait_for(turn, 5)
        assert answers[0]['user_response'] == secret
    finally:
        await unused_stream.aclose()
        orch._pending_input_service().close()
