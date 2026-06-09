"""H20.2 — OpenRouter adapter + /model hot-swap. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.llm.openrouter import OpenRouterBackend, parse_model_command, OPENROUTER_BASE


class _Resp:
    def __init__(self, data, status=200):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self, data):
        self.calls = []
        self._data = data

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _Resp(self._data)


@pytest.mark.asyncio
async def test_generate_strips_thinking_and_sends_bearer():
    client = _Client({"choices": [{"message": {"content": "answer <think>hidden</think>"}}]})
    backend = OpenRouterBackend(api_key="sk-or-xyz", client=client)
    out = await backend.generate("openai/gpt-4o", "hi", system="be brief")
    assert out == "answer"                            # chain-of-thought stripped
    call = client.calls[0]
    assert call["url"] == "/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-or-xyz"
    assert call["json"]["model"] == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_generate_error_is_caught():
    class _Boom:
        async def post(self, *a, **k):
            raise RuntimeError("network down")

    out = await OpenRouterBackend(client=_Boom()).generate("m", "p")
    assert out.startswith("[OpenRouter error")


def test_parse_model_command():
    assert parse_model_command("/model anthropic/claude-3.5") == {"model": "anthropic/claude-3.5"}
    assert parse_model_command("/model") == {"list": True}
    assert parse_model_command("/MODEL  openai/gpt-4o extra") == {"model": "openai/gpt-4o"}
    assert parse_model_command("hello there") is None
    assert parse_model_command("") is None


def test_base_constant():
    assert OPENROUTER_BASE.startswith("https://openrouter.ai")
