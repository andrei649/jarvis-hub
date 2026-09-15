"""Only confirmed complete streams may replace estimates with usage."""
import asyncio
import json

import httpx
import pytest

from tests.test_text_usage_propagation import agent_for, backend_for

PROVIDERS = ['ollama', 'lmstudio', 'anthropic']


def frames(provider):
    if provider == 'ollama':
        return [{'response': 'answer', 'done': False},
                {'done': True, 'done_reason': 'stop', 'prompt_eval_count': 123, 'eval_count': 17}]
    if provider == 'lmstudio':
        return [{'choices': [{'delta': {'content': 'answer'}}]},
                {'choices': [], 'usage': {'prompt_tokens': 123, 'completion_tokens': 17}}, '[DONE]']
    return [{'type': 'message_start', 'message': {'usage': {'input_tokens': 23,
                'cache_read_input_tokens': 90, 'cache_creation_input_tokens': 10, 'output_tokens': 1}}},
            {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'answer'}},
            {'type': 'message_delta', 'usage': {'output_tokens': 9}},
            {'type': 'message_delta', 'usage': {'output_tokens': 17}}, {'type': 'message_stop'}]


def encode(provider, frame):
    data = frame if isinstance(frame, str) else json.dumps(frame)
    return ((data+'\n') if provider == 'ollama' else ('data: '+data+'\n\n')).encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, provider, rows, *, error=False, wait=None):
        self.provider, self.rows, self.error, self.wait = provider, rows, error, wait
    async def __aiter__(self):
        for row in self.rows:
            yield encode(self.provider, row)
        if self.wait is not None:
            self.wait.set()
            await asyncio.Event().wait()
        if self.error:
            raise httpx.ReadError('transport interrupted')


async def invoke(provider, rows, *, error=False):
    sent, events, tokens = [], [], []
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, stream=Stream(provider, rows, error=error))
    backend = await backend_for(provider, handler)
    try:
        answer = await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
                                                    on_token=tokens.append, usage_sink=events.append)
        return answer, events, tokens, sent
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_complete_stream_reports_once(provider):
    answer, events, tokens, sent = await invoke(provider, frames(provider))
    assert answer == ''.join(tokens) == 'answer'
    assert len(events) == 1
    usage = events[0]
    assert usage.input_tokens + usage.cache_read + usage.cache_write == 123
    assert usage.output_tokens == 17
    assert all('stream_options' not in request and 'usage' not in request for request in sent)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('ending', ['missing', 'error', 'malformed', 'transport'])
async def test_incomplete_or_error_stream_never_reports(provider, ending):
    rows = frames(provider)
    if ending in {'missing', 'transport'}:
        rows = rows[:-1]
    elif ending == 'error':
        rows.insert(-1, {'type': 'error', 'error': {'message': 'failed'}})
    else:
        rows.insert(-1, '{invalid json')
    _, events, _, _ = await invoke(provider, rows, error=ending == 'transport')
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_done', ['true', 1, False, None])
async def test_ollama_requires_literal_done_true(bad_done):
    rows = frames('ollama')
    rows[-1]['done'] = bad_done
    assert (await invoke('ollama', rows))[1] == []


@pytest.mark.asyncio
async def test_lmstudio_usage_snapshots_replace_not_sum():
    rows = frames('lmstudio')
    rows.insert(1, {'choices': [], 'usage': {'prompt_tokens': 123, 'completion_tokens': 9}})
    answer, events, _, _ = await invoke('lmstudio', rows)
    assert answer == 'answer'
    assert len(events) == 1 and events[0].output_tokens == 17


@pytest.mark.asyncio
async def test_anthropic_cache_only_start_is_preserved():
    rows = frames('anthropic')
    rows[0]['message']['usage']['input_tokens'] = 0
    _, events, _, _ = await invoke('anthropic', rows)
    assert len(events) == 1
    assert (events[0].input_tokens, events[0].cache_read, events[0].cache_write) == (0, 90, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_cancellation_discards_staged_usage(provider):
    ready, events = asyncio.Event(), []
    backend = await backend_for(provider, lambda req: httpx.Response(200,
        stream=Stream(provider, frames(provider)[:-1], wait=ready)))
    try:
        task = asyncio.create_task(agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
                                                        on_token=lambda text: None, usage_sink=events.append))
        readiness = asyncio.create_task(ready.wait())
        done, _ = await asyncio.wait({task, readiness}, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        if readiness not in done:
            readiness.cancel()
            task.cancel()
            await asyncio.gather(readiness, task, return_exceptions=True)
            pytest.fail("stream failed before cancellation point")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_terminal_without_usage_keeps_estimate(provider):
    rows = frames(provider)
    if provider == 'ollama':
        rows[-1] = {'done': True}
    elif provider == 'lmstudio':
        rows = [rows[0], '[DONE]']
    else:
        rows[0]['message']['usage'] = {}
        for row in rows:
            if row.get('type') == 'message_delta':
                row['usage'] = {}
    answer, events, _, _ = await invoke(provider, rows)
    assert answer == 'answer' and events == []


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_thinking_never_reaches_callback_or_final_answer(provider):
    rows = frames(provider)
    if provider == 'ollama':
        rows[0]['response'] = '<think>private</think>answer'
        rows[0]['thinking'] = 'private'
    elif provider == 'lmstudio':
        rows[0]['choices'][0]['delta'] = {'content': '<think>private</think>answer', 'reasoning_content': 'private'}
    else:
        rows.insert(1, {'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'private'}})
    answer, events, tokens, _ = await invoke(provider, rows)
    assert answer == ''.join(tokens) == 'answer' and len(events) == 1


@pytest.mark.asyncio
async def test_lmstudio_unloaded_retry_does_not_report_failed_attempt():
    attempts, events = [], []
    def handler(req):
        attempts.append(req)
        if len(attempts) == 1:
            return httpx.Response(400, json={'error': 'Model unloaded by user or API request.',
                                            'usage': {'prompt_tokens': 9999, 'completion_tokens': 888}})
        return httpx.Response(200, stream=Stream('lmstudio', frames('lmstudio')))
    backend = await backend_for('lmstudio', handler)
    try:
        answer = await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
            on_token=lambda text: None, usage_sink=events.append)
        assert answer == 'answer' and len(attempts) == 2
        assert len(events) == 1 and events[0].input_tokens == 123
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_anthropic_delta_can_replace_input_and_cache_counts():
    rows = frames('anthropic')
    rows[-2]['usage'].update(input_tokens=0, cache_read_input_tokens=100, cache_creation_input_tokens=0)
    _, events, _, _ = await invoke('anthropic', rows)
    assert len(events) == 1
    assert (events[0].input_tokens, events[0].cache_read, events[0].cache_write) == (0, 100, 0)


@pytest.mark.asyncio
async def test_lmstudio_usage_only_frame_preserves_text_without_terminal():
    answer, events, tokens, _ = await invoke('lmstudio', frames('lmstudio')[:-1])
    assert answer == ''.join(tokens) == 'answer'
    assert events == []


@pytest.mark.asyncio
async def test_lmstudio_retry_clears_staged_usage_from_previous_attempt():
    # Exercise a transport adapter surfacing an unload after buffering metadata,
    # before any answer text. The existing retry contract permits this exception.
    class UnloadedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield encode('lmstudio', {'choices': [], 'usage': {'prompt_tokens': 9999, 'completion_tokens': 8}})
            request = httpx.Request('POST', 'https://provider.test/v1/chat/completions')
            response = httpx.Response(400, request=request, json={'error': 'Model unloaded by user or API request.'})
            raise httpx.HTTPStatusError('unloaded', request=request, response=response)
    attempts, events = [], []
    def handler(req):
        attempts.append(req)
        stream = UnloadedStream() if len(attempts) == 1 else Stream('lmstudio', [frames('lmstudio')[0], '[DONE]'])
        return httpx.Response(200, stream=stream)
    backend = await backend_for('lmstudio', handler)
    try:
        answer = await agent_for().generate_response(backend, 'model', 'hello', '', 128, .2,
            on_token=lambda text: None, usage_sink=events.append)
        assert answer == 'answer' and len(attempts) == 2
        assert events == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [None, [], 'malformed', {}, {'input_tokens': 100},
                                {'output_tokens': True}, {'output_tokens': -1}])
async def test_anthropic_invalid_final_usage_never_reuses_earlier_output(bad):
    rows = frames('anthropic')
    rows[-2]['usage'] = bad
    answer, events, tokens, _ = await invoke('anthropic', rows)
    assert answer == ''.join(tokens) == 'answer'
    assert events == []


@pytest.mark.asyncio
async def test_anthropic_missing_delta_is_not_final_output():
    rows = [row for row in frames('anthropic') if row.get('type') != 'message_delta']
    answer, events, _, _ = await invoke('anthropic', rows)
    assert answer == 'answer' and events == []


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [None, [], 'malformed'])
async def test_anthropic_malformed_start_usage_invalidates_measurement(bad):
    rows = frames('anthropic')
    rows[0]['message']['usage'] = bad
    answer, events, _, _ = await invoke('anthropic', rows)
    assert answer == 'answer' and events == []


@pytest.mark.asyncio
async def test_anthropic_final_zero_output_preserves_valid_cache_fields():
    rows = frames('anthropic')
    rows[-2]['usage'] = {'output_tokens': 0, 'input_tokens': []}
    answer, events, _, _ = await invoke('anthropic', rows)
    assert answer == 'answer' and len(events) == 1
    assert (events[0].input_tokens, events[0].output_tokens, events[0].cache_read, events[0].cache_write) == (0, 0, 90, 10)
