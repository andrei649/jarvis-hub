import httpx
import pytest

from agents.core.context_compressor import CompactionPolicy
from agents.core.llm.base import OllamaBackend


@pytest.mark.asyncio
async def test_ollama_probes_effective_parameter_and_sends_it():
    backend = OllamaBackend()
    await backend.client.aclose()
    sent = []
    def handler(req):
        import json
        payload = json.loads(req.content)
        sent.append((req.url.path, payload))
        if req.url.path == '/api/show':
            return httpx.Response(200, json={'parameters': 'temperature 0.7\nnum_ctx 2048',
                                          'model_info': {'llama.context_length': 131072}})
        return httpx.Response(200, json={'response': 'ok'})
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://localhost')
    assert await backend.resolve_context_window('llama') == 2048
    await backend.generate('llama', 'hi')
    assert sent[-1][1]['options']['num_ctx'] == 2048
    await backend.aclose()


@pytest.mark.asyncio
async def test_ollama_configured_limit_wins_without_probe():
    backend = OllamaBackend(num_ctx=4096)
    assert await backend.resolve_context_window('llama') == 4096
    assert backend.context_window('llama') == 4096
    await backend.aclose()


def test_compaction_never_waits_past_85_percent():
    policy = CompactionPolicy(soft=.8, hard=1, per_model={'m': 1000})
    assert policy.tier(850, 'm') == 'summarize'


def test_gemini_auto_output_is_reserved_in_compaction_window():
    policy = CompactionPolicy(per_model={'gemini-test': 32768}, output_reserve=8192)
    assert policy.window('gemini-test') == 24576
    assert policy.tier(21000, 'gemini-test') == 'summarize'


@pytest.mark.asyncio
async def test_ollama_unknown_architectural_max_is_not_an_effective_limit():
    backend = OllamaBackend()
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(base_url='http://localhost', transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'model_info': {'llama.context_length': 131072}})))
    assert await backend.resolve_context_window('m') is None
    assert backend._context_options('m') == {}
    await backend.aclose()
